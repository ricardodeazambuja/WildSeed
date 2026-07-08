"""Custom-biome loading under the testing contract (docs/EXPERIMENT_PLAN.md D6)."""

import pytest

from wildseed.core.biomes import BiomeDef, load_biome_file
from wildseed.core.scenario import resolve_scenario

GOOD = """
mangrove:
  presets: [lakeland]
  knobs: {feature_m: [110, 150], detail: [0.1, 0.2]}
  ground: grassland
  water: true
  density: {tree: 90, rock: 20, bush: 140, grass: 200}
  palette_from: wetland
"""


def _write(tmp_path, text, name="biomes.yaml"):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_good_biome_loads_and_resolves(tmp_path):
    spaces, prov = load_biome_file(_write(tmp_path, GOOD))
    assert set(spaces) == {"mangrove"}
    assert prov["biomes"] == ["mangrove"] and len(prov["sha256"]) == 64

    spec = resolve_scenario(7, biome="mangrove", extra_biomes=spaces)
    assert spec["biome"] == "mangrove"
    assert spec["ground_biome"] == "grassland" and spec["water"] is True
    assert spec["palette_source"] == {"manifest_biome": "wetland"}
    assert 110 <= spec["terrain_knobs"]["feature_m"] <= 150
    # determinism: same seed + same file -> same spec
    assert spec == resolve_scenario(7, biome="mangrove", extra_biomes=spaces)


def test_custom_biome_never_joins_the_draw_pool(tmp_path):
    """Seed->biome mapping with the file loaded must equal the mapping without."""
    spaces, _ = load_biome_file(_write(tmp_path, GOOD))
    for seed in range(20):
        assert (resolve_scenario(seed, extra_biomes=spaces)["biome"]
                == resolve_scenario(seed)["biome"])


def test_builtin_names_are_not_redefinable(tmp_path):
    bad = GOOD.replace("mangrove:", "temperate:")
    with pytest.raises(ValueError, match="collides with a built-in"):
        load_biome_file(_write(tmp_path, bad))


def test_contract_requires_all_densities(tmp_path):
    bad = GOOD.replace("density: {tree: 90, rock: 20, bush: 140, grass: 200}",
                       "density: {tree: 90}")
    with pytest.raises(ValueError, match="landmark-supply"):
        load_biome_file(_write(tmp_path, bad))


def test_contract_requires_known_ground_family(tmp_path):
    bad = GOOD.replace("ground: grassland", "ground: mud")
    with pytest.raises(ValueError, match="ground family"):
        load_biome_file(_write(tmp_path, bad))


def test_contract_requires_exactly_one_palette_source(tmp_path):
    with pytest.raises(ValueError, match="palette"):
        load_biome_file(_write(tmp_path, GOOD.replace(
            "  palette_from: wetland\n", "")))
    both = GOOD + "  palette: {trees: [island_tree_01]}\n"
    with pytest.raises(ValueError, match="exactly one"):
        load_biome_file(_write(tmp_path, both))


def test_contract_rejects_unknown_knobs_and_bad_ranges(tmp_path):
    with pytest.raises(ValueError, match="unknown terrain knob"):
        load_biome_file(_write(tmp_path, GOOD.replace(
            "feature_m: [110, 150]", "steepness: [1, 2]")))
    with pytest.raises(ValueError, match="hi < lo"):
        load_biome_file(_write(tmp_path, GOOD.replace(
            "feature_m: [110, 150]", "feature_m: [150, 110]")))


def test_explicit_palette_biome(tmp_path):
    text = GOOD.replace(
        "  palette_from: wetland\n",
        "  palette: {trees: [island_tree_01], bushes: [], grasses: [], rocks: [rock_07]}\n")
    spaces, _ = load_biome_file(_write(tmp_path, text))
    spec = resolve_scenario(3, biome="mangrove", extra_biomes=spaces)
    assert spec["palette_source"]["explicit"]["trees"] == ["island_tree_01"]
    assert spec["palette_source"]["explicit"]["rocks"] == ["rock_07"]


def test_biome_def_rows_envelope_validated():
    with pytest.raises(ValueError, match="unknown row param"):
        BiomeDef(presets=["flat"], knobs={}, ground="desert", water=False,
                 density={"tree": 0, "rock": 0, "bush": 0, "grass": 0},
                 palette_from="savanna",
                 rows={"tree": {"spacing": [1, 2]}})


def test_experiment_spec_biome_file_roundtrip(tmp_path):
    from wildseed.core.experiment import ExperimentSpec, resolve_experiment
    biome_path = _write(tmp_path, GOOD)
    spec = ExperimentSpec(hypothesis="custom biome scores", seed=7,
                          profile=None, biome="mangrove",
                          biome_file=str(biome_path))
    r = resolve_experiment(spec)
    assert r["biome"] == "mangrove"
    assert r["biome_file"]["sha256"]
    # without the file the same name must be rejected up-front
    with pytest.raises(Exception, match="unknown biome"):
        ExperimentSpec(hypothesis="x", seed=7, profile=None, biome="mangrove")


def test_relative_biome_file_resolves_against_spec_dir(tmp_path):
    from wildseed.core.experiment import load_experiment
    _write(tmp_path, GOOD, "my_biomes.yaml")
    spec_p = tmp_path / "exp.yaml"
    spec_p.write_text("hypothesis: h\nseed: 7\nprofile: null\n"
                      "biome: mangrove\nbiome_file: my_biomes.yaml\n")
    spec = load_experiment(spec_p)
    assert spec.biome_file == str(tmp_path / "my_biomes.yaml")
