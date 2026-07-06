"""Heightmap relief ground (option d2): fractal relief + gz <heightmap> world."""

from xml.etree import ElementTree as ET

import numpy as np
from PIL import Image

from wildseed.core.heightmap import (
    build_heightmap_world, fractal_relief, generate_heightmap_world,
    is_pow2_plus_1, slope_stats, write_heightmap_png,
)


def test_is_pow2_plus_1():
    assert all(is_pow2_plus_1(n) for n in (129, 513, 1025, 2049))
    assert not any(is_pow2_plus_1(n) for n in (1000, 1024, 512, 100))


def test_fractal_relief_shape_and_range():
    a = fractal_relief(129, seed=7)
    assert a.shape == (129, 129)
    assert abs(a.min()) < 1e-9 and abs(a.max() - 1.0) < 1e-9  # normalized 0..1


def test_fractal_relief_deterministic():
    """Same (res, seed) -> byte-identical relief; different seed -> different."""
    assert np.array_equal(fractal_relief(129, 7), fractal_relief(129, 7))
    assert not np.array_equal(fractal_relief(129, 7), fractal_relief(129, 8))


def test_fractal_relief_macro_flat():
    """Low frequencies are skipped, so the coarse tilt across the patch is small."""
    a = fractal_relief(257, seed=3)
    # mean of each half should be close: no macro north/south tilt.
    top, bot = a[:128].mean(), a[129:].mean()
    assert abs(top - bot) < 0.15


def test_slope_stats_reports():
    a = fractal_relief(129, seed=7)
    s = slope_stats(a, extent=60.0, relief=0.35)
    assert s["relief_m"] <= 0.35 + 1e-6
    assert s["mean_slope_deg"] >= 0.0
    assert s["p95_slope_deg"] >= s["mean_slope_deg"]


def test_write_heightmap_png_is_pow2_plus_1(tmp_path):
    a = fractal_relief(129, seed=7)
    p = write_heightmap_png(a, tmp_path / "hm.png")
    img = np.asarray(Image.open(p))
    assert img.shape == (129, 129)
    assert is_pow2_plus_1(img.shape[0])


def test_build_world_has_heightmap_visual_and_collision(tmp_path):
    models = tmp_path / "models"
    (models / "ground" / "texture").mkdir(parents=True)
    a = fractal_relief(129, seed=7)
    png = write_heightmap_png(a, tmp_path / "hm.png")
    world = build_heightmap_world(png, tmp_path / "hm.world", extent=60.0,
                                  relief=0.35, models_dir=models, rig=False)
    root = ET.parse(world).getroot()
    link = root.find(".//model[@name='heightmap_terrain']/link")
    kinds = {el.tag: el for el in link if el.tag in ("visual", "collision")}
    assert "visual" in kinds and "collision" in kinds
    for el in kinds.values():
        assert el.find(".//heightmap") is not None
    # only the visual carries the texture skin
    assert kinds["visual"].find(".//heightmap/texture") is not None
    assert kinds["collision"].find(".//heightmap/texture") is None


def test_generate_heightmap_world_same_seed_identical_png(tmp_path):
    models = tmp_path / "models"
    (models / "ground" / "texture").mkdir(parents=True)

    def build(tag):
        info = generate_heightmap_world(
            tmp_path / f"{tag}.world", tmp_path / f"{tag}.png",
            extent=60.0, relief=0.35, res=129, seed=7,
            models_dir=models, rig=False)
        return info, (tmp_path / f"{tag}.png").read_bytes()

    (i1, b1), (i2, b2) = build("a"), build("b")
    assert b1 == b2                       # identical PNG bytes
    assert i1["pow2_plus_1"] is True
    assert i1["mean_slope_deg"] == i2["mean_slope_deg"]


def test_heightmap_cli_help():
    from click.testing import CliRunner
    from wildseed.cli.heightmap import heightmap
    res = CliRunner().invoke(heightmap, ["--help"])
    assert res.exit_code == 0
    for opt in ("--relief", "--seed", "--res", "--rig"):
        assert opt in res.output
