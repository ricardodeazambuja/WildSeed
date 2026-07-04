"""Forest world generation with procedural model placement."""

import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET

import numpy as np
from stl import mesh

from wildseed.config.schema import DensityConfig
from wildseed.core.rig import add_label_plugin

logger = logging.getLogger("wildseed.forest")


class WorldPopulator:
    """Procedurally generate forest worlds with intelligent model placement.

    Places models on terrain using zone weighting, distance constraints,
    and natural clustering patterns. Handles cross-category collision
    avoidance and scale-aware spacing.
    """

    # Scale ranges for each model category
    # Phase C (DEMO_REALISM_V2): scale UP for a mature canopy + landmark boulders, and
    # widen the ranges so per-instance size variation breaks repeated-feature aliasing
    # (a repeated model at a repeated size yields repeated VIO features; varied size does
    # not). Trees read tall/mature like the originals; the rock max gives hero boulders.
    SCALE_RANGES = {
        "tree": (1.0, 2.2),
        "rock": (0.6, 2.6),
        "bush": (0.4, 1.2),
        "grass": (0.25, 0.7),
        "sand": (1.0, 2.5),
    }

    # Minimum distances between models of same category
    MIN_DISTANCES = {
        "tree": 8.0,
        "bush": 2.0,
        "rock": 4.0,
        "grass": 0.5,
        "sand": 3.0,
    }

    # Cross-category minimum distances
    # Keys are tuples of (category1, category2), order doesn't matter
    CROSS_CATEGORY_DISTANCES = {
        ("tree", "tree"): 8.0,
        ("tree", "bush"): 1.5,
        ("tree", "rock"): 2.0,
        ("tree", "grass"): 0.5,
        ("tree", "sand"): 4.0,
        ("bush", "bush"): 2.0,
        ("bush", "rock"): 1.5,
        ("bush", "grass"): 0.3,
        ("bush", "sand"): 2.0,
        ("rock", "rock"): 4.0,
        ("rock", "grass"): 0.5,
        ("rock", "sand"): 2.0,
        ("grass", "grass"): 0.5,
        ("grass", "sand"): 0.5,
        ("sand", "sand"): 3.0,
    }

    # Zone weights (edge vs center preference)
    ZONE_WEIGHTS = {
        "tree": {"edge": 0.2, "center": 0.8},
        "rock": {"edge": 0.8, "center": 0.2},
        "bush": {"edge": 0.4, "center": 0.6},
        "grass": {"edge": 0.5, "center": 0.5},
        "sand": {"edge": 0.7, "center": 0.3},
    }

    def __init__(
            self,
            base_path: Path,
            progress_callback: Optional[Callable[[int, str], None]] = None,
            seed: Optional[int] = None,
            variants: Optional[Dict[str, List[str]]] = None,
            density_maps: Optional[Dict[str, Path]] = None,
    ):
        """Initialize the world populator.

        Args:
            base_path: Project base path containing models/ and worlds/.
            progress_callback: Optional callback for progress updates (percent, message).
            seed: Optional RNG seed. When set, model placement is reproducible
                (same seed -> identical world), which is required for debugging
                VIO/lidar failures against a specific generated scenario.
            variants: Optional per-category allow-list of model ids (a biome
                palette). When set, placement only picks from these; models in
                the list but missing from models/<cat>/ are skipped with a
                warning. When None, every model on disk is eligible.
            density_maps: Optional category -> grayscale image path. Placement
                probability for that category follows pixel intensity (white =
                dense, black = never) instead of the built-in zone/cluster
                heuristics. Key ``"*"`` applies to any category without its own
                map. The image spans the full terrain extent, north-up (row 0 =
                +Y edge, col 0 = -X edge).

        Raises:
            FileNotFoundError: If required paths don't exist.
        """
        self.base_path = Path(base_path)
        self.models_path = self.base_path / "models"
        self.worlds_path = self.base_path / "worlds"
        self.progress_callback = progress_callback
        self.seed = seed
        self.allowed_variants = variants
        # Instance RNG (never the global np.random state): placement stays
        # reproducible even if other code — ours or a library's — consumes the
        # global stream. Re-created per create_forest_world() call when seeded,
        # so repeated builds from one populator are identical too.
        self.rng = np.random.default_rng(seed)

        # Store (x, y, z, scale) for each placed model
        self.placed_models: Dict[str, List[Tuple[float, float, float, float]]] = {
            "tree": [],
            "bush": [],
            "rock": [],
            "grass": [],
            "sand": [],
        }
        # Full per-instance ground truth (model id, pose, scale) — exported next
        # to the world file so perception evaluations can associate sensor
        # returns with the exact object that produced them (idea from
        # CropCraft's field_description output).
        self.instances: List[Dict] = []
        self._name_counters: Dict[str, int] = {}

        self._verify_paths()
        self.model_variants = self._get_model_variants()
        self.density_maps = self._load_density_maps(density_maps)

    @staticmethod
    def _load_density_maps(density_maps: Optional[Dict[str, Path]]) -> Dict[str, Dict]:
        """Load grayscale density images into sampling tables.

        Each map becomes ``{"weights": HxW float array, "cdf": flat cumsum}``;
        positions are drawn by inverting the CDF (exact intensity-proportional
        sampling — no rejection loop, so even a map that is 99% black places
        every requested instance in the white sliver).
        """
        loaded: Dict[str, Dict] = {}
        for key, path in (density_maps or {}).items():
            from PIL import Image
            arr = np.asarray(Image.open(path).convert("L"), dtype=np.float64) / 255.0
            total = float(arr.sum())
            if total <= 0.0:
                raise ValueError(f"Density map {path} is all black (nothing can be placed)")
            loaded[key] = {
                "weights": arr,
                "cdf": np.cumsum(arr.ravel()) / total,
                "path": str(path),
            }
            logger.info(f"Density map for '{key}': {path} ({arr.shape[1]}x{arr.shape[0]})")
        return loaded

    def _density_map_for(self, category: str) -> Optional[Dict]:
        """Return the density-map entry for a category ('*' is the fallback)."""
        return self.density_maps.get(category) or self.density_maps.get("*")

    def _sample_map_position(
            self, entry: Dict, extent: Tuple[float, float, float, float]
    ) -> Tuple[float, float]:
        """Draw (x, y) with probability proportional to map pixel intensity.

        The image is stretched over the FULL terrain extent, north-up: row 0
        maps to the +Y edge, column 0 to the -X edge. A uniform jitter inside
        the chosen pixel avoids grid-aligned placement on coarse maps.
        """
        min_x, max_x, min_y, max_y = extent
        h, w = entry["weights"].shape
        idx = int(np.searchsorted(entry["cdf"], self.rng.random(), side="right"))
        idx = min(idx, h * w - 1)
        row, col = divmod(idx, w)
        u = (col + self.rng.random()) / w
        v = (row + self.rng.random()) / h
        x = min_x + u * (max_x - min_x)
        y = max_y - v * (max_y - min_y)
        return float(x), float(y)

    def _verify_paths(self) -> None:
        """Verify all required paths exist."""
        required_paths = [
            self.models_path / "ground",
            self.worlds_path,
            ]

        # Check for at least one model category
        categories = ["tree", "rock", "bush", "grass", "sand"]
        has_category = False
        for cat in categories:
            if (self.models_path / cat).exists():
                has_category = True
                required_paths.append(self.models_path / cat)

        if not has_category:
            logger.warning("No model categories found in models directory")

        missing_paths = []
        for path in required_paths:
            if not path.exists():
                missing_paths.append(str(path))

        if self.models_path / "ground" not in [Path(p) for p in missing_paths]:
            # Ground is required
            pass
        elif missing_paths:
            missing_str = "\n  - ".join(missing_paths)
            raise FileNotFoundError(f"Required paths not found:\n  - {missing_str}")

        # Create worlds directory if it doesn't exist
        self.worlds_path.mkdir(parents=True, exist_ok=True)

    def _get_model_variants(self) -> Dict[str, List[str]]:
        """Get available variants for each model category."""
        variants = {}
        categories = ["tree", "bush", "rock", "grass", "sand"]

        for category in categories:
            category_path = self.models_path / category
            if category_path.exists():
                variants[category] = []
                # Sorted: filesystem iteration order is OS/filesystem-dependent,
                # and the variant list feeds the seeded RNG — unsorted, the same
                # seed could place different species on different machines.
                for d in sorted(category_path.iterdir(), key=lambda p: p.name):
                    if d.is_dir() and not d.name.startswith("."):
                        variants[category].append(d.name)
                if self.allowed_variants is not None and category in self.allowed_variants:
                    allowed = self.allowed_variants[category]
                    on_disk = set(variants[category])
                    for missing in sorted(set(allowed) - on_disk):
                        logger.warning(
                            f"Palette model {category}/{missing} not found in models/ "
                            "(run tools/build_assets.py?) — skipping")
                    variants[category] = [v for v in variants[category] if v in allowed]
                if variants[category]:
                    logger.info(f"Found {len(variants[category])} variants for {category}")

        return variants

    def _get_terrain_mesh(self) -> mesh.Mesh:
        """Get terrain mesh for height sampling."""
        mesh_path = self.models_path / "ground" / "mesh" / "terrain.stl"
        if not mesh_path.exists():
            raise FileNotFoundError(f"Terrain mesh not found at: {mesh_path}")
        return mesh.Mesh.from_file(str(mesh_path))

    def _add_instance(self, world: ET.Element, category: str, variant: str,
                      x: float, y: float, z: float,
                      roll: float, pitch: float, yaw: float, scale: float) -> str:
        """Append one model include to the world AND record its ground truth."""
        idx = self._name_counters.get(category, 0)
        self._name_counters[category] = idx + 1
        name = f"{category}_{idx}"
        include = ET.SubElement(world, "include")
        ET.SubElement(include, "uri").text = f"model://{category}/{variant}"
        ET.SubElement(include, "name").text = name
        ET.SubElement(include, "pose").text = (
            f"{x:.4f} {y:.4f} {z:.4f} {roll:.4f} {pitch:.4f} {yaw:.4f}")
        ET.SubElement(include, "scale").text = f"{scale:.3f} {scale:.3f} {scale:.3f}"
        # Per-category class label: segmentation cameras label these pixels
        # with the same id laser_retro uses for lidar intensity (see core/rig.py)
        add_label_plugin(include, category)
        # float()/str() casts: rng draws are numpy scalars, which round()
        # preserves and json.dumps rejects.
        self.instances.append({
            "name": name, "category": category, "model": str(variant),
            "pose": {"x": round(float(x), 4), "y": round(float(y), 4),
                     "z": round(float(z), 4), "roll": round(float(roll), 4),
                     "pitch": round(float(pitch), 4), "yaw": round(float(yaw), 4)},
            "scale": round(float(scale), 3),
        })
        return name

    def _place_rows(self, world: ET.Element, terrain_mesh: mesh.Mesh,
                    category: str, spec: Dict) -> int:
        """Structured row planting (orchards, vineyards, plantations).

        Inspired by CropCraft's bed engine (Apache-2.0, INRAE): regular rows
        with per-plant lateral jitter, tilt noise, missing-plant dropout and
        aligned/random yaw — adapted to WildSeed's terrain (rows follow the
        DEM height, the planted block is bounded by `field_size` and can be
        rotated by `angle`; an optional sine wave bends the rows).

        Spec keys (all optional): row_distance, plant_distance, field_size,
        angle, jitter, tilt, missing, yaw ('aligned'|'random'), wave_amplitude,
        wave_length, scale_range [lo, hi], margin.
        """
        import math

        bounds = terrain_mesh.vectors.reshape(-1, 3)
        min_x, max_x = float(bounds[:, 0].min()), float(bounds[:, 0].max())
        min_y, max_y = float(bounds[:, 1].min()), float(bounds[:, 1].max())
        cx, cy = (min_x + max_x) / 2.0, (min_y + max_y) / 2.0

        margin = float(spec.get("margin", 4.0))
        row_d = max(0.5, float(spec.get("row_distance", 6.0)))
        plant_d = max(0.3, float(spec.get("plant_distance", 4.0)))
        angle = float(spec.get("angle", 0.0))
        jitter = float(spec.get("jitter", 0.15))
        tilt = float(spec.get("tilt", 0.03))
        missing = float(spec.get("missing", 0.08))
        yaw_mode = spec.get("yaw", "aligned")
        wave_amp = float(spec.get("wave_amplitude", 0.0))
        wave_len = max(1.0, float(spec.get("wave_length", 40.0)))
        cat_lo, cat_hi = self.SCALE_RANGES.get(category, (0.8, 1.2))
        # Plantations are size-uniform: default to the middle third of the
        # category's natural scale range.
        span = cat_hi - cat_lo
        lo, hi = spec.get("scale_range", (cat_lo + span / 3.0, cat_hi - span / 3.0))

        usable = min(max_x - min_x, max_y - min_y) - 2 * margin
        field = min(float(spec.get("field_size", 90.0)), usable)
        half = field / 2.0
        ca, sa = math.cos(angle), math.sin(angle)

        placed = 0
        n_rows = int(field // row_d)
        n_plants = int(field // plant_d)
        for vi in range(n_rows + 1):
            v0 = -half + vi * row_d
            for ui in range(n_plants + 1):
                u = -half + ui * plant_d
                if self.rng.random() < missing:
                    continue
                v = v0 + wave_amp * math.sin(2 * math.pi * u / wave_len)
                x = cx + u * ca - v * sa + self.rng.normal(0.0, jitter)
                y = cy + u * sa + v * ca + self.rng.normal(0.0, jitter)
                if not (min_x + margin <= x <= max_x - margin
                        and min_y + margin <= y <= max_y - margin):
                    continue
                variant = self._get_random_variant(category)
                if not variant:
                    return placed
                scale = float(self.rng.uniform(lo, hi))
                z = self._sample_terrain_height(terrain_mesh, x, y) \
                    + self.rng.uniform(-0.05, 0.02)
                roll = self.rng.normal(0.0, tilt)
                pitch = self.rng.normal(0.0, tilt)
                if yaw_mode == "aligned":
                    yaw = angle + self.rng.normal(0.0, 0.08)
                else:
                    yaw = self.rng.uniform(0, 2 * np.pi)
                self._add_instance(world, category, variant, x, y, z,
                                   roll, pitch, yaw, scale)
                self.placed_models[category].append((x, y, z, scale))
                placed += 1
        return placed

    def _get_random_variant(self, category: str) -> Optional[str]:
        """Get random variant for category."""
        variants = self.model_variants.get(category, [])
        if not variants:
            return None
        return self.rng.choice(variants)

    def _get_cross_distance(self, cat1: str, cat2: str) -> float:
        """Get minimum distance between two categories.

        Args:
            cat1: First category name.
            cat2: Second category name.

        Returns:
            Minimum required distance between the two categories.
        """
        # Try both orderings since we store only one direction
        if (cat1, cat2) in self.CROSS_CATEGORY_DISTANCES:
            return self.CROSS_CATEGORY_DISTANCES[(cat1, cat2)]
        elif (cat2, cat1) in self.CROSS_CATEGORY_DISTANCES:
            return self.CROSS_CATEGORY_DISTANCES[(cat2, cat1)]
        else:
            # Fallback to average of individual minimum distances
            return (self.MIN_DISTANCES.get(cat1, 1.0) + self.MIN_DISTANCES.get(cat2, 1.0)) / 2

    def _check_distance_to_placed(
            self, x: float, y: float, category: str, scale: float = 1.0
    ) -> bool:
        """Check if position is far enough from ALL placed models.

        Args:
            x: X coordinate of proposed position.
            y: Y coordinate of proposed position.
            category: Category of model being placed.
            scale: Scale factor of model being placed.

        Returns:
            True if position is valid (far enough from all models), False otherwise.
        """
        for other_category, positions in self.placed_models.items():
            # Get base minimum distance between these categories
            base_distance = self._get_cross_distance(category, other_category)

            for px, py, pz, p_scale in positions:
                # Calculate actual distance
                dist = np.sqrt((x - px) ** 2 + (y - py) ** 2)

                # Adjust required distance based on both models' scales
                # Use average of scales, clamped to reasonable range
                scale_factor = (max(scale, 0.5) + max(p_scale, 0.5)) / 2
                required_dist = base_distance * scale_factor

                if dist < required_dist:
                    return False

        return True

    def _sample_terrain_height(self, terrain_mesh: mesh.Mesh, x: float, y: float) -> float:
        """Sample terrain height at given x, y coordinates.

        Args:
            terrain_mesh: The terrain mesh to sample from.
            x: X coordinate.
            y: Y coordinate.

        Returns:
            Interpolated Z height at the given position.
        """
        point = np.array([x, y])
        vectors = terrain_mesh.vectors

        # Find closest triangle
        distances = np.linalg.norm(vectors[:, :, :2] - point, axis=2)
        closest_tri = vectors[np.argmin(distances.min(axis=1))]

        # Use barycentric interpolation for more accurate height
        # Fallback to mean if interpolation fails
        try:
            v0, v1, v2 = closest_tri

            # Calculate barycentric coordinates
            denom = (v1[1] - v2[1]) * (v0[0] - v2[0]) + (v2[0] - v1[0]) * (v0[1] - v2[1])
            if abs(denom) < 1e-10:
                return np.mean(closest_tri[:, 2])

            w0 = ((v1[1] - v2[1]) * (x - v2[0]) + (v2[0] - v1[0]) * (y - v2[1])) / denom
            w1 = ((v2[1] - v0[1]) * (x - v2[0]) + (v0[0] - v2[0]) * (y - v2[1])) / denom
            w2 = 1 - w0 - w1

            # Interpolate height
            z = w0 * v0[2] + w1 * v1[2] + w2 * v2[2]
            return z
        except Exception:
            return np.mean(closest_tri[:, 2])

    def _get_random_position(
            self,
            terrain_mesh: mesh.Mesh,
            category: str,
            scale: float = 1.0,
            margin: float = 2.0
    ) -> Optional[Tuple[float, float, float]]:
        """Get random position with intelligent placement.

        Args:
            terrain_mesh: Terrain mesh for bounds and height sampling.
            category: Model category being placed.
            scale: Scale of the model (affects distance requirements).
            margin: Minimum distance from terrain edges.

        Returns:
            Tuple of (x, y, z) if valid position found, None otherwise.
        """
        bounds = terrain_mesh.vectors.reshape(-1, 3)
        raw_extent = (float(np.min(bounds[:, 0])), float(np.max(bounds[:, 0])),
                      float(np.min(bounds[:, 1])), float(np.max(bounds[:, 1])))
        min_x, max_x = raw_extent[0] + margin, raw_extent[1] - margin
        min_y, max_y = raw_extent[2] + margin, raw_extent[3] - margin

        max_attempts = 100  # Increased attempts for better placement
        map_entry = self._density_map_for(category)

        for _ in range(max_attempts):
            x, y = None, None
            is_edge = self.rng.random() < self.ZONE_WEIGHTS[category]["edge"]

            if map_entry is not None:
                # Image-driven placement replaces the zone/cluster heuristics:
                # the map IS the spatial prior. Distance constraints still apply.
                x, y = self._sample_map_position(map_entry, raw_extent)

            elif category == "sand":
                if is_edge:
                    edge = self.rng.choice(["top", "bottom", "left", "right"])
                    if edge in ["top", "bottom"]:
                        x = self.rng.uniform(min_x + margin, max_x - margin)
                        y = max_y - margin if edge == "top" else min_y + margin
                        y += self.rng.uniform(-1, 1)
                    else:
                        x = max_x - margin if edge == "right" else min_x + margin
                        x += self.rng.uniform(-1, 1)
                        y = self.rng.uniform(min_y + margin, max_y - margin)
                else:
                    x = self.rng.uniform(min_x + margin, max_x - margin)
                    y = self.rng.uniform(min_y + margin, max_y - margin)

            elif category == "tree":
                if self.placed_models["tree"] and self.rng.random() < 0.7:
                    # Cluster near existing trees
                    base_idx = self.rng.integers(len(self.placed_models["tree"]))
                    base_tree = self.placed_models["tree"][base_idx]
                    base_scale = base_tree[3]

                    # Adjust cluster radius based on scales
                    min_cluster_dist = self.MIN_DISTANCES["tree"] * max(scale, base_scale)
                    max_cluster_dist = min_cluster_dist * 2

                    radius = self.rng.uniform(min_cluster_dist, max_cluster_dist)
                    angle = self.rng.uniform(0, 2 * np.pi)
                    x = base_tree[0] + radius * np.cos(angle)
                    y = base_tree[1] + radius * np.sin(angle)
                else:
                    # Place in open area, avoiding sand
                    for _ in range(10):
                        x = self.rng.uniform(min_x + margin, max_x - margin)
                        y = self.rng.uniform(min_y + margin, max_y - margin)

                        # Check distance from sand areas
                        sand_clear = all(
                            np.sqrt((x - sx) ** 2 + (y - sy) ** 2) >
                            self._get_cross_distance("tree", "sand") * max(scale, s_scale)
                            for sx, sy, _, s_scale in self.placed_models["sand"]
                        )
                        if sand_clear:
                            break
                    else:
                        continue

            elif category == "rock":
                if is_edge:
                    edge = self.rng.choice(["top", "bottom", "left", "right"])
                    edge_variance = self.rng.uniform(-2, 2)
                    if edge in ["top", "bottom"]:
                        x = self.rng.uniform(min_x + margin, max_x - margin)
                        y = (max_y - margin if edge == "top" else min_y + margin) + edge_variance
                    else:
                        x = (max_x - margin if edge == "right" else min_x + margin) + edge_variance
                        y = self.rng.uniform(min_y + margin, max_y - margin)
                else:
                    x = self.rng.uniform(min_x + margin, max_x - margin)
                    y = self.rng.uniform(min_y + margin, max_y - margin)

            elif category == "bush":
                if self.rng.random() < 0.6 and self.placed_models["tree"]:
                    # Place near trees
                    base_idx = self.rng.integers(len(self.placed_models["tree"]))
                    base_tree = self.placed_models["tree"][base_idx]
                    base_scale = base_tree[3]

                    # Bushes cluster closer to trees but not too close
                    min_dist = self._get_cross_distance("bush", "tree") * max(scale, base_scale)
                    radius = self.rng.uniform(min_dist, min_dist + 3.0)
                    angle = self.rng.uniform(0, 2 * np.pi)
                    x = base_tree[0] + radius * np.cos(angle)
                    y = base_tree[1] + radius * np.sin(angle)
                else:
                    x = self.rng.uniform(min_x + margin, max_x - margin)
                    y = self.rng.uniform(min_y + margin, max_y - margin)

            elif category == "grass":
                # Grass can go almost anywhere but prefers areas with trees/bushes
                if self.rng.random() < 0.5 and (self.placed_models["tree"] or self.placed_models["bush"]):
                    # Place near vegetation
                    all_vegetation = self.placed_models["tree"] + self.placed_models["bush"]
                    base = all_vegetation[self.rng.integers(len(all_vegetation))]
                    radius = self.rng.uniform(1.0, 5.0)
                    angle = self.rng.uniform(0, 2 * np.pi)
                    x = base[0] + radius * np.cos(angle)
                    y = base[1] + radius * np.sin(angle)
                else:
                    x = self.rng.uniform(min_x + margin, max_x - margin)
                    y = self.rng.uniform(min_y + margin, max_y - margin)

            else:
                x = self.rng.uniform(min_x + margin, max_x - margin)
                y = self.rng.uniform(min_y + margin, max_y - margin)

            # Validate position
            if x is None or y is None:
                continue

            if not (min_x <= x <= max_x and min_y <= y <= max_y):
                continue

            if not self._check_distance_to_placed(x, y, category, scale):
                continue

            # Sample height from terrain
            z = self._sample_terrain_height(terrain_mesh, x, y)

            # Category-specific height adjustments
            if category == "sand":
                z += self.rng.uniform(-0.2, 0)
            elif category == "grass":
                z += self.rng.uniform(-0.05, 0.05)
            elif category == "rock":
                z += self.rng.uniform(-0.1, 0.1)
            else:
                z += self.rng.uniform(-0.08, 0.08)

            # Store position with scale
            self.placed_models[category].append((x, y, z, scale))
            return x, y, z

        # No valid position found after max attempts
        return None

    def _add_scene_settings(self, world: ET.Element) -> None:
        """Add scene settings for proper PBR lighting.

        Args:
            world: World XML element to add settings to.
        """
        scene = ET.SubElement(world, "scene")
        # Ambient kept low (sky-tinted) so the sun's shadows stay readable;
        # the old 0.4 grey + fill lights washed every shadow out.
        ET.SubElement(scene, "ambient").text = "0.25 0.27 0.3 1"
        ET.SubElement(scene, "background").text = "0.7 0.8 0.9 1"
        # Procedural sky (sun disc + gradient) — without it cameras see a
        # flat background colour and half of every outdoor frame is dead.
        ET.SubElement(scene, "sky")

    def _add_extra_lighting(self, world: ET.Element) -> None:
        """Add a weak sky-fill light so shadowed sides don't go black.

        Deliberately far below the sun's intensity: the previous fill
        (0.6 directional + 0.3 point + 0.4 ambient) out-powered the
        shadow-casting sun and flattened the whole scene.

        Args:
            world: World XML element to add lights to.
        """
        ambient = ET.SubElement(world, "light", {"name": "ambient", "type": "directional"})
        ET.SubElement(ambient, "cast_shadows").text = "false"
        ET.SubElement(ambient, "pose").text = "0 0 10 0 0 0"
        ET.SubElement(ambient, "diffuse").text = "0.18 0.2 0.24 1"
        ET.SubElement(ambient, "specular").text = "0.02 0.02 0.02 1"
        # Opposed to the sun so it only lifts the shadowed sides.
        ET.SubElement(ambient, "direction").text = "0.5 -0.25 -0.8"

    def create_forest_world(
            self,
            density_config: Optional[Dict[str, int]] = None,
            rows_config: Optional[Dict[str, Dict]] = None,
            rig_config=None,
            rig_pose: Optional[Tuple[float, ...]] = None,
    ) -> Path:
        """Create forest world with placed models.

        Args:
            density_config: Dict of category -> count. Uses defaults if None.
            rows_config: Optional dict of category -> row spec (see _place_rows).
                A category with a row spec is planted in structured rows and
                skipped by the density scatter.
            rig_config: Optional RigConfig. When given, the sensor rig model is
                (re)generated under models/, included in the world, and the
                world gains the sensor system plugins + spherical coordinates
                (docs/SENSOR_RIG.md).
            rig_pose: Optional (x, y, z, roll, pitch, yaw) for the rig. Default:
                terrain centre, 25 m above ground.

        Returns:
            Path to created world file.
        """
        import json

        from wildseed.utils.sdf import create_world_base, write_world_file

        if self.seed is not None:
            self.rng = np.random.default_rng(self.seed)
            logger.info(f"Placement seeded with seed={self.seed} (reproducible)")

        # Reset placed models
        for category in self.placed_models:
            self.placed_models[category] = []
        self.instances = []
        self._name_counters = {}
        rows_config = rows_config or {}

        # Use provided config or defaults
        if density_config is None:
            config = DensityConfig()
            density_config = {
                "tree": config.tree,
                "bush": config.bush,
                "rock": config.rock,
                "grass": config.grass,
                "sand": config.sand,
            }

        # Create world with shared base (plugins, physics, gravity, sun)
        world_elem, world = create_world_base("forest_world")

        # Add scene settings for proper PBR lighting
        self._add_scene_settings(world)

        # Add extra lighting for forest scenes
        self._add_extra_lighting(world)

        # Add terrain
        terrain = ET.SubElement(world, "include")
        ET.SubElement(terrain, "uri").text = "model://ground"
        ET.SubElement(terrain, "name").text = "terrain"
        ET.SubElement(terrain, "pose").text = "0 0 0 0 0 0"
        add_label_plugin(terrain, "ground")

        terrain_mesh = self._get_terrain_mesh()

        # Structured rows go FIRST so the scatter pass keeps its distance from
        # the planted rows (cross-category minimums see them in placed_models).
        for category, spec in rows_config.items():
            if category not in self.model_variants or not self.model_variants.get(category):
                logger.warning(f"rows: no models available for {category}; skipping")
                continue
            n = self._place_rows(world, terrain_mesh, category, spec or {})
            logger.info(f"  {category}: planted {n} in rows")

        # Process categories in specific order (larger/important first)
        category_order = ["sand", "rock", "tree", "bush", "grass"]
        total_models = sum(density_config.get(c, 0) for c in category_order)
        models_placed = 0
        models_failed = 0

        for category in category_order:
            if category in rows_config:
                continue  # planted in rows above
            if category not in density_config or category not in self.model_variants:
                continue

            count = density_config[category]
            if count == 0:
                continue

            logger.info(f"Adding {count} {category} models...")
            category_placed = 0
            category_failed = 0

            for i in range(count):
                try:
                    variant = self._get_random_variant(category)
                    if not variant:
                        logger.warning(f"No variants available for {category}")
                        continue

                    # Generate scale FIRST (needed for distance calculations)
                    scale = self.rng.uniform(*self.SCALE_RANGES[category])

                    # Get position considering scale
                    position = self._get_random_position(terrain_mesh, category, scale)

                    if position is None:
                        category_failed += 1
                        models_failed += 1
                        logger.debug(f"Could not find valid position for {category}_{i}")
                        continue

                    x, y, z = position

                    # Category-specific rotations
                    if category == "sand":
                        roll = pitch = 0
                        yaw = self.rng.uniform(0, 2 * np.pi)
                    elif category == "tree":
                        # Slight tilt for natural look
                        roll = self.rng.uniform(-0.05, 0.05)
                        pitch = self.rng.uniform(-0.05, 0.05)
                        yaw = self.rng.uniform(0, 2 * np.pi)
                    elif category == "rock":
                        # Rocks can have more tilt
                        roll = self.rng.uniform(-0.15, 0.15)
                        pitch = self.rng.uniform(-0.15, 0.15)
                        yaw = self.rng.uniform(0, 2 * np.pi)
                    elif category == "bush":
                        roll = self.rng.uniform(-0.03, 0.03)
                        pitch = self.rng.uniform(-0.03, 0.03)
                        yaw = self.rng.uniform(0, 2 * np.pi)
                    else:  # grass
                        roll = pitch = 0
                        yaw = self.rng.uniform(0, 2 * np.pi)

                    self._add_instance(world, category, variant, x, y, z,
                                       roll, pitch, yaw, scale)

                    category_placed += 1
                    models_placed += 1

                    if self.progress_callback and total_models > 0:
                        progress = int((models_placed / total_models) * 100)
                        self.progress_callback(progress, f"Placing {category}...")

                except Exception as e:
                    logger.warning(f"Failed to add {category} model: {e}")
                    category_failed += 1
                    models_failed += 1
                    continue

            logger.info(f"  {category}: placed {category_placed}/{count} (failed: {category_failed})")

        # Sensor rig (opt-in): regenerate the model, include it, and inject the
        # world-level sensor requirements (plugins + spherical coordinates)
        if rig_config is not None:
            from wildseed.core.rig import (add_rig_include,
                                           add_world_sensor_requirements,
                                           write_rig_model)
            add_world_sensor_requirements(world)
            write_rig_model(rig_config, self.models_path)
            if rig_pose is None:
                cx = float((terrain_mesh.x.min() + terrain_mesh.x.max()) / 2)
                cy = float((terrain_mesh.y.min() + terrain_mesh.y.max()) / 2)
                cz = self._sample_terrain_height(terrain_mesh, cx, cy) + 25.0
                rig_pose = (cx, cy, cz, 0.0, 0.0, 0.0)
            add_rig_include(world, rig_config, tuple(rig_pose))
            logger.info(f"Sensor rig included at pose {rig_pose}")

        # Save the world file
        output_path = self.worlds_path / "forest_world.world"
        write_world_file(world_elem, output_path)

        # Ground-truth sidecar: every placed instance with model id + pose +
        # scale, in placement order (deterministic under --seed).
        gt_path = output_path.with_name(output_path.stem + ".instances.json")
        gt_path.write_text(json.dumps({
            "world": output_path.name,
            "seed": self.seed,
            "count": len(self.instances),
            "instances": self.instances,
        }, indent=1))
        logger.info(f"Ground-truth instances -> {gt_path}")

        logger.info(f"World file created at: {output_path}")
        logger.info(f"Total models placed: {models_placed}/{total_models} (failed: {models_failed})")
        logger.info("Models placed by category:")
        for category in category_order:
            if category in self.placed_models:
                logger.info(f"  - {category}: {len(self.placed_models[category])}")

        return output_path

    def get_model_statistics(self) -> Dict:
        """Get statistics about placed models.

        Returns:
            Dictionary containing placement statistics.
        """
        stats = {
            "total_models": sum(len(models) for models in self.placed_models.values()),
            "by_category": {
                category: len(models) for category, models in self.placed_models.items()
            },
            "variants_available": {
                category: len(variants) for category, variants in self.model_variants.items()
            },
        }

        # Add scale statistics per category
        stats["scale_stats"] = {}
        for category, models in self.placed_models.items():
            if models:
                scales = [m[3] for m in models]
                stats["scale_stats"][category] = {
                    "min": float(np.min(scales)),
                    "max": float(np.max(scales)),
                    "mean": float(np.mean(scales)),
                }

        return stats

    def get_placement_density_map(self, resolution: int = 50) -> Dict[str, np.ndarray]:
        """Generate density maps for visualization/debugging.

        Args:
            resolution: Grid resolution for density calculation.

        Returns:
            Dictionary of category -> 2D density array.
        """
        density_maps = {}

        # Get bounds from placed models
        all_positions = []
        for models in self.placed_models.values():
            all_positions.extend([(m[0], m[1]) for m in models])

        if not all_positions:
            return density_maps

        all_positions = np.array(all_positions)
        min_x, max_x = np.min(all_positions[:, 0]), np.max(all_positions[:, 0])
        min_y, max_y = np.min(all_positions[:, 1]), np.max(all_positions[:, 1])

        for category, models in self.placed_models.items():
            if not models:
                density_maps[category] = np.zeros((resolution, resolution))
                continue

            density = np.zeros((resolution, resolution))
            for x, y, z, scale in models:
                # Convert to grid coordinates
                gx = int((x - min_x) / (max_x - min_x + 1e-6) * (resolution - 1))
                gy = int((y - min_y) / (max_y - min_y + 1e-6) * (resolution - 1))
                gx = np.clip(gx, 0, resolution - 1)
                gy = np.clip(gy, 0, resolution - 1)
                density[gy, gx] += 1

            density_maps[category] = density

        return density_maps