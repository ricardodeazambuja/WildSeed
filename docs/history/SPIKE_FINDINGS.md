# Forest3D integration spike — findings

> **⚠️ Historical (superseded).** Findings from the original integration spike, kept for
> provenance. Paths that say `spike/` now live under `tools/` (one-off diagnostic images,
> incl. `proof_*`, `forest_cam_*`, `verify_tree`, under `tools/archive/`); this archived text
> is not rewritten for the rename. Current usage is documented in the top-level
> [`README.md`](../../README.md).

**Date:** 2026-06-27 · **Host:** hybrid laptop, NVIDIA RTX 2070 Max-Q (driver 535), gz Harmonic.
**Scope:** de-risk adopting [Forest3D](https://github.com/unitsSpaceLab/Forest3D) (`main`, `5c3d331`)
as a procedural off-road world generator for the AutonomyTests ROS 2 / gz Harmonic project.
AutonomyTests was treated read-only; all artifacts live under `~/GitStuff/Forest3D/`.

---

## Verdict: **YES — with work.**

Forest3D **can** host the consuming project's robot in gz Harmonic headless. I proved the full
chain end-to-end on this machine: built the image, generated a world, loaded it headless on the
**GPU** (non-blank camera), and ran a standalone sensor rig in a merged "shell" world with a
**working camera, lidar (returns off both the terrain and a placed `model://` object), and a
NavSat GPS fix** — no plugin load errors.

There is **no fatal blocker.** The single biggest gap vs. the project's goal is **Q1: there is no
random seed** — and "reproducibility is the product." That is a real miss, but it is a *cheap* fix
(global `np.random`, one seed call + a CLI flag). The largest *effort* item is **BYO-assets** (the
`Blender-Assets/*` dirs ship empty; vegetation needs Blender-side conversion). Both are tractable.

Two things surprised me vs. the brief, both in our favor or cheaply handled:
- Forest3D **does** emit a (partial) world base — 3 plugins + physics + scene + lights — not "terrain
  only" (Q6). The merge is therefore a clean **graft of `<include>` blocks** into the project's shell.
- The published Docker image is **broken out-of-the-box** (NumPy 2 vs GDAL ABI) — but a one-line
  `numpy<2` pin fixes it (documented below).

---

## Open questions Q1–Q7 (answered with evidence)

### Q1 — Seed / reproducibility: **NONE. Non-reproducible. Easy to add.**
`grep` over `src/forest3d/`: **no** `np.random.seed`, `default_rng`, `RandomState`, `--seed` flag,
or config field anywhere. Placement (`core/forest.py`) uses the **global** `np.random.*` (~40 calls).
Empirical proof — generated the same density twice (15 rocks via a stub model):

| run | rock_0 pose (x y z r p y) | files identical? |
|-----|---------------------------|------------------|
| A | `56.8285 12.9631 36.9222 0.0088 -0.1487 5.6085` | **no — differ** |
| B | `27.5857 -36.3195 37.2556 0.0443 -0.0628 5.3775` | (15 placed both runs) |

→ A failure could **not** be reproduced today. **Fix is small:** because everything uses the global
RNG, a single `np.random.seed(seed)` at the top of `WorldPopulator.create_forest_world()` plus a
`--seed` CLI option + config field makes generation deterministic. (Cleaner: thread a
`np.random.default_rng(seed)`.) Est. **~1–2 h** incl. a regression test.

### Q2 — License: **three-way conflict; the controlling `LICENSE` file is AGPL-3.0.**
- `LICENSE` file = **GNU AGPL-3.0** (full text, verified).
- `pyproject.toml` line 10 = `license = {text = "MIT"}` + classifier `License :: OSI Approved :: MIT License`.
- `README.md`: MIT **badge** (line 11) but the **License section** (line 321) says AGPL-3.0.
- No per-file SPDX headers in `src/`.

→ The repository ships **contradictory** license metadata. The safe, conservative reading is the
most-restrictive controlling document: **treat as AGPL-3.0** until upstream resolves it (worth filing
an issue). AGPL on **offline world-gen tooling** (generate worlds, then run them in a separate sim)
is low-risk — it is not linked into the robot/runtime — but must be a conscious, recorded decision.
Asset licenses are moot today (no assets shipped); any CC0 assets added later carry their own terms.

### Q3 — Footprint:
- **Docker image:** base `forest3d` = **4.08 GB**; patched `forest3d:egl` = **4.15 GB** (README's
  "~2 GB" is ~2× low). Ubuntu 22.04 + gz-harmonic + Blender 4.2.3 dominate.
- **One generated world (terrain-only):** `models/ground` = **2.1 MB** (`terrain.obj` 1.3 MB +
  `terrain.stl` 748 KB) + `worlds/*.world` ~16 KB ≈ **~2.1 MB/world**. Vegetation adds per-model
  glTF (BYO; not measured — depends on asset complexity).
- **Disk policy (~60 GB):** the **4 GB image is the cost**; individual worlds are tiny, so
  generate→use→prune is comfortable. Build the image once, keep it; prune worlds freely.

### Q4 — Assets / minimum viable path: **terrain-only generation WORKS.**
`Blender-Assets/{tree,rock,bush,grass,soil}` are empty (`.gitkeep`). The `convert` step needs `.blend`
files → it is a no-op today. **But `generate` does not require assets:** `core/forest.py:_verify_paths`
hard-requires only `models/ground`; each category is appended only `if (models_path/cat).exists()`.
Empirically, `generate` on terrain-only **succeeded** — 0 models placed, valid world emitted:
```
Success! World created at: /workspace/worlds/forest_world.world ; Total models placed: 0
```
(Cosmetic bug: it prints "120 models couldn't be placed (area too crowded)" when the real reason is
"no variants".) **Minimum viable path = terrain mesh only, no assets.**

**UPDATE — the full Blender asset pipeline is now PROVEN end-to-end** (no longer "the main remaining
unknown"). I authored 7 procedural CC0 assets (`spike/make_assets.py`: 3 conifers, 2 rocks, 2 bushes,
each with Principled-BSDF Base-Color materials), then ran the real chain in the container's Blender 4.2.3:
```
forest3d convert -i Blender-Assets -o models      # 7/7 -> glTF (.glb) + collision + SDF, 2.4 MB
forest3d generate --density '{"tree":40,"rock":15,"bush":25}'   # placed 40/40, 15/15, 25/25 on terrain
```
The merged world (81 includes) **rendered on the GPU** from 3 cameras — an elevated overview shows
trees+rocks+bushes spread across the hill with shadows; a ground-level "robot's-eye" camera
(auto-aimed at the densest tree cluster) shows upright trees on the slope; the ground **lidar got
2985/5760 returns off the vegetation** (min 8.9 m = nearest tree). See `spike/forest_*.png`.
Gotchas that bite asset authors (both handled in `make_assets.py`): glTF reads the **Principled-BSDF
Base Color node**, not `material.diffuse_color` (else everything exports white); and start each asset
from an empty scene or the default cube ships inside every model. The convert default decimation
(visual 0.1 / collision 0.01) was **fine for these low-poly assets** — real downloaded high-poly
assets may need it tuned (it is a config knob). **What remains** for production: sourcing+license-vetting
real CC0 assets and tuning decimation/collision for them — author-side work, not a pipeline blocker.

### Q5 — gz version match: **MATCH (confirmed twice).**
Dockerfile is `FROM ubuntu:22.04` + installs **`gz-harmonic`** from OSRF. In-image
`gz sim --version` → **Gazebo Sim 8.14.0**. AutonomyTests runs Harmonic **8.11.0** — both are
**gz-sim 8.x**, so the shell's `libgz-sim-*-system.so` plugin filenames are ABI-compatible (patch
diff only). **Empirically confirmed:** the merged world loaded all six system plugins (Physics,
UserCommands, SceneBroadcaster, Sensors, Imu, NavSat) with **zero load errors**.

### Q6 — Output format: **SDF 1.8; a *partial* world base + `<include>` graft points.**
`core/utils/sdf.py` + the generated `worlds/forest_world.world`:
- `<sdf version="1.8">` (Harmonic-era; **not** the brief shell's 1.4).
- Emits **3** plugins only: `gz-sim-physics-system`, `-user-commands-system`, `-scene-broadcaster-system`.
- `<physics name="1ms" type="ignored">`, `<gravity>`, `<scene>`, 3 lights (sun + ambient + point).
- Terrain + each model as **`<include><uri>model://…</uri>`** (terrain = `model://ground`; assets =
  `model://{cat}/{variant}` with `<pose>` and `<scale>`).
- **Missing for the consuming project:** `Sensors`, `Imu`, `NavSat` plugins **and**
  `<spherical_coordinates>`. → exactly what the §4 shell supplies. So the world is host-able only
  **after** the merge.

### Q7 — Texture randomization: **a manual knob, not a randomizer (yet).**
`config/schema.py::TerrainConfig` has `texture_blend` (path to a soil `.blend`, textures extracted
into `models/ground/texture/` as albedo/normal/roughness PBR maps) + `material_name`; CLI
`terrain --texture …`. The `feature/terrain-types-refactor` branch is a large refactor that adds a
**pluggable terrain-type registry** (`type: dem | crop_rows | custom`, new `terrain_base.py` /
`terrain_crop.py`) but keeps texture as the same `texture_blend` knob. → Texture/material variation
**is supported** by swapping the soil `.blend` (the README's "Soil 1/2/3"), and terrain *structure*
can vary by type — but **neither is seeded/randomized**. "Texture randomization" = the team scripts
"pick a soil.blend (and/or terrain type) per run", same gap as Q1. Not measured live (needs `.blend`).

---

## The merge recipe (what worked) — strategy **(a) GRAFT**

Forest3D already uses self-contained `<include>` blocks, so the clean merge is: **keep the project's
shell** (it has the better/complete plugin set + `<spherical_coordinates>` + scene/light/physics) and
**graft Forest3D's `<include>` elements into it**, discarding Forest3D's weaker 3-plugin base. Steps:

1. Generate with Forest3D → `worlds/forest_world.world`.
2. Take the project's working `pipeline`-world shell; **bump its `<sdf version>` to 1.8** (the brief's
   1.4 cannot host SDF-1.8 `<include><scale>` reliably) and ensure it has the 6 plugins +
   `<spherical_coordinates>` (template: `worlds/forest_spike.world` here).
3. Copy every `<include>` from `forest_world.world` into the shell (the terrain one + all model ones).
   Drop Forest3D's `<plugin>/<physics>/<scene>/<light>` (the shell's win).
4. Make models resolvable: `export GZ_SIM_RESOURCE_PATH=…/models` (Forest3D's `model://ground`,
   `model://tree/…` resolve against it; the image already sets `GZ_SIM_RESOURCE_PATH=/workspace/models`).

This is ~30 lines of XML splicing (ElementTree: parse both, move `world.findall('include')`). It is
**robust** because includes are position-independent and path-relative via `model://`. A `worldgen/`
helper in the consuming project should do steps 1–4 programmatically and stamp the seed (Q1).

**A working graft helper now exists:** `spike/merge_world.py` parses the generated world, grafts
**all 81 includes** (terrain + 40 trees + 15 rocks + 25 bushes) into the shell, and adds proof
cameras — it loaded clean with **zero** errors. This is a direct starting point for `worldgen/`.

> **Both include types verified in gz**, not just terrain:
> - `worlds/forest_spike.world` — terrain-only graft: loaded headless, all 6 plugins up,
>   camera non-blank, lidar **928/5760** returns off terrain (58–150 m), NavSat fix.
> - `worlds/forest_modelinclude_test.world` — adds a `model://rock/box1` include 12 m in front of
>   the rig (the **exact `model://{cat}/{variant}` form Forest3D emits**). Result: no resolution
>   error, camera shows the object (std 22→**37**), lidar gains a **near return at 10.0 m** distinct
>   from the 58 m terrain floor (**1077** returns). → model-include **resolution + render + lidar
>   returns are proven**, standing in for "returns off the trees."
>
> Remaining unverified (needs real assets): `<include><scale>` actually taking effect, and the
> Blender→glTF asset pipeline itself (Q4). A box stub proved the *include* path, not the *asset* path.

---

## Gotchas hit (and the fixes), in order

1. **NumPy 2 vs GDAL (image broken OOB).** First `terrain` run: `_ARRAY_API not found` →
   `numpy.core.multiarray failed to import`. The image ships **NumPy 2.2.6**, but system GDAL
   (`osgeo`, 3.4.1) was built against NumPy 1.x. **Fix:** pin `numpy<2` (→ 1.26.4). Baked into
   [`docker/Dockerfile.egl`](../../docker/Dockerfile.egl). *This will bite anyone who builds the stock image.*
2. **Headless EGL / llvmpipe (the brief's §5 #1).** Pre-empted: baked the NVIDIA EGL vendor ICD
   (`/usr/share/glvnd/egl_vendor.d/10_nvidia.json`) into the derived image. **Verified the render path
   the authoritative way** — `~/.gz/rendering/ogre2.log` reported
   `GL_RENDERER = NVIDIA GeForce RTX 2070`, **not** `llvmpipe`. (`glxinfo` is the *wrong* probe here —
   gz renders through EGL, not GLX.) Run flags: `--gpus all -e NVIDIA_DRIVER_CAPABILITIES=all`.
3. **Frame capture: `<camera><save>` does nothing headless** in this gz build (no PNGs anywhere).
   Switched to a **native gz-transport subscriber** ([`spike/capture_cam.py`](../../tools/capture_cam.py),
   [`spike/capture_sensors.py`](../../tools/capture_sensors.py)) — the image has `python3-gz-transport13`
   + `python3-gz-msgs10`. No ROS needed. (AutonomyTests captures via the ROS bridge; out of scope here.)
4. **Camera-below-deck blank (§5 / notes #8 cause B):** avoided entirely by testing a **bare sensor
   rig, no robot** — the project must still mount the Husky camera at **z ≥ 0.25 m** when it wires the
   real robot.

---

## Effort estimate to a `worldgen/` capability in AutonomyTests: **MEDIUM**

The plumbing works today; the work is productizing it. Rough breakdown:
- Build+patch image (numpy pin + EGL ICD): **done here** — reuse `docker/Dockerfile.egl`. *S.*
- Seed support (Q1) for reproducibility: **~1–2 h** + test. *S.*
- World-shell graft helper (parse Forest3D world → splice includes into the project shell, set
  resource path, stamp seed): **~half a day**. *S–M.*
- **Assets (Q4): still the big one, but now de-risked.** The convert→generate→render→lidar pipeline
  is **proven** (procedural assets, this spike). Remaining: source CC0 `.blend` trees/rocks/bushes,
  license-vet each, and validate/tune collision decimation per asset. **Days** (sourcing + vetting,
  not plumbing). *M.*
- Texture/terrain-type randomization (Q7): script soil-`.blend`/type selection per seed: **~half a day**. *S.*
- License decision (Q2): a meeting + an upstream issue, not engineering. *S.*

### Top 3 risks
1. **AGPL-3.0 (Q2).** Contradictory metadata; the controlling file is AGPL. Low-risk for *offline*
   world-gen, but get a deliberate sign-off before depending on it; the MIT badge is **not** safe to rely on.
2. **Real-asset collision meshes (Q4).** The *pipeline* is proven, but only with simple low-poly
   assets. Aggressive default decimation (collision 0.01) on complex downloaded meshes could produce
   bad collision hulls that wreck lidar/physics realism — validate per asset and tune the knob.
3. **Reproducibility debt (Q1) compounding.** Until the seed is added, every "world that broke VIO/lidar"
   is unreproducible — which defeats the stated reason for adopting Forest3D. Add the seed *first*.

---

## Artifacts (all under `~/GitStuff/Forest3D/`)

| What | Path |
|------|------|
| Patched image recipe (numpy pin + EGL ICD) | `docker/Dockerfile.egl` → image `forest3d:egl` (4.15 GB) |
| Generated terrain-only world (Q6 sample) | `worlds/forest_world.world` |
| Camera-only render test world (Tier 2) | `worlds/spike_cam_test.world` |
| **Merged shell world (Tier 3, the deliverable)** | `worlds/forest_spike.world` |
| Merged shell + `model://` include (model-graft proof) | `worlds/forest_modelinclude_test.world` |
| **GPU-render proof, terrain-only (non-blank)** | `spike/proof_camera.png` |
| **GPU-render proof, merged world w/ placed object** | `spike/proof_merged_world.png` |
| **Populated forest — full pipeline proof (overview ×2 + ground)** | `spike/forest_cam_over1.png`, `forest_cam_over2.png`, `forest_cam_ground.png` |
| Single-tree pipeline verify (green + upright) | `spike/verify_tree.png` |
| Procedural asset generator (Blender) | `spike/make_assets.py` → `Blender-Assets/{tree,rock,bush}/*.blend` |
| **Graft helper (generated world → shell + cameras)** | `spike/merge_world.py` → `worlds/forest_full.world` (81 includes) |
| Multi-camera capture | `spike/capture_multi.py` |
| Native gz-transport capture scripts | `spike/capture_cam.py`, `spike/capture_sensors.py` |
| Raw frame data | `frames/cam.npy`, `frames/cam.ppm`, gz logs in `frames/` |
| Execution plan followed | `EXECUTION_PLAN.md` |

### Key commands (reproducible)
```bash
# build (base + patched)
docker build -t forest3d -f docker/Dockerfile .                 # 214 s, 4.08 GB
docker build -t forest3d:egl -f docker/Dockerfile.egl .         # adds numpy<2 + NVIDIA EGL ICD

# generate a terrain-only world from the bundled DEM
docker run --rm -v "$PWD:/workspace" forest3d:egl terrain --dem ./dem/terrain.tif
docker run --rm -v "$PWD:/workspace" forest3d:egl generate

# load headless ON THE GPU + prove a non-blank camera frame
docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all \
  -e GZ_SIM_RESOURCE_PATH=/workspace/models -v "$PWD:/workspace" \
  --entrypoint bash forest3d:egl -c \
  'gz sim -s -r --headless-rendering /workspace/worlds/forest_spike.world & \
   python3 /workspace/spike/capture_sensors.py'
# => CAMERA std=22.2 NON-BLANK | LIDAR 928/5760 returns 58-150 m | NAVSAT 57.026,-115.427 alt 675 FIX OK
# => ~/.gz/rendering/ogre2.log: GL_RENDERER = NVIDIA GeForce RTX 2070  (NOT llvmpipe)
```

**Bottom line:** adopt-able. Do it in this order — patch the image, **add the seed**, build the graft
helper, then invest in assets. The render/sensor/GPS path is already proven on this hardware.
