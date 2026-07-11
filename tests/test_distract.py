"""Tests for the dynamics axis (seeded distractors on the record path).

Synthesis + SDF + track interpolation are pure and run without gz; the
recorder's segmentation stream is exercised with protobuf-shaped fakes like
tests/test_record.py.
"""

import json
import math
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from wildseed.core.distract import (DISTRACTOR_LABEL, MAX_DISTRACTORS,
                                    TRACK_RATE, list_mover_models, mover_sdf,
                                    synthesize_distractors, track_pose,
                                    write_plan)
from wildseed.core.fly import synthesize
from wildseed.core.rig import CLASS_LABELS


class FlatTerrain:
    """height = 3 everywhere; the analytic stand-in for a TerrainSampler."""
    x_min, y_min, x_max, y_max = -100.0, -100.0, 100.0, 100.0

    def height(self, x, y):
        return np.full(np.shape(np.asarray(x)), 3.0)

    def bounds(self, margin=0.0):
        return (self.x_min + margin, self.y_min + margin,
                self.x_max - margin, self.y_max - margin)


@pytest.fixture(scope="module")
def traj():
    return synthesize("flythrough", seed=11, terrain=FlatTerrain())


MODELS = ["bush/fern_02", "rock/moss_rock_01", "bush/dune_grass"]


def test_distractor_label_registered():
    assert CLASS_LABELS["distractor"] == DISTRACTOR_LABEL == 8
    # the shared id space must not have been renumbered
    assert CLASS_LABELS["tree"] == 1 and CLASS_LABELS["water"] == 7


def test_dial_zero_is_none_and_count_scales(traj):
    assert synthesize_distractors(traj, FlatTerrain(), 0.0, 5, MODELS) is None
    half = synthesize_distractors(traj, FlatTerrain(), 0.5, 5, MODELS)
    full = synthesize_distractors(traj, FlatTerrain(), 1.0, 5, MODELS)
    assert half["count"] == round(MAX_DISTRACTORS * 0.5) == len(half["distractors"])
    assert full["count"] == MAX_DISTRACTORS == len(full["distractors"])
    assert full["label"] == DISTRACTOR_LABEL


def test_plan_deterministic_and_seed_sensitive(traj, tmp_path):
    a = synthesize_distractors(traj, FlatTerrain(), 0.7, 5, MODELS)
    b = synthesize_distractors(traj, FlatTerrain(), 0.7, 5, MODELS)
    pa = write_plan(a, tmp_path / "a.json")
    pb = write_plan(b, tmp_path / "b.json")
    assert pa.read_bytes() == pb.read_bytes()
    c = synthesize_distractors(traj, FlatTerrain(), 0.7, 6, MODELS)
    assert json.dumps(c) != json.dumps(a)


def test_no_models_is_an_error(traj):
    with pytest.raises(ValueError, match="no mover models"):
        synthesize_distractors(traj, FlatTerrain(), 0.5, 5, [])


def test_tracks_ground_follow_and_cover_flight(traj):
    plan = synthesize_distractors(traj, FlatTerrain(), 1.0, 5, MODELS)
    assert plan["duration"] == traj["duration"]
    for m in plan["distractors"]:
        wp = np.array(m["waypoints"])
        assert wp[0, 0] == 0.0
        assert wp[-1, 0] >= traj["duration"] - 2.0 / TRACK_RATE
        assert np.allclose(wp[:, 3], 3.0 + 0.25)      # z = ground + clearance
        # speed honoured along the patrol (away from turnarounds)
        v = np.hypot(wp[:, 5], wp[:, 6])
        assert np.isclose(np.median(v), m["speed"], atol=0.01)
        assert m["model"] in MODELS


def test_track_pose_interpolates_and_clamps(traj):
    plan = synthesize_distractors(traj, FlatTerrain(), 0.5, 5, MODELS)
    m = plan["distractors"][0]
    wp = m["waypoints"]
    x, y, z, yaw = track_pose(m, -1.0)                # clamp low
    assert (x, y, z, yaw) == tuple(wp[0][1:5])
    x, y, z, yaw = track_pose(m, 1e9)                 # clamp high
    assert (x, y, z, yaw) == tuple(wp[-1][1:5])
    t_mid = (wp[3][0] + wp[4][0]) / 2                 # halfway between wps
    x, y, z, yaw = track_pose(m, t_mid)
    assert min(wp[3][1], wp[4][1]) - 1e-9 <= x <= max(wp[3][1], wp[4][1]) + 1e-9


def test_mover_sdf_shape():
    sdf = mover_sdf("distractor_03", "bush/fern_02", (1.0, -2.0, 3.25, 0.5))
    root = ET.fromstring(sdf)
    model = root.find("model")
    assert model.get("name") == "distractor_03"
    assert model.findtext("static") == "true"
    plugin = model.find("plugin")
    assert plugin.get("name") == "gz::sim::systems::Label"
    assert plugin.findtext("label") == str(DISTRACTOR_LABEL)
    inc = model.find("include")
    assert inc.get("merge") == "true"
    assert inc.findtext("uri") == "model://bush/fern_02"
    pose = [float(v) for v in model.findtext("pose").split()]
    assert pose[:3] == [1.0, -2.0, 3.25] and math.isclose(pose[5], 0.5)


def test_list_mover_models_sorted_and_filtered(tmp_path):
    for name in ("bush/b2", "bush/b1", "rock/r1", "tree/t1"):
        d = tmp_path / name
        d.mkdir(parents=True)
        (d / "model.sdf").write_text("<sdf/>")
    (tmp_path / "bush" / "incomplete").mkdir()        # no model.sdf -> skipped
    # rock/r1 has no readable GLB -> benefit of the doubt, kept
    assert list_mover_models(tmp_path) == ["bush/b1", "bush/b2", "rock/r1"]
    assert list_mover_models(tmp_path / "missing") == []


def _mini_glb(positions, triangles):
    """Minimal valid GLB: one mesh, one indexed primitive."""
    import struct

    pos = np.asarray(positions, np.float32)
    idx = np.asarray(triangles, np.uint16).ravel()
    binchunk = pos.tobytes() + idx.tobytes()
    binchunk += b"\x00" * (-len(binchunk) % 4)
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binchunk)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": pos.nbytes},
            {"buffer": 0, "byteOffset": pos.nbytes, "byteLength": idx.nbytes},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": len(pos),
             "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": len(idx),
             "type": "SCALAR"},
        ],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0},
                                    "indices": 1}]}],
    }
    j = json.dumps(gltf).encode()
    j += b" " * (-len(j) % 4)
    total = 12 + 8 + len(j) + 8 + len(binchunk)
    return (b"glTF" + struct.pack("<II", 2, total)
            + struct.pack("<I", len(j)) + b"JSON" + j
            + struct.pack("<I", len(binchunk)) + b"BIN\x00" + binchunk)


TETRA = _mini_glb([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]],
                  [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]])  # closed
SHELL = _mini_glb([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])  # open


def test_glb_open_ratio_discriminates():
    from wildseed.core.distract import glb_open_ratio

    def write(tmp, name, blob):
        p = tmp / name
        p.write_bytes(blob)
        return p

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        assert glb_open_ratio(write(td, "tetra.glb", TETRA)) == 0.0
        assert glb_open_ratio(write(td, "shell.glb", SHELL)) == 1.0
        assert glb_open_ratio(td / "missing.glb") is None


def test_open_shell_rocks_are_dropped_from_pool(tmp_path):
    for name, blob in (("rock/solid", TETRA), ("rock/shell", SHELL),
                       ("bush/cards", SHELL)):        # open bushes are kept
        d = tmp_path / name
        (d / "mesh").mkdir(parents=True)
        (d / "model.sdf").write_text("<sdf/>")
        (d / "mesh" / f"{d.name}.glb").write_bytes(blob)
    assert list_mover_models(tmp_path) == ["bush/cards", "rock/solid"]


# --------------------------------------------------------------------------- #
# recorder segmentation stream
# --------------------------------------------------------------------------- #

cv2 = pytest.importorskip("cv2")


def _header(t):
    return SimpleNamespace(stamp=SimpleNamespace(sec=int(t),
                                                 nsec=int((t % 1) * 1e9)))


def test_recorder_seg_stream_roundtrips_labels(tmp_path):
    from wildseed.core.record import RunRecorder

    rec = RunRecorder(tmp_path / "run", dataset=True)
    rec.frames_dir.mkdir(parents=True)
    rec.dataset_dir.mkdir(parents=True)
    rec.active = True
    seg = np.zeros((48, 64, 3), dtype=np.uint8)
    seg[10:20, 30:40, 2] = DISTRACTOR_LABEL          # class label in channel 2
    msg = SimpleNamespace(header=_header(2.5), width=64, height=48,
                          data=seg.tobytes())
    rec._seg_cb(msg)
    assert rec.counts["segmentation"] == 1
    rec.active = False
    rec._writer_loop()
    rec.stop()

    loaded = cv2.imread(str(rec.dataset_dir / "seg_000000.png"))
    assert np.array_equal(loaded, seg)               # exact byte round-trip
    assert (loaded[15, 35, 2] == DISTRACTOR_LABEL and
            (loaded[:, :, 2] == DISTRACTOR_LABEL).sum() == 100)
    seg_csv = (rec.dataset_dir / "seg.csv").read_text().splitlines()
    assert seg_csv[0] == "idx,t" and seg_csv[1].startswith("0,2.5")


def test_recorder_seg_ignored_without_dataset(tmp_path):
    from wildseed.core.record import RunRecorder

    rec = RunRecorder(tmp_path / "run", dataset=False)
    rec.frames_dir.mkdir(parents=True)
    rec.active = True
    seg = np.zeros((8, 8, 3), dtype=np.uint8)
    rec._seg_cb(SimpleNamespace(header=_header(1.0), width=8, height=8,
                                data=seg.tobytes()))
    assert "segmentation" not in rec.counts
