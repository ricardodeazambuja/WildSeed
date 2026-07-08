"""Seeded sensor-calibration randomization (the instrument-error axis).

Targets calibration-error robustness (docs/EXPERIMENT_PLAN.md, deferred-axes
design): a dial 0..1 perturbs the rig's camera intrinsics (via horizontal
FOV -> fx), sensor mount extrinsics, and injects IMU noise — and exports the
TRUE drawn values to ``rig_calibration.json`` next to the model. One axis,
two uses: feed an estimator the *true* values for a clean test, or the
*nominal* ones for a mismatch/robustness test.

This is an INSTRUMENT property, not world state: it lives on ``wildseed rig``
(and ``rig_calibration.json`` travels with the model), independent of the
scenario master seed.

Dial mapping (all zero-mean gaussians, sigmas scale linearly with the dial):
    mount position   sigma = dial * 5 mm    per axis
    mount rotation   sigma = dial * 0.3 deg per axis
    camera FOV       sigma = dial * 1 %     (multiplicative; fx shifts with it)
    IMU noise        scale = 4 * dial^2  x  a MEMS baseline (EuRoC
                     ADIS16448-class densities) -> 0x at 0, 1x at 0.5, 4x at 1

Pairing invariant: rgbd + segcam sit AT cam_left's pose so RGB/depth/labels
are pixel-paired ground truth — they receive cam_left's SAME perturbation
(the instrument is miscalibrated; the GT pairing is not).

Draws happen in a FIXED order for the full sensor set regardless of which
sensors a config enables (disabled sensors' draws are discarded), so the same
(dial, seed) always produces the same perturbation per sensor.
"""

import json
import math
from pathlib import Path
from typing import Dict, Optional
from xml.etree import ElementTree as ET

import numpy as np

# Continuous-time MEMS baseline (EuRoC / ADIS16448-class IMU):
GYRO_NOISE_DENSITY = 1.6968e-4   # rad/s/sqrt(Hz)
GYRO_RANDOM_WALK = 1.9393e-5     # rad/s^2/sqrt(Hz)
ACCEL_NOISE_DENSITY = 2.0e-3     # m/s^2/sqrt(Hz)
ACCEL_RANDOM_WALK = 3.0e-3       # m/s^3/sqrt(Hz)
BIAS_CORRELATION_TIME_S = 400.0

POS_SIGMA_M = 0.005              # at dial 1.0
ROT_SIGMA_RAD = math.radians(0.3)
FOV_SIGMA_FRAC = 0.01

# fixed draw order (D1 principle: draws never depend on what's enabled)
_DRAW_ORDER = ("cam_left", "cam_right", "wideangle", "lidar", "imu")


def _fx(width: int, fov_rad: float) -> float:
    return (width / 2.0) / math.tan(fov_rad / 2.0)


def _draw_all(dial: float, seed: int) -> Dict[str, dict]:
    """One perturbation per sensor in _DRAW_ORDER, deterministic in (dial, seed)."""
    rng = np.random.default_rng(np.random.SeedSequence((0x5EED_CA11B, int(seed))))
    draws = {}
    for name in _DRAW_ORDER:
        d = {
            "dpos": [float(v) for v in rng.normal(0.0, dial * POS_SIGMA_M, 3)],
            "drot": [float(v) for v in rng.normal(0.0, dial * ROT_SIGMA_RAD, 3)],
            "fov_scale": float(1.0 + rng.normal(0.0, dial * FOV_SIGMA_FRAC)),
        }
        draws[name] = d
    return draws


def _perturb_pose(pose_text: str, dpos, drot):
    nominal = [float(t) for t in (pose_text or "0 0 0 0 0 0").split()]
    true = [nominal[i] + dpos[i] for i in range(3)] + \
           [nominal[3 + i] + drot[i] for i in range(3)]
    return nominal, true


def perturb_rig_model(model: ET.Element, dial: float, seed: int) -> dict:
    """Apply the (dial, seed) calibration perturbation to a built rig
    ``<model>`` element IN PLACE; return the truth record.

    dial=0 leaves the SDF byte-identical (all sigmas zero, no IMU noise) but
    still returns the record — useful as a plain calibration export.
    """
    dial = float(min(max(dial, 0.0), 1.0))
    draws = _draw_all(dial, seed)
    link = model.find("link")
    sensors = {s.get("name"): s for s in link.findall("sensor")}

    truth: dict = {"dial": dial, "seed": int(seed),
                   "cameras": {}, "lidar": None, "imu": None}

    # cameras: cam_left's draw is shared by rgbd + segcam (pairing invariant)
    cam_groups = {
        "cam_left": ("cam_left", "rgbd", "segcam"),
        "cam_right": ("cam_right",),
        "wideangle": ("wideangle",),
    }
    for draw_name, members in cam_groups.items():
        d = draws[draw_name]
        for sname in members:
            s = sensors.get(sname)
            if s is None:
                continue
            pose_el = s.find("pose")
            nominal, true = _perturb_pose(pose_el.text, d["dpos"], d["drot"])
            if dial > 0.0:
                pose_el.text = " ".join(f"{v:.6f}" for v in true)
            cam = s.find("camera")
            fov_el = cam.find("horizontal_fov")
            fov_nom = float(fov_el.text)
            fov_true = fov_nom * d["fov_scale"]
            if dial > 0.0:
                fov_el.text = f"{fov_true:.6f}"
            img = cam.find("image")
            w = int(img.findtext("width"))
            h = int(img.findtext("height"))
            truth["cameras"][sname] = {
                "pose_nominal": nominal, "pose_true": true,
                "horizontal_fov_nominal": fov_nom,
                "horizontal_fov_true": fov_true,
                "width": w, "height": h,
                "fx_nominal": _fx(w, fov_nom), "fx_true": _fx(w, fov_true),
                "fy_nominal": _fx(w, fov_nom), "fy_true": _fx(w, fov_true),
                "cx": w / 2.0, "cy": h / 2.0,
            }

    if "lidar" in sensors:
        d = draws["lidar"]
        pose_el = sensors["lidar"].find("pose")
        nominal, true = _perturb_pose(pose_el.text, d["dpos"], d["drot"])
        if dial > 0.0:
            pose_el.text = " ".join(f"{v:.6f}" for v in true)
        truth["lidar"] = {"pose_nominal": nominal, "pose_true": true}

    if "imu" in sensors:
        s = sensors["imu"]
        d = draws["imu"]
        pose_el = s.find("pose")
        nominal, true = _perturb_pose(pose_el.text, d["dpos"], d["drot"])
        if dial > 0.0:
            pose_el.text = " ".join(f"{v:.6f}" for v in true)
        rate = float(s.findtext("update_rate", "100"))
        scale = 4.0 * dial * dial
        imu_truth = {"pose_nominal": nominal, "pose_true": true,
                     "rate_hz": rate, "noise_scale": scale}
        if scale > 0.0:
            # gz per-sample stddev = continuous density * sqrt(rate); the json
            # keeps BOTH so estimator configs can consume either convention.
            gyro_sd = scale * GYRO_NOISE_DENSITY * math.sqrt(rate)
            accel_sd = scale * ACCEL_NOISE_DENSITY * math.sqrt(rate)
            gyro_bias = scale * GYRO_RANDOM_WALK * math.sqrt(BIAS_CORRELATION_TIME_S)
            accel_bias = scale * ACCEL_RANDOM_WALK * math.sqrt(BIAS_CORRELATION_TIME_S)
            imu_el = ET.SubElement(s, "imu")
            for group, axis_tag, sd, bias in (
                    ("angular_velocity", ("x", "y", "z"), gyro_sd, gyro_bias),
                    ("linear_acceleration", ("x", "y", "z"), accel_sd, accel_bias)):
                g = ET.SubElement(imu_el, group)
                for ax in axis_tag:
                    a = ET.SubElement(g, ax)
                    n = ET.SubElement(a, "noise", {"type": "gaussian"})
                    ET.SubElement(n, "mean").text = "0"
                    ET.SubElement(n, "stddev").text = f"{sd:.8g}"
                    ET.SubElement(n, "dynamic_bias_stddev").text = f"{bias:.8g}"
                    ET.SubElement(n, "dynamic_bias_correlation_time").text = \
                        f"{BIAS_CORRELATION_TIME_S:g}"
            imu_truth.update({
                "gyro": {"noise_density": scale * GYRO_NOISE_DENSITY,
                         "random_walk": scale * GYRO_RANDOM_WALK,
                         "gz_stddev": gyro_sd,
                         "gz_dynamic_bias_stddev": gyro_bias,
                         "gz_dynamic_bias_correlation_time_s": BIAS_CORRELATION_TIME_S},
                "accel": {"noise_density": scale * ACCEL_NOISE_DENSITY,
                          "random_walk": scale * ACCEL_RANDOM_WALK,
                          "gz_stddev": accel_sd,
                          "gz_dynamic_bias_stddev": accel_bias,
                          "gz_dynamic_bias_correlation_time_s": BIAS_CORRELATION_TIME_S},
            })
        else:
            imu_truth["gyro"] = imu_truth["accel"] = "ideal (no noise injected)"
        truth["imu"] = imu_truth

    return truth


def write_calibration(model_dir: Path, truth: dict) -> Path:
    out = Path(model_dir) / "rig_calibration.json"
    out.write_text(json.dumps(truth, indent=2))
    return out
