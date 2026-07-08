"""Sensor-calibration randomization (core.calib): determinism, pairing
invariant, truth export fidelity, dial-0 no-op."""

import json
import math
from xml.etree import ElementTree as ET

from wildseed.core.calib import perturb_rig_model, write_calibration
from wildseed.core.rig import RigConfig, build_rig_model, write_rig_model


def _model():
    return build_rig_model(RigConfig())


def _sensor_pose(model, name):
    link = model.find("link")
    s = [x for x in link.findall("sensor") if x.get("name") == name][0]
    return [float(v) for v in s.findtext("pose").split()], s


def test_dial_zero_is_a_noop_export():
    a, b = _model(), _model()
    truth = perturb_rig_model(b, 0.0, seed=7)
    assert ET.tostring(a) == ET.tostring(b)          # SDF byte-identical
    cl = truth["cameras"]["cam_left"]
    assert cl["pose_true"] == cl["pose_nominal"]
    assert cl["fx_true"] == cl["fx_nominal"] == (640 / 2) / math.tan(1.0 / 2)
    assert truth["imu"]["gyro"] == "ideal (no noise injected)"


def test_same_dial_seed_same_perturbation():
    m1, m2 = _model(), _model()
    t1 = perturb_rig_model(m1, 0.6, seed=42)
    t2 = perturb_rig_model(m2, 0.6, seed=42)
    assert ET.tostring(m1) == ET.tostring(m2)
    assert t1 == t2
    m3 = _model()
    t3 = perturb_rig_model(m3, 0.6, seed=43)
    assert t3["cameras"]["cam_left"]["pose_true"] != t1["cameras"]["cam_left"]["pose_true"]


def test_pairing_invariant_rgbd_segcam_move_with_cam_left():
    m = _model()
    perturb_rig_model(m, 1.0, seed=5)
    left, _ = _sensor_pose(m, "cam_left")
    rgbd, _ = _sensor_pose(m, "rgbd")
    seg, _ = _sensor_pose(m, "segcam")
    assert left == rgbd == seg                       # still pixel-paired
    right, _ = _sensor_pose(m, "cam_right")
    assert right != left                             # stereo miscalibrated independently


def test_perturbations_bounded_and_recorded_in_sdf():
    m = _model()
    truth = perturb_rig_model(m, 1.0, seed=11)
    for name, cam in truth["cameras"].items():
        dp = [abs(t - n) for t, n in zip(cam["pose_true"], cam["pose_nominal"])]
        assert all(d < 0.005 * 6 for d in dp[:3]), f"{name}: {dp} pos out of 6-sigma"
        assert all(d < math.radians(0.3) * 6 for d in dp[3:])
        # SDF carries the TRUE values
        pose, s = _sensor_pose(m, name)
        assert pose == [round(v, 6) for v in cam["pose_true"]]
        fov_sdf = float(s.find("camera").findtext("horizontal_fov"))
        assert fov_sdf == round(cam["horizontal_fov_true"], 6)
        assert cam["fx_true"] != cam["fx_nominal"]


def test_imu_noise_injected_and_scales():
    m = _model()
    truth = perturb_rig_model(m, 0.5, seed=3)        # scale = 4*0.25 = 1x MEMS
    imu = truth["imu"]
    assert imu["noise_scale"] == 1.0
    assert imu["gyro"]["noise_density"] == 1.6968e-4
    _, s = _sensor_pose(m, "imu")
    noises = s.findall(".//noise")
    assert len(noises) == 6                          # 3 gyro + 3 accel axes
    sd = float(noises[0].findtext("stddev"))
    assert sd == round(1.6968e-4 * math.sqrt(100.0), 8) or \
        abs(sd - 1.6968e-4 * math.sqrt(100.0)) < 1e-9
    m2 = _model()
    t2 = perturb_rig_model(m2, 1.0, seed=3)          # scale = 4x
    assert t2["imu"]["noise_scale"] == 4.0
    assert t2["imu"]["gyro"]["gz_stddev"] > imu["gyro"]["gz_stddev"] * 3.9


def test_write_rig_model_exports_calibration(tmp_path):
    model_dir = write_rig_model(RigConfig(), tmp_path, calib_dial=0.8,
                                calib_seed=9)
    calib = json.loads((model_dir / "rig_calibration.json").read_text())
    assert calib["dial"] == 0.8 and calib["seed"] == 9
    # the written SDF matches the truth record
    sdf = ET.parse(model_dir / "model.sdf").getroot().find("model")
    pose, _ = _sensor_pose(sdf, "cam_left")
    assert pose == [round(v, 6) for v in calib["cameras"]["cam_left"]["pose_true"]]
    # no calib -> no file
    d2 = write_rig_model(RigConfig(name="plain"), tmp_path)
    assert not (d2 / "rig_calibration.json").exists()


def test_disabled_sensors_do_not_shift_draws():
    """cam_right disabled: cam_left/wideangle/lidar draws must be unchanged."""
    full = perturb_rig_model(_model(), 0.7, seed=13)
    slim_cfg = RigConfig(stereo_baseline=0.0)
    slim = perturb_rig_model(build_rig_model(slim_cfg), 0.7, seed=13)
    assert "cam_right" not in slim["cameras"]

    def delta(rec):
        return [t - n for t, n in zip(rec["pose_true"], rec["pose_nominal"])]

    import pytest
    for name in ("cam_left", "wideangle"):
        # nominal mounts differ (baseline 0 recentres cam_left) — the DRAW
        # (true - nominal) is what must not shift (approx: reconstructing the
        # delta from different nominals costs a ulp)
        assert delta(slim["cameras"][name]) == pytest.approx(
            delta(full["cameras"][name]), abs=1e-12)
    assert delta(slim["lidar"]) == pytest.approx(delta(full["lidar"]), abs=1e-12)
