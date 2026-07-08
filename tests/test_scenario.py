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
    assert len(set(seeds.values())) == 4, "spawned stage seeds must not collide"


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
    assert a["scenario_format"] == 4


# --------------------------------------------------------- vio_lio profile ----

def test_vio_lio_profile_reproducible_and_well_formed():
    from wildseed.core.scenario import resolve_scenario
    a = resolve_scenario(7, profile="vio_lio")
    b = resolve_scenario(7, profile="vio_lio")
    assert a == b                                   # reproducible
    assert a["profile"] == "vio_lio"
    assert a["water"] is False                      # drivable recipe, no lakes
    assert a["preset"] == "flat"                    # drivable macro
    assert a["biome"] in WILD_BIOMES                # palette/ground only
    assert sum(a["density"].values()) == a["object_density"] == 175
    assert a["density"]["grass"] == 0               # grass -> patchy ground texture
    assert a["corridor"]["half_width"] == 8.0 and a["corridor"]["soft"] is True
    assert a["rig"]["z"] == 2.0
    assert set(a["stage_seeds"]) == {"terraingen", "ground", "placement",
                                     "texrand", "sun"}
    assert a["terrain_knobs"]["max_mean_slope_deg"] == 20.0


def test_vio_lio_knobs_flow_through():
    from wildseed.core.scenario import resolve_scenario
    s = resolve_scenario(7, profile="vio_lio", object_density=200,
                         corridor_width=5.0)
    assert sum(s["density"].values()) == 200
    assert s["corridor"]["half_width"] == 5.0


def test_vio_lio_variety_monotonic_variant_count():
    from wildseed.core.scenario import resolve_scenario
    counts = [resolve_scenario(7, profile="vio_lio", variety=v)["variant_count"]
              for v in (0.0, 0.3, 0.6, 1.0)]
    assert counts == sorted(counts)                 # non-decreasing
    assert counts[0] == 0 and counts[-1] == 3       # 0..3 recolour variants


def test_vio_lio_relief_and_variety_scale_terrain():
    from wildseed.core.scenario import resolve_scenario
    lo = resolve_scenario(7, profile="vio_lio", relief=0.0, variety=0.0)
    hi = resolve_scenario(7, profile="vio_lio", relief=1.0, variety=1.0)
    assert hi["terrain_knobs"]["amplitude_m"] > lo["terrain_knobs"]["amplitude_m"]
    assert hi["terrain_knobs"]["detail"] > lo["terrain_knobs"]["detail"]


def test_vio_lio_different_seed_differs_same_identical():
    from wildseed.core.scenario import resolve_scenario
    assert resolve_scenario(7, profile="vio_lio") != resolve_scenario(8, profile="vio_lio")
    assert resolve_scenario(7, profile="vio_lio") == resolve_scenario(7, profile="vio_lio")


def test_profile_none_path_unchanged():
    """The default biome resolution is untouched by the profile plumbing."""
    from wildseed.core.scenario import resolve_scenario
    s = resolve_scenario(7)
    assert "profile" not in s
    assert len(s["stage_seeds"]) == 4  # terraingen, ground, placement, sun


def test_unknown_profile_raises():
    from wildseed.core.scenario import resolve_scenario
    with pytest.raises(ValueError):
        resolve_scenario(7, profile="nope")


def test_biome_override_on_vio_lio():
    from wildseed.core.scenario import resolve_scenario
    s = resolve_scenario(7, profile="vio_lio", biome="temperate")
    assert s["biome"] == "temperate"
    assert s["ground_biome"] == "grassland"


def test_apply_recolour_variants_noop_when_zero():
    from wildseed.core.scenario import _apply_recolour_variants
    pal = {"tree": ["oak"], "rock": ["r1"], "bush": [], "grass": ["g1"]}
    assert _apply_recolour_variants("ignored", pal, 0, seed=1) == pal


def test_apply_recolour_variants_extends_palette(tmp_path, monkeypatch):
    """A stamped variant dir on disk is appended to its category's palette."""
    from wildseed.core.scenario import _apply_recolour_variants
    models = tmp_path / "models"
    for cat, ids in {"tree": ["oak"], "rock": ["r1"], "bush": ["b1"]}.items():
        for i in ids:
            (models / cat / i).mkdir(parents=True)

    def fake_randomize(models_root, cats, variants, seed, strength, mode):
        made = []
        for cat in cats:
            for base_dir in sorted((models_root / cat).iterdir()):
                for k in range(variants):
                    d = base_dir.parent / f"{base_dir.name}_dr{k}"
                    d.mkdir(exist_ok=True)
                    made.append(d)
        return made

    # the helper does `from wildseed.core.texrand import randomize_models`
    monkeypatch.setattr("wildseed.core.texrand.randomize_models", fake_randomize)

    pal = {"tree": ["oak"], "rock": ["r1"], "bush": ["b1"], "grass": ["g1"]}
    out = _apply_recolour_variants(models, pal, 2, seed=3)
    assert "oak_dr0" in out["tree"] and "oak_dr1" in out["tree"]
    assert "r1_dr0" in out["rock"]
    assert out["grass"] == ["g1"]                   # grass not a variant category


def test_build_corridor_for_writes_map(tmp_path):
    from wildseed.core.scenario import _build_corridor_for
    obj = tmp_path / "models" / "ground" / "mesh"
    obj.mkdir(parents=True)
    (obj / "terrain.obj").write_text("v -30 -30 0\nv 30 30 0\nv 0 0 0\n")
    spec = {"corridor": {"half_width": 6.0, "y0": 0.0, "res": 64, "soft": False}}
    png = _build_corridor_for(tmp_path, spec, "vio_lio_7")
    assert png.exists() and png.name == "vio_lio_7_corridor.png"
    import numpy as np
    from PIL import Image
    arr = np.asarray(Image.open(png))
    assert arr.shape == (64, 64)
    assert arr.max() == 255 and arr.min() == 0      # a real corridor band


def test_scenario_cli_exposes_profile_knobs():
    from wildseed.cli.scenario import scenario
    names = {p.name for p in scenario.params}
    for opt in ("profile", "object_density", "corridor_width", "relief", "variety"):
        assert opt in names
