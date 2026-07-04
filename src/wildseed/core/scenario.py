"""Master-seed scenario orchestration.

One master seed deterministically drives every stage of world generation:

    SeedSequence(master) --spawn--> [param stream, terraingen seed, ground seed,
                                     placement seed]

The param stream picks the biome, terrain preset, terrain knobs and densities
inside per-biome envelopes; the three stage seeds feed the existing stage RNGs
(``terraingen --seed``, ``ground --seed``, ``generate --seed``) unchanged. Every
resolved value is written to ``scenario.yaml`` next to the world, so any world is
reproducible from the master seed (plus the explicit CLI overrides) alone.

SCENARIO_FORMAT versions the resolution scheme: the mapping seed -> world is only
stable within a format version (editing BIOME_SPACE or the draw order changes what
a seed resolves to, and must bump it).
"""

import logging
import shutil
from pathlib import Path
from typing import Dict, List, Optional
from xml.etree import ElementTree as ET

import numpy as np
import yaml

logger = logging.getLogger("wildseed.scenario")

# 3: terrain_knobs gained max_mean_slope_deg (ground-robot slope cap, default
#    20°) — same seed yields the same layout but capped relief vs format 2.
SCENARIO_FORMAT = 3

# Wilderness biomes: random scatter, subject to the >=3-tree/>=2-understory
# species-variety floor (repeated-model aliasing is the enemy there).
WILD_BIOMES = ("temperate", "savanna", "wetland", "alpine", "winter", "coastal")
# Structured biomes: row plantations inspired by CropCraft's bed engine
# (INRAE, Apache-2.0 — see README Credits). Deliberately monoculture +
# repetitive — the hardest case for place recognition / loop closure, which
# is exactly why a VIO/LIO test suite wants them.
STRUCTURED_BIOMES = ("orchard", "vineyard")
BIOME_NAMES = WILD_BIOMES + STRUCTURED_BIOMES

# Per-biome envelopes. Centre values mirror the tuned demo scenarios
# (tools/build_scenarios.py + docs/DEMO_REALISM_V2_REPORT.md); the ranges give
# seed-to-seed variety without leaving the envelope the demos proved renders well
# at robot scale. `knobs` are terraingen overrides drawn uniformly from (lo, hi);
# knobs a biome's demo never set are left to the preset defaults.
BIOME_SPACE = {
    "temperate": dict(
        presets=("hilly", "valley"),
        knobs=dict(amplitude_m=(15, 35), feature_m=(90, 140),
                   detail=(0.08, 0.16), smooth_sigma=(1.4, 1.8)),
        ground="grassland", water=False,
        density=dict(tree=120, rock=45, bush=150, grass=300)),
    "savanna": dict(
        presets=("hilly", "flat"),
        knobs=dict(amplitude_m=(6, 16), feature_m=(120, 160),
                   detail=(0.06, 0.14), smooth_sigma=(1.6, 2.0)),
        ground="desert", water=False,
        density=dict(tree=60, rock=42, bush=200, grass=380)),
    "wetland": dict(
        presets=("lakeland",),
        knobs=dict(feature_m=(110, 150), detail=(0.08, 0.16),
                   smooth_sigma=(1.4, 1.8)),
        ground="grassland", water=True,
        density=dict(tree=100, rock=38, bush=160, grass=240)),
    "alpine": dict(
        presets=("mountainous",),
        knobs=dict(amplitude_m=(60, 100), feature_m=(70, 110), detail=(0.2, 0.4),
                   smooth_sigma=(1.0, 1.4), ridged=(0.2, 0.45)),
        ground="snow", water=False,
        density=dict(tree=70, rock=75, bush=55, grass=120)),
    "winter": dict(
        presets=("valley", "hilly"),
        knobs=dict(amplitude_m=(15, 30), feature_m=(80, 120),
                   detail=(0.12, 0.24), smooth_sigma=(1.3, 1.7)),
        ground="snow", water=False,
        density=dict(tree=115, rock=42, bush=0, grass=140)),
    "coastal": dict(
        presets=("hilly", "flat"),
        knobs=dict(amplitude_m=(4, 10), feature_m=(130, 170),
                   detail=(0.06, 0.12), smooth_sigma=(1.8, 2.2)),
        ground="desert", water=False,
        density=dict(tree=45, rock=30, bush=130, grass=220)),
    # Structured plantations (CropCraft-inspired). `rows` plants that category
    # in regular rows instead of scattering it; row params are drawn from the
    # envelopes below and recorded in scenario.yaml like every other knob.
    "orchard": dict(
        presets=("flat", "hilly"),
        knobs=dict(amplitude_m=(3, 9), feature_m=(140, 180),
                   detail=(0.05, 0.10), smooth_sigma=(1.8, 2.2)),
        ground="grassland", water=False,
        density=dict(tree=0, rock=8, bush=25, grass=200),
        rows=dict(tree=dict(row_distance=(5.0, 8.0), plant_distance=(3.5, 5.5),
                            field_size=(60, 95), angle=(0.0, 3.1416),
                            jitter=(0.08, 0.25), missing=(0.03, 0.12),
                            wave_amplitude=(0.0, 1.5)))),
    "vineyard": dict(
        presets=("flat", "hilly"),
        knobs=dict(amplitude_m=(2, 7), feature_m=(140, 180),
                   detail=(0.05, 0.10), smooth_sigma=(1.8, 2.2)),
        ground="desert", water=False,
        density=dict(tree=10, rock=10, bush=0, grass=120),
        rows=dict(bush=dict(row_distance=(2.2, 3.2), plant_distance=(1.2, 1.8),
                            field_size=(45, 70), angle=(0.0, 3.1416),
                            jitter=(0.04, 0.12), missing=(0.02, 0.10),
                            wave_amplitude=(0.0, 0.8)))),
}

# Density counts jitter by this factor range around the biome base (then scale by
# --density-scale), so two seeds of the same biome differ in population too.
DENSITY_JITTER = (0.75, 1.25)


def _stage_seed(seed_seq: np.random.SeedSequence) -> int:
    return int(seed_seq.generate_state(1)[0])


def resolve_scenario(
        seed: int,
        biome: Optional[str] = None,
        preset: Optional[str] = None,
        density_scale: float = 1.0,
        size: int = 192,
        pixel_m: float = 1.6,
        max_slope_deg: float = 20.0,
) -> dict:
    """Deterministically resolve a master seed into a full scenario spec.

    Same (seed, biome, preset, density_scale, size, pixel_m) -> identical spec.
    Explicit biome/preset overrides don't consume different draw counts for the
    remaining knobs: every draw happens unconditionally, overrides just replace
    the drawn value, so `--biome temperate --seed 7` shares its terrain knobs
    with whatever seed 7 would draw for temperate at random.
    """
    ss = np.random.SeedSequence(seed)
    param_ss, tg_ss, ground_ss, place_ss = ss.spawn(4)
    rng = np.random.default_rng(param_ss)

    drawn_biome = BIOME_NAMES[int(rng.integers(len(BIOME_NAMES)))]
    use_biome = biome or drawn_biome
    if use_biome not in BIOME_SPACE:
        raise ValueError(f"unknown biome {use_biome!r}; expected one of {BIOME_NAMES}")
    space = BIOME_SPACE[use_biome]

    presets = space["presets"]
    drawn_preset = presets[int(rng.integers(len(presets)))]
    use_preset = preset or drawn_preset

    knobs = {k: round(float(rng.uniform(lo, hi)), 3)
             for k, (lo, hi) in sorted(space["knobs"].items())}
    # Ground-robot slope cap (terraingen rescales relief to meet it — see
    # TerrainSynthesizer step 6b). Scenario worlds host robots, so it is ON by
    # default; 0 disables (aerial/scenery). Applied AFTER the draws above so it
    # consumes no RNG — same seed, same layout, gentler relief. format 3.
    knobs["max_mean_slope_deg"] = float(max_slope_deg)

    density = {}
    for cat in ("tree", "rock", "bush", "grass"):
        base = space["density"][cat]
        jitter = float(rng.uniform(*DENSITY_JITTER))
        density[cat] = int(round(base * jitter * density_scale))

    # Structured-row envelopes (orchard/vineyard): draw every row param the
    # same way terrain knobs are drawn, in sorted key order.
    rows = {}
    for cat, envelope in sorted(space.get("rows", {}).items()):
        drawn = {}
        for key, (lo, hi) in sorted(envelope.items()):
            drawn[key] = round(float(rng.uniform(lo, hi)), 3)
        rows[cat] = drawn

    return {
        "scenario_format": SCENARIO_FORMAT,
        "seed": int(seed),
        "biome": use_biome,
        "preset": use_preset,
        "ground_biome": space["ground"],
        "water": bool(space["water"]),
        "size": int(size),
        "pixel_m": float(pixel_m),
        "density_scale": float(density_scale),
        "terrain_knobs": knobs,
        "density": density,
        "rows": rows,
        "stage_seeds": {
            "terraingen": _stage_seed(tg_ss),
            "ground": _stage_seed(ground_ss),
            "placement": _stage_seed(place_ss),
        },
    }


def palette_from_manifest(manifest_path: Path, biome: str) -> Dict[str, List[str]]:
    """Read the per-biome model palette from assets/manifest.yaml."""
    man = yaml.safe_load(Path(manifest_path).read_text())
    pal = man["biomes"][biome]
    return {
        "tree": list(pal.get("trees", [])),
        "bush": list(pal.get("bushes", [])),
        "grass": list(pal.get("grasses", [])),
        "rock": list(pal.get("rocks", [])),
    }


def _append_water_includes(world_path: Path, n_basins: int) -> None:
    """Add one <include> per basin water model to a generated world."""
    tree = ET.parse(world_path)
    world = tree.getroot().find("world")
    for i in range(n_basins):
        inc = ET.SubElement(world, "include")
        ET.SubElement(inc, "uri").text = f"model://water_{i}"
        ET.SubElement(inc, "name").text = f"water_{i}"
        ET.SubElement(inc, "pose").text = "0 0 0 0 0 0"
    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    tree.write(str(world_path), encoding="utf-8", xml_declaration=True)


def run_scenario(
        spec: dict,
        base_path: Path,
        manifest_path: Path,
        texture_root: Optional[Path] = None,
        progress_callback=None,
) -> dict:
    """Build the world a resolved spec describes: terraingen -> terrain -> ground
    (+ per-basin water) -> generate. Returns paths of everything written."""
    from wildseed.config.loader import load_config
    from wildseed.config.schema import GroundConfig, TerrainGenConfig
    from wildseed.core.terraingen import synthesize_dem
    from wildseed.core.terrain import TerrainGenerator
    from wildseed.core.ground import (GroundCompositor, write_basin_water_models)
    from wildseed.core.forest import WorldPopulator

    base_path = Path(base_path)
    seeds = spec["stage_seeds"]

    # 1. synthesize the landform
    dem_path = base_path / "dem" / f"scenario_{spec['seed']}.tif"
    dem_path.parent.mkdir(parents=True, exist_ok=True)
    tg_cfg = TerrainGenConfig(preset=spec["preset"], seed=seeds["terraingen"],
                              resolution=spec["size"], pixel_m=spec["pixel_m"],
                              **spec["terrain_knobs"])
    tg_info = synthesize_dem(tg_cfg, dem_path)
    logger.info(f"DEM: {tg_info['out']} extent={tg_info['extent_m']} m "
                f"relief={tg_info['z_extent']} m lakes={len(tg_info['lakes'])}")

    # 2. mesh it
    config = load_config(None)
    generator = TerrainGenerator(tif_path=dem_path,
                                 output_path=base_path / "models" / "ground",
                                 config=config.terrain,
                                 blender_path=config.blender.path)
    generator.process_terrain()

    # 3. ground material (+ water)
    gc = GroundConfig(mode="patchy", biome=spec["ground_biome"], seed=seeds["ground"])
    troot = Path(texture_root) if texture_root else base_path / "Blender-Assets" / "soil"
    comp = GroundCompositor(ground_dir=base_path / "models" / "ground",
                            texture_root=troot, config=gc)
    comp.generate()

    lakes = tg_info["lakes"] if spec["water"] else []
    if lakes:
        write_basin_water_models(base_path / "models", lakes)

    # 4. populate (palette-constrained, placement-seeded; structured biomes
    # plant their rows category in rows, everything else scatters)
    palette = palette_from_manifest(manifest_path, spec["biome"])
    populator = WorldPopulator(base_path=base_path, seed=seeds["placement"],
                               variants=palette, progress_callback=progress_callback)
    world_path = populator.create_forest_world(dict(spec["density"]),
                                               rows_config=spec.get("rows") or None)

    # 5. finalize: name the world after the seed, add water, record the spec
    out_world = base_path / "worlds" / f"scenario_{spec['seed']}.world"
    shutil.move(str(world_path), str(out_world))
    gt_src = world_path.with_name(world_path.stem + ".instances.json")
    out_gt = out_world.with_name(out_world.stem + ".instances.json")
    if gt_src.exists():
        shutil.move(str(gt_src), str(out_gt))
    if lakes:
        _append_water_includes(out_world, len(lakes))

    spec_path = out_world.with_suffix(".yaml")
    record = dict(spec)
    record["outputs"] = {
        "world": str(out_world),
        "dem": str(dem_path),
        "lakes": len(lakes),
        "instances": str(out_gt),
    }
    record["palette"] = palette
    spec_path.write_text(yaml.safe_dump(record, sort_keys=False))

    return {"world": out_world, "spec": spec_path, "dem": dem_path,
            "instances": out_gt, "lakes": len(lakes),
            "stats": populator.get_model_statistics()}
