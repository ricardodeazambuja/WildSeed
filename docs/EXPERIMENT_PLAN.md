# Experiment-spec program — implementation plan

> Working plan for the overnight autonomous session of 2026-07-07/08. Source of
> truth for design decisions; updated + committed as phases land. The driving
> ideas are in `scratchpad/goal.txt` (session-local); the five items, condensed:
> (1) declarative experiment spec with stressor dials, (2) new stress axes each
> with a GT channel, (3) extensibility that preserves the testing contract,
> (4) sweeps → graded benchmark report cards, (5) reproducibility hardening →
> citable results. Guiding rule: **no randomization axis without a mapped
> failure mode, a GT channel, and a metric.**

## Status

- [x] Phase 0 — this plan, committed
- [x] Phase 1 — experiment spec: stressor dials + sun/weather folded under the master seed
- [x] Phase 1v — unit tests + determinism for the spec pipeline (188 tests green;
      golden fixture pins format-3 draws; D5 provenance stamping landed early)
- [x] Phase 2 — `wildseed sweep`: axis sweep + benchmark report card
- [x] Phase 2/3v — GPU ladders MEASURED: photometric (negative result — sun
      geometry does not stress fixed-exposure matching), structure (monotone
      41→59→70 inliers, RTF cost visible), fog A/B (ORB/frame −62%, the
      world-side photometric stressor confirmed; also surfaced + fixed a
      silent stale-frame reuse bug in the render harness)
- [x] Phase 4 — reproducibility: hashes + provenance stamped, determinism
      tests, CI workflow, G4 MEASURED (identical condition in two separate
      container runs → identical world sha256)
- [x] Phase 5 — extensibility: user-YAML biomes under the contract
- [ ] Wrap-up — docs (EXPERIMENTS.md), README trail, morning report

## Design decisions (locked unless evidence overturns them)

### D1. Seed-compatibility: append, never reorder

`SeedSequence.spawn()` is append-safe: spawning more children later leaves
earlier children unchanged, and appending *draws* after existing ones leaves
existing draws unchanged. All new randomization therefore:
- spawns its stage stream AFTER the existing spawns (vio_lio: child 5;
  biome path: child 4);
- draws unconditionally (so overrides never shift the stream), applies only
  when the dial is set.

`SCENARIO_FORMAT` bumps 3→4: format 4 = format 3 + an optional photometric/
weather stage. With the new dials unset, a format-4 world is byte-identical
to its format-3 counterpart (verified by test).

### D2. The dial set (v1) — every dial maps to a measured lever

| dial | range | maps to | failure mode targeted | evidence |
|---|---|---|---|---|
| `structure` | 0..1 | `object_density = round(250·d)` (0.7 ≈ 175, the measured VIO saturation) | landmark starvation | GROUND_CLUTTER option (c): saturates ~175, RTF-only beyond |
| `texture` | 0..1 | <0.5 → `uniform` ground (aliasing worst case); ≥0.5 → `patchy` (de-aliased). Discrete lever, discretization recorded in the resolved YAML | perceptual aliasing of the ground | P1 baseline + Phase A: texture is a multiplier on structure |
| `relief` | 0..1 | existing vio_lio knob (2–10 m macro under the slope cap) | weak parallax / LIO range flatness | GROUND_CLUTTER option (d) |
| `variety` | 0..1 | existing vio_lio knob (recolour variants + roughness + corridor softness) | repeated-instance aliasing | vio_lio recipe |
| `photometric` | 0..1 | sun elevation 55°→5° (linear), intensity 1+4d², emissive sun disk at d≥0.75; azimuth drawn seeded from the sun stream and recorded | KLT/descriptor loss under long shadows + glare (auto-exposure stress) | to be MEASURED in Phase 2/3v — this axis only ships if the benchmark moves |

`weather` (preset name or `random`, drawn from the sun stream) rides along as a
named stressor, not a dial — presets are categorical.

### D3. Spec file = experiment record

`wildseed experiment --spec exp.yaml`:

```yaml
name: lowsun_a                 # output stem; default exp_<seed>
hypothesis: "Grazing sun halves confident inliers on the recipe world"
seed: 42
profile: vio_lio               # or biome: temperate (dials needing the profile error out)
dials: {structure: 0.7, texture: 1.0, relief: 0.5, variety: 0.5, photometric: 0.9}
weather: clear                 # optional; "random" = seeded draw
overrides: {corridor_width: 8.0}   # raw-knob escape hatch, recorded verbatim
```

The resolved record (`worlds/<name>.yaml`) carries: the spec verbatim
(hypothesis included), every drawn value, stage seeds, output paths — and the
Phase-4 hashes. One file = the exact stress condition, regenerable.

### D4. Sweep = build→bench→next, never build-all-then-bench

`models/ground` is shared mutable state (existing constraint: pipelines can't
run concurrently), so a sweep interleaves: for each (axis value × seed): build
world → run requested benchmarks → append row. `wildseed sweep --spec exp.yaml
--axis photometric --values 0,0.5,1 [--seeds 42,43] [--bench vio,lidar,rtf]`
→ `runs/sweep_<name>/report.md` + `report.json`. Columns: axis value, seed,
inliers/pair, ratio_reject, verdict, ring_roughness_m, rtf_min, load_s, world
hash. vio_bench already emits JSON (`frames/vio_bench_<tag>.json`); rtf/lidar
tools' JSON outputs are consumed the same way.

### D5. Hashes + provenance (Phase 4)

`run_scenario` stamps into the resolved YAML: sha256 of the world XML, the
`instances.json`, and the DEM; `wildseed.__version__`; and (best-effort) the
git commit of the generating tree. A determinism pytest builds the CPU-only
prefix (resolve + DEM synth) twice and asserts hash equality. CI (GitHub
Actions): pytest on ubuntu-latest; GDAL-dependent tests already skip cleanly
when GDAL is absent, so the workflow starts GDAL-less and the determinism gate
runs wherever GDAL exists (locally + container) — CI hardening can follow.

### D6. Extensibility contract (Phase 5, time-boxed)

User YAML biomes/profiles loaded from `--biome-file` / a search path;
pydantic-validated with REQUIRED VIO/LIO declarations (ground biome, density
envelopes, terrain knobs). GT machinery (instances.json, labels, passable) is
category-level and automatic — the contract is enforced at load, not trusted.
If the night runs short this phase ships as design + schema only.

## Validation gates

- G1 (after Phase 1): full pytest green; same seed + dials-unset ⇒ world XML
  identical to pre-change output (golden test); dial determinism tests green.
- G2 (after Phase 2): a CPU dry sweep (no benches) produces a coherent report
  skeleton; then the GPU ladder: structure sweep 0/0.35/0.7 and photometric
  sweep 0/0.5/1.0 on one seed with `--bench vio` (+lidar where cheap).
- G3 (photometric axis): ships only if vio_bench moves monotonically-ish along
  the dial (else the mapping is revisited — scientific method, not vibes).
- G4 (Phase 4): two consecutive full builds of the same spec produce identical
  world hashes (in-container check).

## Deferred axes — designed, not built (next session's Phase 1)

Two goal-item-2 axes need more than a night; recording the design so they
start from a decision, not a blank page:

**Dynamics (static-world violation).** Dial = fraction-of-view-in-motion.
Mechanism: N distractor models on seeded waypoint loops driven by a tiny
world plugin (gz TrajectoryFollower or pose-publisher script via
`wildseed fly`-style kinematics; NO physics wrenches — kinematic movers keep
RTF flat and trajectories byte-reproducible). GT channel: per-instance
velocity + track in `instances.json` (FORMAT 3) and per-frame 2D motion
masks derivable from the segmentation camera (moving ids are known). Metric:
vio_bench gains a `--dynamic-frac` report column = fraction of putative
matches landing on moving-class pixels; validate = ATE with/without motion
masks in the reference estimator. Gate: the dial must degrade E-matrix
inlier_ratio monotonically at fixed structure.

**Sensor randomization (calibration-error robustness).** Not a world axis —
a RIG config transform. `wildseed rig --randomize <dial> --seed N` perturbs:
IMU noise density/bias walk (gz `<imu><noise>`), camera intrinsics (fx,fy,
cx,cy ± dial·1%), extrinsic mount pose (± dial·[mm, mrad]). The TRUE drawn
values go into `rig_calibration.json` next to the model (clean test = feed
estimator truth; robustness test = feed nominal). Gate: mismatch dial must
grow validate-ATE monotonically while the clean run stays flat.

## Risk register

- GPU benches are minutes-each → sweeps sized small (3–5 points × 1 seed).
- Weather emitters cost RTF → default experiment weather = clear; rtf bench
  in the report card is the honest gauge.
- `models/` mutable state → sweep is strictly sequential (D4); no parallel
  builds this session.
- Container must see live source: `-e PYTHONPATH=/workspace/src` (README gotcha).
