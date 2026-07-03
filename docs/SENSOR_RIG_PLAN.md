# Plan: seeded sensor rig — a flying eye to test worlds and record demos

> **Self-contained execution plan (Phase 0 → 5).** Written so it can be run with a cleared
> context: it states the current repo state, the tools/commands, the known gotchas, and a
> measurable acceptance gate per phase. Hand this file to `/goal`.

---

## 0. Goal in one sentence

Give WildSeed a **built-in, seeded sensor rig** (3D lidar, stereo + wide-angle + RGB +
depth + segmentation cameras, IMU, GPS, baro, mag) that flies scripted trajectories
through any generated world — to **test the worlds with real sensor streams** and to
**record reproducible demo videos** — all headless, all seeded, no ROS.

**Scope guard (decided by the user — don't relitigate):** WildSeed's focus is **world
generation, not robots**. The rig is a *test instrument and camera dolly*: no autopilot,
no state estimation, no navigation stack. ROS is optional and confined to Phase 5.

---

## 1. Current state (what already exists — start here, don't rebuild)

Branch: `main`. Everything below is committed.

**Already proven (a previous spike paid for this — reuse it):**
- `worlds/forest_spike.world` — a WildSeed world **already hosting live sensors**:
  the 6 gz Harmonic system plugins (`Physics`, `UserCommands`, `SceneBroadcaster`,
  `Sensors` w/ ogre2, `Imu`, `NavSat`), `<spherical_coordinates>` (required by navsat),
  and a static `sensor_rig` model with camera + 16-ch `gpu_lidar` + navsat + imu.
- `tools/capture_sensors.py` — subscribes camera/lidar/navsat via **Python
  `gz.transport13` / `gz.msgs10`** (available inside the containers, no ROS) and
  verdicts each stream. `tools/capture_cam.py` grabs one frame from any image topic.
- The gz server runs headless: `gz sim -s -r <world>` inside `wildseed:egl`.

**Pipeline (context):**
- `wildseed` CLI (`src/wildseed/cli/main.py` registers subcommands; core logic in
  `src/wildseed/core/`). Worlds in `worlds/`, models in `models/` (gitignored,
  regenerable via `tools/build_assets.py` + `assets/manifest.yaml`).
- `wildseed scenario --seed N` — master-seeded world recipe (SeedSequence.spawn per
  stage); the 6 CC0 demos build via `tools/build_scenarios.py`.
- `src/wildseed/core/assetgen.py` — seeded parametric assets generated in Blender.
- `tools/compare.py` — image-level feature metrics harness (from DEMO_REALISM_V2).
- Ground truth: `instances.json` per world + `laser_retro` per-instance labels
  (**written but never verified against a gz lidar** — Phase 0 closes this).

**How to run anything (GPU render needs this exact form):**
```bash
docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -v "$PWD:/workspace" \
  --entrypoint bash wildseed:egl -c 'cd /workspace && <command>'
```
`wildseed:egl` and `:latest` are the **pinned** images (rebuild from `docker/Dockerfile*`
if missing). Host has `ffmpeg` (conda env `local`) and an RTX 2070 (`--gpus all` works).

**Read these memory notes first (hard-won gotchas):** `forest3d-reproducible-demos`,
`wildseed-cropcraft-features`, `wildseed-domain-randomization`,
`forest3d-master-seed-scenario`, `wildseed-rename-standalone`.

**Prior art being ported (concept, not code):**
[`simple_quad_gazebo`](https://github.com/ricardodeazambuja/simple_quad_gazebo) — the
user's Gazebo-Classic/ROS2 "hand-of-god" fork. Its mechanics: PD force tracking
(`force = kl·pos_err − cl·vel` via `AddForce`) keeps physics consistent (⇒ sane IMU),
plus **faked pitch/roll from commanded acceleration** for visual realism, plus `cmd_vel`.
Gazebo Classic + `gazebo_ros` are dead ends here (we're gz-sim Harmonic, ROS-free);
rebuild the concept with Harmonic built-ins — **no custom C++**:
- `gz::sim::systems::ApplyLinkWrench` — accepts wrench commands on a topic ⇒ the PD
  loop becomes a small Python gz-transport script (Phase 4).
- `/world/<name>/set_pose` service — kinematic pose driving for cinematic shots (Phase 2).

---

## 2. The sensor suite (all gz-sim Harmonic built-ins, ogre2/EGL)

| sensor | gz type | notes |
|---|---|---|
| 3D lidar | `gpu_lidar` | configurable channels; VLP-16-ish (16×360) default, OS-32-ish preset |
| stereo pair | 2 × `camera` | rigid baseline (e.g. 12 cm), identical intrinsics |
| RGB + depth | `rgbd_camera` | aligned RGB+D in one sensor |
| wide-angle | `wideangle_camera` (fallback: `camera` w/ large FOV) | what real VIO rigs use |
| IMU | `imu` | needs `Imu` system plugin; only meaningful in Phase-4 dynamic mode |
| GPS | `navsat` | needs `NavSat` system plugin + `<spherical_coordinates>` (seeded origin) |
| barometer | `air_pressure` | needs `AirPressure` system plugin |
| magnetometer | `magnetometer` | needs `Magnetometer` system plugin + `<magnetic_field>` in world |
| segmentation | `segmentation_camera` | **requires `Label` system + `<label>` on models** — worldgen must inject labels (pairs with `instances.json` / `laser_retro` GT) |
| GT pose | `gz::sim::systems::OdometryPublisher` | ground-truth trajectory → TUM export |

Deliberately out (revisit later if asked): thermal, boundingbox camera, altimeter, contact.

---

## PHASE 0 — full sensor spike, verified headless (BUILD FIRST)

**Objective:** prove every sensor above publishes non-blank, plausible data in a WildSeed
world, headless in `wildseed:egl` — before any productization.

**Steps:**
1. Extend `worlds/forest_spike.world`'s rig with: second camera (stereo baseline),
   `rgbd_camera`, `air_pressure`, `magnetometer` (+ `<magnetic_field>` + `AirPressure`/
   `Magnetometer` system plugins), `segmentation_camera`, `OdometryPublisher`.
2. Segmentation needs labels: add the `Label` system + `<label>` to at least two included
   models in the spike world (tree, rock) — hand-edit is fine at spike stage.
3. Extend `tools/capture_sensors.py` to subscribe **all** streams. 3D lidar must be read
   as `PointCloudPacked` (`<topic>/points`), not `LaserScan`. Verdict each stream
   (non-blank image / finite hit stats / gravity-magnitude accel / plausible pressure &
   field / ≥2 distinct segmentation ids).
4. **Verify `laser_retro`:** check the lidar message's intensity field against the labels
   written by the converter (this has been claimed-but-unverified since the cropcraft
   work — settle it; if gz Harmonic drops it, document that honestly and lean on the
   segmentation camera for semantic GT instead).

**Acceptance gate:** one command runs the spike world + capture script in `wildseed:egl`
and prints a PASS verdict per sensor; findings (esp. laser_retro + segmentation)
committed to this file's §Findings.

---

## PHASE 1 — the rig as a first-class, templated model

**Objective:** `sensor_rig` becomes a generated, configurable model + CLI, dropped into
any world.

**Files:** new `src/wildseed/core/rig.py`, `src/wildseed/cli/rig.py` (register in
`cli/main.py`), rig YAML config (defaults in `src/wildseed/config/`), template →
`models/sensor_rig/{model.config,model.sdf}`.

**Steps:**
- YAML config: which sensors on/off, rates, resolutions, lidar channels, stereo baseline,
  mount poses. `wildseed rig --config … --output models/` generates the model.
- Visual body: simple seeded parametric quad via the existing `assetgen` machinery (keep
  it light; it's a camera dolly, not a hero asset). Gravity off / kinematic-friendly:
  `<static>false</static>` + `<gravity>false</gravity>` on the link so both Phase-2
  (kinematic) and Phase-4 (wrench) modes work with the same model.
- Worldgen integration: `--rig` flag on `wildseed generate` / `scenario` includes the rig
  and injects the required system plugins + seeded `<spherical_coordinates>` +
  `<magnetic_field>`; `<label>` injection for all placed instances (ties into
  `instances.json` numbering so segmentation ids == instance ids).

**Acceptance gate:** `gz sdf -p` validates the generated model; a scenario world built
with `--rig` shows **all** rig topics live (Phase-0 capture script passes against it);
unit tests cover config→SDF generation (no GPU needed).

---

## PHASE 2 — seeded trajectories: cinematic fly mode

**Objective:** `wildseed fly --seed N --pattern orbit|flythrough|lawnmower|dolly` drives
the rig smoothly through the world for camera work.

**Files:** new `src/wildseed/core/fly.py` (trajectory synth), `src/wildseed/cli/fly.py`.

**Steps:**
- Trajectory synth: seeded waypoints per pattern → smooth spline (Catmull-Rom / cubic;
  `scipy` is available) → `(t, pose)` samples at fixed rate; yaw follows velocity
  (look-ahead), pitch gentle. **Terrain-following:** sample the world's DEM (we generate
  it — reuse `core/terraingen.py` grids) to hold AGL; clamp above canopy where needed.
- Runtime: Python gz-transport loop calls `/world/<name>/set_pose` at sim-time rate
  (subscribe `/clock` or `/stats`; do NOT free-run wall-clock).
- Trajectory is also written to disk (`trajectory.json`: t, xyz, quat) **before** playback
  — the seed defines the file, the file defines the flight.

**Acceptance gate:** same seed ⇒ byte-identical `trajectory.json`; a capture from a fly
run shows smooth motion (no teleport jumps between consecutive frames); unit tests for
seeded determinism + AGL bounds (no GPU needed).

---

## PHASE 3 — recording: demo videos + sensor datasets

**Objective:** `wildseed record` turns a world + seed + pattern into (a) an mp4 demo
video, (b) optionally a dataset dump.

**Files:** new `src/wildseed/core/record.py`, `src/wildseed/cli/record.py`.

**Steps:**
- Frame capture: subscribe the rig's RGB camera (reuse capture machinery), write
  numbered PNGs to `frames/<run>/`; drive the flight (Phase 2) in the same process or
  as a child; stop after the trajectory completes.
- Encode: host-side `ffmpeg` (document the exact command) OR inside-container if ffmpeg
  is present — do NOT rebuild the pinned images just for encoding.
- Dataset mode (`--dataset`): also dump lidar `PointCloudPacked` → `.npy`, IMU → CSV,
  GT odometry → TUM `groundtruth.txt`, camera info → YAML. Everything under one run dir
  with a `manifest.json` (seed, world, pattern, rates).
- Wire a `tools/record_demo.sh` (or Make target) that does world→fly→record→encode for
  one scenario in one command.

**Acceptance gate:** one command produces an mp4 for a demo scenario; re-running with the
same seed produces the same trajectory (frames may differ per GPU nondeterminism — the
*trajectory* is the reproducibility contract). Dataset mode emits all files with sane
sizes/counts.

---

## PHASE 4 — dynamic mode: hand-of-god reborn (honest IMU)

**Objective:** an alternative fly mode where the rig is *pushed* by forces, not
teleported — so IMU/dynamics are physically consistent (real sensor-fusion test data).

**Files:** `src/wildseed/core/fly.py` (add `--mode dynamic`), rig SDF gains
`ApplyLinkWrench` plugin (Phase-1 template flag).

**Steps:**
- PD tracker in Python (port of `gazebo_ros_simple_quad.cpp` mechanics): wrench =
  `kp·pos_err − kd·vel` + **gravity compensation** (mass from SDF), published to the
  `ApplyLinkWrench` command topic; angular PD for yaw; optional **fake pitch/roll** from
  commanded acceleration (the old plugin's visual trick) — implemented as orientation
  targets, small angles.
- Enable gravity on the link in this mode (it's compensated); tune gains against a
  Phase-2 spline at modest speed.
- IMU sanity check in the capture script: at hover, |accel| ≈ 9.81 ± tolerance; during
  flight, accel is smooth (no set_pose-style spikes).

**Acceptance gate:** on a reference spline, position tracking error stays bounded
(state the bound after tuning, e.g. < 1 m at ≤ 5 m/s); IMU verdict PASS (gravity at
hover, spike-free in flight); documented gain defaults.

---

## PHASE 5 (optional) — ROS 2 bridge overlay

**Objective:** rosbag recording for ROS users **without touching the core images**.

**Steps:** `docker/Dockerfile.ros` overlay `FROM wildseed:egl` adding `ros-<distro>-ros-gz`
(pick the distro matching gz Harmonic pairings — Jazzy); a bridge YAML for the rig topics;
short doc section.

**Acceptance gate (minimal):** overlay builds; `ros2 topic list` shows bridged rig topics
against a running spike world; `ros2 bag record` produces a non-empty bag. **If the build
proves too heavy, deliver the Dockerfile + doc marked EXPERIMENTAL/untested and say so.**

---

## Order of attack & working rules

- **Phase 0 first** — it retires all remaining unknowns (segmentation labels,
  laser_retro, PointCloudPacked, baro/mag plugins) in one session. Then 1→2→3 (this
  yields the demo videos), then 4, then 5.
- **Commit per phase** with the gate evidence in the message. **Do NOT push.**
- IMU from kinematic (`set_pose`) motion is garbage by construction — never present it
  as sensor data; dataset mode must record which fly mode produced it.
- gz render needs the GPU docker form (§1) — llvmpipe otherwise; sensors need
  `<render_engine>ogre2</render_engine>` in the `Sensors` system.
- Sim time, not wall time, for anything that touches playback or capture.
- Keep `models/` gitignored (generated); the rig *template/config/code* is committed,
  the generated model is not.
- Update auto-memory with new gotchas as they're found (gz message field quirks,
  segmentation label behavior, wrench topic naming, etc.).
- Honest reporting: every gate verdict goes into §Findings below, including failures.

---

## Findings (filled as phases complete)

### Phase 0 — GATE MET: 13/13 sensor streams PASS (headless, wildseed:egl, GPU)

World: `worlds/sensor_spike.world` (superset of `forest_spike.world`, kept separate);
harness: `tools/capture_sensors.py`. Debug frames in `frames/spike/`. Run:
```bash
docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -v "$PWD:/workspace" \
  --entrypoint bash wildseed:egl -c 'cd /workspace && \
  GZ_SIM_RESOURCE_PATH=/workspace/models gz sim -s -r worlds/sensor_spike.world \
  > /tmp/gz.log 2>&1 & sleep 10; python3 tools/capture_sensors.py'
```

Stream verdicts: stereo cams, wide-angle (`wideanglecamera` works on ogre2/EGL),
rgbd (rgb + float32 depth), instance segmentation (labels + colored), 3D gpu_lidar
(PointCloudPacked, fields x/y/z/intensity/ring), imu, navsat, air_pressure,
magnetometer, GT odometry (`OdometryPublisher`) — all publishing plausible data.

**Hard-won findings (do not rediscover):**
1. **`laser_retro` is read from the VISUAL, not the collision.** gpu_lidar is
   rendering-based: the retro-box control (retro=500 on visual) shows intensity 500;
   our converted tree/rock (retro on collision, values 1/3) return intensity 0. The
   converter's collision-side `laser_retro` (cropcraft feature) is **invisible to
   gpu_lidar** → Phase 1 must move/duplicate it onto visuals.
2. **Segmentation labels_map channel layout** (instance mode, gz-sim8/ogre2):
   ch2 = class label, ch0 (+ch1 high byte) = per-class instance id, background 0.
   NOT the R channel the docs imply. `Label` plugin inside `<include>` works, incl.
   on our MASK-foliage models — leaves label per-pixel, not as quads. Terrain has no
   label → renders 0/background; give ground a label in Phase 1 if wanted.
3. **Magnetometer publishes WMM in Gauss.** With `<spherical_coordinates>` present,
   gz Harmonic computes the World Magnetic Model at the world origin and writes it
   into `field_tesla` in **Gauss** (0.574 @ 57.03N,-115.43E); the world
   `<magnetic_field>` element is ignored.
4. IMU on a gravity-off link still reads |acc| = 9.80 (specific force w/ world
   gravity subtracted) with a valid quaternion — usable as a static sanity check.
5. navsat/baro behave: lat offset matches the rig's -120 m Y, alt = elevation+z,
   pressure ~100.4 kPa at 675 m AMSL.

### Phase 1 — GATE MET: generated rig world verdicts 13/13; 96/96 unit tests

`wildseed rig` writes `models/sensor_rig/` from a YAML-able `RigConfig`
(`src/wildseed/core/rig.py`); `wildseed generate --rig [--rig-config Y]
[--rig-pose x,y,z[,r,p,y]]` includes it (default pose: terrain centre, 25 m AGL),
injects the sensor system plugins + `<spherical_coordinates>` idempotently, and
labels every placed instance + terrain via the `Label` system. `gz sdf -p`
validates the model; the Phase-0 harness (now env-parameterizable:
`RIG_EXPECT_POSE`, `SPIKE_OUTDIR`) passes 13/13 against a seeded generated world.

- **One id space for semantic GT:** segmentation class labels == laser_retro
  intensities (tree=1 bush=2 rock=3 grass=4 sand=5) + ground=6, water=7
  (`CLASS_LABELS` in core/rig.py; enforced by a unit test against
  `LASER_RETRO_DEFAULTS`). Verified live: lidar intensities {0,1,3} and
  segmentation labels {1,3,6} in the same world.
- **Converter fixed** to write `laser_retro` on visual AND collision; all 52
  on-disk model.sdf regenerated (models/ stays gitignored — rebuilt worlds pick
  the fix up automatically).
- **Body-occlusion gotcha (found by looking at the frames, not the verdicts):**
  a body-center camera mount rendered a rotor disk filling the frame corner and
  a 0.2 m depth min. Mounts are now computed against the body geometry: cameras
  front-bottom (0.20, ±b/2, -0.08) — rgbd + segcam exactly at cam_left's pose so
  RGB/depth/labels are pixel-paired; lidar on a mast at z=0.45 where the
  steepest default ray (0.7 rad) crosses the rotor plane at 0.45 m radial,
  outside the disks (0.40 m). Depth min went 0.2 m -> 64 m in the same scene.
  The wide-angle still sees rotors at the frame edge — deliberate (a real
  drone's fisheye does too).
- Deviation from plan: the rig body is SDF primitives (box + rotors + mast),
  not an assetgen Blender mesh — `wildseed rig` needs no Blender this way.
