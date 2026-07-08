# Experiments & sweeps — hypothesis-driven world generation

WildSeed's experiment layer turns "make me a hard world" into a **controlled
stress condition**: you write a spec naming a hypothesis and a set of
*stressor dials*, and one command resolves it — through the master seed —
into a world that applies exactly that stress, plus a record that regenerates
and pins it. Sweeps then grade a dial into a difficulty ladder with real
benchmark numbers per rung.

The rule behind the design: **every dial maps to a measured VIO/LIO failure
mode, carries its ground truth, and is observable by a benchmark.** The
mappings come from the ground-clutter study ([GROUND_CLUTTER.md](GROUND_CLUTTER.md)).

## The dials

| dial | 0 → 1 means | failure mode it drives | measured by |
|---|---|---|---|
| `structure` | 0 → 250 steered objects (0.7 ≈ 175, the VIO saturation point) | landmark starvation | `benchmark vio` inliers/pair |
| `texture` | uniform (aliasing worst case) → patchy (de-aliased) ground | ground perceptual aliasing | `benchmark vio` ratio_reject/verdict |
| `relief` | flat → 10 m drivable macro relief | weak parallax, flat lidar returns | `benchmark vio` + `benchmark lidar` |
| `variety` | repeated instances → recolour variants + roughness | repeated-instance aliasing | `benchmark vio` self-ambiguity |
| `photometric` | high sun (55°) → grazing sun (5°) + 5× intensity + glare disk | photometric stress: long shadows, low-contrast ground, auto-exposure | `benchmark vio --world-sun` |

`weather` (a preset name or `random`) rides along the same seeded stage:
`clear`, `overcast`, `fog`, `rain`, `snow`, `sunglare`. Emitters cost RTF —
keep `benchmark rtf` in the loop when you use them.

All of it resolves under the **master seed** (scenario format 4): the sun
stream is an appended `SeedSequence` child, so pre-existing seeds still build
byte-identical worlds when the new dials are unset.

## One experiment

```yaml
# exp_lowsun.yaml
hypothesis: "Grazing sun halves confident inliers on the recipe world"
seed: 42
name: lowsun
dials: {structure: 0.7, texture: 1.0, photometric: 0.9}
benchmark: [vio]
```

```bash
wildseed experiment --spec exp_lowsun.yaml --dry-run   # inspect the condition
wildseed experiment --spec exp_lowsun.yaml             # build it (GDAL/container)
```

Outputs: `worlds/exp_lowsun.world` + `worlds/exp_lowsun.yaml` — the record
holds the hypothesis, every drawn value (e.g. the seeded sun azimuth), and a
provenance block:

```yaml
provenance:
  wildseed_version: 0.2.0
  git_commit: <the generating tree>
  sha256: {world: ..., dem: ..., instances: ...}
```

Cite results against the world sha256; anyone can rebuild from the record and
verify the hash matches.

Spec fields: `hypothesis` (required), `seed` (required), `name`, `profile`
(default `vio_lio`; the structure/texture/relief/variety dials act through
it — `photometric`/`weather` also work on the plain biome path with
`profile: null`), `biome`, `preset`, `dials`, `weather`, `overrides` (raw
`scenario` knobs, recorded verbatim, win over dials), `benchmark` (default
bench list for sweeps).

## Sweeps → difficulty ladders

```bash
# grade the photometric axis: 3 rungs, one seed, vio benchmark per rung
wildseed sweep --spec exp_lowsun.yaml --axis photometric --values 0,0.5,1 --bench vio

# structure ladder with replicates and the RTF cost column
wildseed sweep --spec exp_lowsun.yaml --axis structure --values 0,0.35,0.7 \
    --seeds 42,43 --bench vio,rtf
```

Each condition is built and benchmarked immediately (worlds share `models/`,
so the loop is sequential; a world's benches run while its models are
current). Results land in `runs/sweep_exp_<name>_<axis>/`:

- `report.md` — the ladder, one row per (value × seed): inliers/pair,
  ratio_reject, verdict, lidar ring roughness, rtf_min, build time, world
  sha256.
- `report.json` — the same, machine-readable.
- `spec.yaml` — the spec; any row regenerates with the row's value + seed.

`benchmark vio` rows run the study's canonical ground-robot pose (AGL 2 m,
2 m/frame — the P1 failure pose), so ladder numbers are directly comparable
to the study tables in [GROUND_CLUTTER.md](GROUND_CLUTTER.md).

**GPU prerequisite:** `--bench` needs the `wildseed:egl` container
(`--gpus all -e PYTHONPATH=/workspace/src`), same as the `wildseed benchmark`
group. Build-only sweeps (no `--bench`) need GDAL only.

## The photometric axis is rendered, not just recorded

`benchmark vio --world-sun` (set automatically by sweeps when a condition has
a photometric/weather stage) makes the render harness adopt the world's sun,
scene, glare disk and weather emitters. Without it the harness uses its
historical fixed sun — that default keeps every previously measured baseline
comparable.

## Measured ladders

Validation runs of 2026-07-08 (seed 42, recipe world: structure 0.7,
texture 1.0; vio at the P1 ground-robot pose; RTX 2070 Max-Q, wildseed:egl).

### photometric — a measured NEGATIVE result (kept, but read it right)

| photometric | sun | inliers/pair | ratio_reject | inlier_ratio | verdict |
|---|---|---|---|---|---|
| 0.0 | 55°, 1× | 88 | 0.92 | 0.73 | MARGINAL |
| 0.5 | 30°, 2× | 87 | 0.93 | 0.79 | MARGINAL |
| 1.0 | 5°, 5× + disk | **98** | 0.92 | **0.84** | MARGINAL |

**The sun-geometry dial does NOT stress frame-to-frame matching in this
render model — it mildly helps.** Physics: the sun is static and the gz
camera has fixed exposure, so long grazing-light shadows are *scene-fixed,
high-contrast edges* — extra trackable landmarks (inlier_ratio rises 0.73 →
0.84). The glare disk at 5° elevation sits above the down-pitched camera's
frame at this pose. The real-world low-sun failure modes (auto-exposure
transients, lens flare/bloom, moving shadows) are camera-plugin and dynamics
effects this world-side axis cannot inject — pair the `sunglare` preset with
the `gz-sim-lens-flare-system` camera snippet on YOUR robot for those.

Use the dial for reproducible lighting *variation* (domain randomization);
do not assume high values make a world harder for VIO. The verdict came from
running the benchmark under the world's actual sun (`--world-sun`) — the
axis is measurable, the effect is just not the naive one. Weather presets
(fog/overcast) are the world-side photometric stressor candidates instead —
see the fog A/B below.

### structure — the flagship ladder (monotone gain, visible RTF cost)

Same spec, `--axis structure --values 0,0.35,0.7 --bench vio,rtf`
(photometric held at the spec's 0.9):

| structure | objects | inliers/pair | ratio_reject | rtf_min | load_s | world sha256[:12] |
|---|---|---|---|---|---|---|
| 0.00 | 0 | 41 | 0.96 | 0.999 | 2.2 | 45b68343ac5f |
| 0.35 | 88 | 59 | 0.95 | 0.999 | 22.0 | 91ce7cf92f5c |
| 0.70 | 175 | 70 | 0.94 | 0.927 | 24.0 | c1c0fe98d2a5 |

Monotone VIO gain along the dial, and the study's cost story reproduced in
the same table: the object budget is what you pay RTF and load time for.
This is the report card working as designed — gain and cost per rung, each
rung regenerable from the spec + value + seed.

### Byte-determinism, measured end to end (G4)

The `structure=0.7` rung resolves to the identical condition as a standalone
`wildseed experiment` build run ~25 minutes earlier in a *separate container
invocation* — and produced the **identical world sha256**
(`c1c0fe98d2a5…`). The full chain (DEM synth → Blender mesh → 4K ground
bake → placement → seeded weather stage → world XML) is byte-deterministic;
the provenance hash in the record is a real pin, not a checksum of luck.

### fog A/B — the weather axis IS the photometric stressor

Same world as the clear baseline (structure 0.7, texture 1.0, seed 42),
`weather: fog` applied under the master seed, rendered with `--world-sun`:

| condition | ORB/frame | putative/pair | inliers/pair | verdict |
|---|---|---|---|---|
| clear (55° sun) | 1461 | 122 | 88 | MARGINAL |
| **fog** | **556** | **80** | **66** | MARGINAL |

Fog collapses the detector's feature supply (−62% ORB/frame — contrast
washout), thinning matches end to end. On this recipe world the budget
absorbs it (still MARGINAL); on a leaner world the same fog pushes toward
failure. Together with the sun-geometry negative result above: **randomize
`photometric` for lighting variation, use `weather: fog`/`overcast` when the
experiment needs photometric difficulty** — and keep `benchmark rtf` in the
loop, since emitters cost RTF.

*(Found while measuring this: weather worlds used to crash the render
harness on a duplicate emitter model and vio_bench silently re-scored the
previous run's cached frames. Both fixed — stale captures are now purged and
an empty capture aborts loudly. If you benchmarked a weather world before
2026-07-08, re-run it.)*

## See also

- [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) — design decisions + gates for this layer
- [VIO_LIO_FEATURES.md](VIO_LIO_FEATURES.md) — the underlying recipe + measure→tune loop
- [GROUND_CLUTTER.md](GROUND_CLUTTER.md) — the evidence behind the dial mappings
