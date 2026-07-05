# Ground clutter / relief for VIO + LIO (ground vehicles)

Goal: make WildSeed terrain yield good, non-ambiguous features for a **ground vehicle**
running VIO (camera) and LIO (LIDAR) **without** dragging the sim's real-time factor (RTF)
down. Deliver switchable options — (c) steered scatter and (d) geometric relief — each judged
on **feature-gain per RTF-cost**.

Companion docs: `docs/VIO_BENCH.md` (data-association benchmark method), `tools/README.md`
(VIO tools table). Plan of record: `scratchpad/PLAN_ground_clutter.md`.

All renders run in the GPU container (`wildseed:egl`); helper: `scratchpad/dgpu.sh '<CMD>'`.

---

## Binding constraint — RTF

When RTF sags (trouble at ≲0.3), ROS 2 nodes advance internal timers on `sim_time` but DDS
delivery is wall-clock → desync → message-filter/TF timeouts → failures. **Keep RTF ≥ ~0.5.**
Every clutter/relief choice is judged by (VIO+LIDAR feature gain) / (RTF cost), measured under
load (sensors rendering + physics stepping), never assumed. Corollaries:
- Must be **real geometry**: LIDAR is blind to baked albedo/normal maps — texture-only clutter
  is out (fails for LIO).
- Instance **count** is the enemy; single-mesh geometry is cheap.
- Primary target = ground vehicle (~2 m eye); drone is secondary.

---

## P1 — Ground-vehicle failure baseline (DONE)

The benchmark (`tools/vio_bench.py`) renders the real rig camera (640×480, 57° FOV) along a
canonical translate-+X + yaw trajectory, matches ORB between consecutive frames and reports
`ratio_reject` (ambiguity), `inlier_ratio` (E-matrix RANSAC), `inliers/pair` (reliable
correspondences) and a verdict. Prior work (§2.6 of the plan) had never shown bare ground
*failing* at a ground-robot pose — every tested scene stayed GOOD, carried by landmarks or by
feature-rich hilly/patchy terrain.

**Result — a realistic ground-robot failure exists, and it is reached by removing the three
things that were secretly carrying VIO:** terrain relief (horizon parallax), ground texture
richness, and slow motion. Escalation gradient, all **bare** (`generate` with explicit zeros
`{"tree":0,"rock":0,"bush":0,"grass":0,"sand":0}`), camera at **2 m AGL**:

| scene | pose | verdict | inliers/pair | ratio_reject | inlier_ratio |
|---|---|---|---|---|---|
| hilly + patchy desert | pitch 0.5, step 0.6 m/fr | **GOOD** | 341 | 0.71 | 0.78 |
| flat + uniform grassland | pitch 0.35, step 1.2 m/fr | **MARGINAL** | 106 | 0.89 | 0.71 |
| **flat + uniform grassland** | **pitch 0.35, step 2.0 m/fr, yaw ±10°** | **ALIASING RISK** | **20** | **0.98** | **0.60** |

The last row is the **failure baseline** both options must beat: realistic fast driving
(2 m/frame ≈ brisk ground speed) over flat, smooth, landmark-free ground. `ratio_reject 0.98`
(near-total descriptor ambiguity) with only **20** surviving inliers/pair (< 40 = starvation).
Viz: matches cling to a thin near-field ground band; the smooth mid/far field is blank.

Reproduce (in container):
```
python3 -m wildseed.cli.main terraingen --preset flat --seed 3 --size 192 --pixel 1.6 -o dem/flat.tif
python3 -m wildseed.cli.main terrain --dem dem/flat.tif
python3 -m wildseed.cli.main ground --mode uniform --biome grassland --seed 7 --res 4096
python3 -m wildseed.cli.main generate --density '{"tree":0,"rock":0,"bush":0,"grass":0,"sand":0}' --seed 7
python3 tools/vio_bench.py --tag p1_flatunif_fast --agl 2 --pitch 0.35 --step 2.0 --yaw-amp-deg 10 --region full --viz
```
Outputs: `frames/vio_bench_p1_flatunif_fast.json`, `..._matches.png`.

**This flat + uniform-grassland scene is the fixed test bed for options (c) and (d):** flat
terrain is exactly where scatter and relief must prove their worth (no horizon to lean on).

---

## P2 — RTF-under-load harness (DONE)

`tools/vio_bench.py` renders one-shot (no RTF signal). `tools/rtf_bench.py` adds a real-time
run: it launches a real `gz sim -s -r` server on a rig world (`generate --rig`), attaches
subscribers to the camera + lidar topics (a stand-in VIO/LIO consumer, so the sensors are
genuinely on the render path), waits until the sim clock **actually advances**, then samples
`real_time_factor` off `/world/<world>/stats`.

**Harness gotcha (found + fixed):** `/stats` publishes a **frozen** clock while the world is
still loading (hundreds of instance meshes take tens of seconds — 26 s for 880 instances). A
fixed-settle measurement catches pure load time and reports a bogus RTF ~0 with
`sim_advanced_s == 0`. The harness now waits for the clock to advance (up to `--load-timeout`,
default 240 s) before the window opens, and reports `load_wait_s` + a `stalled` flag.

Validation: **bare rig world = RTF 0.999** (median 1.0) — sensors are cheap over empty ground.

`tools/lidar_spread.py` is the V3 gate (LIO axis the camera benchmark can't see): launches the
rig world, grabs gpu_lidar scans, reports `ring_roughness_m` (mean std of Δrange between
adjacent azimuth beams — ~0 over flat ground, rises with clutter/relief), `range_std_m`,
`near_frac`, `finite_frac`.

---

## Option (c) — density-map-steered scatter (measured)

Plumbing: `tools/corridor_map.py` paints a driving corridor (white band at the drive line
y=0, `--soft` Gaussian taper) → fed to `generate --density-maps` → the object budget lands in
the band the vehicle drives (high LOCAL density, low TOTAL count). Ground kept flat + uniform
grassland (the P1 failure bed); rig at 2 m; benchmark at the P1 failure pose
(pitch 0.35, step 2.0, yaw ±10°). Same seed used for the no-rig (VIO) and rig (RTF/LIDAR) worlds.

**Frontier — VIO gain saturates early; extra instances only cost RTF:**

| config | instances | VIO verdict | inliers/pair | ratio_reject | RTF median | RTF min |
|---|---|---|---|---|---|---|
| P1 baseline (bare) | 0 | ALIASING RISK | 20 | 0.98 | ~1.0 | — |
| **c_light** (tree15/bush90/rock70) | **175** | MARGINAL | **57** | 0.92 | **1.00** | **0.998** |
| c_med (tree25/bush180/rock120) | 325 | MARGINAL | 56 | 0.93 | 0.75 | 0.43 |
| c_clutter (+400 grass) | 880 | MARGINAL | 51 | 0.96 | 0.19 | 0.11 |

Findings:
- **~175 steered distinct objects lift VIO from ALIASING RISK (20 inliers) to MARGINAL
  (57 inliers, 2.85×) at full real-time (RTF 1.0).** This is the option-(c) operating point.
- **The VIO gain SATURATES**: 325 and 880 instances give the *same* ~56 inliers but tank RTF
  (0.75 → 0.19). Instance count is pure RTF cost past the saturation point — confirming §2.4
  (distinct objects, not object *quantity*, carry VIO) and the RTF binding constraint.
- **Grass is a trap**: the 400 alpha-textured grass instances in `c_clutter` add the most RTF
  cost *and slightly worsen* VIO (ratio_reject 0.92 → 0.96 — foliage self-similarity adds
  ambiguity). Steer distinct landmarks (rock/bush/tree), not carpet foliage.
- **c3 "drop collision" lever is moot here:** placed clutter models are already `<static>`, so
  RTF cost is render/instance-count-bound, not dynamics/collision — the lever to pull is
  in-view instance count (which corridor-steering already minimizes), not collision.
- Ceiling: even c_light only reaches MARGINAL (`ratio_reject` stays 0.92) — the smooth uniform
  GROUND between objects is still ambiguous. Objects fix landmark starvation; they do not fix
  ground ambiguity. → motivates pairing (c) with (d) or a ground-texture fix.

LIDAR (V3): the 880-instance clutter scan gave `ring_roughness_m` 8.96 vs a flat-bare
reference (below) — objects produce large adjacent-beam range jumps the LIO can register.
