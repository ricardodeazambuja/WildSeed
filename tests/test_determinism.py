"""Byte-level determinism gates (docs/EXPERIMENT_PLAN.md D5/G4).

The reproducibility promise is BYTE-level: same spec -> same artifact hashes.
These tests pin the CPU-side prefix of that chain (resolution + DEM synth +
corridor map). The full-world gate (mesh + ground bake + placement, needing
Blender/GDAL/GPU) is exercised in-container; see docs/EXPERIMENTS.md.
"""

import hashlib

import pytest

from wildseed.core.experiment import ExperimentSpec, resolve_experiment
from wildseed.core.scenario import resolve_scenario
from wildseed.core.terraingen import GDAL_AVAILABLE


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_resolution_is_pure():
    """Resolving is a pure function of (seed, knobs) — no hidden global state."""
    a = [resolve_scenario(s, profile="vio_lio", photometric=0.5) for s in (1, 2, 3)]
    b = [resolve_scenario(s, profile="vio_lio", photometric=0.5) for s in (3, 2, 1)]
    assert a == list(reversed(b))
    spec = ExperimentSpec(hypothesis="h", seed=5, dials={"texture": 0.0})
    assert resolve_experiment(spec) == resolve_experiment(spec)


@pytest.mark.skipif(not GDAL_AVAILABLE, reason="GDAL not installed")
def test_dem_synthesis_is_byte_deterministic(tmp_path):
    """Same resolved spec -> byte-identical GeoTIFF, twice in one process."""
    from wildseed.config.schema import TerrainGenConfig
    from wildseed.core.terraingen import synthesize_dem

    spec = resolve_scenario(7, profile="vio_lio")
    hashes = []
    for name in ("a.tif", "b.tif"):
        cfg = TerrainGenConfig(preset=spec["preset"],
                               seed=spec["stage_seeds"]["terraingen"],
                               resolution=96, pixel_m=spec["pixel_m"],
                               **spec["terrain_knobs"])
        synthesize_dem(cfg, tmp_path / name)
        hashes.append(_sha(tmp_path / name))
    assert hashes[0] == hashes[1]


def test_corridor_map_is_byte_deterministic(tmp_path):
    from wildseed.core.density_maps import build_corridor_map, save_png
    imgs = [build_corridor_map(300.0, 8.0, y0=0.0, res=512, soft=True)
            for _ in range(2)]
    paths = [save_png(img, tmp_path / f"c{i}.png") for i, img in enumerate(imgs)]
    assert _sha(paths[0]) == _sha(paths[1])
