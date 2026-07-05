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

LIDAR (V3): steered objects raise `ring_roughness_m` above the flat-bare reference (3.23) —
3.73 at 175 objects, 8.96 at 880 — the near returns off objects give the LIO registrable
along-track structure. finite_frac stays low (~0.1) because at 2 m over open ground most of
the 16 beams point above the ground into the sky.

---

## Option (d) — geometric ground relief (measured)

One surface, not N objects: put relief into the ground MESH itself. Prototyped via the
existing `terraingen` detail knobs (d1 — mesh displacement) at max mesh resolution
(`--size 512 --pixel 0.6` = 307 m extent, 0.6 m/px), smooth uniform grassland texture kept so
the test isolates **geometry** (same failure bed + failure pose as (c)). One static mesh → no
per-instance cost.

| config | relief | mean slope | VIO verdict | inliers/pair | ratio_reject | RTF min | load | LIDAR rough |
|---|---|---|---|---|---|---|---|---|
| P1 baseline (flat) | 7.2 m* | 1.9° | ALIASING RISK | 20 | 0.98 | ~1.0 | — | 3.23 |
| (d) gentle relief | 5.8 m | 8.8° | ALIASING RISK | 38 | 0.96 | **0.998** | 3.2 s | 4.46 |
| (d) rough relief | 7.0 m | 15.2° | **MARGINAL** | **91** | 0.92 | ~1.0† | 3 s | — |

\* the `flat` preset already has ~7 m of very-gentle relief (mean slope 1.9°), which is why
bare-flat LIDAR roughness is 3.23 not 0. † rough-relief RTF inferred from gentle relief
(0.998): identical 512² single mesh, bare — same render/physics cost.

Findings:
- **Relief runs at full real-time (RTF 0.998, load 3.2 s) as ONE mesh** — no instance count,
  no ogre2 instance ceiling, no long load. This is the RTF-safest lever, exactly as predicted.
- **VIO gain is coupled to relief amplitude, and amplitude is capped by TRAVERSABILITY.**
  Gentle relief a ground robot can actually drive (mean slope 8.8°) only reaches 38 inliers
  (still ALIASING RISK). To reach MARGINAL (91 inliers) needs mean slope 15.2° / p95 29.6° —
  borderline drivable; a `terraingen --max-slope 20` cap (scenario default) would rescale it
  back down and give the gain back up. So on **must-stay-flat** terrain, mesh relief alone
  cannot fix VIO.
- **Root cause = mesh Nyquist.** The pure-Python mesh at 0.6 m/px resolves only ≳1.2 m relief,
  so to make VIO features it must use large-amplitude, few-metre undulation (→ slope) rather
  than the cm–dm surface roughness (clods, ruts, tufts) that would add camera texture + LIO
  range variation WITHOUT raising the macro slope. **This is the case for d2 (gz `<heightmap>`
  / Terra):** a hi-res height field GPU-tessellated + LOD'd carries cm relief on otherwise-flat
  ground — decoupling VIO/LIO texture from traversability — at one-mesh cost. Not yet built
  (bigger pipeline change); d1 establishes the relief lever and its mesh-resolution ceiling.
- LIO: gentle relief lifts roughness 3.23 → 4.46 (+38%) — relief helps the lidar even where it
  under-delivers for the camera.

---

## Frontier & recommendation

All at the P1 failure pose (flat, uniform grassland, 2 m, fast driving; baseline = 20
inliers, ALIASING RISK). Everything below holds **RTF ≥ 0.998** — the binding constraint is
respected by both levers when sized right.

| lever | best VIO | verdict | RTF | LIO | drivable? | cost |
|---|---|---|---|---|---|---|
| (c) steered objects, ~175 | 57 | MARGINAL | 1.0 | + | yes (flat path) | asset + placement; RTF cost climbs fast past ~200 in-view |
| (d) mesh relief, gentle | 38 | ALIASING RISK | 1.0 | ++ | yes | none (one mesh) |
| (d) mesh relief, rough | 91 | MARGINAL | 1.0 | ++ | borderline (15° mean) | traversability |

- **They are complementary, not competing.** (c) fixes **landmark starvation** (distinct
  objects beside a flat, drivable path) — the strongest lever when the ground must stay flat.
  (d) fixes it with **surface geometry** at zero instance cost and the best LIO gain — the
  strongest lever when the terrain is *allowed* to be rough. Ship BOTH as switchable knobs
  (plumbing already exists: `corridor_map.py` + `--density-maps` for (c); `terraingen`
  detail/amplitude flags for (d)).
- **Neither reaches GOOD alone** because the uniform ground *texture* between features stays
  ambiguous (`ratio_reject` stuck ~0.92–0.96). The third lever is the **ground material**: P1
  showed *patchy* desert ground (composited gravel/pebble) scores GOOD even bare. So the full
  recipe for a VIO/LIO-friendly ground-robot world is **patchy ground texture + a modest
  steered-object budget (c) and/or drivable relief (d)** — texture kills ground aliasing,
  objects/relief supply landmarks and LIO structure.
- **Instance count is the RTF enemy, confirmed**: (c) saturates its VIO gain at ~175 objects;
  everything above is pure RTF cost (and grass foliage is negative-value). (d) sidesteps the
  count axis entirely — its only ceiling is mesh resolution (→ d2/Terra for cm relief).
- **Next step for the strongest single lever:** d2 (Terra `<heightmap>`) to carry cm–dm surface
  roughness on flat, drivable ground — the one thing the current mesh path (Nyquist-limited)
  and the object path (RTF-limited) both cannot deliver.
