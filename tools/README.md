# `tools/` — dev/build tooling for the reproducible demos

These are **standalone scripts**, not part of the installed `wildseed` package (the library in
`src/` does not import anything here). They build the CC0 demo asset set, render the 6 demo
scenarios, and measure realism against the reference screenshots. Most render steps need the
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
| `normalize_blend.py` | Blender normalizer: pick LOD/variant, recenter/base-z0/scale, **rebuild foliage as `alphaMode=MASK`**, prefer the assembled tree object. The single most important asset-prep step. |
| `import_gltf.py`, `normalize_island_tree.py` | Variants of the normalizer for glTF input and the island-tree special case. |
| `build_scenarios.py` | Builds + renders all 6 demos end-to-end (terraingen → terrain → ground → generate → render). `FOREST_SCN=name` filters to one scene. |
| `terrain_scene.py` | Assembles the gz render world + the 3 cameras (`cam_hero`, `cam_oblique`, `cam_top`). |
| `capture_cams.py` | Captures frames from the gz camera topics → `frames/*.npy`. |

## Realism metrics

| Script | What it does |
|--------|--------------|
| `compare.py` | Image-level metric harness: ORB/FAST per-MP, 8×8 coverage, tiling autocorrelation, vs the 3 reference screenshots. Emits `compare.png` + a markdown table. Needs `opencv-python-headless` (in `:egl`). |
| `quickmetric.py` | Fast single-scene readout (`python3 tools/quickmetric.py savanna_flats`). |
| `regen_galleries.py` | Rebuilds the 6-panel `scenarios_gallery.png` / `scenarios_overview.png` from frames on disk — use after a single-scene `FOREST_SCN=` build. |
| `scenario_gallery.py` | Builds + renders N `wildseed scenario --seed` worlds (default 101/107/108) → `scenario_seeds_gallery.png`, the master-seed diversity proof. For rows scenarios the hero cam auto-aims at the plantation centroid (from the `.instances.json` ground truth). `scenario_structured_gallery.png` (seeds 204/207) shows the vineyard + orchard biomes. |

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
