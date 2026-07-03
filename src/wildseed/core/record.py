"""Recording: demo videos + sensor datasets from a rig flight (Phase 3).

One run = one directory under ``runs/``:

    manifest.json          seed, pattern, world, mode, stream counts
    trajectory.json        the exact flight (copied before takeoff)
    video.mp4              cam frames encoded at the measured capture rate
    frames/                numbered PNGs (kept with --keep-frames or --dataset)
    dataset/               (--dataset) lidar_XXXXXX.npz, imu.csv, navsat.csv,
                           groundtruth.txt (TUM: t x y z qx qy qz qw)

Subscribers run on gz-transport callback threads; callbacks only enqueue/write
cheap work. Timestamps are SIM time from message headers throughout — the
video fps is measured from them, so a slow render (RTF < 1) still yields a
real-time-correct video.
"""

import csv
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np

logger = logging.getLogger("wildseed.record")


def _stamp(header) -> float:
    return header.stamp.sec + header.stamp.nsec * 1e-9


class RunRecorder:
    """Subscribe to rig streams and persist them under a run directory."""

    def __init__(self, run_dir: Path, topic_prefix: str = "rig",
                 model: str = "sensor_rig", dataset: bool = False):
        self.run_dir = Path(run_dir)
        self.frames_dir = self.run_dir / "frames"
        self.dataset_dir = self.run_dir / "dataset"
        self.topic_prefix = topic_prefix
        self.model = model
        self.dataset = dataset
        self.active = False
        self.counts: Dict[str, int] = {}
        self._frame_times = []
        self._frame_queue = []   # drained by a writer thread, not callbacks
        self._writer = None
        self._imu_rows = []
        self._navsat_rows = []
        self._gt_rows = []

    def _writer_loop(self):
        import cv2
        done = 0
        while self.active or done < len(self._frame_queue):
            if done >= len(self._frame_queue):
                time.sleep(0.02)
                continue
            i, h, w, data = self._frame_queue[done]
            img = np.frombuffer(data, dtype=np.uint8)[: h * w * 3].reshape(h, w, 3)
            cv2.imwrite(str(self.frames_dir / f"frame_{i:06d}.png"),
                        img[:, :, ::-1])
            self._frame_queue[done] = None   # free the bytes as we go
            done += 1

    # -- callbacks (cheap; called from transport threads) ------------------
    def _cam_cb(self, m):
        # PNG encoding takes ~10 ms; doing it here starves the transport
        # thread that also serves service responses (measured: set_pose
        # round-trips ballooned under load). Copy bytes, enqueue, return.
        if not self.active:
            return
        i = self.counts.get("frames", 0)
        self._frame_queue.append((i, m.height, m.width, bytes(m.data)))
        self._frame_times.append(_stamp(m.header))
        self.counts["frames"] = i + 1

    def _lidar_cb(self, m):
        if not (self.active and self.dataset):
            return
        off = {f.name: f.offset for f in m.field}
        n = m.width * m.height
        buf = np.frombuffer(m.data, dtype=np.uint8).reshape(n, m.point_step)

        def f32(name):
            return buf[:, off[name]:off[name] + 4].copy().view(np.float32).ravel()

        i = self.counts.get("lidar", 0)
        arrays = {k: f32(k) for k in ("x", "y", "z") if k in off}
        if "intensity" in off:
            arrays["intensity"] = f32("intensity")
        np.savez_compressed(self.dataset_dir / f"lidar_{i:06d}.npz",
                            t=_stamp(m.header), **arrays)
        self.counts["lidar"] = i + 1

    def _imu_cb(self, m):
        if not (self.active and self.dataset):
            return
        self._imu_rows.append((
            _stamp(m.header),
            m.linear_acceleration.x, m.linear_acceleration.y, m.linear_acceleration.z,
            m.angular_velocity.x, m.angular_velocity.y, m.angular_velocity.z,
            m.orientation.w, m.orientation.x, m.orientation.y, m.orientation.z))
        self.counts["imu"] = len(self._imu_rows)

    def _navsat_cb(self, m):
        if not (self.active and self.dataset):
            return
        self._navsat_rows.append((_stamp(m.header), m.latitude_deg,
                                  m.longitude_deg, m.altitude))
        self.counts["navsat"] = len(self._navsat_rows)

    def _odom_cb(self, m):
        if not (self.active and self.dataset):
            return
        p, q = m.pose.position, m.pose.orientation
        self._gt_rows.append((_stamp(m.header), p.x, p.y, p.z,
                              q.x, q.y, q.z, q.w))
        self.counts["groundtruth"] = len(self._gt_rows)

    # -- lifecycle ----------------------------------------------------------
    def start(self):
        from gz.msgs10.image_pb2 import Image
        from gz.msgs10.imu_pb2 import IMU
        from gz.msgs10.navsat_pb2 import NavSat
        from gz.msgs10.odometry_pb2 import Odometry
        from gz.msgs10.pointcloud_packed_pb2 import PointCloudPacked
        from gz.transport13 import Node

        self.frames_dir.mkdir(parents=True, exist_ok=True)
        if self.dataset:
            self.dataset_dir.mkdir(parents=True, exist_ok=True)
        self._node = Node()   # keep a ref: GC'd node drops subscriptions
        p = self.topic_prefix
        self._topics = [f"{p}/cam_left"]
        self._node.subscribe(Image, f"{p}/cam_left", self._cam_cb)
        if self.dataset:
            self._node.subscribe(PointCloudPacked, f"{p}/lidar/points",
                                 self._lidar_cb)
            self._node.subscribe(IMU, f"{p}/imu", self._imu_cb)
            self._node.subscribe(NavSat, f"{p}/navsat", self._navsat_cb)
            self._node.subscribe(Odometry, f"/model/{self.model}/odometry",
                                 self._odom_cb)
            self._topics += [f"{p}/lidar/points", f"{p}/imu", f"{p}/navsat",
                             f"/model/{self.model}/odometry"]
        self.active = True
        import threading
        self._writer = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer.start()

    def stop(self):
        self.active = False
        # Teardown must be ORDERLY: a subscription left alive at interpreter
        # exit lets gz-transport call back into a dying Python — a flaky,
        # load-dependent segfault (observed after `run complete` under heavy
        # server load). Unsubscribe everything, then drain.
        for topic in getattr(self, "_topics", []):
            try:
                self._node.unsubscribe(topic)
            except Exception as e:
                logger.debug(f"unsubscribe({topic}): {e}")
        time.sleep(0.3)   # let in-flight callbacks drain
        if self._writer is not None:
            self._writer.join(timeout=60)
        if self.dataset:
            with open(self.dataset_dir / "imu.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["t", "ax", "ay", "az", "wx", "wy", "wz",
                            "qw", "qx", "qy", "qz"])
                w.writerows(self._imu_rows)
            with open(self.dataset_dir / "navsat.csv", "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["t", "lat_deg", "lon_deg", "alt_m"])
                w.writerows(self._navsat_rows)
            with open(self.dataset_dir / "groundtruth.txt", "w") as f:
                f.write("# TUM trajectory: t x y z qx qy qz qw (sim time)\n")
                for row in self._gt_rows:
                    f.write(" ".join(f"{v:.6f}" for v in row) + "\n")

    def measured_fps(self) -> Optional[float]:
        if len(self._frame_times) < 2:
            return None
        span = self._frame_times[-1] - self._frame_times[0]
        if span <= 0:
            return None
        return (len(self._frame_times) - 1) / span


def encode_video(frames_dir: Path, out_path: Path, fps: float) -> Optional[Path]:
    """PNG sequence -> mp4 via cv2 (the containers ship no ffmpeg binary)."""
    import cv2

    frames = sorted(Path(frames_dir).glob("frame_*.png"))
    if not frames:
        return None
    first = cv2.imread(str(frames[0]))
    h, w = first.shape[:2]
    writer = cv2.VideoWriter(str(out_path),
                             cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    if not writer.isOpened():
        logger.error("cv2.VideoWriter failed to open; keeping frames only")
        return None
    for fp in frames:
        writer.write(cv2.imread(str(fp)))
    writer.release()
    return out_path


def record_run(traj: Dict, run_dir: Path, world: str = "forest_world",
               model: str = "sensor_rig", topic_prefix: str = "rig",
               dataset: bool = False, keep_frames: bool = False,
               mode: str = "kinematic") -> Dict:
    """Fly ``traj`` against a RUNNING server while recording; returns summary.

    The trajectory (with its mode) is copied into the run dir before takeoff,
    so the run is reproducible and datasets can never lose the provenance of
    their IMU validity: kinematic (set_pose) flight has garbage IMU; dynamic
    (PD wrench) flight has physics-consistent IMU.
    """
    from wildseed.core.fly import fly_dynamic, play_trajectory

    traj = dict(traj, mode=mode)
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "trajectory.json").write_text(json.dumps(traj, indent=1))

    rec = RunRecorder(run_dir, topic_prefix=topic_prefix, model=model,
                      dataset=dataset)
    rec.start()
    tracking = None
    try:
        if mode == "dynamic":
            tracking = fly_dynamic(traj, world=world, model=model)
            calls = tracking.pop("cycles")
        else:
            calls = play_trajectory(traj, world=world, model=model)
    finally:
        rec.stop()

    fps = rec.measured_fps()
    video = None
    if fps:
        video = encode_video(rec.frames_dir, run_dir / "video.mp4", fps)
    if video and not (keep_frames or dataset):
        shutil.rmtree(rec.frames_dir)

    summary = {
        "world": world, "model": model,
        "pattern": traj.get("pattern"), "seed": traj.get("seed"),
        "mode": traj.get("mode"),
        "duration_s": traj.get("duration"),
        "pose_updates": calls,
        "video": video.name if video else None,
        "video_fps": round(fps, 2) if fps else None,
        "streams": rec.counts,
        "dataset": dataset,
    }
    if tracking:
        summary["tracking"] = tracking
    (run_dir / "manifest.json").write_text(json.dumps(summary, indent=1))
    return summary
