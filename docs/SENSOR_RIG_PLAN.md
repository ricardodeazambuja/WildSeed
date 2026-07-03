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

### Phase 2 — GATE MET: byte-identical seeded trajectories; live flight smooth

`wildseed fly --pattern orbit|flythrough|lawnmower|dolly --seed N [--play]`
(`core/fly.py`): seeded waypoints → spline → terrain-following AGL (fast
`TerrainSampler`: one LinearNDInterpolator over the terrain STL vertices, not
the per-query triangle scan) → `trajectory_<pattern>_<seed>.json` written
BEFORE playback. Playback drives `/world/<w>/set_pose` paced by sim time.

Gate evidence: same seed ⇒ `cmp`-identical JSON; live orbit in the seeded demo
world: 148 m path, odometry step mean 0.14 m / max 0.40 m at 50 Hz — no
teleports (verifier ignores the legitimate initial spawn→start jump). Unit
tests 113/113 (17 new: determinism, AGL bounds, margin, look-at-centre, yaw
follows velocity, interpolation, kinematic-mode flag).

**Hard-won findings:**
1. **`/world/<w>/stats` publishes at ~5 Hz and `/clock` is silent headless** —
   pacing a flight on raw stats quantizes motion into 0.2 s pose jumps (0.9 m
   at 5 m/s). Fix: extrapolate sim time between stats ticks with the reported
   real-time factor. (`set_pose` itself is fast: 0.2 ms median round-trip.)
2. **Sim stalls (lazy sensor init) break wall-clock extrapolation** — one
   stall snapped the pose 5 m. The commanded trajectory time is now monotonic
   with bounded advance (4× nominal step): glitches become momentary
   slow-downs, never jumps.
3. Cubic splines overshoot zigzag waypoints (lawnmower turnarounds violated
   the terrain margin by 12 m). Open paths use PCHIP (shape-preserving);
   orbit keeps a periodic cubic for roundness.
4. Kinematic playback is recorded as `"mode": "kinematic"` in the trajectory
   JSON — IMU during set_pose flight is garbage by construction and datasets
   must be able to tell.

### Phase 3 — GATE MET: one command → demo video (sim-time-correct)

`wildseed record` (core/record.py): subscribes the rig streams while flying
the trajectory, buffers PNG frames, encodes `video.mp4` with cv2 (the images
ship no ffmpeg binary) at the fps MEASURED from sensor sim-time stamps, and
writes `manifest.json` + the exact `trajectory.json`. `--dataset` adds lidar
npz, imu/navsat csv, TUM `groundtruth.txt`. `tools/record_demo.sh` is the
one-command wrapper (server + record in one container). Gate: 56.3 s orbit →
584 frames at exactly 10.0 fps (the camera's nominal rate — zero drops),
58 s video matching sim time 1:1; unit tests 119/119.

**Hard-won findings:**
1. **Never do real work on gz-transport callback threads.** PNG encoding
   (~10 ms) in the camera callback starved the thread pool that also serves
   service responses: set_pose round-trips ballooned to ~1 s and a fixed
   per-iteration advance bound stretched a 75 s flight into 570 s of slow
   motion. Callbacks now only enqueue bytes (a writer thread encodes), and
   the advance bound is relative to sim progress (2x catch-up), so a slow
   loop skips ahead instead of dilating the flight. Verified: 2418 updates,
   1.5% rejected, flight duration == trajectory duration.
2. Encode at the measured fps, not the nominal sensor rate — then the video
   duration always equals sim duration even if the render drops frames.

### Phase 5 — GATE MET: ROS 2 bridge overlay builds and bridges

`docker/Dockerfile.ros` (`wildseed:ros`, 4.8 GB): ROS 2 Humble +
`ros-humble-ros-gzharmonic` on top of `wildseed:egl` — the core images stay
ROS-free. `docker/ros_gz_bridge.yaml` maps all default rig topics. Gate:
against a running gz world, `parameter_bridge` lists the topic in
`ros2 topic list`, `ros2 topic echo` returns live rig odometry, and a 12 s
`ros2 bag record` captured 1164 Odometry messages.

Findings: the base images run as user `wildseed` — overlay needs `USER root`
for apt (then drops back). Jammy base ⇒ Humble; the Harmonic bridge package
is `ros-humble-ros-gzharmonic` (plain `ros-gz` targets Fortress).

### Phase 4 — GATE MET: dynamic hand-of-god flight with honest IMU

`wildseed fly/record --mode dynamic` (fly_dynamic in core/fly.py): kinematic
pre-position to the trajectory start, then a PD wrench loop (kp=4, kd=4,
attitude PD toward the trajectory quaternion) via ApplyLinkWrench.

Gate (tools/verify_dynamic.py + manifest, dolly seed 3 @ 4 m/s, dataset on):
**tracking err mean 0.029 m / p95 0.065 m / max 0.116 m**; IMU hover 9.80 ±
0.000 (specific force at rest — correct with gravity-off link since gz still
subtracts world gravity); flight p50 9.80 / p99 9.96 / max 16.9 (initial
catch-up transient, physically real); 181 m path; full dataset + video.

**Hard-won findings — ApplyLinkWrench protocol (all measured):**
1. Persistent wrenches ACCUMULATE as a list; the summed force is exact but the
   server iterates the list per step: 4000 entries drag RTF 1.0 → 0.32, and
   naive 50 Hz delta publishing froze whole flights (~4 lidar scans in
   15 min).
2. clear+set per cycle is 0% effective duty: clear and set are DIFFERENT
   topics (different publishers — no cross-topic ordering), and the race
   reliably wipes the fresh wrench. A flight "worked" this way — moving on
   stray impulses with flat-9.8 IMU and 3.3 m mean tracking error.
3. The working protocol: deadbanded DELTAS on the single ordered persistent
   topic (2 % of clamp deadband keeps the list tiny), rare consolidation
   (clear → 60 ms wall gap → full-value re-base), and a final clear so the
   world is left with zero entries.
4. Debugging method note: hypotheses 1–2 were separated only by analyzing the
   recorded dataset (groundtruth.txt showed purely along-track error with
   commanded-force/IMU contradiction) and two CPU-only probe experiments
   (duty factor, list cost) — not by re-running the gate blind. Datasets
   from failed runs are evidence; use them first.
5. gz OdometryPublisher twist is CHILD-frame (probe-verified) — rotate to
   world before using as PD velocity feedback.

### Final — demo videos delivered; plan complete

All phases 0–5 gated and committed. Demo videos (reproducible: seed + world
+ pattern in each run's `manifest.json`/`trajectory.json`; `runs/` is
gitignored — regenerate with the commands below):

- **temperate flythrough** — `wildseed scenario --seed 77 --biome temperate
  --density-scale 1.6` (870 instances, 162 trees) + `wildseed rig --inject
  worlds/scenario_77.world --config configs/rig_cinematic.yaml` +
  `tools/record_demo.sh flythrough 11 worlds/scenario_77.world --speed 6
  --agl 11` → 65 s @ 20 fps 1280×720, canopy-level pass over trees and
  boulder clusters.
- **temperate orbit** — same world, `tools/record_demo.sh orbit 5 ...
  --radius 55 --agl 16 --speed 5` → 69 s @ 20 fps.
- **dynamic dolly (honest IMU)** — the Phase-4 gate run itself
  (`record -p dolly --seed 3 --mode dynamic --dataset`): video + full
  lidar/IMU/GPS/TUM-ground-truth dataset, 3 cm mean tracking.

Note for future demo recordings: pick the biome deliberately
(`--biome temperate` + `--density-scale ≥1.5`); a random sparse biome
(e.g. bush-heavy wetland seed 204) reads as empty terrain from altitude.

**Exit-segfault, root-caused and fixed** (was initially misfiled as
"cosmetic"): a gz-transport subscription left alive at interpreter exit lets
the C++ layer call back into a dying Python — a flaky, load-dependent SIGSEGV
after `run complete` (observed exactly on the run with heavy set_pose
rejections; 3 light-load repro attempts stayed clean, minimal-case probes all
exited 0 — the race needs load). Fix: every subscriber (`RunRecorder.stop`,
both fly loops via `_quiet_unsubscribe`, the gate tools) unsubscribes all
topics and drains before returning — the mechanism is removed rather than
made rarer. Verified: 2× heavy 20 fps 720p flythroughs under load, exit 0
with faulthandler armed; 120/120 tests.
