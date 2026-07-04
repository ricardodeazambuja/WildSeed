"""Tests for the recording pipeline (docs/SENSOR_RIG.md).

RunRecorder callbacks are exercised with protobuf-shaped fakes so the tests
need no gz installation; encoding uses real cv2.
"""

import json
from types import SimpleNamespace

import numpy as np
import pytest

from wildseed.core.record import RunRecorder, encode_video

cv2 = pytest.importorskip("cv2")


def _header(t):
    return SimpleNamespace(stamp=SimpleNamespace(sec=int(t),
                                                 nsec=int((t % 1) * 1e9)))


def _image_msg(t, w=64, h=48, value=128):
    data = np.full((h, w, 3), value, dtype=np.uint8)
    return SimpleNamespace(header=_header(t), width=w, height=h,
                           data=data.tobytes())


def _imu_msg(t):
    v = SimpleNamespace
    return v(header=_header(t),
             linear_acceleration=v(x=0.0, y=0.0, z=9.8),
             angular_velocity=v(x=0.0, y=0.0, z=0.1),
             orientation=v(w=1.0, x=0.0, y=0.0, z=0.0))


def _odom_msg(t, x):
    v = SimpleNamespace
    return v(header=_header(t),
             pose=v(position=v(x=x, y=0.0, z=30.0),
                    orientation=v(w=1.0, x=0.0, y=0.0, z=0.0)))


def test_frames_written_and_fps_measured(tmp_path):
    rec = RunRecorder(tmp_path / "run")
    rec.frames_dir.mkdir(parents=True)
    rec.active = True
    for i in range(10):
        rec._cam_cb(_image_msg(t=1.0 + i * 0.1, value=i * 20))
    assert rec.counts["frames"] == 10
    rec.active = False
    rec._writer_loop()   # drain the queue synchronously (no thread in test)
    assert len(list(rec.frames_dir.glob("frame_*.png"))) == 10
    assert abs(rec.measured_fps() - 10.0) < 0.2


def test_inactive_recorder_drops_messages(tmp_path):
    rec = RunRecorder(tmp_path / "run")
    rec.frames_dir.mkdir(parents=True)
    rec._cam_cb(_image_msg(t=1.0))   # active is False
    assert rec.counts == {}


def test_dataset_files_written_on_stop(tmp_path):
    rec = RunRecorder(tmp_path / "run", dataset=True)
    rec.frames_dir.mkdir(parents=True)
    rec.dataset_dir.mkdir(parents=True)
    rec.active = True
    for i in range(5):
        rec._imu_cb(_imu_msg(1.0 + i * 0.01))
        rec._odom_cb(_odom_msg(1.0 + i * 0.02, x=float(i)))
    rec.stop()

    imu_lines = (rec.dataset_dir / "imu.csv").read_text().strip().splitlines()
    assert len(imu_lines) == 6 and imu_lines[0].startswith("t,ax")
    gt = (rec.dataset_dir / "groundtruth.txt").read_text().strip().splitlines()
    assert gt[0].startswith("#") and len(gt) == 6
    # TUM order: t x y z qx qy qz qw
    row = gt[2].split()
    assert len(row) == 8 and float(row[1]) == 1.0 and float(row[7]) == 1.0


def test_lidar_npz_roundtrip(tmp_path):
    rec = RunRecorder(tmp_path / "run", dataset=True)
    rec.dataset_dir.mkdir(parents=True)
    rec.active = True
    pts = np.arange(12, dtype=np.float32).reshape(3, 4)   # x y z intensity
    fields = [SimpleNamespace(name=n, offset=i * 4)
              for i, n in enumerate(("x", "y", "z", "intensity"))]
    msg = SimpleNamespace(header=_header(2.0), field=fields, width=3, height=1,
                          point_step=16, data=pts.tobytes())
    rec._lidar_cb(msg)
    loaded = np.load(rec.dataset_dir / "lidar_000000.npz")
    assert np.allclose(loaded["x"], [0, 4, 8])
    assert np.allclose(loaded["intensity"], [3, 7, 11])
    assert float(loaded["t"]) == 2.0


def test_encode_video(tmp_path):
    frames = tmp_path / "frames"
    frames.mkdir()
    for i in range(12):
        img = np.full((48, 64, 3), i * 20, dtype=np.uint8)
        cv2.imwrite(str(frames / f"frame_{i:06d}.png"), img)
    out = encode_video(frames, tmp_path / "video.mp4", fps=10.0)
    assert out is not None and out.exists() and out.stat().st_size > 1000
    cap = cv2.VideoCapture(str(out))
    assert cap.isOpened() and cap.get(cv2.CAP_PROP_FRAME_COUNT) == 12


def test_encode_video_no_frames(tmp_path):
    (tmp_path / "empty").mkdir()
    assert encode_video(tmp_path / "empty", tmp_path / "v.mp4", 10.0) is None
