"""Guards that placement seeding is wired (reproducible scenarios for VIO)."""

import inspect

import numpy as np
import pytest

from forest3d.core.forest import WorldPopulator


def test_world_populator_accepts_seed():
    sig = inspect.signature(WorldPopulator.__init__)
    assert "seed" in sig.parameters


def test_generate_cli_exposes_seed():
    from forest3d.cli.generate import generate
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
