# Closing the gap to the originals — realism + VIO/LIO variability plan

Target: get the demo scenes meaningfully closer to `Screenshot from 2026-01-*.png`, with
**spatial feature variability** as the hard requirement (these worlds are for testing VIO
and LIO — repeated features cause drift and false loop closures). Built so progress is
**measured, not eyeballed** (eyeballing has produced false "fixed" calls repeatedly).

## What the originals actually do (from the 3 screenshots)

1. **Ground-level, robot-eye camera deliberately placed next to a large hero asset** — a
   big boulder and/or a mature tree fills part of the frame; the forest recedes behind.
2. **Many large, mature, varied trees** — acacia (detailed bark, broad bare canopy), birch,
   blue spruce — forming a real canopy, not scattered dots.
3. **Smooth rolling terrain** — gentle green/rock hills over tens of metres; NO sub-metre
   sponginess.
4. **Rich, NON-repeating ground textures** — sandstone strata, mossy grass with litter;
   high feature density, no visible tiling.
5. **No artificial trails.**

## Honest ceiling (we use CC0; the originals didn't)

The mature acacias with detailed bark are **Maxtree** (commercial); the photoscanned
ground/rocks are **Megascans** (commercial) — see `spike/ASSET_REGISTRY.md` /
`[[upstream-asset-provenance]]`. We deliberately ship credential-free CC0. So this plan
closes the **achievable** gap — framing, density, variety, terrain shape, ground
non-repetition, hero landmarks — but **cannot match per-asset fidelity** on CC0. "Match the
originals" means comparable composition + feature richness, not identical assets.

## The binding requirement: feature variability (and how each fix serves it)

- **VIO (visual):** needs spatially-distinct visual features. The **tiled base ground
  (repeats every ~4 m)** produces identical features across the scene → aliasing → false
  loop closures. One repeated grass model does the same.
- **LIO (geometric):** needs varied 3-D structure. Uniform terrain *bumpiness is not
  structure* — it aliases. **Smooth terrain + many discrete varied objects** (rocks,
  trunks, bushes) is what gives LIO distinguishable geometry.
- **Hero landmarks** (one big boulder, one distinctive tree per area — as in the originals)
  double as **loop-closure anchors**.

Net: kill sub-object terrain noise, kill ground tiling, add varied discrete objects +
landmarks. Realism and VIO/LIO point the same way here.

---

## Phase 0 — the measurable comparison loop (BUILD FIRST, before any fix)

`spike/compare.py` — the thing that makes every later change checkable and stops
premature-victory:

1. **Metricize the 3 originals** (crop the Gazebo toolbar/playbar first, or we count GUI
   corners): ORB + FAST **feature count**, **spatial coverage** (occupied cells on an 8×8
   grid + uniformity), and **texture-tiling autocorrelation peak** (FFT/auto-correlation;
   a strong peak at a fixed pixel offset = visible tiling). → these are the **target
   numbers**.
2. **Render ours** from comparable ground-level poses and compute the same metrics.
3. Emit **`spike/compare.png`** (ours | original, per scene) + a **metric table** + the gap,
   in one command.

**Establish the baseline gap on the CURRENT scenes before changing anything**, and commit
it. From here, iterate against the numbers (e.g. "tiling-peak 0.61 @4 m → target <0.1";
"features 410 → target ~1800; coverage 0.31 → 0.78").

Dependency: `opencv-python` (ORB/FAST) — add to `docker/constraints.txt` pinned.

## Phase A — terrain at robot/human scale (problem #1)

- **Decouple terrain from density.** Undo `--pixel 1.6` as a *density* hack (it couples
  world-scale to plant spacing). Choose `pixel_m / amplitude_m / feature_m / detail` for
  realism; get density from asset count/size/clustering (Phase C) instead.
- **Kill sub-object noise:** `detail ≈ 0.1` (attenuate fine fBm octaves), larger
  `feature_m`, larger `smooth_sigma` → terrain rolls gently over tens of metres with no
  sub-2 m lumps. Per-biome tuned (alpine keeps relief; temperate/coastal get smooth).
- VIO/LIO: clean LIO structure comes from objects, not noisy ground.

## Phase B — non-repeating ground (problem #2a — the VIO killer) + drop trails (#3)

- **Break the tiled base** in `core/ground.py`: blend 2–3 base materials with a
  **large-period** macro noise (30–60 m), raise the base `tile_m` substantially, and/or
  feed a higher-res source — so no identical feature recurs every few metres. Keep the
  organic patch overlays.
- **Remove trails** (`kind: "trail"` layers) — they aren't in any original and their
  straight, hard edges read as artificial. (Curved+feathered is more work for a feature
  nothing here needs.)
- Metric gate: **tiling-autocorrelation peak below threshold**; feature coverage up.

## Phase C — density, variety, placement (problem #2b)

- **More species + much higher instance counts**; per-instance **scale + rotation + slight
  hue jitter** so repeated models don't yield repeated features.
- **A few large hero assets as landmarks** — the biggest boulder + a distinctive tree —
  placed near the representative camera (like the originals).
- **Bigger canopy trees** (the originals' are mature/tall; scale up + favour the fuller
  LOD0/LOD1 we already fixed).
- **Clustered, slope/elevation-aware placement** (not uniform grid).
- Metric gate: feature count + coverage approach the originals.

## Phase D — ground-level hero cameras + close the loop (problem #4)

- Add **representative ground-level cameras** placed near a hero asset (boulder + tree in
  frame), matching the originals' *framing intent* (not pixel-matching hand-posed GUI
  shots). These become the demo gallery shots.
- Re-render galleries; run `compare.py` → side-by-side vs originals + metric table.

## Acceptance — "loop closed"

For each demo, `compare.py` shows: feature count + spatial coverage within a stated % of
the originals, tiling peak below threshold, and a side-by-side that's visually comparable in
**composition, density, and variety** — with the CC0 per-asset-fidelity caveat noted. The
metric table is the deliverable that proves it, not a screenshot we declared good.

## Sequencing note

Phase 0 first (always). Then A→B→C→D, re-running `compare.py` after each so every change is
justified by a metric movement. Scope per the user: **image-level metrics**, not a full
VIO/LIO pipeline (no odometry stack / trajectory / ground-truth rig).
