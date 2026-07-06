"""Grayscale density-map placement: pixel intensity steers where models go."""

import numpy as np
import pytest
from PIL import Image

from wildseed.core.forest import WorldPopulator


@pytest.fixture
def tiny_world(tmp_path):
    """Minimal base_path: a flat 2-triangle terrain + empty model dirs."""
    from stl import mesh as stl_mesh
    ground_mesh = tmp_path / "models" / "ground" / "mesh"
    ground_mesh.mkdir(parents=True)
    data = np.zeros(2, dtype=stl_mesh.Mesh.dtype)
    s = 40.0  # 80x80 m flat square at z=0
    data["vectors"][0] = [[-s, -s, 0], [s, -s, 0], [s, s, 0]]
    data["vectors"][1] = [[-s, -s, 0], [s, s, 0], [-s, s, 0]]
    stl_mesh.Mesh(data).save(str(ground_mesh / "terrain.stl"))
    for cat, models in {"tree": ["oak"], "grass": ["g1"]}.items():
        for m in models:
            (tmp_path / "models" / cat / m).mkdir(parents=True)
    (tmp_path / "worlds").mkdir()
    return tmp_path


def _map_png(path, arr):
    Image.fromarray(arr.astype(np.uint8), mode="L").save(path)
    return path


def _placed_xy(populator, category):
    return [(x, y) for x, y, _, _ in populator.placed_models[category]]


def test_half_black_map_confines_placement(tiny_world, tmp_path):
    """Left half black, right half white -> every instance lands at x >= 0."""
    arr = np.zeros((64, 64))
    arr[:, 32:] = 255
    mp = _map_png(tmp_path / "east.png", arr)
    pop = WorldPopulator(base_path=tiny_world, seed=7,
                         density_maps={"grass": mp})
    pop.create_forest_world({"grass": 40, "tree": 0})
    xy = _placed_xy(pop, "grass")
    assert len(xy) >= 30  # dense white half: nearly all should place
    assert all(x >= 0.0 for x, _ in xy)


def test_north_up_orientation(tiny_world, tmp_path):
    """Row 0 of the image is the +Y edge: white top half -> placements y >= 0."""
    arr = np.zeros((64, 64))
    arr[:32, :] = 255  # top half white
    mp = _map_png(tmp_path / "north.png", arr)
    pop = WorldPopulator(base_path=tiny_world, seed=7,
                         density_maps={"grass": mp})
    pop.create_forest_world({"grass": 30, "tree": 0})
    assert all(y >= 0.0 for _, y in _placed_xy(pop, "grass"))


def test_star_fallback_applies_to_unmapped_categories(tiny_world, tmp_path):
    arr = np.zeros((32, 32))
    arr[:, 16:] = 255
    mp = _map_png(tmp_path / "east.png", arr)
    pop = WorldPopulator(base_path=tiny_world, seed=3,
                         density_maps={"*": mp})
    pop.create_forest_world({"grass": 20, "tree": 5})
    for cat in ("grass", "tree"):
        assert all(x >= 0.0 for x, _ in _placed_xy(pop, cat)), cat


def test_seeded_map_placement_is_reproducible(tiny_world, tmp_path):
    arr = (np.linspace(0, 255, 64)[None, :] * np.ones((64, 1)))
    mp = _map_png(tmp_path / "grad.png", arr)

    def build():
        pop = WorldPopulator(base_path=tiny_world, seed=11,
                             density_maps={"grass": mp, "tree": mp})
        return pop.create_forest_world({"grass": 25, "tree": 6}).read_text()

    assert build() == build()


def test_gradient_map_biases_density(tiny_world, tmp_path):
    """Linear west->east ramp: mean x of placements must be clearly east."""
    arr = (np.linspace(0, 255, 64)[None, :] * np.ones((64, 1)))
    mp = _map_png(tmp_path / "grad.png", arr)
    pop = WorldPopulator(base_path=tiny_world, seed=5,
                         density_maps={"grass": mp})
    pop.create_forest_world({"grass": 60, "tree": 0})
    xs = [x for x, _ in _placed_xy(pop, "grass")]
    # ramp weighting puts the expectation at +1/6 of the extent (~13 m of 80)
    assert np.mean(xs) > 5.0


def test_all_black_map_rejected(tiny_world, tmp_path):
    mp = _map_png(tmp_path / "black.png", np.zeros((16, 16)))
    with pytest.raises(ValueError, match="all black"):
        WorldPopulator(base_path=tiny_world, seed=1, density_maps={"grass": mp})


def test_generate_cli_exposes_density_maps():
    from wildseed.cli.generate import generate
    names = {p.name for p in generate.params}
    assert "density_maps" in names


# --------------------------------------------------------------- corridor map --

def test_corridor_map_white_band_at_y0():
    """A hard corridor is white exactly where |world_y - y0| <= half_width."""
    from wildseed.core.density_maps import build_corridor_map
    extent, hw = 80.0, 8.0
    img = build_corridor_map(extent, hw, y0=0.0, res=256)
    # centre row is +/- extent/2 mapped; row for world_y=0 is the middle.
    mid = img.shape[0] // 2
    assert img[mid].min() == 255           # centre band fully white
    assert img[0].max() == 0 and img[-1].max() == 0  # edges (|y|=40) black
    # white fraction ~ (2*hw)/extent = 16/80 = 0.20
    frac = (img > 12).mean()
    assert abs(frac - (2 * hw / extent)) < 0.02


def test_corridor_map_offset_y0():
    """Shifting y0 north moves the band toward row 0 (the +Y edge)."""
    from wildseed.core.density_maps import build_corridor_map
    img = build_corridor_map(80.0, 6.0, y0=20.0, res=256)
    rows = np.where(img.max(axis=1) == 255)[0]
    # y0=+20 of +/-40 extent -> upper quarter (rows well above the middle).
    assert rows.mean() < img.shape[0] * 0.4


def test_corridor_map_soft_tapers():
    """--soft gives a smooth peak-at-centre profile, not a hard 0/255 edge."""
    from wildseed.core.density_maps import build_corridor_map
    hard = build_corridor_map(80.0, 8.0, res=128, soft=False)
    soft = build_corridor_map(80.0, 8.0, res=128, soft=True)
    col_soft = soft[:, 0].astype(float)
    mid = 64
    assert col_soft[mid] >= 250                       # near-peak white at centre
    assert col_soft[mid] == col_soft.max()            # centre is the maximum
    assert col_soft[mid - 12] < col_soft[mid] - 30    # graded shoulder, clearly lower
    assert 0 < col_soft[mid - 12] < 255               # (a hard edge would be 0 or 255)
    assert set(np.unique(hard[:, 0])) <= {0, 255}     # hard is strictly binary


def test_corridor_map_deterministic_no_seed():
    """Shape is fully determined by geometry — no RNG."""
    from wildseed.core.density_maps import build_corridor_map
    a = build_corridor_map(120.0, 10.0, y0=3.0, res=200, soft=True)
    b = build_corridor_map(120.0, 10.0, y0=3.0, res=200, soft=True)
    assert np.array_equal(a, b)


def test_terrain_extent_y_reads_obj(tmp_path):
    from wildseed.core.density_maps import terrain_extent_y
    obj = tmp_path / "terrain.obj"
    obj.write_text("v -30 -25 1\nv 30 25 2\nvn 0 0 1\nv 0 5 0\n")
    assert terrain_extent_y(obj) == (-25.0, 25.0)


def test_corridor_map_cli_help():
    """CLI renders --help without error and exposes the key options."""
    from click.testing import CliRunner
    from wildseed.cli.corridor_map import corridor_map
    res = CliRunner().invoke(corridor_map, ["--help"])
    assert res.exit_code == 0
    for opt in ("--half-width", "--y0", "--soft", "--extent"):
        assert opt in res.output


def test_corridor_map_cli_writes_png(tmp_path):
    from click.testing import CliRunner
    from wildseed.cli.corridor_map import corridor_map
    out = tmp_path / "c.png"
    ctx = {"console": __import__("rich.console", fromlist=["Console"]).Console()}
    res = CliRunner().invoke(
        corridor_map,
        ["--out", str(out), "--extent", "80", "--half-width", "8", "--res", "64"],
        obj=ctx)
    assert res.exit_code == 0, res.output
    assert out.exists()
    img = np.asarray(Image.open(out))
    assert img.shape == (64, 64)
