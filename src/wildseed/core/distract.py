"""Dynamics axis: seeded kinematic distractors on the record path.

The static-world violation stressor (docs/EXPERIMENT_PLAN.md, deferred-axes
design): ``wildseed record --distractors <dial>`` spawns seeded mover models
into the RUNNING world and drives them along precomputed tracks while the rig
flies — scene motion for the cameras, zero change to the world file (the
world's provenance hashes stay valid; the run directory carries the motion
record instead).

Architecture decision (2026-07-08, recorded in the plan): vio_bench is a
static-scene benchmark by construction, so this axis lives on the RECORDING
path and reuses the machinery `fly` already verified — kinematic ``set_pose``
transport (batched via ``set_pose_vector`` when the server offers it), sim-time
pacing, NO physics wrenches and NO gz actors, so RTF stays flat and the
commanded tracks are byte-reproducible from the seed.

Synthesis is pure and deterministic: (trajectory, terrain, dial, seed, model
list) -> a track plan (JSON-ready). The dial 0..1 maps to the mover count
(``round(MAX_DISTRACTORS * dial)``) — the lever behind fraction-of-view-in-
motion; each mover patrols a seeded crossing segment placed ahead of the rig
at its anchor time, so movers enter the camera's view spread across the whole
flight.

Ground truth: the plan itself (per-instance waypoint tracks + velocities) is
copied into the run dir as ``distractors.json`` and the driver's sim-time
epoch lands in the manifest — sample track time ``t_sim - t0_sim`` to get
every mover's commanded pose/velocity at any sensor timestamp. Movers carry
the dedicated ``distractor`` class label (CLASS_LABELS: 8), so per-frame 2-D
motion masks are a plain ``label == 8`` test on the recorded segmentation
stream.
"""

import json
import logging
import math
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from wildseed.core.rig import CLASS_LABELS

logger = logging.getLogger("wildseed.distract")

DISTRACTOR_FORMAT = 1
DISTRACTOR_LABEL = CLASS_LABELS["distractor"]
MAX_DISTRACTORS = 16          # dial 1.0; scales fraction-of-view-in-motion
TRACK_RATE = 10.0             # waypoints/s in the plan (interpolated at drive)
_TRACK_COLUMNS = ("t", "x", "y", "z", "yaw", "vx", "vy", "vz")

# distractor stream tag: its own seed family, disjoint from world stages and
# the calib/sampler streams by construction.
_DISTRACT_TAG = 0xD15_7AC7

# categories whose converted models make plausible ground-level movers
_MOVER_CATEGORIES = ("bush", "rock")
_GROUND_CLEARANCE = 0.25      # m; movers glide just above the terrain


def list_mover_models(models_root: Path,
                      categories=_MOVER_CATEGORIES) -> List[str]:
    """Sorted ``category/model`` URIs usable as movers (deterministic listing)."""
    out = []
    for cat in categories:
        cat_dir = Path(models_root) / cat
        if not cat_dir.is_dir():
            continue
        for d in sorted(cat_dir.iterdir()):
            if (d / "model.sdf").exists():
                out.append(f"{cat}/{d.name}")
    return out


def synthesize_distractors(traj: Dict, terrain, dial: float, seed: int,
                           model_uris: List[str]) -> Optional[Dict]:
    """Seeded mover plan for one flight (pure; same inputs -> same JSON).

    Each mover patrols a crossing segment ahead of the rig at its anchor time
    (anchors spread over the flight), phase-aligned so it is near the rig's
    line of sight when the rig gets there. Returns None at dial 0.
    """
    dial = float(min(max(dial, 0.0), 1.0))
    count = int(round(MAX_DISTRACTORS * dial))
    if count == 0:
        return None
    if not model_uris:
        raise ValueError("no mover models found (need converted bush/rock "
                         "models under models/)")
    from wildseed.core.fly import interpolate_pose

    rng = np.random.default_rng(np.random.SeedSequence((_DISTRACT_TAG,
                                                        int(seed))))
    duration = float(traj["duration"])
    n_wp = max(int(duration * TRACK_RATE), 2)
    t_wp = np.arange(n_wp) / TRACK_RATE
    x0, y0, x1, y1 = (terrain.x_min, terrain.y_min,
                      terrain.x_max, terrain.y_max)

    movers = []
    for i in range(count):
        # anchor: when (and roughly where) this mover should cross the view
        frac = (i + 0.5) / count + rng.uniform(-0.3, 0.3) / count
        t_anchor = float(np.clip(frac, 0.02, 0.98)) * duration
        p = interpolate_pose(traj, t_anchor)
        yaw = 2.0 * math.atan2(p["qz"], p["qw"])   # rig yaw (roll/pitch small)

        ahead = rng.uniform(8.0, 22.0)             # crossing distance, m
        cx = p["x"] + ahead * math.cos(yaw)
        cy = p["y"] + ahead * math.sin(yaw)
        half = rng.uniform(5.0, 14.0)              # patrol half-length, m
        c_ang = yaw + math.pi / 2 + rng.uniform(-0.5, 0.5)
        ax, ay = cx - half * math.cos(c_ang), cy - half * math.sin(c_ang)
        bx, by = cx + half * math.cos(c_ang), cy + half * math.sin(c_ang)
        # keep endpoints on the terrain (movers outside the mesh glide on the
        # nearest-neighbour fallback height — visually fine, but clamp anyway)
        ax, bx = np.clip([ax, bx], x0, x1)
        ay, by = np.clip([ay, by], y0, y1)

        speed = float(rng.uniform(0.6, 2.4))       # m/s along the patrol
        leg = math.hypot(bx - ax, by - ay)
        period = 2.0 * leg / speed                 # A->B->A
        # phase so the mover sits at the segment centre at t_anchor
        phase = (0.25 * period - t_anchor) % period

        # triangle-wave patrol position over the whole flight
        s = ((t_wp + phase) % period) / period     # 0..1
        u = np.where(s < 0.5, 2.0 * s, 2.0 - 2.0 * s)  # 0->1->0
        xs = ax + (bx - ax) * u
        ys = ay + (by - ay) * u
        zs = np.asarray(terrain.height(xs, ys), dtype=float) + _GROUND_CLEARANCE
        direction = np.where(s < 0.5, 1.0, -1.0)
        yaw_m = math.atan2(by - ay, bx - ax)
        yaws = np.where(direction > 0, yaw_m,
                        math.atan2(-(by - ay), -(bx - ax)))
        vx = direction * speed * math.cos(yaw_m)
        vy = direction * speed * math.sin(yaw_m)
        vz = np.gradient(zs, 1.0 / TRACK_RATE)

        model = str(model_uris[int(rng.integers(0, len(model_uris)))])
        movers.append({
            "name": f"distractor_{i:02d}",
            "model": model,
            "speed": round(speed, 3),
            "anchor_t": round(t_anchor, 3),
            "waypoints": [
                [round(float(t_wp[k]), 3), round(float(xs[k]), 4),
                 round(float(ys[k]), 4), round(float(zs[k]), 4),
                 round(float(yaws[k]), 5), round(float(vx[k]), 4),
                 round(float(vy[k]), 4), round(float(vz[k]), 4)]
                for k in range(n_wp)],
        })

    return {
        "format": DISTRACTOR_FORMAT,
        "dial": dial, "seed": int(seed),
        "count": count, "label": DISTRACTOR_LABEL,
        "rate": TRACK_RATE, "duration": round(duration, 4),
        "columns": list(_TRACK_COLUMNS),
        "distractors": movers,
    }


def mover_sdf(name: str, model_uri: str, pose_xyzyaw) -> str:
    """SDF string for one spawned mover (EntityFactory payload).

    Static (no physics body to fall or cost RTF; ``set_pose`` moves static
    models fine — it writes the world pose directly), wrapped so the Label
    system rides along: motion masks come from segmentation label == 8.
    """
    x, y, z, yaw = pose_xyzyaw
    return f"""<?xml version="1.0"?>
<sdf version="1.9">
  <model name="{name}">
    <static>true</static>
    <pose>{x:.4f} {y:.4f} {z:.4f} 0 0 {yaw:.5f}</pose>
    <plugin filename="gz-sim-label-system" name="gz::sim::systems::Label">
      <label>{DISTRACTOR_LABEL}</label>
    </plugin>
    <include merge="true">
      <uri>model://{model_uri}</uri>
    </include>
  </model>
</sdf>
"""


def track_pose(mover: Dict, t: float):
    """Commanded (x, y, z, yaw) of one mover at track time t (clamped)."""
    wp = mover["waypoints"]
    if t <= wp[0][0]:
        r = wp[0]
        return r[1], r[2], r[3], r[4]
    if t >= wp[-1][0]:
        r = wp[-1]
        return r[1], r[2], r[3], r[4]
    i = min(int(t * TRACK_RATE), len(wp) - 2)
    a, b = wp[i], wp[i + 1]
    if not a[0] <= t <= b[0]:
        i = next(j for j in range(len(wp) - 1)
                 if wp[j][0] <= t <= wp[j + 1][0])
        a, b = wp[i], wp[i + 1]
    w = (t - a[0]) / max(b[0] - a[0], 1e-9)
    x = a[1] + w * (b[1] - a[1])
    y = a[2] + w * (b[2] - a[2])
    z = a[3] + w * (b[3] - a[3])
    # yaw flips 180 deg at patrol turnarounds — take the nearer endpoint
    yaw = a[4] if w < 0.5 else b[4]
    return x, y, z, yaw


class DistractorDriver:
    """Spawn the plan's movers into a RUNNING world and drive them.

    Kinematic, sim-time paced (same discipline as play_trajectory): ONE
    batched ``set_pose_vector`` request per tick (Harmonic always offers it),
    short timeout, and a timed-out tick is simply skipped — under render load
    the server answers late but still applies the command, and any retry or
    per-model fallback just multiplies the service contention until the rig's
    own playback starves (measured: a serial per-model fallback drove the
    rig's set_pose rejections from 55/554 to 134/134). Runs on its own thread
    so the rig flight loop is untouched.
    """

    def __init__(self, plan: Dict, world: str = "forest_world",
                 update_hz: float = 10.0):
        self.plan = plan
        self.world = world
        self.update_hz = update_hz
        self.t0_sim: Optional[float] = None
        self.ticks = 0
        self.acks = 0
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- gz plumbing --------------------------------------------------------
    def _connect(self):
        from gz.msgs10.world_stats_pb2 import WorldStatistics
        from gz.transport13 import Node

        self._node = Node()
        self._sim = {"t": None, "wall": None, "rtf": 1.0}

        def stats_cb(msg):
            self._sim["t"] = msg.sim_time.sec + msg.sim_time.nsec * 1e-9
            self._sim["wall"] = time.time()
            if msg.real_time_factor > 0:
                self._sim["rtf"] = msg.real_time_factor

        self._stats_topic = f"/world/{self.world}/stats"
        self._node.subscribe(WorldStatistics, self._stats_topic, stats_cb)
        deadline = time.time() + 30
        while self._sim["t"] is None:
            if time.time() > deadline:
                raise RuntimeError(
                    f"no sim clock on {self._stats_topic} in 30 s")
            time.sleep(0.05)

    def _sim_now(self):
        s = self._sim
        return s["t"] + (time.time() - s["wall"]) * s["rtf"]

    def spawn(self):
        """Create every mover at its t=0 pose; returns the spawned count."""
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10.entity_factory_pb2 import EntityFactory

        self._connect()
        service = f"/world/{self.world}/create"
        spawned = 0
        for m in self.plan["distractors"]:
            req = EntityFactory()
            req.sdf = mover_sdf(m["name"], m["model"], track_pose(m, 0.0))
            req.name = m["name"]
            req.allow_renaming = False
            ok, rep = self._node.request(service, req, EntityFactory,
                                         Boolean, 5000)
            if ok and rep.data:
                spawned += 1
            else:
                logger.warning(f"spawn failed for {m['name']} "
                               f"({m['model']}) on {service}")
        # let the render/scene absorb the new entities before driving them —
        # right after spawn every service round-trip times out for a while
        time.sleep(3.0)
        return spawned

    def _drive_batch(self, poses, timeout_ms: int = 300) -> bool:
        """One set_pose_vector request for all movers; False on timeout."""
        from gz.msgs10.boolean_pb2 import Boolean
        from gz.msgs10 import pose_pb2  # noqa: F401 — registers gz.msgs.Pose,
        # or Pose_V's repeated field can't construct entries (measured:
        # "No message class registered for 'gz.msgs.Pose'")
        from gz.msgs10.pose_v_pb2 import Pose_V

        req = Pose_V()
        for name, (x, y, z, yaw) in poses:
            p = req.pose.add()
            p.name = name
            p.position.x, p.position.y, p.position.z = x, y, z
            p.orientation.w = math.cos(yaw / 2)
            p.orientation.z = math.sin(yaw / 2)
        ok, rep = self._node.request(
            f"/world/{self.world}/set_pose_vector", req, Pose_V, Boolean,
            timeout_ms)
        return bool(ok and rep.data)

    def _loop(self):
        t0 = self._sim_now()
        self.t0_sim = t0
        end_t = float(self.plan["duration"]) + 30.0   # settle + overrun slack
        while not self._stop.is_set():
            t = self._sim_now() - t0
            if t > end_t:
                break
            poses = [(m["name"], track_pose(m, t))
                     for m in self.plan["distractors"]]
            try:
                if self._drive_batch(poses, 250):
                    self.acks += 1
            except Exception as e:
                # a driver hiccup must degrade to no-motion-this-tick, never
                # kill the thread mid-flight (a dead driver = silent static
                # scene, indistinguishable from dial 0 in the dataset)
                logger.warning(f"distractor drive tick failed: {e}")
            self.ticks += 1
            time.sleep(1.0 / self.update_hz)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        # wait for the epoch so callers can record it
        deadline = time.time() + 10
        while self.t0_sim is None and time.time() < deadline:
            time.sleep(0.02)

    def stop(self, remove: bool = False):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
        if remove:
            try:
                from gz.msgs10.boolean_pb2 import Boolean
                from gz.msgs10.entity_pb2 import Entity
                for m in self.plan["distractors"]:
                    req = Entity()
                    req.name = m["name"]
                    req.type = Entity.MODEL
                    self._node.request(f"/world/{self.world}/remove",
                                       req, Entity, Boolean, 1000)
            except Exception as e:   # best-effort cleanup only
                logger.debug(f"remove distractors: {e}")
        try:
            self._node.unsubscribe(self._stats_topic)
        except Exception as e:
            logger.debug(f"unsubscribe({self._stats_topic}): {e}")
        time.sleep(0.2)   # let in-flight callbacks drain (teardown gotcha)


def write_plan(plan: Dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=1))
    return path
