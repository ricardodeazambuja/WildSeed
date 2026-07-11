# WildSeed asset registry

Tracks every 3D asset / texture evaluated for the realism upgrade. **Rule:** before
trying a new asset, check the REJECTED table so we don't re-test a dead end. Every asset
that ships in a world goes in USED with its source + license, even though we are not
publishing yet (so provenance is recoverable later).

Columns — keep them filled at evaluation time, not retroactively.

## USED — assets currently in the pipeline

| id | category | name | source + URL | license | poly (visual/coll) | tex res | size | notes |
|----|----------|------|--------------|---------|--------------------|---------|------|-------|
| rock-namaqualand_boulder_04 | rock | Namaqualand Boulder 04 (grey granite, lichen) | Poly Haven · https://polyhaven.com/a/namaqualand_boulder_04 | **CC0** | ~30 k tris visual (LOD0 59k → realism 0.5) / **convex-hull** collision (~80 tris) | 2K albedo, 1K normal+rough | 22 MB glb | **USED — renders normal-mapped on GPU.** Single clean Principled BSDF (no node group, no alpha) → normalize = keep LOD0 + downscale nor/rough to 1K + pack (`tools/normalize` inline). Converted with `configs/realism.yaml` (rock: visual 0.5 + convex_hull). 1.9 m base; `generate` scales ×0.5–2.0. **Note:** diffuse has heavy orange iron/lichen staining — for a cleaner grey granite, try `boulder_01` / `rock_07`. Sample renders: `tools/archive/hero_scene.png`, `tools/archive/scene_sidebyside.png`. |
| terrain-Grass004 | soil/terrain | ambientCG Grass 004 (PBR ground) | ambientCG · https://ambientcg.com/view?id=Grass004 | **CC0** | n/a (terrain UV-tiled) | 2K Color + 1K NormalGL + Roughness | ~36 MB (3 PNGs) | **Base grass.** Used as the `uniform` base and the `patchy` base layer (see ground compositor below). |
| terrain-Ground027 | soil | ambientCG Ground 027 (sand/tan) | ambientCG · https://ambientcg.com/view?id=Ground027 | **CC0** | n/a | 1K | ~3 MB | Sand overlay layer. |
| terrain-Ground054 | soil | ambientCG Ground 054 (brown dirt) | ambientCG · https://ambientcg.com/view?id=Ground054 | **CC0** | n/a | 1K | ~3 MB | **Trail/dirt** overlay (the winding path). |
| terrain-Gravel023 | soil | ambientCG Gravel 023 (light gravel) | ambientCG · https://ambientcg.com/view?id=Gravel023 | **CC0** | n/a | 1K | ~3 MB | Gravel patch overlay. |
| terrain-Rocks023 | soil | ambientCG Rocks 023 (pebbles) | ambientCG · https://ambientcg.com/view?id=Rocks023 | **CC0** | n/a | 1K | ~3 MB | Pebble patch overlay. |
| terrain-Snow006 | soil | ambientCG Snow 006 | ambientCG · https://ambientcg.com/view?id=Snow006 | **CC0** | n/a | 1K | ~3 MB | **Snow biome** base. |
| terrain-Ground037 | soil | ambientCG Ground 037 (olive dry) | ambientCG · https://ambientcg.com/view?id=Ground037 | **CC0** | n/a | 1K | ~3 MB | Bare-ground patch (snow biome). |

> **Ground compositor (`tools/make_ground.py`) — the patchy-terrain capability.** Replicates how the *original* Forest3D made its Soil 1/2/3 references (single PBR material extracted from a `soil.blend` via `extract_terrain_texture`; the variation is whatever's baked into the source image, mapped at low tiling) **and extends it** with controllable variation the original lacks: seeded `patchy` mode bakes a 1:1 composite of a base + overlay layers (sand/gravel/pebble **patches** via seeded noise blobs, **trails** via explicit waypoints *or* random walk, soft mask edges, normals lerp+renormalised). `uniform` mode keeps the crisp tiled single material (feed a varied texture at low `--tile`). Output is one `<pbr><metal>` material. Bake resolution is the only crispness lever (4K default ≈ 5 cm/texel ≈ ~78 MB for 3 maps; 8K sharper but ~4× footprint; patchy is softer up close than uniform tiling). Seeded → reproducible. **TODO:** fold into `wildseed terrain` as a `--ground-mode uniform|patchy` + layer/trail spec. Sample renders: `tools/archive/ground_capability.png`, `tools/archive/patchy_cam_*.png`, `tools/archive/ground_topdown.png`.
| tree-island_tree_01 | tree | Island Tree 01 (acacia-like, sparse foliage) | Poly Haven · https://polyhaven.com/a/island_tree_01 | **CC0** | 490 k tris visual (LOD1) / trunk-cylinder collision (~92 tris) | 2K albedo, 1K normal+rough | **102 MB glb** (textures embedded) | **USED (hero tree).** Normalized via `tools/normalize_island_tree.py`: kept the LOD1 object (file ships LOD0 812k + LOD1 490k + kit pieces + geometry-nodes — exporting all = 1.7M overlapping tris), **rebuilt leaf material** as Principled BSDF (custom node GROUP in source is unreadable by the glTF exporter) with alpha→`Math:GreaterThan(0.5)`→Alpha so Blender 4.2 writes **alphaMode=MASK** (EEVEE-Next dropped CLIP; exporter now reads the node pattern, not `blend_method`), branches/trunk set OPAQUE (solid geometry), nor/rough downscaled to 1K. Converted with `configs/realism.yaml` (tree: visual 1.0 + skip-foliage + trunk_cylinder). Renders upright on GPU (NVIDIA, not llvmpipe) with **transparent foliage (sky between leaves)**, textured bark, cast shadows; ground lidar 2403/5760 returns. **glb 102 MB is over the size budget** → TODO: drop to LOD-lower / 2K→1K albedo / decimate solid branches, target tens of MB. Sample renders: `tools/archive/hero_closeup.png`, `tools/archive/hero_sidebyside.png`, `tools/archive/hero_cam_*.png`. |

### Added for demo scenarios (2026-06-27) — all Poly Haven, **CC0**

Fetched via `tools/fetch_polyhaven.py <id> 1k <dir>` (glTF bundle), normalized with
`tools/import_gltf.py` (recenter + base-to-z0 + foliage-alpha MASK fix), converted with
`wildseed -c configs/realism.yaml convert`. **Credit (CC0, attribution appreciated):**
Poly Haven — https://polyhaven.com. Model binaries live under `models/` (gitignored,
regenerable from these ids + scripts).

| id | category | name | source + URL | license | notes |
|----|----------|------|--------------|---------|-------|
| rock-boulder_01 | rock | Boulder 01 | Poly Haven · https://polyhaven.com/a/boulder_01 | **CC0** | clean grey boulder, single material; gltf→convert (convex_hull). Renders textured. |
| rock-namaqualand_rocks_01 | rock | Namaqualand Rocks 01 | Poly Haven · https://polyhaven.com/a/namaqualand_rocks_01 | **CC0** | small scattered pebbles/stones; ground-detail rock. |
| tree-dead_tree_trunk_02 | tree | Dead Tree Trunk 02 | Poly Haven · https://polyhaven.com/a/dead_tree_trunk_02 | **CC0** | fallen/dead trunk; winter + forest-floor dressing. No foliage → OPAQUE, trivial. |
| tree-fir_sapling | tree | Fir Sapling | Poly Haven · https://polyhaven.com/a/fir_sapling | **CC0** | young firs (clump of 3, scaled ×4); conifer foliage for SNOW scenes. **Gotcha:** Poly Haven's glTF omits the foliage alpha map (twigs export OPAQUE) — `import_gltf.py` downloads `twigs_alpha` separately and wires it via Math:GreaterThan→Alpha so it exports alphaMode=MASK. See [[blender42-gltf-mask-foliage]]. |
| rock-namaqualand_boulder_04 | rock | (existing) | — | **CC0** | see row above. |

> **Procedural terrain (`wildseed terraingen`, `core/terraingen.py`) — NO external asset.** The
> landform itself is synthesized (numpy/scipy fBm + ridged noise, Gaussian peaks, carved
> basins/creeks), written as a GeoTIFF DEM, and fed to the existing `wildseed terrain --dem`
> pipeline unchanged. Presets: `flat`/`hilly`/`valley`/`mountainous`/`lakeland`. Seeded → same
> `--seed` gives the same landform. No license/provenance to track (self-authored math). Ground
> *texture* still comes from the ambientCG packs above; lakeland water reuses `write_water_model`.
> Proof: `tools/terrain_gallery.png` (5 presets on GPU; lakeland holds water in its basins).

## REJECTED — tested and discarded (do NOT retry)

| date | category | name | source | reason rejected |
|------|----------|------|--------|-----------------|
| 2026-07-03 | grass | moss_01 | Poly Haven (CC0) | photoscan sprig is 15 cm long; at grass placement scales (0.25-0.7x) it's invisible ground clutter — useless as scatter. Converted fine (3.2 MB); dropped from manifest+palettes. |
| 2026-06-27 | tree/rock/bush | `make_assets.py` procedural primitives (cones/cylinders/icospheres) | self-authored (`tools/make_assets.py`) | Proved the *pipeline* only. Too low-poly + flat-color for realistic worlds. Kept as a smoke-test asset set. |

## Source shortlist (license posture — verify per-asset at adoption time)

**Policy (2026-07-03):** assets do **not** have to be CC0 — any license that allows
free redistribution is acceptable, attribution is easy and always given (this
registry + README credits). That admits **CC-BY** (and CC-BY-SA for asset files,
kept clearly separate from the AGPL code). Still excluded: **NC/ND** variants and
any "royalty-free but no redistribution" terms (Fab, BlenderKit-RF, TurboSquid/
CGTrader free) — the repo is public.

| source | content | license posture | good for |
|--------|---------|-----------------|----------|
| [Poly Haven](https://polyhaven.com/models) | photo-scanned rocks, tree trunks, small veg; 8K PBR | **CC0** — no attribution, native `.blend` w/ packed textures, credential-free API | rocks/boulders (best), ground detail props |
| [ambientCG](https://ambientcg.com) | CC0 PBR ground/material textures (forest floor, grass, dirt, moss, bark, pine needles) | **CC0** | terrain texturing + retexturing assets |
| [Sketchfab](https://sketchfab.com) | huge user library incl. photogrammetry trees/rocks | filter **CC0 / CC-BY** (avoid CC-BY-NC/ND); **OK under policy** with credit; download API needs a free account token (breaks the no-login rebuild guarantee → manual fetch + vendored source, or user-supplied token) | variety / specific species |
| [Poly Pizza](https://poly.pizza) | aggregated low-poly CC0/CC-BY models (incl. Google Poly rescue) | **CC0 / CC-BY** per asset; free API key | stylized variety, quick props |
| [OpenGameArt](https://opengameart.org) | community models/textures | per-asset **CC0 / CC-BY / CC-BY-SA / GPL** — check each | odd species, ground clutter |
| [Quaternius](https://quaternius.com) | stylized low-poly nature packs, direct zip download | **CC0** | stylized/DR worlds, prototyping |
| [Kenney Nature Kit](https://kenney.nl/assets/nature-kit) | game-ready, **stylized/low-poly** | **CC0** | prototyping only — not photoreal |
| [Fab / Quixel Megascans](https://www.fab.com) | photoreal trees, boulders, 3D plants, scatter | **Fab Standard License** — internal sim use OK, **no redistribution** → excluded by policy | (reference only) |
| [BlenderKit](https://www.blenderkit.com) | trees/shrubs/grass with pre-wired alpha foliage | **CC0 or RF** — RF forbids redistribution → CC0-filtered only | alpha-foliage trees (CC0 subset) |

> Redistribution note: anything adopted under CC-BY/CC-BY-SA gets its author + license
> in the USED table AND the README credits section. NC/ND/RF assets are not adopted at
> all — the repo and the generated worlds that embed `.glb` copies are public.

## Variety upgrade plan (2026-06-28)

**Context:** the upstream project ships **no** assets (all `Blender-Assets/` are
`.gitkeep`; `.gitignore` blocks `*.blend`) and its own renders used **commercial**
libraries (Maxtree, Quixel Megascans) that are **not redistributable** → we build the
look with freely-redistributable assets instead. The gap is asset **variety**, not
the pipeline.

**Confirmed 2026 licensing (verified 2026-06-28):**
- **Quixel Megascans** — PAID since 2025-01-01 (only a small rotating free set). Fab Standard License
  forbids standalone redistribution of raw `.blend`/`.fbx` (only embedded in a build/render). **Not
  repo-shippable.** EULA: https://www.fab.com/eula
- **BlenderKit** — free assets are **CC0 _or_ Royalty-Free**. Only the **CC0** subset is
  redistributable; RF forbids it. Filter strictly to CC0. https://www.blenderkit.com/docs/licenses/

**Recommended CC0 sources, ranked for VARIETY + redistributable-in-MIT-repo:**

| rank | source | what | license | variety | notes |
|------|--------|------|---------|---------|-------|
| 1 | **ffish.asia / floraZia** (Sketchfab) · https://sketchfab.com/ffishAsia-and-floraZia | photoscanned real organisms incl. **land plants/grasses/weeds with scientific binomial names** (e.g. *Beckmannia syzigachne*, *Hordeum vulgare*) | **CC0** (Kyushu Univ. / QOU public-domain catalog) | **3,026 models** | Downloadable glTF/USDZ + original (.obj/.fbx/.blend). Free Sketchfab account, ~50 dl/day rate limit. Real species → photoreal like Maxtree, but CC0. |
| 2 | **Sapling Tree Gen** (built-in) + **geometry-nodes grass** | procedural windswept coastal trees, marram-grass clumps, shrubs | code GPL; **generated mesh output is yours** → ship as CC0/MIT | **infinite** | zero licensing risk; best for grass clumps + bent coastal trees. Geometry-nodes templates must themselves be CC0/self-authored. |
| 3 | **Poly Haven** · https://polyhaven.com/models | photoscanned rocks/boulders, tree trunks, some veg | **CC0** | ~100–150 nature models | already in pipeline; the redistributable Megascans-rock equivalent. Best for hero rocks + sand/coastal-clay material. |
| 4 | **ambientCG** · https://ambientcg.com | 2,000+ PBR **textures** (sand, gravel, coastal clay, bark) + a few debris meshes | **CC0** | textures only | already in pipeline for terrain/retexturing. |
| — | Gazebo Fuel · https://app.gazebosim.org/fuel/models | sim models | mixed (often **CC-BY/CC-BY-SA** — MIT-compatible *with attribution*, verify per asset) | ~50–100, low-poly | verify+credit each; mostly low-poly. |
| ✗ | Megascans/Fab, BlenderKit-RF, Grass-Free addon (no formal license) | — | non-redistributable / legal gray area | — | do NOT ship raw. |

**Open follow-up:** ffish.asia remains the largest untapped CC0 species pool (grasses/shrubs);
adopting from it means `import_gltf.py` normalization + a USED-table entry with Sketchfab URL per asset.

## Variety harvest (2026-07-03) — 15 new Poly Haven assets, all **CC0**

**Source decision:** the ffish.asia/floraZia plan above needs a Sketchfab **account token**
for its download API (none on this machine; blocked without user input) and would break the
repo's "reproduce with NO account/login" guarantee. Poly Haven still had **88 unused CC0
nature models** on its credential-free API — enough to clear the variety DoD (>=3 tree +
>=2 understory species per biome) without Sketchfab. ffish.asia stays open as a documented
follow-up if per-species photoscan realism is later needed (requires user-provided token).

All fetched/normalized/converted by the standard manifest pipeline (`assets/manifest.yaml`
→ `tools/build_assets.py`), sha256-locked in `assets/manifest.lock.yaml`, verified via the
catalog render (`tools/asset_catalog.png`). Palettes: temperate 5 trees, savanna 4, wetland
3, alpine 6, winter 6, coastal 3; every biome >=2 understory species.

| id | category | biomes | notes |
|----|----------|--------|-------|
| island_tree_03 | tree | temperate, wetland, coastal | broadleaf, LOD1, 50.5 MB |
| jacaranda_tree | tree | temperate, wetland | **149 MB (over budget):** leaves are real meshes (LOD1 = 1.5 M tri; LOD0/LOD1 only, no lighter LOD ships). Same slim-down TODO as island_tree_01. |
| tree_small_02 | tree | coastal, temperate | small generic broadleaf, LOD1, 53 MB |
| quiver_tree_02 | tree | savanna | second quiver species, 7.4 MB |
| searsia_burchellii | tree | savanna | large karoo shrub-tree, 27.6 MB |
| dead_quiver_trunk | tree | savanna | dead landmark trunk, no foliage, 5.6 MB |
| pine_sapling_medium | tree | alpine, winter | conifer understory-canopy bridge, 25.4 MB |
| fir_sapling_medium | tree | alpine, winter | conifer, 15.9 MB |
| shrub_02 | bush | temperate, wetland, alpine | kit variant a, 4.8 MB |
| shrub_04 | bush | temperate, coastal | kit variant a, 4.7 MB |
| othonna_cerarioides | bush | savanna | succulent shrub, 13.7 MB |
| nettle_plant | bush | wetland | 6.0 MB |
| dandelion_01 | grass | temperate, wetland | kit variant a, 5.4 MB |
| flower_ursinia | grass | savanna | karoo wildflower, 5.3 MB |
| dry_branches_medium_01 | grass | winter, alpine | ground debris scatter, 7.2 MB |

**Pipeline fix shipped with the harvest:** `tools/normalize_blend.py` foliage detection now
also triggers on the presence of an **alpha/opacity texture map**, not only on material-name
keywords — species-named materials (`dandelion_01`, `jacaranda_tree`, ...) carry no keyword
and would otherwise export OPAQUE (the black-blob bug pattern). Bark/rock/trunk materials
never ship an alpha map, so the signal is safe.

## Diversity harvest (2026-07-03, Poly Haven catalogue review) — 15 new assets, all **CC0**

Found by browsing the Poly Haven nature catalogue — its credential-free CC0 API had
everything needed, so no Sketchfab token was required.
Focus: forest-floor deadwood, mossy/barren rock variety, and species for the thin
biomes. Built by the standard manifest pipeline, sha256-locked.

| id | category | biomes | visual glb |
|----|----------|--------|------------|
| searsia_lucida | tree | savanna | 10.6 MB |
| pine_sapling_small | tree | alpine, winter | 34.1 MB |
| tree_stump_01 | tree | temperate, wetland | 7.9 MB |
| tree_stump_02 | tree | alpine, winter | 8.6 MB |
| dead_tree_trunk | tree | temperate, wetland | 8.6 MB |
| rock_09 | rock | temperate, wetland | 18.9 MB |
| rock_face_01 | rock | alpine | 24.3 MB — **open shell**: front-surface-only cliff scan, hollow back (welded boundary-edge ratio 0.037, every other rock ~0). ogre2 backface-culls the open side, so it vanishes when seen from behind — fine embedded in static scenery viewed front-ish, auto-excluded from the distractor mover pool (`glb_open_ratio`, core/distract.py), never pick it for anything that rotates or is orbited close-up. |
| rock_moss_set_01 | rock | temperate, wetland | 6.2 MB |
| coast_rocks_02 | rock | coastal | 44.3 MB |
| namaqualand_boulder_02 | rock | savanna | 27.8 MB |
| moon_rock_01 | rock | alpine, winter | 4.4 MB |
| cheiridopsis_succulent | bush | savanna, coastal | 5.5 MB |
| shrub_sorrel_01 | bush | temperate, wetland | 4.8 MB |
| celandine_01 | grass | temperate, wetland | 5.0 MB |
| periwinkle_plant | grass | temperate | 8.2 MB |
