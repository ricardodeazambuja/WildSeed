# Building & tuning VIO/LIO-friendly worlds

A task-oriented guide to generating outdoor worlds that give a **ground robot**
good, non-ambiguous features for VIO (camera) and LIO (LIDAR) — **without**
dragging the simulator's real-time factor (RTF) down.

This is the *user* front-end to the ground-clutter/relief study. For the evidence
and method behind every choice here, read **`docs/GROUND_CLUTTER.md`** (the study)
and **`docs/VIO_BENCH.md`** (what the camera metric measures); the tool table is
in **`tools/README.md`**.

---

## TL;DR — one command

```bash
wildseed scenario --seed 7 --profile vio_lio
```

builds the measured recipe in one seeded step:

- **patchy ground** — a seeded multi-material compositor (trails/patches), which
  the study found beats single-material tiling ~8× for feature quality and de-aliases
  the ground;
- **steered corridor scatter** — a modest object budget (default 175, where VIO
  saturates) concentrated into the strip the robot actually drives, so local
  landmark density is high while the *total* instance count stays RTF-friendly;
- **flat, drivable macro relief** — a gentle terrain kept under the ground-robot
  slope cap (fine detail, no un-drivable slopes);
- **the sensor rig** — injected at `(0, 0, 2 m)`, ready to render/record.

Outputs (under the project root):

| File | What |
|------|------|
| `worlds/vio_lio_<seed>.world` | the gz world (rig included) |
| `worlds/vio_lio_<seed>.instances.json` | placement ground truth |
| `worlds/vio_lio_<seed>.yaml` | the fully-resolved spec (reproducible from the seed) |
| `dem/vio_lio_<seed>.tif` | the terrain DEM |
| `dem/vio_lio_<seed>_corridor.png` | the steered-placement density map |

Same `--seed` + same knobs → **byte-identical world**.

Inspect without building:

```bash
wildseed scenario --seed 7 --profile vio_lio --dry-run
```

---

## Prerequisites

- **GPU container `wildseed:egl`.** Generation of the world files is CPU-only, but
  *rendering* (the benchmarks, `record`, `launch`) needs the GPU image. Run from
  the project root:

  ```bash
  docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -e PYTHONPATH=/workspace/src \
    -v "$PWD:/workspace" --entrypoint bash wildseed:egl -c 'cd /workspace && wildseed scenario --seed 7 --profile vio_lio'
  ```

- **GDAL** (terrain synthesis) — present in the container; locally
  `sudo apt install python3-gdal gdal-bin`.
- The **ground texture** must exist for the standalone `heightmap` knob (any prior
  `scenario`/`ground`/`generate` produces it).

---

## The knobs (uniqueness & tuning)

All are options on `wildseed scenario --profile vio_lio`:

| Knob | Default | What it controls | When to turn it |
|------|---------|------------------|-----------------|
| `--seed` | — (required) | The whole world (reproducible randomness). | Different worlds; regression-fix a specific failure. |
| `--variety` | 0.5 | **The single uniqueness dial (0..1).** Co-scales recolour-variant count, terrain roughness, and corridor softness. | ↑ for less repetition / harder place-recognition; ↓ for a plainer world. |
| `--object-density` | 175 | Total steered objects (VIO saturates ~175). | ↑ for more landmarks (watch RTF); ↓ for a sparser, cheaper scene. |
| `--corridor-width` | 8 | Driving-corridor **half**-width, m. | Match the width your trajectory actually sweeps. |
| `--relief` | 0.5 | Macro amplitude 0..1, kept under the slope cap. | ↑ for more horizon parallax; stays drivable. |
| `--biome` | seed-random (wild) | Palette + ground material only. | Fix the look (`temperate`, `savanna`, `alpine`, …). |
| `--max-slope` | 20° | Ground-robot slope cap (terrain rescaled to meet it). | ↓ for flatter/skid-steer platforms; `0` = off. |

### Why "uniqueness" is one dial now

The individual levers still exist (seed, variants, relief, density, corridor
width), but `--variety` gives you **one** monotonic control over "how
non-repeating are the features". Internally it raises:

1. **recolour-variant count** (0→3) — more distinct-looking instances per species
   (in-process domain randomization; see `docs/DOMAIN_RANDOMIZATION.md`);
2. **terrain roughness** (the fractal `detail` knob) — more non-repeating relief;
3. **corridor softness** — a smoother placement band.

The corridor's *shape* is deterministic (no seed); the *objects* scattered into it
are seeded via the master seed.

---

## The measure → tune loop

Build a world, then measure it on the three axes the study identified. All run in
`wildseed:egl` from the project root:

```bash
# 1. build
wildseed scenario --seed 7 --profile vio_lio

# 2. measure
wildseed benchmark vio   --tag recipe                    # camera aliasing / inliers (V1)
wildseed benchmark rtf   --world vio_lio_7 --tag recipe  # RTF under sensor load (V2, the cost)
wildseed benchmark lidar --world vio_lio_7 --tag recipe  # LIDAR range roughness (V3)

# 3. tune (raise variety / density / relief) and re-measure
wildseed scenario --seed 7 --profile vio_lio --variety 0.8 --object-density 200
```

Reading the numbers (full guidance in `docs/VIO_BENCH.md` / `docs/GROUND_CLUTTER.md`):

- **`benchmark vio`** → GOOD when `inlier_ratio ≥ 0.65`, `inliers/pair ≥ 100`,
  `ratio_reject ≤ 0.85`. Aliasing shows up as high `ratio_reject`; VIO robustness
  hinges on **landmark density**, so raise `--object-density` if starved.
- **`benchmark rtf`** → keep `rtf_min ≥ ~0.5`. This is the binding constraint —
  every gain above is only worth it if RTF holds. Back off `--object-density` if it sags.
- **`benchmark lidar`** → higher `ring_roughness_m` = more LIO-registrable
  geometry (~0 over flat bare ground). Objects and relief both raise it.

### End-to-end proof (optional)

To turn the proxies into real trajectory drift, record a run and score ATE against
a bare baseline:

```bash
wildseed record --dataset --keep-frames ...      # record over the recipe world, then a baseline
wildseed benchmark validate runs/recipe runs/baseline
```

`recipe ATE < baseline ATE` confirms the recipe cuts real VIO/LIO drift (the study
verified this on 2 seeds — see the Phase C commit).

---

## Standalone knobs (not in the recipe)

Two feature generators are exposed directly for A/B experiments and advanced use:

### `wildseed corridor-map` — steered-scatter plumbing

Paint a driving-corridor density map by hand and feed it to `generate`:

```bash
wildseed corridor-map --out corridor.png --half-width 8 --soft
wildseed generate --density-maps '{"rock":"corridor.png","bush":"corridor.png"}' \
    --density '{"rock":200,"bush":300,"tree":0,"grass":0}' --rig
```

The recipe does this for you; use the command directly to steer placement on a
world you build with `generate` instead of `scenario`.

### `wildseed heightmap` — geometric relief ground (option d2)

A gz `<heightmap>` carrying **cm–dm surface roughness on a flat, drivable macro** —
VIO/LIO texture the Nyquist-limited WildSeed mesh can't produce, at RTF ~1.0:

```bash
wildseed heightmap --out-world worlds/hm.world --relief 0.35 --seed 7
wildseed benchmark rtf   --world hm     # RTF cost
wildseed benchmark lidar --world hm     # LIO roughness gain
```

This is a **standalone** knob — object placement + ground truth on a heightmap
were deferred in the study (the recipe's mesh relief suffices). Keep it separate
from the recipe for now.

---

## See also

- **`docs/GROUND_CLUTTER.md`** — the study: RTF constraint, the P1 failure
  baseline, options (c) steered scatter and (d) geometric relief, the
  feature-gain/RTF-cost frontier, and the shippable recipe's evidence.
- **`docs/VIO_BENCH.md`** — the camera data-association method (why aliasing, not
  feature count, predicts VIO failure).
- **`docs/DOMAIN_RANDOMIZATION.md`** — the recolour-variant mechanism `--variety`
  drives.
- **`tools/README.md`** — the underlying `tools/*.py` scripts (each recipe/benchmark
  command wraps one; the tools stay runnable directly for reproduction).
