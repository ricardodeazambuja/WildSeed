# Plan: close the gap to the original screenshots (realism + VIO/LIO variability)

> **Self-contained execution plan (Phase 0 → D).** Written so it can be run with a cleared
> context: it states the current repo state, the tools/commands, the known gotchas, and a
> measurable acceptance gate per phase. Hand this file to `/goal`.

---

## 0. Goal in one sentence

Make the 6 demo scenes meaningfully closer to `Screenshot from 2026-01-*.png` **and**
give them enough **spatial feature variability** to be usable for VIO/LIO testing —
proven by a **metric harness**, not by eyeballing renders.

Scope decision already made by the user: **image-level feature metrics**, NOT a full
VIO/LIO odometry/eval rig (no odometry stack, trajectories, or ground-truth plumbing).

---

## 1. Current state (what already exists — start here, don't rebuild)

Branch: `feature/realism-convert-fork`. Everything below is committed.

**Pipeline (all CC0, credential-free):**
- `assets/manifest.yaml` — single source of truth: ~22 Poly Haven CC0 assets
  (id/category/res/lod/variant/scale/biomes) + per-biome species palettes.
  `assets/manifest.lock.yaml` — sha256 of each **source** download.
- `spike/build_assets.py [ids...]` — idempotent fetch→normalize→convert → `models/<cat>/<id>/`.
- `spike/fetch_polyhaven.py <id> <res> <dir> blend` — credential-free fetch.
- `spike/normalize_blend.py` — open native .blend, pick LOD/variant, recenter/base-z0/scale,
  rebuild foliage→Principled BSDF→MASK.
- `spike/build_scenarios.py` — builds the 6 demos + renders galleries. `FOREST_SCN=name`
  filters to one scene. Reads biome palettes from the manifest; per-category stashing.
- `spike/terrain_scene.py` — assembles the gz render world + cameras (`cam_hero`,
  `cam_oblique`, `cam_top`). Hero camera honours `HERO_EX/EY/AX/AY/EYE` env vars.
- `spike/render_catalog.py` + `spike/compose_catalog.py` → `spike/asset_catalog.png`
  (per-model thumbnails).
- Core code: `src/forest3d/core/terraingen.py` (DEM synth), `core/ground.py` (ground
  texture compositor), `core/forest.py` (placement/density), `cli/generate.py`
  (`--density '{"tree":..,"rock":..,"bush":..,"grass":..}'`).

**How to run anything (GPU render needs this exact form):**
```bash
docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -v "$PWD:/workspace" \
  --entrypoint bash forest3d:egl -c 'cd /workspace && <command>'
```
`forest3d:egl` and `:latest` are the **pinned** images (rebuild from `docker/Dockerfile*`
if missing). `models/` and `Blender-Assets/**.blend` are gitignored/regenerable.

**Read these memory notes first (they hold hard-won gotchas):**
`forest3d-reproducible-demos`, `blender42-gltf-mask-foliage`, `forest3d-terrain-synthesis`,
`forest3d-terrain-texturing`, `upstream-asset-provenance`.

**Gotchas already paid for — do not rediscover:**
- Foliage exports `alphaMode=BLEND` (dark depth-sort blob) unless the leaf material is
  rebuilt as a Principled BSDF with leaf-alpha→`Math:GreaterThan(0.5)`→Alpha → `MASK`.
- Poly Haven tree .blends ship the **assembled** `<id>_LOD<n>` tree AND kit pieces
  `<id>_leaves_a_LOD<n>`; keep the assembled one (>100k tris), not a kit piece (<1k tris).
- `jacaranda_tree` is pathological (2–4M tris) — dropped.
- gz render must be GPU (`--gpus all -e NVIDIA_DRIVER_CAPABILITIES=all`), else llvmpipe.

---

## 2. What the originals do (the target) + the honest ceiling

The 3 `Screenshot from 2026-01-*.png` share one recipe:
1. **Ground-level camera placed next to a large hero asset** (big boulder and/or mature
   tree fills part of the frame; forest recedes behind).
2. **Many large mature varied trees** (acacia/birch/spruce) — a real canopy.
3. **Smooth rolling terrain** (tens of metres; no sub-metre sponginess).
4. **Rich NON-repeating ground texture** (sandstone strata, mossy litter).
5. **No artificial trails.**

**Ceiling (state this in the final report; don't relitigate):** the mature acacias
(detailed bark) are **Maxtree**, the photoscanned ground/rocks are **Megascans** — both
commercial, deliberately rejected for CC0. This plan closes the *achievable* gap (framing,
density, variety, terrain shape, ground non-repetition, landmarks). It will NOT match
per-asset fidelity. "Match" = comparable composition + feature richness, not identical assets.

---

## 3. The binding requirement — feature variability (ties each fix to VIO/LIO)

- **VIO (visual):** needs spatially-distinct features. The **tiled base ground (~4 m
  period)** repeats identical features across the scene → aliasing → false loop closures.
  A single repeated grass model does the same.
- **LIO (geometric):** needs varied 3-D structure. Uniform terrain bumpiness is **not**
  structure (it aliases); **smooth terrain + many discrete varied objects** (rocks, trunks,
  bushes) is.
- **Hero landmarks** (one big boulder + one distinctive tree per area) double as
  **loop-closure anchors**.

So: kill sub-object terrain noise, kill ground tiling, add varied discrete objects +
landmarks. Realism and VIO/LIO align here.

---

## PHASE 0 — measurable comparison loop (BUILD FIRST, before any fix)

**Objective:** one command that quantifies the gap to the originals, so every later change
is justified by a metric movement (not a "looks better").

**Build `spike/compare.py`:**
1. **Metricize the 3 originals.** Crop the Gazebo toolbar (top ~95 px) and playbar
   (bottom ~40 px) FIRST or you count GUI corners. Compute per image:
   - **ORB + FAST feature count** (`cv2.ORB_create`, `cv2.FastFeatureDetector_create`).
   - **Spatial coverage**: fraction of cells occupied on an 8×8 grid + a uniformity score
     (e.g. 1 − normalized stddev of per-cell counts).
   - **Tiling autocorrelation peak**: autocorrelate the grayscale (or FFT power spectrum);
     report the strongest non-DC peak and its pixel period. A strong peak at a fixed offset
     = visible tiling. → these are the **target numbers**.
2. **Render ours** from comparable ground-level poses (use `cam_hero` with `HERO_*` set
   near a hero asset) and compute the same metrics.
3. Emit **`spike/compare.png`** (ours | original, per scene) + a printed/markdown **metric
   table** + the gap.

**Dependency:** add `opencv-python-headless` to `docker/constraints.txt` (pinned) and
install in `docker/Dockerfile.egl`; rebuild `forest3d:egl`. (Headless variant — no GUI libs.)

**Acceptance gate:** `compare.py` runs in the container, prints a table with all three
metrics for the 3 originals and the 6 current scenes, writes `spike/compare.png`, and the
**baseline gap is committed** (e.g. `docs/baseline_metrics.md`). Example expected baseline:
ground tiling-peak high (~4 m), our feature count well below originals, coverage low.

---

## PHASE A — terrain at robot/human scale (problem #1)

**Objective:** gently rolling terrain over tens of metres; no sub-2 m lumps.

**Files:** `spike/build_scenarios.py` (the `tg=[...]` per scene), `src/forest3d/core/terraingen.py`
(presets/`detail`).

**Steps:**
- **Decouple terrain scale from density.** Remove `--pixel 1.6` as a *density* hack (it
  couples world size to plant spacing). Pick `pixel_m / amplitude_m / feature_m / detail`
  for realism; get density from Phase C instead.
- **Kill fine octaves:** set `--detail ~0.1` (attenuates fine fBm), raise `feature_m`,
  raise `smooth_sigma`. Per-biome: alpine keeps relief; temperate/coastal/savanna smooth.
- Verify the meshed terrain has no sub-2 m height oscillation (sample the DEM / eyeball the
  oblique cam — but the real gate is the metric below).

**Acceptance gate:** re-run `compare.py`; terrain reads smooth in `compare.png`; the LIO-side
note holds (structure will come from objects in Phase C, not ground noise). No regression in
feature metrics from terrain alone.

---

## PHASE B — non-repeating ground + drop trails (problems #2a, #3)

**Objective:** kill the visual feature repetition that breaks VIO.

**File:** `src/forest3d/core/ground.py` (the `BIOMES` table + `_tiled` + `_trail_mask`).

**Steps:**
- **Break the tiled base:** blend 2–3 base materials with a **large-period macro noise**
  (30–60 m) so no identical feature recurs every few metres; raise base `tile_m`
  substantially and/or feed a higher-res source. Keep the organic patch overlays (they add
  variation). This is the single most important VIO fix.
- **Remove trails** — delete the `kind: "trail"` layers from every biome. They're in zero
  originals and their straight hard edges read as artificial.

**Acceptance gate (hard, numeric):** `compare.py` **tiling-autocorrelation peak drops below
threshold** (target: no dominant peak, comparable to the originals' ~0.04) and **feature
spatial coverage rises**. This is the gate that proves the VIO-killer is fixed.

---

## PHASE C — density, variety, placement, hero landmarks (problem #2b)

**Objective:** populated, varied scenes with distinguishable features + loop-closure anchors.

**Files:** `assets/manifest.yaml` (palettes/scales), `spike/build_scenarios.py` (densities),
`src/forest3d/core/forest.py` (placement: scale/rotation jitter, clustering, hero placement).

**Steps:**
- **More species + much higher instance counts** per biome.
- **Per-instance variation:** scale + rotation + slight hue/brightness jitter so repeated
  models don't yield repeated features (forest.py already has SCALE_RANGES; add rotation +
  a small material-tint jitter at export or via SDF, and confirm placement isn't a regular
  grid — clustered).
- **Hero landmarks:** place the biggest boulder + a distinctive large tree near the
  representative camera in each scene (loop-closure anchors).
- **Bigger canopy trees:** the originals' are mature/tall — scale up canopy trees and prefer
  the fuller LOD0/LOD1 (already fixed to keep the assembled tree).
- Consider 2–3 more CC0 species if a biome is thin (add to manifest, run `build_assets.py`).

**Acceptance gate:** `compare.py` feature count + coverage **approach the originals'
targets** for each demo; side-by-side shows comparable density/variety.

---

## PHASE D — ground-level hero cameras + close the loop (problem #4)

**Objective:** the gallery shots match the originals' *framing intent*.

**Files:** `spike/terrain_scene.py` (camera), `spike/build_scenarios.py` (gallery compose).

**Steps:**
- Add a **representative ground-level camera** per scene, placed near a hero asset (boulder +
  tree in frame), looking slightly down — matching the originals' composition (do NOT
  pixel-match; they're hand-posed GUI shots). The `HERO_*` env knobs + terrain-height
  sampling already exist; bake good per-scene values in.
- Re-render the 6 galleries from these cameras.
- Run `compare.py` → final `spike/compare.png` (ours | original) + metric table.

**Acceptance gate = Definition of Done:** for each demo, `compare.py` reports feature count
+ spatial coverage **within a stated % of the originals**, **tiling peak below threshold**,
and a side-by-side that's visually comparable in **composition, density, variety**. Commit:
updated `spike/scenarios_gallery.png`, `spike/compare.png`, the metric table
(`docs/baseline_metrics.md` updated to before/after), and a short honest report including the
**CC0 ceiling caveat**.

---

## Working rules (so this doesn't regress)

- **Phase 0 first, always.** Then A→B→C→D, re-running `compare.py` after each phase; every
  change must move a metric. No "looks better" claims without the number.
- **Verify foliage/asset changes** against the gotchas in §1 (alphaMode=MASK, assembled
  tree >100k tris) — these have produced false "fixed" calls before.
- **Commit per phase** with the metric delta in the message. Keep `models/` gitignored.
- **Update memory** (`forest3d-reproducible-demos`) with any new gotcha.
- Honest reporting: state what the metrics show, including where the CC0 ceiling caps the gap.
