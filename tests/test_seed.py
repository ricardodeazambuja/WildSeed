"""Guards that placement seeding is wired (reproducible scenarios for VIO)."""

import inspect

import numpy as np
import pytest

from wildseed.core.forest import WorldPopulator


def test_world_populator_accepts_seed():
    sig = inspect.signature(WorldPopulator.__init__)
    assert "seed" in sig.parameters


def test_generate_cli_exposes_seed():
    from wildseed.cli.generate import generate
    names = {p.name for p in generate.params}
    assert "seed" in names


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
    for cat, models in {"tree": ["oak", "pine"], "rock": ["r1"],
                        "bush": ["b1", "b2"], "grass": ["g1"]}.items():
        for m in models:
            (tmp_path / "models" / cat / m).mkdir(parents=True)
    (tmp_path / "worlds").mkdir()
    return tmp_path


DENSITY = {"tree": 8, "rock": 4, "bush": 6, "grass": 10}


def _build(base, seed, variants=None):
    populator = WorldPopulator(base_path=base, seed=seed, variants=variants)
    path = populator.create_forest_world(dict(DENSITY))
    return path.read_text()


def test_same_seed_identical_world(tiny_world):
    assert _build(tiny_world, 42) == _build(tiny_world, 42)


def test_different_seed_different_world(tiny_world):
    assert _build(tiny_world, 42) != _build(tiny_world, 43)


def test_variants_palette_constrains_placement(tiny_world):
    world = _build(tiny_world, 42, variants={"tree": ["oak"]})
    assert "model://tree/oak" in world
    assert "model://tree/pine" not in world


def test_instances_ground_truth_written(tiny_world):
    import json
    populator = WorldPopulator(base_path=tiny_world, seed=42)
    world_path = populator.create_forest_world(dict(DENSITY))
    gt_path = world_path.with_name(world_path.stem + ".instances.json")
    assert gt_path.exists()
    gt = json.loads(gt_path.read_text())
    assert gt["seed"] == 42
    # every include except the terrain itself must be ground-truthed
    assert gt["count"] == len(gt["instances"]) \
        == world_path.read_text().count("<include>") - 1
    inst = gt["instances"][0]
    assert set(inst) == {"name", "category", "model", "pose", "scale"}
    assert set(inst["pose"]) == {"x", "y", "z", "roll", "pitch", "yaw"}
    # names must be unique (gz requires unique entity names)
    names = [i["name"] for i in gt["instances"]]
    assert len(names) == len(set(names))


def test_rows_placement_structured_and_deterministic(tiny_world):
    import json
    rows = {"tree": {"row_distance": 6.0, "plant_distance": 4.0, "field_size": 40,
                     "jitter": 0.0, "missing": 0.0, "angle": 0.0, "yaw": "aligned"}}

    def build():
        populator = WorldPopulator(base_path=tiny_world, seed=7)
        path = populator.create_forest_world({"grass": 5}, rows_config=rows)
        gt = json.loads(path.with_name(path.stem + ".instances.json").read_text())
        return path.read_text(), gt

    world_a, gt_a = build()
    world_b, _ = build()
    assert world_a == world_b, "rows placement must be seed-deterministic"
    trees = [i for i in gt_a["instances"] if i["category"] == "tree"]
    # 40 m field, 6 m rows x 4 m spacing -> a 7x11 grid (inclusive endpoints)
    assert len(trees) == 7 * 11
    # zero jitter -> every tree y sits exactly on a row line; x on plant grid
    ys = sorted({round(t["pose"]["y"], 3) for t in trees})
    assert len(ys) == 7
    # aligned yaw stays near the row angle (sigma 0.08)
    assert all(abs(t["pose"]["yaw"]) < 0.5 for t in trees)


def test_rows_missing_dropout(tiny_world):
    import json
    rows = {"tree": {"row_distance": 6.0, "plant_distance": 4.0, "field_size": 40,
                     "jitter": 0.0, "missing": 0.5}}
    populator = WorldPopulator(base_path=tiny_world, seed=7)
    path = populator.create_forest_world({}, rows_config=rows)
    gt = json.loads(path.with_name(path.stem + ".instances.json").read_text())
    n = len([i for i in gt["instances"] if i["category"] == "tree"])
    assert 15 <= n <= 62, f"50% dropout of 77 slots should land well inside (15, 62), got {n}"


def test_vio_lio_seed_reproducible_and_seed_sensitive():
    """The recipe spec is a pure function of (seed + knobs): same seed -> identical,
    different seed -> different placement/relief."""
    from wildseed.core.scenario import resolve_scenario
    a = resolve_scenario(7, profile="vio_lio")
    assert a == resolve_scenario(7, profile="vio_lio")
    b = resolve_scenario(8, profile="vio_lio")
    # different placement seed AND different terrain -> a genuinely different world
    assert a["stage_seeds"]["placement"] != b["stage_seeds"]["placement"]
    assert a["terrain_knobs"] != b["terrain_knobs"]


def test_vio_lio_variety_dial_changes_variant_count():
    """--variety monotonically changes the recolour-variant count (uniqueness)."""
    from wildseed.core.scenario import resolve_scenario
    counts = [resolve_scenario(7, profile="vio_lio", variety=v)["variant_count"]
              for v in (0.0, 0.5, 1.0)]
    assert counts[0] < counts[-1]
    assert counts == sorted(counts)


def test_variant_order_does_not_depend_on_listing_order(tiny_world, monkeypatch):
    """Placement must not change with filesystem iteration order (it is OS/
    filesystem dependent); model listings are sorted before any RNG use."""
    baseline = _build(tiny_world, 42)

    from pathlib import Path
    real_iterdir = Path.iterdir

    def reversed_iterdir(self):
        return iter(sorted(real_iterdir(self), key=lambda p: p.name, reverse=True))

    monkeypatch.setattr(Path, "iterdir", reversed_iterdir)
    assert _build(tiny_world, 42) == baseline
