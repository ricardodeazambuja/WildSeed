#!/usr/bin/env python3
"""Verdict every sensor stream of worlds/sensor_spike.world (SENSOR_RIG_PLAN Phase 0).

Subscribes via gz-transport (no ROS) to the full rig suite: stereo cams, rgbd,
wide-angle, instance segmentation, 3D gpu_lidar (PointCloudPacked), imu, navsat,
air pressure, magnetometer, ground-truth odometry. Prints PASS/FAIL per stream and
saves debug images under frames/spike/. Run inside wildseed:egl next to a headless
server:  GZ_SIM_RESOURCE_PATH=/workspace/models gz sim -s -r worlds/sensor_spike.world
"""
import os
import time

import numpy as np
from gz.transport13 import Node
from gz.msgs10.image_pb2 import Image
from gz.msgs10.pointcloud_packed_pb2 import PointCloudPacked
from gz.msgs10.imu_pb2 import IMU
from gz.msgs10.navsat_pb2 import NavSat
from gz.msgs10.fluid_pressure_pb2 import FluidPressure
from gz.msgs10.magnetometer_pb2 import Magnetometer
from gz.msgs10.odometry_pb2 import Odometry

OUTDIR = "/workspace/frames/spike"
TIMEOUT_S = 90
got = {}   # stream name -> dict(ok=bool, info=str)
node = Node()


def _img_np(m, channels=3, dtype=np.uint8):
    raw = np.frombuffer(m.data, dtype=dtype)
    return raw[: m.height * m.width * channels].reshape(m.height, m.width, channels)


def _save_png(name, arr):
    try:
        import cv2
        cv2.imwrite(os.path.join(OUTDIR, name), arr)
    except Exception as e:  # debug image is best-effort, never fail the verdict on it
        print(f"  (png save failed for {name}: {e})", flush=True)


def make_rgb_cb(key):
    def cb(m):
        if key in got:
            return
        img = _img_np(m)
        got[key] = dict(ok=img.std() > 1.0,
                        info=f"{img.shape} std={img.std():.1f}")
        _save_png(f"{key}.png", img[:, :, ::-1])  # RGB -> BGR for cv2
    return cb


def depth_cb(m):
    if "rgbd_depth" in got:
        return
    d = np.frombuffer(m.data, dtype=np.float32)[: m.height * m.width]
    finite = d[np.isfinite(d)]
    frac = finite.size / d.size if d.size else 0
    ok = frac > 0.05 and finite.size > 0 and finite.min() > 0.05
    info = (f"{m.width}x{m.height} finite={frac:.2f} "
            f"range=[{finite.min():.1f},{finite.max():.1f}]m" if finite.size
            else "all non-finite")
    got["rgbd_depth"] = dict(ok=ok, info=info)
    if finite.size:
        vis = np.clip((d.reshape(m.height, m.width) / 60.0) * 255, 0, 255)
        _save_png("rgbd_depth.png", np.nan_to_num(vis).astype(np.uint8))


def seg_labels_cb(m):
    if "segmentation" in got:
        return
    img = _img_np(m)
    # instance mode layout (measured, gz-sim8/ogre2): ch2 = class label,
    # ch0(+ch1 high byte) = per-class instance id, background = 0
    labels = np.unique(img[:, :, 2])
    nonzero = [int(v) for v in labels if v != 0]
    inst = np.unique(img[:, :, 0].astype(np.uint16) | (img[:, :, 1].astype(np.uint16) << 8))
    got["segmentation"] = dict(ok=len(nonzero) >= 2,
                               info=f"class labels {sorted(nonzero)} (expect [10,20,30]), "
                                    f"instance ids {[int(v) for v in inst if v][:6]}")
    _save_png("segmentation_labels.png",
              (img.astype(np.uint16) * 5).clip(0, 255).astype(np.uint8))


def seg_colored_cb(m):
    if "seg_colored" in got:
        return
    img = _img_np(m)
    got["seg_colored"] = dict(ok=img.std() > 1.0, info=f"std={img.std():.1f}")
    _save_png("segmentation_colored.png", img[:, :, ::-1])


def points_cb(m):
    if "lidar_points" in got:
        return
    off = {f.name: f.offset for f in m.field}
    n = m.width * m.height
    buf = np.frombuffer(m.data, dtype=np.uint8).reshape(n, m.point_step)

    def f32(name):
        return buf[:, off[name]:off[name] + 4].copy().view(np.float32).ravel()

    x, y, z = f32("x"), f32("y"), f32("z")
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    retro_info = "NO intensity field"
    if "intensity" in off:
        vals = np.unique(f32("intensity")[finite].round(1))
        retro_info = f"intensity values: {vals[:12].tolist()}{'...' if vals.size > 12 else ''}"
    # from 75 m AGL with 150 m max range only ~3 of 16 rings reach terrain,
    # plus the floating targets -> a few hundred returns is the honest expectation
    got["lidar_points"] = dict(
        ok=finite.sum() > 500,
        info=f"{n} pts, {int(finite.sum())} finite, fields={sorted(off)}; {retro_info}")


def imu_cb(m):
    if "imu" in got:
        return
    a = np.array([m.linear_acceleration.x, m.linear_acceleration.y,
                  m.linear_acceleration.z])
    q = m.orientation
    qn = q.w**2 + q.x**2 + q.y**2 + q.z**2
    got["imu"] = dict(ok=bool(np.isfinite(a).all()) and abs(qn - 1) < 0.01,
                      info=f"|acc|={np.linalg.norm(a):.2f} m/s2 (gravity-off link), |q|^2={qn:.3f}")


def navsat_cb(m):
    if "navsat" in got:
        return
    got["navsat"] = dict(ok=abs(m.latitude_deg - 57.0271155) < 0.01,
                         info=f"lat={m.latitude_deg:.5f} lon={m.longitude_deg:.5f} alt={m.altitude:.1f}")


def baro_cb(m):
    if "air_pressure" in got:
        return
    got["air_pressure"] = dict(ok=80000 < m.pressure < 110000,
                               info=f"{m.pressure:.0f} Pa @ ref_alt 600 m")


def mag_cb(m):
    if "magnetometer" in got:
        return
    b = np.array([m.field_tesla.x, m.field_tesla.y, m.field_tesla.z])
    mag = np.linalg.norm(b)
    # gz Harmonic gotcha (measured): with <spherical_coordinates> present the
    # magnetometer system computes the World Magnetic Model field for the world
    # origin and publishes it in GAUSS despite the field_tesla name; the world
    # <magnetic_field> element is ignored. WMM @ 57.03N,-115.43E ~= 0.574 G.
    got["magnetometer"] = dict(ok=abs(mag - 0.574) < 0.06,
                               info=f"|B|={mag:.3f} G-in-tesla-field (WMM@origin ~0.574)")


def odom_cb(m):
    if "odometry" in got:
        return
    p = m.pose.position
    ok = abs(p.x - 0) < 1 and abs(p.y + 120) < 1 and abs(p.z - 75) < 1
    got["odometry"] = dict(ok=ok, info=f"pose=({p.x:.1f},{p.y:.1f},{p.z:.1f}) expect (0,-120,75)")


EXPECTED = ["cam_left", "cam_right", "wideangle", "rgbd_rgb", "rgbd_depth",
            "segmentation", "seg_colored", "lidar_points", "imu", "navsat",
            "air_pressure", "magnetometer", "odometry"]

os.makedirs(OUTDIR, exist_ok=True)
node.subscribe(Image, "rig/cam_left", make_rgb_cb("cam_left"))
node.subscribe(Image, "rig/cam_right", make_rgb_cb("cam_right"))
node.subscribe(Image, "rig/wideangle", make_rgb_cb("wideangle"))
node.subscribe(Image, "rig/rgbd/image", make_rgb_cb("rgbd_rgb"))
node.subscribe(Image, "rig/rgbd/depth_image", depth_cb)
node.subscribe(Image, "rig/segmentation/labels_map", seg_labels_cb)
node.subscribe(Image, "rig/segmentation/colored_map", seg_colored_cb)
node.subscribe(PointCloudPacked, "rig/lidar/points", points_cb)
node.subscribe(IMU, "rig/imu", imu_cb)
node.subscribe(NavSat, "rig/navsat", navsat_cb)
node.subscribe(FluidPressure, "rig/air_pressure", baro_cb)
node.subscribe(Magnetometer, "rig/magnetometer", mag_cb)
node.subscribe(Odometry, "/model/sensor_rig/odometry", odom_cb)

t0 = time.time()
while time.time() - t0 < TIMEOUT_S and len(got) < len(EXPECTED):
    time.sleep(0.2)

print("=== SENSOR SPIKE RESULTS ===", flush=True)
n_pass = 0
for k in EXPECTED:
    if k in got:
        verdict = "PASS" if got[k]["ok"] else "FAIL"
        n_pass += got[k]["ok"]
        print(f"{verdict:4} {k:14} {got[k]['info']}", flush=True)
    else:
        print(f"MISS {k:14} no message in {TIMEOUT_S}s", flush=True)
print(f"=== {n_pass}/{len(EXPECTED)} PASS ===", flush=True)
