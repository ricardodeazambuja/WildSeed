# Sensor rig — fly a sensor suite through any WildSeed world

The rig is a flying sensor platform (a camera dolly, not a robot — robots and
autonomy stacks stay out of scope) for exercising generated worlds: fly a seeded
trajectory, record video and/or a sensor dataset, and get per-instance ground
truth that matches the world's `instances.json`.

## Quick start

```bash
# Build a world that hosts the rig (adds sensor system plugins, GPS
# georeference, and semantic labels on every placed instance)
wildseed generate --rig --seed 42

# One command: fly + record (GPU container; server + record in one shot)
tools/record_demo.sh orbit 7

# Or drive it yourself inside wildseed:egl, next to a running
# `gz sim -s -r worlds/forest_world.world`:
wildseed fly -p flythrough --seed 3 --agl 10 --play        # camera work
wildseed record -p orbit --seed 7 --dataset                # + lidar/IMU/GT dump
wildseed record -p dolly --seed 5 --mode dynamic --dataset # physically consistent IMU
```

## Sensors

All gz-sim Harmonic built-ins (ogre2/EGL):

| sensor | gz type | notes |
|---|---|---|
| 3D lidar | `gpu_lidar` | configurable channels; VLP-16-ish (16×360) default |
| stereo pair | 2 × `camera` | rigid baseline, identical intrinsics |
| RGB + depth | `rgbd_camera` | aligned RGB+D in one sensor |
| wide-angle | `wideangle_camera` | large-FOV lens as used on real VIO rigs |
| IMU | `imu` | meaningful only in `--mode dynamic` (see below) |
| GPS | `navsat` | seeded `<spherical_coordinates>` origin injected by `--rig` |
| barometer | `air_pressure` | |
| magnetometer | `magnetometer` | |
| segmentation | `segmentation_camera` | per-instance `Label`s injected by `--rig` |
| GT pose | `OdometryPublisher` | ground-truth trajectory → TUM export |

## Configuration

`wildseed rig` generates `models/sensor_rig/` from a YAML `RigConfig`: sensors
on/off, rates, resolutions, lidar channels, stereo baseline, mount poses.

- `wildseed generate --rig [--rig-config cfg.yaml] [--rig-pose x,y,z[,r,p,y]]` —
  build a world with the rig included (default pose: terrain centre, 25 m AGL)
- `wildseed rig --inject worlds/<w>.world --config cfg.yaml` — add the rig to an
  existing world
- `wildseed rig --inject worlds/<w>.world --shell-only` — add only the
  world-shell (sensor system plugins, `<spherical_coordinates>`, semantic
  labels) with **no** rig include/model — for worlds that will host an
  externally spawned robot (e.g. a ROS 2 UGV) instead of the flying rig
- `wildseed height -x X -y Y [--json]` — print the terrain ground z at (x, y)
  (sampled from `models/ground/mesh/terrain.stl`), so an external spawner can
  place its robot ON the surface instead of inside or above it
- `wildseed rig --calib 0.5 --calib-seed N` — **seeded calibration
  randomization** (the instrument-error axis): perturbs sensor mount
  extrinsics (±5 mm/0.3° at dial 1.0), camera FOV→fx (±1%), and injects IMU
  noise (EuRoC-class MEMS baseline × 4·dial²; 0→ideal, 0.5→1×, 1→4×). The
  TRUE drawn values are exported to `rig_calibration.json` in the model dir
  (both continuous-time densities and the gz per-sample stddevs) — feed an
  estimator the truth for a clean test, or the nominals for a
  calibration-robustness test. rgbd/segcam move WITH cam_left so the
  pixel-paired ground truth survives the miscalibration. `--calib 0` writes
  the unperturbed calibration export.

Bundled configs: `configs/rig_cinematic.yaml` (720p main camera only, for
videos), `configs/rig_showcase.yaml` (1080p, same idea),
`configs/rig_dataset.yaml` (full suite at dataset rates).

## Flight patterns

`wildseed fly --pattern orbit|flythrough|lawnmower|dolly --seed N
[--agl M] [--speed S] [--play]` synthesizes a seeded, terrain-following
trajectory and writes `trajectory_<pattern>_<seed>.json` before playback —
same seed ⇒ byte-identical trajectory.

Two drive modes:

- **kinematic** (default) — poses are set directly (`set_pose`): the smoothest
  camera motion. The IMU stream is meaningless in this mode by construction;
  the trajectory JSON records `"mode": "kinematic"` so datasets can tell.
- **dynamic** (`--mode dynamic`) — a PD wrench loop pushes the rig with forces
  (`ApplyLinkWrench`), so the IMU is physically consistent. Tracks the same
  seeded trajectory within centimetres at cruise speeds.

## Recording & datasets

`wildseed record -p <pattern> --seed N [--dataset]` flies the trajectory while
recording, then writes to `runs/<world>_<pattern>_seed<N>/`:

- `video.mp4` — encoded at the fps measured from **sensor sim-time stamps**, so
  a slow render (RTF < 1) still yields a real-time-correct video
- `manifest.json` + the exact `trajectory.json`
- with `--dataset`: lidar `.npz`, imu/navsat `.csv`, TUM `groundtruth.txt`

`tools/record_demo.sh <pattern> <seed> [world] [extra args]` wraps the gz
server + record in one container run.

## Known behaviors & gotchas

- **Semantic ground truth shares one id space**: lidar `laser_retro` intensity
  and the segmentation class label carry the same per-category value (tree=1,
  bush=2, rock=3, grass=4, sand=5), consistent with `instances.json`. Ground
  (6) and water (7) exist only as segmentation labels — the ground/water
  models carry no `laser_retro`, so lidar intensity from them stays 0.
- **`laser_retro` is read from the visual, not the collision** — gz's GPU lidar
  is rendering-based. WildSeed puts the labels on visuals; if you add your own
  labelled models, do the same.
- **Segmentation image channel layout** (instance mode, gz-sim 8 / ogre2):
  channel 2 = class label, channel 0 (+1 high byte) = per-class instance id,
  background = 0 — not the R channel the gz docs imply.
- **Magnetometer publishes the World Magnetic Model in Gauss** (computed from
  the world's `<spherical_coordinates>` origin); the world `<magnetic_field>`
  element is ignored by gz Harmonic.
- **gz OdometryPublisher twist is child-frame** — rotate to world before using
  it as velocity feedback.
- **ROS 2**: use the `wildseed:ros` overlay image (`docker/Dockerfile.ros`,
  ROS 2 Humble). The Harmonic bridge package is `ros-humble-ros-gzharmonic`
  (plain `ros-gz` targets Fortress); `docker/ros_gz_bridge.yaml` maps all
  default rig topics.

## Reproducing the demo videos

Each run's `manifest.json`/`trajectory.json` records the seed, world and
pattern (`runs/` is gitignored — regenerate at will):

```bash
# temperate flythrough (dense showcase world; see README Demo videos)
wildseed generate --rig --rig-config configs/rig_showcase.yaml --seed 7
tools/record_demo.sh flythrough 11 worlds/forest_world.world --agl 6

# orbit over the same world
tools/record_demo.sh orbit 5 worlds/forest_world.world --radius 55 --agl 16

# dynamic dolly with a physically consistent IMU + full dataset
wildseed record -p dolly --seed 3 --mode dynamic --dataset
```
