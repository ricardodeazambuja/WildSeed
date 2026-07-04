"""Master-seed scenario resolution: deterministic, seed-sensitive, well-formed."""

import pytest

from wildseed.core.scenario import (BIOME_NAMES, BIOME_SPACE, SCENARIO_FORMAT,
                                    STRUCTURED_BIOMES, WILD_BIOMES,
                                    palette_from_manifest, resolve_scenario)


def test_same_seed_same_spec():
    a = resolve_scenario(42)
    b = resolve_scenario(42)
    assert a == b


def test_different_seed_different_spec():
    a = resolve_scenario(42)
    b = resolve_scenario(43)
    assert a != b
    # the stage seeds must differ too (not just the drawn params)
    assert a["stage_seeds"] != b["stage_seeds"]


def test_stage_seeds_are_independent():
    seeds = resolve_scenario(7)["stage_seeds"]
    assert len(set(seeds.values())) == 3, "spawned stage seeds must not collide"


def test_biome_override_keeps_format_and_knob_envelope():
    spec = resolve_scenario(7, biome="alpine")
    assert spec["biome"] == "alpine"
    assert spec["scenario_format"] == SCENARIO_FORMAT
    space = BIOME_SPACE["alpine"]
    for knob, (lo, hi) in space["knobs"].items():
        assert lo <= spec["terrain_knobs"][knob] <= hi
    assert spec["preset"] in space["presets"]


def test_explicit_preset_override_wins():
    spec = resolve_scenario(7, biome="temperate", preset="flat")
    assert spec["preset"] == "flat"


def test_density_scale_scales_counts():
    base = resolve_scenario(7, biome="temperate")
    double = resolve_scenario(7, biome="temperate", density_scale=2.0)
    for cat, count in base["density"].items():
        assert double["density"][cat] == pytest.approx(count * 2, abs=1)


def test_all_biomes_resolve():
    for biome in BIOME_NAMES:
        spec = resolve_scenario(1, biome=biome)
        assert spec["ground_biome"] in ("grassland", "desert", "gravel", "snow")
        assert all(v >= 0 for v in spec["density"].values())


def test_unknown_biome_raises():
    with pytest.raises(ValueError):
        resolve_scenario(1, biome="lunar")


def test_scenario_cli_registered():
    from wildseed.cli.main import main
    assert "scenario" in main.commands


def test_palette_from_manifest_covers_dod(tmp_path=None):
    """Every WILD biome palette must give placement >=3 tree + >=2 understory
    species (the variety floor that breaks repeated-model VIO feature
    aliasing). Structured biomes (orchard/vineyard) are deliberately
    monoculture — they only need a non-empty palette."""
    from pathlib import Path
    manifest = Path(__file__).parent.parent / "assets" / "manifest.yaml"
    if not manifest.exists():
        pytest.skip("assets/manifest.yaml not present")
    for biome in WILD_BIOMES:
        pal = palette_from_manifest(manifest, biome)
        assert len(pal["tree"]) >= 3, f"{biome}: <3 tree species"
        assert len(pal["bush"]) + len(pal["grass"]) >= 2, f"{biome}: <2 understory species"
    for biome in STRUCTURED_BIOMES:
        pal = palette_from_manifest(manifest, biome)
        assert any(pal.values()), f"{biome}: empty palette"


def test_structured_biomes_resolve_rows_within_envelope():
    for biome in STRUCTURED_BIOMES:
        spec = resolve_scenario(11, biome=biome)
        assert spec["rows"], f"{biome}: no rows drawn"
        for cat, drawn in spec["rows"].items():
            envelope = BIOME_SPACE[biome]["rows"][cat]
            for key, val in drawn.items():
                lo, hi = envelope[key]
                assert lo <= val <= hi, f"{biome}.{cat}.{key}={val} outside ({lo},{hi})"
        # the rows category must not also be scattered
        for cat in spec["rows"]:
            assert spec["density"][cat] == 0, f"{biome}: {cat} both rowed and scattered"


def test_wild_biomes_have_no_rows():
    for biome in WILD_BIOMES:
        assert resolve_scenario(11, biome=biome)["rows"] == {}


def test_format_bumped_for_structured_biomes():
    assert SCENARIO_FORMAT >= 2


def test_max_slope_in_spec_and_consumes_no_rng():
    from wildseed.core.scenario import resolve_scenario
    a = resolve_scenario(42)
    b = resolve_scenario(42, max_slope_deg=0.0)
    assert a["terrain_knobs"]["max_mean_slope_deg"] == 20.0   # scenario default ON
    assert b["terrain_knobs"]["max_mean_slope_deg"] == 0.0
    # the cap must not consume RNG draws: every other knob identical
    ka = {k: v for k, v in a["terrain_knobs"].items() if k != "max_mean_slope_deg"}
    kb = {k: v for k, v in b["terrain_knobs"].items() if k != "max_mean_slope_deg"}
    assert ka == kb and a["density"] == b["density"]
    assert a["scenario_format"] == 3
