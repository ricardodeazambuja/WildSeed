# `tools/` — dev/build tooling for the reproducible demos

These are **standalone scripts**, not part of the installed `wildseed` package (the library in
`src/` does not import anything here). They build the CC0 demo asset set, render the 6 demo
scenarios, and measure image-level feature metrics on the renders. Most render steps need the
GPU `wildseed:egl` image — see the repo `README.md` → *Gotchas, best practices & caveats*.

Run from the repo root, inside the container, e.g.:

```bash
docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -e PYTHONPATH=/workspace/src \
  -v "$PWD:/workspace" --entrypoint bash wildseed:egl -c 'cd /workspace && python3 tools/build_scenarios.py'
```

## Core demo pipeline (the path that produces the galleries)

| Script | What it does |
|--------|--------------|
| `build_assets.py` | Idempotent fetch → normalize → convert of the CC0 Poly Haven asset set → `models/<cat>/<id>/`. Writes `assets/manifest.lock.yaml`. |
| `fetch_polyhaven.py` | Credential-free download of one Poly Haven asset (`.blend`/glTF). |
| `normalize_blend.py` | Blender normalizer: pick LOD/variant, recenter/base-z0/scale, **rebuild foliage as `alphaMode=MASK`**, prefer the assembled tree object. |
| `import_gltf.py`, `normalize_island_tree.py` | Variants of the normalizer for glTF input and the island-tree special case. |
| `build_scenarios.py` | Builds + renders all 6 demos end-to-end (terraingen → terrain → ground → generate → render). `FOREST_SCN=name` filters to one scene. |
| `terrain_scene.py` | Assembles the gz render world + the 3 cameras (`cam_hero`, `cam_oblique`, `cam_top`). |
| `capture_cams.py` | Captures frames from the gz camera topics → `frames/*.npy`. |

## Realism metrics

| Script | What it does |
|--------|--------------|
| `compare.py` | Image-level metric harness: ORB/FAST per-MP, 8×8 coverage, tiling autocorrelation. Compares the 6 scenes against local reference images if present (not bundled). Emits `compare.png` + a markdown table. Needs `opencv-python-headless` (in `:egl`). |
| `quickmetric.py` | Fast single-scene readout (`python3 tools/quickmetric.py savanna_flats`). |
| `regen_galleries.py` | Rebuilds the 6-panel `scenarios_gallery.png` / `scenarios_overview.png` from frames on disk — use after a single-scene `FOREST_SCN=` build. |
| `scenario_gallery.py` | Builds + renders N `wildseed scenario --seed` worlds (default 101/107/108) → `scenario_seeds_gallery.png`, the seed-diversity gallery. For rows scenarios the hero cam auto-aims at the plantation centroid (from the `.instances.json` ground truth). `scenario_structured_gallery.png` (seeds 204/207) shows the vineyard + orchard biomes. |

### VIO benchmarking (does a generated world actually support VIO?)

Renders the **real sensor-rig camera** (640×480, 57° FOV; `core/rig.py`) at the actual
operating poses (`cli/fly.py`: 12 m drone, 2 m ground-robot) — the axis the gallery cams
above cannot see (they are oblique 720p framing shots). The three scripts escalate from
"are there features" to "are the features *usable*". All run in `wildseed:egl` (GPU).
See **`docs/VIO_BENCH.md`** for the full method + how to read the numbers.

| Script | What it does |
|--------|--------------|
| **`vio_bench.py`** | **The VIO benchmark.** Measures descriptor **data-association quality under motion** — the metric that predicts VIO failure (perceptual **aliasing**: repeated/indistinct features that break matching), which feature *count* misses. Renders a canonical translation+yaw trajectory over the current `models/` world and reports Lowe-ratio rejection, essential-matrix **inlier ratio**, inliers/pair, self-ambiguity + a GOOD/ALIASING-RISK verdict. `python3 tools/vio_bench.py --tag myworld` (or `--ground-modes patchy,uniform_t1` to A/B). |
| `vio_exp.py` | Per-frame **ground-region** feature density (FAST/MP, ORB/MP, coverage, tiling autocorrelation, high-frequency energy) for A/B ground materials at the drone + ground-robot poses. |
| `vio_seq.py` | Temporal **KLT feature-track-length** over a forward-motion sequence (how many frames a feature survives). NB: KLT is a *local* tracker → long tracks do **not** rule out aliasing; use `vio_bench.py` for that. |
| `vio_clutter_exp.py` | Worked example: holds terrain+ground constant, varies **placement density** (bare→trees→full clutter), benchmarks each. Shows landmark density — not ground texture — drives confident matches (inliers/pair 200→604). |
| **`rtf_bench.py`** | **RTF-under-load harness** — the COST gauge. Launches a real `gz sim -s -r` server on a rig world, attaches cam/lidar consumers, waits for the sim clock to advance (skips load stall), and samples `real_time_factor` off `/stats`. Reports `window_rtf` / `rtf_min` / `load_wait_s` / `stalled`. Keep the operating point where `rtf_min` ≥ ~0.5. |
| **`lidar_spread.py`** | **LIO axis (V3)** the camera benchmark can't see: gpu_lidar range **roughness**. `ring_roughness_m` = mean std of Δrange between adjacent azimuth beams (~0 over flat ground, rises with clutter/relief), plus `range_std_m` / `near_frac` / `finite_frac`. |
| `corridor_map.py` | **Steered-scatter (c) plumbing**: paints a driving-corridor density map (white band at the drive line, `--soft` Gaussian taper) for `generate --density-maps` → the object budget lands where the vehicle drives (high local density, low total count). |
| `heightmap_relief.py` | **Geometric-relief (d2) plumbing**: writes a hi-res gz `<heightmap>` ground with cm–dm surface roughness on a FLAT drivable macro (Ogre2 Terra: GPU-tessellated + LOD'd, one static mesh) + injects the rig. Carries relief the Nyquist-limited WildSeed mesh (d1) can't, at RTF 1.0. Measure with `rtf_bench` / `lidar_spread` / `vio_bench --heightmap`. |
| **`vio_validate.py`** | **End-to-end VIO/LIO ATE validation (Phase C)** — turns the proxies into real trajectory drift. Self-contained reference estimator (no ROS): monocular ORB+essential-matrix VO (GT-scaled) + point-to-point ICP LIO, Umeyama-aligned to TUM ground truth from `record --dataset`. Reports segment/relative drift, global ATE, and tracking-failure counts per run. `python3 tools/vio_validate.py runs/recipe runs/baseline`. |

See **`docs/GROUND_CLUTTER.md`** for the ground-clutter/relief study (P1 failure baseline,
RTF harness, options (c) steered scatter + (d) geometric relief, on the feature-gain/RTF-cost frontier).

`terrain_scene.py` gained two gated hooks for these: `VIO_CAMS=1` adds the drone/ground
cams; `VIO_TRAJ="x,y,z,pitch,yaw;…"` places one `vio_cam_<i>` per pose so a whole
trajectory renders in a single gz session.

## Catalog & diagnostics

| Script | What it does |
|--------|--------------|
| `render_catalog.py` + `compose_catalog.py` | Render + tile the per-asset catalog → `asset_catalog.png`. |
| `terrain_gallery.py` | Tile the terrain-preset gallery → `terrain_gallery.png`. |
| `make_ground.py` | The patchy-ground compositor preview/standalone. |
| `model_probe.py` | Drop a single model into a probe world for inspection. |

## Legacy spike helpers (kept for reference, not on the demo path)

`make_assets.py` (procedural CC0 asset generator), `merge_world.py` (world-graft helper),
`hero_scene.py`, `hero_closeup.py`, `water_scene.py`, and the alternate capture scripts
`capture_cam.py` / `capture_multi.py` / `capture_sensors.py` predate the current pipeline.

## Committed artifacts

- **Live deliverables** (in `tools/`): `scenarios_gallery.png`, `scenarios_overview.png`,
  `compare.png`, `asset_catalog.png`, `phaseB_detiling_autocorr.png`, `terrain_gallery.png`,
  `terrain_seeds.png`, `diag_detail.png`.
- **`archive/`** — one-off spike-era diagnostic renders, kept for provenance only.
- **`ASSET_REGISTRY.md`** — per-asset source URL + license credits (all CC0).
