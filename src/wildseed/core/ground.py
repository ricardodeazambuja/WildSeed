"""Procedural ground material compositor for WildSeed terrain.

Generates the terrain's PBR ground material (albedo / normal / roughness) either as
a crisp tiled single texture (``uniform``) or as a seeded baked composite
(``patchy``) that blends a base with overlay layers -- organic patches of
sand/gravel/pebbles/rock and trails (explicit waypoints or seeded random walk).

This is a superset of the original WildSeed terrain texturing (single PBR material
from a soil.blend): same render path, plus controllable, *reproducible* variation
for randomized VIO / lidar test scenarios. Everything is driven by a seed, so the
same seed yields the same ground and a new seed yields a new scenario.

Output is one ``<pbr><metal>`` material written into ``<ground>/texture/`` with the
terrain UVs rewritten accordingly, plus an optional flat water model.
"""

import glob
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.ndimage import gaussian_filter, zoom

logger = logging.getLogger("wildseed.ground")


# --------------------------------------------------------------------------- #
# Biome presets. Each maps logical roles to material *keys* (a substring that
# identifies a texture pack under the texture root, e.g. an ambientCG id). A
# layer is a patch (organic noise blobs) or a trail (path).
# --------------------------------------------------------------------------- #
# Phase B (DEMO_REALISM_V2): non-repeating ground + NO trails.
#   - The single biggest VIO fix: the tiled base (~4 m period) repeats identical features
#     across the scene -> autocorrelation aliasing -> false loop closures. We break it by
#     (a) raising base_tile_m so the within-material repeat is coarser, and (b) blending a
#     SECOND base material with a large-period (45-55 m) MACRO patch at a *different* tile_m,
#     so over tens of metres the ground varies and no identical feature recurs. The MACRO
#     layer is the first entry in each `layers` list (high coverage ~0.3-0.5).
#   - Trails removed entirely: they appear in ZERO originals and their straight hard edges
#     read as artificial. (`kind: "trail"` support is kept in the compositor for callers
#     that pass explicit waypoints, but no biome ships one.)
BIOMES: Dict[str, dict] = {
    "grassland": {
        "base": "Grass004", "base_tile_m": 7.0,
        "layers": [
            {"material": "Ground037", "kind": "patch", "coverage": 0.50, "scale_m": 52.0, "tile_m": 9.0},  # MACRO mossy-litter base variation
            {"material": "Ground027", "kind": "patch", "coverage": 0.10, "scale_m": 30.0, "tile_m": 5.0},  # sand
            {"material": "Gravel023", "kind": "patch", "coverage": 0.06, "scale_m": 16.0, "tile_m": 4.0},  # gravel
            {"material": "Rocks023",  "kind": "patch", "coverage": 0.05, "scale_m": 9.0,  "tile_m": 3.0},  # pebbles
        ],
    },
    "desert": {
        "base": "Ground027", "base_tile_m": 7.0,
        "layers": [
            {"material": "Ground037", "kind": "patch", "coverage": 0.45, "scale_m": 55.0, "tile_m": 9.0},  # MACRO base variation
            {"material": "Gravel023", "kind": "patch", "coverage": 0.14, "scale_m": 24.0, "tile_m": 4.0},
            {"material": "Rocks023",  "kind": "patch", "coverage": 0.08, "scale_m": 9.0,  "tile_m": 3.0},
        ],
    },
    "gravel": {
        "base": "Gravel023", "base_tile_m": 5.0,
        "layers": [
            {"material": "Ground027", "kind": "patch", "coverage": 0.45, "scale_m": 50.0, "tile_m": 9.0},  # MACRO base variation
            {"material": "Rocks023",  "kind": "patch", "coverage": 0.10, "scale_m": 8.0,  "tile_m": 3.0},
        ],
    },
    "snow": {
        "base": "Snow", "base_tile_m": 8.0,
        "layers": [
            {"material": "Ground037", "kind": "patch", "coverage": 0.30, "scale_m": 45.0, "tile_m": 6.0},  # MACRO exposed-ground variation
            {"material": "Rocks023",  "kind": "patch", "coverage": 0.09, "scale_m": 14.0, "tile_m": 4.0},  # exposed rock
        ],
    },
}

# Map -> (color, normal, roughness) filename substrings tried in order.
_COLOR = ("color", "diff", "albedo", "basecolor", "base_color")
_NORMAL = ("normalgl", "nor_gl", "normal_gl", "normaldx", "normal", "_nor")
_ROUGH = ("roughness", "rough")


class GroundCompositor:
    """Compose a terrain ground PBR material set from tiling texture packs."""

    def __init__(
        self,
        ground_dir: Path,
        texture_root: Path,
        config=None,
    ):
        self.ground_dir = Path(ground_dir)
        self.obj = self.ground_dir / "mesh" / "terrain.obj"
        self.texdir = self.ground_dir / "texture"
        self.texture_root = Path(texture_root)
        self.config = config  # GroundConfig (duck-typed)
        self._cache: Dict[str, np.ndarray] = {}

    # ---- material loading ------------------------------------------------- #
    def _find(self, key: str, kinds: Tuple[str, ...]) -> Optional[str]:
        cands = glob.glob(os.path.join(self.texture_root, "**", f"*{key}*"), recursive=True)
        cands = [c for c in cands if c.lower().endswith((".png", ".jpg", ".jpeg"))]
        for k in kinds:
            for c in cands:
                if k in os.path.basename(c).lower():
                    return c
        return None

    def _load(self, path: str) -> np.ndarray:
        from PIL import Image
        if path not in self._cache:
            self._cache[path] = np.asarray(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
        return self._cache[path]

    def material(self, key: str) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
        """Return (albedo, normal, roughness) float arrays for a material key.

        Normal/roughness fall back to flat/mid-grey if the pack lacks them.
        """
        cpath = self._find(key, _COLOR)
        if cpath is None:
            raise FileNotFoundError(
                f"No color texture found for material '{key}' under {self.texture_root}. "
                f"Drop a CC0 pack (e.g. ambientCG {key}) there."
            )
        alb = self._load(cpath)
        npath = self._find(key, _NORMAL)
        nor = self._load(npath) if npath else None
        rpath = self._find(key, _ROUGH)
        rgh = self._load(rpath) if rpath else None
        return alb, nor, rgh

    # ---- geometry / extent ------------------------------------------------ #
    def terrain_extent(self) -> Tuple[float, float, float, float]:
        minx = miny = 1e18
        maxx = maxy = -1e18
        with open(self.obj) as f:
            for line in f:
                if line.startswith("v "):
                    p = line.split()
                    x, y = float(p[1]), float(p[2])
                    minx, maxx = min(minx, x), max(maxx, x)
                    miny, maxy = min(miny, y), max(maxy, y)
        return minx, maxx, miny, maxy

    def _extent_m(self) -> Tuple[float, float]:
        minx, maxx, miny, maxy = self.terrain_extent()
        return (maxx - minx, maxy - miny)

    # ---- sampling / blending --------------------------------------------- #
    @staticmethod
    def _tiled(tex: np.ndarray, res: int, extent_m: Tuple[float, float], tile_m: float,
               warp: Optional[Tuple[np.ndarray, np.ndarray]] = None) -> np.ndarray:
        """Sample `tex` tiled over the terrain extent at `tile_m` metres per repeat.

        Phase B (DEMO_REALISM_V2): the no-warp path is the fast separable tiling and
        produces a perfectly periodic, axis-aligned grid -- which the tiling metric sees
        as a sharp autocorrelation CROSS (== VIO aliasing). When `warp=(wu, wv)` (a smooth
        low-frequency displacement field, in tile units) is supplied, the sample UVs are
        domain-warped so the repetition becomes wavy/non-periodic: the grid no longer
        lines up with itself under any fixed shift, so the autocorrelation cross collapses
        while the texture still reads as the same material. Warped sampling is non-separable
        (full res x res index arrays) so it costs more; callers pass the SAME warp to every
        layer so the maps stay registered.
        """
        h, w = tex.shape[:2]
        ex, ey = extent_m
        if warp is None:
            ux = ((np.arange(res) / res) * (ex / tile_m)) % 1.0
            uy = ((np.arange(res) / res) * (ey / tile_m)) % 1.0
            cols = (ux * w).astype(int) % w
            rows = (uy * h).astype(int) % h
            return tex[np.ix_(rows, cols)]
        u = (np.arange(res, dtype=np.float32) / res) * (ex / tile_m)
        v = (np.arange(res, dtype=np.float32) / res) * (ey / tile_m)
        U = u[None, :] + warp[0]                      # res x res, in tile units
        V = v[:, None] + warp[1]
        cols = (np.mod(U, 1.0) * w).astype(np.int32) % w
        rows = (np.mod(V, 1.0) * h).astype(np.int32) % h
        return tex[rows, cols]

    @staticmethod
    def _blend_normal(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> np.ndarray:
        da, db = a * 2.0 - 1.0, b * 2.0 - 1.0
        out = da * (1 - m[..., None]) + db * m[..., None]
        n = np.linalg.norm(out, axis=2, keepdims=True)
        n[n == 0] = 1
        return (out / n) * 0.5 + 0.5

    # ---- mask generators (the tuned, organic part) ------------------------ #
    @staticmethod
    def _fractal_noise(res: int, scale_px: float, rng: np.random.Generator, octaves: int = 4) -> np.ndarray:
        """Organic value noise in [0,1] via summed smoothed-random octaves.

        Computed at a coarse working resolution (capped) then bilinearly upscaled
        to `res` -- gaussian_filter on a full 4-8K grid per octave is far too slow
        for a CLI that must regenerate many seeded scenarios.
        """
        work = int(min(res, 768))
        s = scale_px * work / res  # keep feature size in output pixels
        out = np.zeros((work, work), np.float32)
        amp, total = 1.0, 0.0
        sigma = s
        for _ in range(octaves):
            n = gaussian_filter(rng.standard_normal((work, work)).astype(np.float32), sigma=max(sigma, 0.8))
            out += amp * n
            total += amp
            amp *= 0.5
            sigma *= 0.5
        out /= total
        out -= out.min()
        mx = out.max()
        out = out / mx if mx > 0 else out
        if work != res:
            out = zoom(out, res / work, order=1).astype(np.float32)
            out = out[:res, :res] if out.shape[0] >= res else np.pad(out, ((0, res - out.shape[0]), (0, res - out.shape[1])), mode="edge")
        return out

    def _patch_mask(self, res: int, coverage: float, scale_m: float, rng: np.random.Generator,
                    extent_m: Tuple[float, float], feather: float = 0.06) -> np.ndarray:
        """Organic patches covering ~`coverage` of the area, feature size ~`scale_m`."""
        scale_px = scale_m / ((extent_m[0] + extent_m[1]) / 2.0) * res
        noise = self._fractal_noise(res, max(scale_px, 2.0), rng)
        thr = float(np.quantile(noise, 1.0 - np.clip(coverage, 0.0, 1.0)))
        band = feather
        return np.clip((noise - (thr - band)) / (2 * band + 1e-6), 0, 1)

    def _trail_mask(self, res: int, waypoints_uv, width_m: float, extent_m: Tuple[float, float],
                    rng: np.random.Generator, feather: float = 0.5) -> np.ndarray:
        ex, ey = extent_m
        pts = np.array(waypoints_uv, dtype=np.float32) * res
        m = np.zeros((res, res), np.float32)
        yy, xx = np.mgrid[0:res, 0:res]
        wpx = width_m / ((ex + ey) / 2) * res / 2.0
        # slight width wobble for a natural, non-uniform path
        wobble = 0.75 + 0.5 * self._fractal_noise(res, res / 60, rng, octaves=2)
        for i in range(len(pts) - 1):
            p, q = pts[i], pts[i + 1]
            seg = q - p
            L2 = float((seg ** 2).sum()) or 1.0
            t = np.clip(((xx - p[0]) * seg[0] + (yy - p[1]) * seg[1]) / L2, 0, 1)
            px, py = p[0] + t * seg[0], p[1] + t * seg[1]
            dist = np.sqrt((xx - px) ** 2 + (yy - py) ** 2)
            local_w = wpx * wobble
            m = np.maximum(m, np.clip(1.0 - (dist - local_w) / (local_w * feather + 1e-3), 0, 1))
        return m

    @staticmethod
    def _random_walk_uv(rng: np.random.Generator, n: int = 6, margin: float = 0.08):
        horizontal = rng.random() < 0.5
        a = rng.uniform(margin, 1 - margin)
        pts = []
        for i in range(n):
            t = margin + (1 - 2 * margin) * i / (n - 1)
            a = float(np.clip(a + rng.uniform(-0.22, 0.22), margin, 1 - margin))
            pts.append((a, t) if horizontal else (t, a))
        return pts

    # ---- domain randomization -------------------------------------------- #
    @staticmethod
    def _hsv_jitter_rgb(alb: np.ndarray, rng: np.random.Generator, strength: float) -> np.ndarray:
        """Seeded global hue/sat/value shift of an RGB float image.

        Domain randomization (Tobin et al. 2017 style): perception stacks trained
        on colour-perturbed renders generalize better, even when the recolour is
        unrealistic. One global shift keeps the texture's spatial structure (and
        the normal/roughness registration) intact.
        """
        from PIL import Image
        u8 = (np.clip(alb, 0, 1) * 255).astype(np.uint8)
        hsv = np.asarray(Image.fromarray(u8, "RGB").convert("HSV"), dtype=np.float32)
        dh = rng.uniform(-0.5, 0.5) * strength * 255.0
        ds = 1.0 + rng.uniform(-0.6, 0.6) * strength
        dv = 1.0 + rng.uniform(-0.4, 0.4) * strength
        h = np.mod(hsv[..., 0] + dh, 256.0)
        s = np.clip(hsv[..., 1] * ds, 0, 255)
        v = np.clip(hsv[..., 2] * dv, 0, 255)
        out = Image.fromarray(np.stack([h, s, v], axis=-1).astype(np.uint8), "HSV").convert("RGB")
        return np.asarray(out, dtype=np.float32) / 255.0

    # ---- top-level generate ---------------------------------------------- #
    def generate(self) -> dict:
        cfg = self.config
        mode = getattr(cfg, "mode", "patchy")
        if mode == "uniform":
            return self._generate_uniform()
        if mode == "wild":
            return self._generate_wild()
        return self._generate_patchy()

    def _generate_uniform(self) -> dict:
        cfg = self.config
        biome = BIOMES.get(getattr(cfg, "biome", "grassland"), BIOMES["grassland"])
        base = getattr(cfg, "base_material", None) or biome["base"]
        alb, nor, rgh = self.material(base)
        jitter = float(getattr(cfg, "hsv_jitter", 0.0) or 0.0)
        if jitter > 0:
            rng = np.random.default_rng(int(getattr(cfg, "seed", 0)))
            alb = self._hsv_jitter_rgb(alb, rng, jitter)
        self._write_maps(self._to8(alb), self._to8(nor) if nor is not None else None,
                         self._to8(rgh) if rgh is not None else None)
        warp = float(getattr(cfg, "tile_warp", 0.0) or 0.0)
        self.set_uv(getattr(cfg, "uniform_tile", 8.0), warp_amp=warp,
                    seed=int(getattr(cfg, "seed", 0)))
        self.write_sdf(has_normal=nor is not None, has_rough=rgh is not None)
        logger.info(f"ground: uniform base={base} tile=x{getattr(cfg, 'uniform_tile', 8.0)} "
                    f"warp={warp} jitter={jitter}")
        return {"mode": "uniform", "base": base, "hsv_jitter": jitter}

    def _generate_wild(self) -> dict:
        """Fully procedural, deliberately UNREALISTIC ground (domain randomization).

        No texture packs needed: a seeded composition of random colour ramps,
        blobs, stripes and checkers. Normal map is flat; roughness is seeded
        noise. Same seed -> same ground, like every other mode.
        """
        cfg = self.config
        res = int(min(int(getattr(cfg, "resolution", 4096)), 2048))
        seed = int(getattr(cfg, "seed", 0))
        rng = np.random.default_rng(seed)
        extent = self._extent_m()

        def rand_color():
            return rng.random(3).astype(np.float32)

        # base: two random colours lerped through large-scale organic noise
        base_noise = self._fractal_noise(res, res / float(rng.uniform(4.0, 12.0)), rng)
        c1, c2 = rand_color(), rand_color()
        alb = c1[None, None, :] + (c2 - c1)[None, None, :] * base_noise[..., None]

        yy, xx = np.mgrid[0:res, 0:res].astype(np.float32) / res
        styles = []
        for _ in range(int(rng.integers(1, 4))):  # 1-3 overlays
            style = str(rng.choice(["blobs", "stripes", "checker", "noise"]))
            col = rand_color()
            if style == "blobs":
                m = self._patch_mask(res, float(rng.uniform(0.1, 0.4)),
                                     float(rng.uniform(5.0, 40.0)), rng, extent)
            elif style == "stripes":
                theta = float(rng.uniform(0, np.pi))
                period_px = float(rng.uniform(res / 40.0, res / 6.0))
                phase = (xx * np.cos(theta) + yy * np.sin(theta)) * res / period_px
                m = ((np.sin(2 * np.pi * phase) * 0.5 + 0.5) > 0.5).astype(np.float32)
            elif style == "checker":
                k = int(rng.integers(4, 24))
                m = (((xx * k).astype(int) + (yy * k).astype(int)) % 2).astype(np.float32)
            else:  # noise
                m = self._fractal_noise(res, res / float(rng.uniform(8.0, 32.0)), rng)
            alpha = float(rng.uniform(0.4, 1.0))
            m3 = (m * alpha)[..., None]
            alb = alb * (1 - m3) + col[None, None, :] * m3
            styles.append(style)

        rgh = self._fractal_noise(res, res / 10.0, rng) * 0.8 + 0.2
        rgh = np.repeat(rgh[..., None], 3, axis=2)
        nor = np.full((res, res, 3), [0.5, 0.5, 1.0], np.float32)

        self._write_maps(self._to8(alb), self._to8(nor), self._to8(rgh))
        self.set_uv(None)
        self.write_sdf(has_normal=True, has_rough=True)
        logger.info(f"ground: wild seed={seed} res={res} overlays={styles}")
        return {"mode": "wild", "seed": seed, "res": res, "styles": styles}

    def _generate_patchy(self) -> dict:
        cfg = self.config
        res = int(getattr(cfg, "resolution", 4096))
        seed = int(getattr(cfg, "seed", 0))
        rng = np.random.default_rng(seed)
        randomize = getattr(cfg, "randomize", True)
        biome_name = getattr(cfg, "biome", "grassland")
        biome = BIOMES.get(biome_name, BIOMES["grassland"])
        extent = self._extent_m()

        # Phase B: a smooth low-frequency UV warp (in tile units) shared by every layer.
        # It bends the otherwise-perfectly-periodic tiling grid into a wavy, non-periodic
        # pattern so the tiling-autocorrelation cross collapses (the VIO de-aliasing fix),
        # while the ground still reads as the same material. ~40 m wobble period, ~1.3
        # tiles of displacement. Disable with cfg.tile_warp = 0.
        base_key = getattr(cfg, "base_material", None) or biome["base"]
        base_tile = biome.get("base_tile_m", 4.0)
        warp_amp = float(getattr(cfg, "tile_warp", 1.3))
        warp = None
        if warp_amp > 0:
            # Wobble period ~6x the base tile (~40 m): coarse enough to gently BEND the
            # periodic grid across the frame (collapsing the long-range autocorrelation
            # cross) without the warp itself introducing a new short period -- a fine,
            # high-amplitude warp folds the texture into visible swirls AND adds its own
            # ~period peak (measured: 18 m warp pushed hero tilePk 0.06 -> 0.30). Amplitude
            # in tile units; octaves=3 keeps it smooth (no high-freq texture tearing).
            warp_period_m = max(6.0 * base_tile, 40.0)
            warp_px = max(warp_period_m / ((extent[0] + extent[1]) / 2.0) * res, 8.0)
            wu = (self._fractal_noise(res, warp_px, rng, octaves=3) - 0.5) * 2.0 * warp_amp
            wv = (self._fractal_noise(res, warp_px, rng, octaves=3) - 0.5) * 2.0 * warp_amp
            warp = (wu.astype(np.float32), wv.astype(np.float32))

        alb, nor, rgh = self.material(base_key)
        alb = self._tiled(alb, res, extent, base_tile, warp)
        nor = self._tiled(nor, res, extent, base_tile, warp) if nor is not None else np.full((res, res, 3), [0.5, 0.5, 1.0], np.float32)
        rgh = self._tiled(rgh, res, extent, base_tile, warp) if rgh is not None else np.full((res, res, 3), 0.9, np.float32)

        layers = getattr(cfg, "layers", None) or biome["layers"]
        applied = []
        for spec in layers:
            spec = dict(spec) if not isinstance(spec, dict) else spec
            key = spec["material"]
            try:
                oa, on, orr = self.material(key)
            except FileNotFoundError as e:
                logger.warning(str(e))
                continue
            tile = spec.get("tile_m", 3.0)
            oa = self._tiled(oa, res, extent, tile, warp)
            on = self._tiled(on, res, extent, tile, warp) if on is not None else np.full((res, res, 3), [0.5, 0.5, 1.0], np.float32)
            orr = self._tiled(orr, res, extent, tile, warp) if orr is not None else np.full((res, res, 3), 0.9, np.float32)

            if spec.get("kind") == "trail":
                count = int(spec.get("count", 1))
                width = float(spec.get("width_m", 2.5))
                wps = spec.get("waypoints")
                m = np.zeros((res, res), np.float32)
                for _ in range(count):
                    pts = wps if wps else self._random_walk_uv(rng)
                    m = np.maximum(m, self._trail_mask(res, pts, width, extent, rng))
                    wps = None  # only first uses explicit; extras random
            else:  # patch
                cov = float(spec.get("coverage", 0.08))
                scale = float(spec.get("scale_m", 15.0))
                if randomize:
                    cov *= float(rng.uniform(0.7, 1.3))
                    scale *= float(rng.uniform(0.8, 1.25))
                m = self._patch_mask(res, cov, scale, rng, extent)

            m3 = m[..., None]
            alb = alb * (1 - m3) + oa * m3
            rgh = rgh * (1 - m3) + orr * m3
            nor = self._blend_normal(nor, on, m)
            applied.append(f"{key}:{spec.get('kind')}")

        jitter = float(getattr(cfg, "hsv_jitter", 0.0) or 0.0)
        if jitter > 0:
            alb = self._hsv_jitter_rgb(alb, rng, jitter)

        self._write_maps(self._to8(alb), self._to8(nor), self._to8(rgh))
        self.set_uv(None)
        self.write_sdf(has_normal=True, has_rough=True)
        logger.info(f"ground: patchy biome={biome_name} seed={seed} res={res} base={base_key} layers={applied} jitter={jitter}")
        return {"mode": "patchy", "biome": biome_name, "seed": seed, "res": res,
                "base": base_key, "layers": applied, "hsv_jitter": jitter}

    # ---- io --------------------------------------------------------------- #
    @staticmethod
    def _to8(a):
        return (np.clip(a, 0, 1) * 255).astype(np.uint8)

    def _write_maps(self, alb, nor, rgh):
        from PIL import Image
        self.texdir.mkdir(parents=True, exist_ok=True)
        for f in glob.glob(os.path.join(self.texdir, "*.png")) + glob.glob(os.path.join(self.texdir, "*.jpg")):
            os.remove(f)
        Image.fromarray(alb).save(self.texdir / "ground_Color.png")
        if nor is not None:
            Image.fromarray(nor).save(self.texdir / "ground_NormalGL.png")
        if rgh is not None:
            Image.fromarray(rgh).save(self.texdir / "ground_Roughness.png")

    def set_uv(self, scale: Optional[float], warp_amp: float = 0.0, seed: int = 0):
        """Rewrite terrain.obj UVs. scale=None -> 0..1 (baked); else x scale (tiled).

        warp_amp>0 (tiled mode only): add a smooth low-frequency displacement (in TILE
        units) to the per-vertex UVs, sampled from a coarse fractal grid. This bends the
        otherwise-perfectly-periodic tiling grid into a wavy, non-periodic one so the
        tiling-autocorrelation cross collapses (VIO de-aliasing) -- the draw-time analog
        of the patchy _tiled warp. Wobble period ~40 m so the warp itself adds no new
        short period (a fine warp folds the texture into visible swirls).
        """
        verts, lines = [], []
        with open(self.obj) as f:
            for line in f:
                lines.append(line)
                if line.startswith("v "):
                    p = line.split()
                    verts.append((float(p[1]), float(p[2])))
        vx = np.array([v[0] for v in verts]); vy = np.array([v[1] for v in verts])
        nx = (vx - vx.min()) / (vx.max() - vx.min())
        ny = (vy - vy.min()) / (vy.max() - vy.min())
        u, v = nx.copy(), ny.copy()
        if scale is not None:
            u, v = u * scale, v * scale
        if warp_amp > 0 and scale is not None:
            ex, ey = float(vx.max() - vx.min()), float(vy.max() - vy.min())
            extent = max((ex + ey) / 2.0, 1e-6)
            warp_period_m = max(40.0, 6.0 * extent / float(scale))  # >= ~6 tiles
            grid = 96
            warp_px = max(grid * warp_period_m / extent, 4.0)
            rng = np.random.default_rng(int(seed))
            du = (self._fractal_noise(grid, warp_px, rng, octaves=3) - 0.5) * 2.0 * warp_amp
            dv = (self._fractal_noise(grid, warp_px, rng, octaves=3) - 0.5) * 2.0 * warp_amp
            ix = np.clip((nx * (grid - 1)).astype(int), 0, grid - 1)
            iy = np.clip((ny * (grid - 1)).astype(int), 0, grid - 1)
            u = u + du[iy, ix]
            v = v + dv[iy, ix]
        out, vi = [], 0
        for line in lines:
            if line.startswith("vt "):
                out.append(f"vt {u[vi]:.6f} {v[vi]:.6f}\n"); vi += 1
            else:
                out.append(line)
        with open(self.obj, "w") as f:
            f.writelines(out)

    def write_sdf(self, has_normal: bool = True, has_rough: bool = True):
        maps = ["                        <albedo_map>model://ground/texture/ground_Color.png</albedo_map>"]
        if has_normal:
            maps.append("                        <normal_map>model://ground/texture/ground_NormalGL.png</normal_map>")
        if has_rough:
            maps.append("                        <roughness_map>model://ground/texture/ground_Roughness.png</roughness_map>")
        maps_str = "\n".join(maps)
        sdf = f'''<?xml version="1.0" ?>
<sdf version="1.8">
    <model name="terrain">
        <static>true</static>
        <link name="link">
            <collision name="collision">
                <geometry><mesh><uri>model://ground/mesh/terrain.stl</uri></mesh></geometry>
            </collision>
            <visual name="visual">
                <geometry><mesh><uri>model://ground/mesh/terrain.obj</uri></mesh></geometry>
                <material>
                    <ambient>1.0 1.0 1.0 1</ambient>
                    <diffuse>1.0 1.0 1.0 1</diffuse>
                    <specular>0.1 0.1 0.1 1</specular>
                    <pbr><metal>
{maps_str}
                        <metalness>0.0</metalness>
                    </metal></pbr>
                </material>
            </visual>
        </link>
    </model>
</sdf>'''
        (self.ground_dir / "model.sdf").write_text(sdf)


def write_water_model(
    models_dir: Path,
    extent_m: Tuple[float, float],
    level: float,
    name: str = "water",
    center_xy: Tuple[float, float] = (0.0, 0.0),
    size_m: Optional[Tuple[float, float]] = None,
) -> Path:
    """Write a flat translucent water plane model at Z=level.

    A simple visual approximation (no waves/refraction). By default the plane
    covers the whole terrain (single global level). Pass ``name``/``center_xy``/
    ``size_m`` to write a smaller, positioned plane for one basin -- the flat plane
    is occluded wherever the terrain rises above ``level``, so a per-basin plane
    sized a bit larger than the basin shows water only inside the bowl.
    """
    wdir = Path(models_dir) / name
    wdir.mkdir(parents=True, exist_ok=True)
    if size_m is None:
        sx, sy = extent_m[0] * 1.1, extent_m[1] * 1.1
    else:
        sx, sy = size_m
    cx, cy = center_xy
    (wdir / "model.config").write_text(
        f'<?xml version="1.0"?>\n<model>\n  <name>{name}</name>\n  <version>1.0</version>\n'
        f'  <sdf version="1.8">model.sdf</sdf>\n  <description>Flat water plane</description>\n</model>\n'
    )
    (wdir / "model.sdf").write_text(f'''<?xml version="1.0" ?>
<sdf version="1.8">
    <model name="{name}">
        <static>true</static>
        <pose>{cx:.3f} {cy:.3f} {level:.3f} 0 0 0</pose>
        <link name="link">
            <visual name="visual">
                <geometry><plane><normal>0 0 1</normal><size>{sx:.2f} {sy:.2f}</size></plane></geometry>
                <material>
                    <ambient>0.10 0.22 0.34 1</ambient>
                    <diffuse>0.12 0.32 0.46 0.78</diffuse>
                    <specular>0.5 0.5 0.6 1</specular>
                    <pbr><metal><metalness>0.1</metalness><roughness>0.12</roughness></metal></pbr>
                </material>
            </visual>
        </link>
    </model>
</sdf>''')
    return wdir


def write_basin_water_models(models_dir: Path, lakes: List[dict],
                             size_factor: float = 2.6) -> List[Path]:
    """Write one water plane per basin, each at its own suggested level.

    ``lakes`` is the list from terraingen's ``<dem>.lakes.json`` sidecar
    (``center_xy_m``, ``radius_m``, ``suggested_water_level``). Each plane is sized
    to ``size_factor * radius`` so it fills the bowl; the flat plane is hidden where
    the terrain rises above its level, so per-basin levels don't flood the rest of
    the map the way a single global plane does. Returns the written model dirs.
    """
    dirs = []
    for i, lk in enumerate(lakes):
        cx, cy = lk.get("center_xy_m", [0.0, 0.0])
        r = float(lk.get("radius_m", 30.0))
        level = float(lk.get("suggested_water_level", 0.0))
        s = size_factor * r
        dirs.append(write_water_model(
            models_dir, (0.0, 0.0), level,
            name=f"water_{i}", center_xy=(float(cx), float(cy)), size_m=(s, s),
        ))
    return dirs
