# Forest3D asset registry

Tracks every 3D asset / texture evaluated for the realism upgrade. **Rule:** before
trying a new asset, check the REJECTED table so we don't re-test a dead end. Every asset
that ships in a world goes in USED with its source + license, even though we are not
publishing yet (so provenance is recoverable later).

Columns — keep them filled at evaluation time, not retroactively.

## USED — assets currently in the pipeline

| id | category | name | source + URL | license | poly (visual/coll) | tex res | size | notes |
|----|----------|------|--------------|---------|--------------------|---------|------|-------|
| tree-island_tree_01 | tree | Island Tree 01 (acacia-like, sparse foliage) | Poly Haven · https://polyhaven.com/a/island_tree_01 | **CC0** | 490 k tris visual (LOD1) / trunk-cylinder collision (~92 tris) | 2K albedo, 1K normal+rough | **102 MB glb** (textures embedded) | **P1 HERO — passes §7 checks.** Normalized via `spike/normalize_island_tree.py`: kept the LOD1 object (file ships LOD0 812k + LOD1 490k + kit pieces + geometry-nodes — exporting all = 1.7M overlapping tris), **rebuilt leaf material** as Principled BSDF (custom node GROUP in source is unreadable by the glTF exporter) with alpha→`Math:GreaterThan(0.5)`→Alpha so Blender 4.2 writes **alphaMode=MASK** (EEVEE-Next dropped CLIP; exporter now reads the node pattern, not `blend_method`), branches/trunk set OPAQUE (solid geometry), nor/rough downscaled to 1K. Converted with `configs/realism.yaml` (tree: visual 1.0 + skip-foliage + trunk_cylinder). Renders upright on GPU (NVIDIA, not llvmpipe) with **transparent foliage (sky between leaves)**, textured bark, cast shadows; ground lidar 2403/5760 returns. **glb 102 MB is over the §6 budget** → P3 TODO: drop to LOD-lower / 2K→1K albedo / decimate solid branches, target tens of MB. Proof: `spike/hero_closeup.png`, `spike/hero_sidebyside.png`, `spike/hero_cam_*.png`. |

## REJECTED — tested and discarded (do NOT retry)

| date | category | name | source | reason rejected |
|------|----------|------|--------|-----------------|
| 2026-06-27 | tree/rock/bush | `make_assets.py` procedural primitives (cones/cylinders/icospheres) | self-authored (`spike/make_assets.py`) | Proved the *pipeline* only. Too low-poly + flat-color to match the reference screenshots. Kept as a smoke-test asset set, NOT for realistic worlds. |

## Source shortlist (license posture — verify per-asset at adoption time)

| source | content | license posture | good for |
|--------|---------|-----------------|----------|
| [Poly Haven](https://polyhaven.com/models) | photo-scanned rocks, tree trunks, small veg; 8K PBR | **CC0** — no attribution, native `.blend` w/ packed textures | rocks/boulders (best), ground detail props |
| [ambientCG](https://ambientcg.com) | CC0 PBR ground/material textures (forest floor, grass, dirt, moss, bark, pine needles) | **CC0** | terrain texturing + retexturing assets |
| [Fab / Quixel Megascans](https://www.fab.com) | photoreal trees, boulders, 3D plants, scatter (the screenshot look) | **Fab Standard License** — engine-agnostic, internal sim use OK, **no redistribution of raw assets**; some free, most ~$0.99 since 2025 | hero trees, rocks, bushes |
| [BlenderKit](https://www.blenderkit.com) | trees/shrubs/grass with **pre-wired alpha foliage**, one-click import | **CC0 or RF** (RF = use OK, no resale/redistribution) | fastest path to alpha-foliage trees |
| [Sketchfab](https://sketchfab.com) | huge user library | filter **CC0 / CC-BY** (avoid CC-BY-NC); CC-BY needs credit in registry | variety / specific species |
| [Kenney Nature Kit](https://kenney.nl/assets/nature-kit) | game-ready, **stylized/low-poly** | **CC0** | prototyping only — not photoreal |

> Redistribution note: Fab + BlenderKit-RF forbid publishing the **raw** assets. Fine while we
> don't publish; if this repo (or generated worlds bundling the `.glb`) is ever made public, those
> assets must be swapped for CC0 or removed. Track which is which in the USED table's `license` col.
