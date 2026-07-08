"""Sweep condition resolution + report-card rendering (no builds, no GPU)."""

import pytest

from wildseed.core.experiment import ExperimentSpec
from wildseed.core.sweep import (SWEEP_AXES, condition_stem, render_report_md,
                                 sweep_conditions)


def _spec(**kw):
    base = dict(hypothesis="low sun kills tracks", seed=42, name="lowsun",
                dials={"structure": 0.7})
    base.update(kw)
    return ExperimentSpec(**base)


def test_conditions_cross_values_and_seeds():
    conds = sweep_conditions(_spec(), "photometric", [0.0, 1.0], [42, 43])
    assert len(conds) == 4
    stems = [c["stem"] for c in conds]
    assert stems == ["exp_lowsun_photometric000_s42", "exp_lowsun_photometric000_s43",
                     "exp_lowsun_photometric100_s42", "exp_lowsun_photometric100_s43"]
    assert len(set(stems)) == 4  # no collisions


def test_conditions_hold_other_dials_and_apply_axis():
    conds = sweep_conditions(_spec(), "photometric", [0.0, 1.0], [42])
    for c in conds:
        assert c["resolved"]["object_density"] == 175  # structure held at 0.7
    assert conds[0]["resolved"]["photometric"]["sun_elevation_deg"] == 55.0
    assert conds[1]["resolved"]["photometric"]["sun_elevation_deg"] == 5.0


def test_conditions_deterministic():
    a = sweep_conditions(_spec(), "texture", [0.0, 1.0], [42])
    b = sweep_conditions(_spec(), "texture", [0.0, 1.0], [42])
    assert a == b
    assert a[0]["resolved"]["ground_mode"] == "uniform"
    assert a[1]["resolved"]["ground_mode"] == "patchy"


def test_axis_and_value_validation():
    with pytest.raises(ValueError, match="unknown sweep axis"):
        sweep_conditions(_spec(), "weather", [0.0], [42])
    with pytest.raises(ValueError, match="outside"):
        sweep_conditions(_spec(), "relief", [1.5], [42])
    assert set(SWEEP_AXES) == {"structure", "texture", "relief", "variety",
                               "photometric"}


def test_condition_stem_is_filesystem_safe():
    s = condition_stem(_spec(), "photometric", 0.35, 7)
    assert s == "exp_lowsun_photometric035_s7"
    assert "/" not in s and "." not in s


def test_report_md_renders_ladder():
    report = {
        "experiment": "exp_lowsun", "hypothesis": "low sun kills tracks",
        "axis": "photometric", "values": [0.0, 1.0], "seeds": [42],
        "benches": ["vio", "rtf"],
        "spec": {},
        "rows": [
            {"value": 1.0, "seed": 42, "stem": "b", "build_s": 60.0,
             "world_sha256": "beef" * 16,
             "vio": {"inliers_per_pair": 20, "ratio_reject": 0.95,
                     "inlier_ratio": 0.7, "verdict": "ALIASING RISK"},
             "rtf": {"rtf_min": 0.9, "load_wait_s": 12.0}},
            {"value": 0.0, "seed": 42, "stem": "a", "build_s": 55.0,
             "world_sha256": "cafe" * 16,
             "vio": {"inliers_per_pair": 150, "ratio_reject": 0.6,
                     "inlier_ratio": 0.99, "verdict": "GOOD"},
             "rtf": {"error": "timeout after 1200s"}},
        ],
    }
    md = render_report_md(report)
    assert "low sun kills tracks" in md
    lines = [l for l in md.splitlines() if l.startswith("| 0") or l.startswith("| 1")]
    assert len(lines) == 2 and lines[0].startswith("| 0.00")  # sorted by value
    assert "GOOD" in lines[0] and "ALIASING RISK" in lines[1]
    assert "cafe" in lines[0] and "beef" in lines[1]
    assert "—" in lines[0]  # failed rtf renders as missing, not crash
