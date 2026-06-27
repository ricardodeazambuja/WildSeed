"""Guards that placement seeding is wired (reproducible scenarios for VIO)."""

import inspect

from forest3d.core.forest import WorldPopulator


def test_world_populator_accepts_seed():
    sig = inspect.signature(WorldPopulator.__init__)
    assert "seed" in sig.parameters


def test_generate_cli_exposes_seed():
    from forest3d.cli.generate import generate
    names = {p.name for p in generate.params}
    assert "seed" in names
