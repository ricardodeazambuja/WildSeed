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
current). Results land in `runs/sweep_exp_<name>/`:

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

<!-- MEASURED_LADDERS: filled by the GPU validation run -->

## See also

- [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) — design decisions + gates for this layer
- [VIO_LIO_FEATURES.md](VIO_LIO_FEATURES.md) — the underlying recipe + measure→tune loop
- [GROUND_CLUTTER.md](GROUND_CLUTTER.md) — the evidence behind the dial mappings
