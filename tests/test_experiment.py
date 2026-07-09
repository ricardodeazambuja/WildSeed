"""Experiment spec + format-4 scenario resolution (photometric/weather/texture).

The golden fixture (tests/fixtures/scenario_format3_golden.json) was captured
from the format-3 code immediately before the format-4 change; the compat test
is the guarantee that the appended sun stream changed no pre-existing seed
mapping (docs/EXPERIMENT_PLAN.md D1 / gate G1).
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from wildseed.core.experiment import (STRUCTURE_BUDGET, DialDist,
                                      ExperimentSpec, experiment_stem,
                                      load_experiment, resolve_experiment,
                                      sample_experiments, write_samples)
from wildseed.core.scenario import SCENARIO_FORMAT, resolve_scenario

FIXTURES = Path(__file__).parent / "fixtures"


# --------------------------------------------------------------------------- #
# format-4 seed compatibility
# --------------------------------------------------------------------------- #

def test_format4_reproduces_format3_draws_exactly():
    golden = json.loads((FIXTURES / "scenario_format3_golden.json").read_text())
    assert golden, "golden fixture missing/empty"
    for case in golden:
        spec = resolve_scenario(**case["kw"])
        for key, want in case["expect"].items():
            got = spec[key]
            if key == "stage_seeds":
                got = {k: v for k, v in got.items() if k != "sun"}
            assert got == want, f"{case['kw']}: {key} drifted"


def test_unset_dials_change_nothing():
    spec = resolve_scenario(7, profile="vio_lio")
    assert spec["scenario_format"] == SCENARIO_FORMAT == 4
    assert spec["photometric"] is None
    assert spec["weather"] is None
    assert spec["ground_mode"] == "patchy"
    assert "sun" in spec["stage_seeds"]


# --------------------------------------------------------------------------- #
# photometric dial
# --------------------------------------------------------------------------- #

def test_photometric_endpoints_and_determinism():
    hi = resolve_scenario(7, profile="vio_lio", photometric=1.0)
    assert hi == resolve_scenario(7, profile="vio_lio", photometric=1.0)
    p = hi["photometric"]
    assert p["sun_elevation_deg"] == 5.0
    assert p["sun_intensity"] == 5.0
    assert p["sun_disk"] is True

    lo = resolve_scenario(7, profile="vio_lio", photometric=0.0)["photometric"]
    assert lo["sun_elevation_deg"] == 55.0
    assert lo["sun_intensity"] == 1.0
    assert lo["sun_disk"] is False


def test_photometric_azimuth_is_seeded_not_dialed():
    a = resolve_scenario(7, profile="vio_lio", photometric=0.1)["photometric"]
    b = resolve_scenario(7, profile="vio_lio", photometric=0.9)["photometric"]
    assert a["sun_azimuth_deg"] == b["sun_azimuth_deg"]  # dial-independent
    c = resolve_scenario(8, profile="vio_lio", photometric=0.1)["photometric"]
    assert c["sun_azimuth_deg"] != a["sun_azimuth_deg"]  # seed-dependent


def test_photometric_monotone_severity():
    dials = [0.0, 0.25, 0.5, 0.75, 1.0]
    blocks = [resolve_scenario(7, profile="vio_lio", photometric=d)["photometric"]
              for d in dials]
    elevations = [b["sun_elevation_deg"] for b in blocks]
    intensities = [b["sun_intensity"] for b in blocks]
    assert elevations == sorted(elevations, reverse=True)
    assert intensities == sorted(intensities)
    assert [b["sun_disk"] for b in blocks] == [False, False, False, True, True]


def test_photometric_on_biome_path_too():
    spec = resolve_scenario(42, photometric=0.5)
    assert spec["photometric"]["sun_elevation_deg"] == 30.0
    assert spec["stage_seeds"]["sun"]


# --------------------------------------------------------------------------- #
# texture dial + weather
# --------------------------------------------------------------------------- #

def test_texture_dial_selects_ground_mode():
    assert resolve_scenario(7, profile="vio_lio", texture=0.0)["ground_mode"] == "uniform"
    assert resolve_scenario(7, profile="vio_lio", texture=0.49)["ground_mode"] == "uniform"
    assert resolve_scenario(7, profile="vio_lio", texture=0.5)["ground_mode"] == "patchy"
    assert resolve_scenario(7, profile="vio_lio", texture=1.0)["ground_mode"] == "patchy"


def test_weather_random_is_seeded():
    a = resolve_scenario(7, weather="random")
    assert a["weather"] == resolve_scenario(7, weather="random")["weather"]
    assert a["weather"] is not None


def test_weather_unknown_rejected():
    with pytest.raises(ValueError, match="unknown weather"):
        resolve_scenario(7, weather="blizzard")


# --------------------------------------------------------------------------- #
# experiment spec
# --------------------------------------------------------------------------- #

def test_experiment_resolves_structure_dial_to_budget():
    spec = ExperimentSpec(hypothesis="h", seed=42, name="lowsun",
                          dials={"structure": 0.7, "photometric": 0.9},
                          benchmark=["vio"])
    r = resolve_experiment(spec)
    assert r["object_density"] == round(STRUCTURE_BUDGET * 0.7) == 175
    assert r["experiment"]["hypothesis"] == "h"
    assert r["experiment"]["dials"] == {"structure": 0.7, "photometric": 0.9}
    assert experiment_stem(spec) == "exp_lowsun"


def test_experiment_stem_defaults_to_seed():
    assert experiment_stem(ExperimentSpec(hypothesis="h", seed=9)) == "exp_9"


def test_experiment_profile_dials_need_profile():
    spec = ExperimentSpec(hypothesis="h", seed=1, profile=None,
                          dials={"structure": 0.5})
    with pytest.raises(ValueError, match="vio_lio profile"):
        resolve_experiment(spec)


def test_experiment_photometric_ok_without_profile():
    spec = ExperimentSpec(hypothesis="h", seed=1, profile=None, biome="temperate",
                          dials={"photometric": 1.0})
    r = resolve_experiment(spec)
    assert "profile" not in r
    assert r["photometric"]["sun_disk"] is True


def test_experiment_overrides_validated_and_win():
    spec = ExperimentSpec(hypothesis="h", seed=1, dials={"structure": 0.5},
                          overrides={"object_density": 42})
    assert resolve_experiment(spec)["object_density"] == 42
    with pytest.raises(ValueError, match="not a scenario knob"):
        resolve_experiment(ExperimentSpec(hypothesis="h", seed=1,
                                          overrides={"nope": 1}))


def test_experiment_validation_errors():
    with pytest.raises(ValidationError):
        ExperimentSpec(seed=1)                                   # no hypothesis
    with pytest.raises(ValidationError):
        ExperimentSpec(hypothesis="h", seed=1, dials={"texture": 1.5})
    with pytest.raises(ValidationError):
        ExperimentSpec(hypothesis="h", seed=1, benchmark=["ate"])
    with pytest.raises(ValidationError):
        ExperimentSpec(hypothesis="h", seed=1, name="bad name!")
    with pytest.raises(ValidationError):
        ExperimentSpec(hypothesis="h", seed=1, profile="nope")


def test_load_experiment_yaml(tmp_path):
    p = tmp_path / "exp.yaml"
    p.write_text("hypothesis: low sun\nseed: 42\n"
                 "dials: {photometric: 0.9}\nbenchmark: [vio, rtf]\n")
    spec = load_experiment(p)
    assert spec.seed == 42 and spec.dials.photometric == 0.9
    r = resolve_experiment(spec)
    assert r["experiment"]["benchmark"] == ["vio", "rtf"]
    p.write_text("- not\n- a\n- mapping\n")
    with pytest.raises(ValueError, match="mapping"):
        load_experiment(p)


# --------------------------------------------------------------------------- #
# distribution dials + curriculum sampling
# --------------------------------------------------------------------------- #

def _dist_spec(**kw):
    base = dict(hypothesis="curriculum", seed=42, name="cur",
                dials={"structure": {"dist": "beta", "params": [2, 5]},
                       "texture": 1.0,
                       "photometric": {"dist": "normal", "params": [0.5, 0.6]}})
    base.update(kw)
    return ExperimentSpec(**base)


def test_dist_dials_parse_and_partition():
    spec = _dist_spec()
    assert spec.dials.set_items() == {"texture": 1.0}
    assert sorted(spec.dials.dist_items()) == ["photometric", "structure"]
    assert isinstance(spec.dials.structure, DialDist)


def test_dist_dials_cannot_resolve_unsampled():
    with pytest.raises(ValueError, match="sample them first"):
        resolve_experiment(_dist_spec())


def test_dist_param_validation():
    for bad in [{"dist": "uniform", "params": [0.8, 0.2]},     # hi < lo
                {"dist": "uniform", "params": [-0.1, 0.5]},    # lo < 0
                {"dist": "normal", "params": [0.5, 0.0]},      # sigma <= 0
                {"dist": "normal", "params": [1.5, 0.1]},      # mean > 1
                {"dist": "beta", "params": [0.0, 2.0]},        # a <= 0
                {"dist": "beta", "params": [2.0]},             # wrong arity
                {"dist": "lognormal", "params": [0.0, 1.0]}]:  # unknown dist
        with pytest.raises(ValidationError):
            ExperimentSpec(hypothesis="h", seed=1, dials={"structure": bad})
    with pytest.raises(ValidationError):                       # float range still
        ExperimentSpec(hypothesis="h", seed=1, dials={"structure": 1.2})


def test_sample_deterministic_and_append_safe():
    spec = _dist_spec()
    a = sample_experiments(spec, 5)
    b = sample_experiments(spec, 5)
    assert [s["dials"] for s in a] == [s["dials"] for s in b]
    assert [s["seed"] for s in a] == [s["seed"] for s in b]
    # append-safety: growing the batch never changes earlier samples
    first3 = sample_experiments(spec, 3)
    assert [s["dials"] for s in first3] == [s["dials"] for s in a[:3]]
    assert [s["seed"] for s in first3] == [s["seed"] for s in a[:3]]


def test_sample_values_in_range_and_fixed_dials_pass_through():
    samples = sample_experiments(_dist_spec(), 40)
    for s in samples:
        d = s["dials"]
        assert d["texture"] == 1.0                    # literal dial unchanged
        assert 0.0 <= d["structure"] <= 1.0           # beta support
        assert 0.0 <= d["photometric"] <= 1.0         # normal draw clipped
    # sigma 0.6 around 0.5 must actually hit the clip rails sometimes
    photos = [s["dials"]["photometric"] for s in samples]
    assert 0.0 in photos or 1.0 in photos
    seeds = [s["seed"] for s in samples]
    assert len(set(seeds)) == len(seeds)              # fresh world seed each
    assert samples[0]["name"] == "cur-k000"


def test_sample_without_dists_gives_seeded_replicates():
    spec = ExperimentSpec(hypothesis="h", seed=7, dials={"structure": 0.7})
    samples = sample_experiments(spec, 3)
    assert all(s["dials"] == {"structure": 0.7} for s in samples)
    assert len({s["seed"] for s in samples}) == 3


def test_sampled_specs_resolve_and_write(tmp_path):
    spec = _dist_spec()
    m = write_samples(spec, 3, tmp_path / "out", source="cur.yaml")
    assert len(m["files"]) == 3 and m["count"] == 3
    assert (tmp_path / "out" / "samples.yaml").exists()
    for path in m["files"]:
        loaded = load_experiment(Path(path))          # round-trips as a spec
        r = resolve_experiment(loaded)                # and builds a condition
        assert r["experiment"]["dials"]["texture"] == 1.0
        assert 0.0 <= r["experiment"]["dials"]["structure"] <= 1.0
    # the manifest pins the same draws the files carry
    assert m["samples"][0]["dials"] == \
        load_experiment(Path(m["files"][0])).dials.set_items()


# --------------------------------------------------------------------------- #
# provenance
# --------------------------------------------------------------------------- #

def test_provenance_hashes_and_version(tmp_path):
    from wildseed import __version__
    from wildseed.core.scenario import _provenance
    w = tmp_path / "w.world"; w.write_text("<sdf/>")
    d = tmp_path / "d.tif"; d.write_bytes(b"dem")
    prov = _provenance(w, d, tmp_path / "missing.json")
    assert prov["wildseed_version"] == __version__
    assert prov["sha256"]["world"] and len(prov["sha256"]["world"]) == 64
    assert prov["sha256"]["dem"] and prov["sha256"]["instances"] is None
    # deterministic in file content
    assert prov["sha256"]["world"] == _provenance(w, d, w)["sha256"]["world"]
