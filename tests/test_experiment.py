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

from wildseed.core.experiment import (STRUCTURE_BUDGET, ExperimentSpec,
                                      experiment_stem, load_experiment,
                                      resolve_experiment)
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
