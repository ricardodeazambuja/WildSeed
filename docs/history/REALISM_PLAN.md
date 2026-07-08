# Forest3D realism plan — reaching reference-screenshot quality

> **⚠️ Historical (superseded).** Original realism plan, kept for provenance. The work it
> scoped was completed — see [`docs/history/DEMO_REALISM_V2_REPORT.md`](DEMO_REALISM_V2_REPORT.md)
> (final report) and [`docs/history/baseline_metrics.md`](baseline_metrics.md) (metrics). Paths
> below that say `spike/` now live under `tools/` (one-off diagnostic images under
> `tools/archive/`); this archived text is not rewritten for the rename.

**Goal:** make generated worlds look like the project's reference screenshots
(`Screenshot from 2026-01-0*.png`: photo-textured savanna trees, normal-mapped boulders,
grass-textured terrain) instead of the spike's flat-color primitives (`spike/forest_*.png`).

**Decisions locked (from the team):**
- **Assets:** sourced photoreal `.blend` (not procedural) for trees; real assets for rock/bush too.
- **Quality budget:** *balanced + LODs* — 2K PBR, moderate poly, alpha foliage; viable for batch VIO/lidar sim + the ~60 GB disk policy.
- **Licensing:** anything goes for now (not publishing), **but every asset is logged** in
  [`spike/ASSET_REGISTRY.md`](../../tools/ASSET_REGISTRY.md) — USED (source+license) and a REJECTED list
  (so dead-ends aren't re-tried).

**Scope note:** the spike already proved the *orchestration* (convert → generate → graft →
headless GPU render → camera/lidar/navsat — see `SPIKE_FINDINGS.md`). This plan is **only** about
closing the visual gap. Nothing here re-litigates that the pipeline runs.

**Branch check (done):** the reference screenshots were served from the upstream
`feature/terrain-texture` branch, which **no longer exists** (succeeded by
`feature/terrain-types-refactor`). I diffed the survivor against `main`: `core/converter.py` is
**unchanged except docstrings** (so the decimation/collision fork below is genuinely *not* done
upstream), terrain texturing still uses the same `texture_blend` extractor (the refactor adds terrain
*types*, not better texturing), and `Blender-Assets/*` are **still empty gitkeeps on every branch** —
the actual screenshot assets were never committed (external, gitignored) and are unrecoverable from
git. Net: nothing upstream short-cuts this plan; sourcing + the convert fork are the real work.

---

## 1. Diagnosis — why ours looks low-poly (and what actually drives the reference look)

| realism factor | reference screenshots | our spike | the fix |
|---|---|---|---|
| **Tree geometry** | high-poly trunks + branches + **alpha leaf cards** | cones on a cylinder | sourced photoreal trees (§3) |
| **Materials** | PBR image textures (albedo/normal/roughness) + alpha | flat Base-Color only | textured assets + glTF material passthrough (§4) |
| **Foliage** | thousands of transparent leaf cards | none | alpha-MASK foliage pipeline (§4) — *the hard part* |
| **Terrain** | grass/soil PBR ("Soil 1/2/3") | untextured grey | `terrain --texture` from a CC0 ground set (§5) |
| **Rocks** | normal-mapped photo-scanned boulders | grey lumpy icosphere | Poly Haven CC0 rocks (§3) |
| **Ground detail** | scatter (twigs, dry grass, dirt patches) | none | grass/scatter category + decals (§6, stretch) |

**Conclusion:** the gap is **assets + texturing + a convert step that doesn't destroy them** — not
the generator. Two of those (real assets, terrain texture) are sourcing/authoring; one (foliage
through `convert`) needs a **code change in our fork**. That third item is the technical crux.

---

## 2. The technical crux — Forest3D's `convert` will *destroy* photoreal assets as-is

Two hard blockers in `core/converter.py` (verified by reading the source):

1. **Blanket decimation.** `_export_glb` (converter.py:116–161) adds a `DECIMATE` modifier at
   `visual_decimation` (**default 0.1**) to **every** mesh and applies it. On a photoreal tree this
   collapses thin branches and **annihilates alpha leaf cards** (a leaf card is 2 tris; 10% of 2 is
   nothing). Real trees must be decimated *gently or not at all* — and foliage must be **excluded**
   from decimation entirely.
2. **Collision = decimated visual mesh.** It exports a second GLB (`*_collision.glb`) from the same
   geometry at `collision_decimation` (converter.py:159–160). For a tree that yields a
   leaf-and-branch-shaped collision hull — wrong and expensive. Lidar/physics want a **simple trunk
   cylinder**; rocks want a **convex hull**; bushes want a **low box/sphere**.

**Required fork changes** (our remote is now `ricardodeazambuja/Forest3D`):
- Make decimation **per-category and material-aware**: skip decimation on objects whose material has
  alpha (foliage); allow a higher trunk/rock ratio (e.g. 0.5) or a target-tri budget instead of a
  blind ratio. Add `visual_decimation` per-category to `BlenderConfig` (config/schema.py).
- Add a **collision strategy per category**: `trunk_cylinder` (tree/bush) vs `convex_hull` (rock) vs
  `mesh` (current). Generate the collision primitive in the Blender script from the mesh bounds
  rather than decimating the visual.
- Ensure the glTF export keeps what we need (it already sets `export_materials='EXPORT'`,
  `export_texcoords=True`, `export_normals=True`, `export_yup=False`) — but it does **not** control
  `alphaMode`/`doubleSided`; those come from the **source `.blend` material** (§4), so asset prep
  must set them.

These are localized changes (~1 file + a config field). Keep them behind config so the existing
behavior is the default for low-poly assets.

---

## 3. Asset sourcing (the look)

Per the registry shortlist (sources + license posture in `spike/ASSET_REGISTRY.md`). Target set for
a first realistic biome (match the savanna reference): **3–5 tree variants, 2–3 rocks, 2–3 bushes,
1–2 grass/scatter**, plus terrain ground textures.

- **Trees (dominant element):**
  - **BlenderKit** — fastest: trees ship with **pre-wired alpha foliage nodes**, one-click import.
    Filter CC0/RF, log which.
  - **Fab / Quixel Megascans** — closest to the screenshot acacia/savanna look; comes as mesh +
    texture sheets incl. **opacity map** → wire the opacity into Principled BSDF `Alpha` manually.
- **Rocks/boulders:** **Poly Haven** (CC0, photo-scanned, native `.blend` w/ packed PBR) — best
  quality-for-effort, zero license risk.
- **Bushes/grass/dry-grass:** BlenderKit or Fab; or build dry-grass clumps from a CC0 grass alpha
  atlas (ambientCG) on crossed quads.
- **Terrain ground:** **ambientCG** CC0 grass/forest-floor/dirt PBR sets (§5).

**Workflow per asset:** download → open in Blender → set up materials per §4 → save a normalized
`.blend` into `Blender-Assets/<category>/<name>.blend` → **add a row to the USED table** (source,
URL, license, poly, tex res, size). If it fails the §7 checks, move it to **REJECTED** with the
reason and try the next.

> Keep raw downloaded packs **out of the repo** (`Blender-Assets/**/*.blend` is gitignored already);
> the registry is the durable record. This also respects Fab/BlenderKit "no raw redistribution".

---

## 4. Foliage + PBR pipeline (Blender → glTF → gz Harmonic/ogre2) — the make-or-break

Researched + cross-checked (URLs in `spike/ASSET_REGISTRY.md` sources / raw notes). gz/ogre2 has
specific rules; get these wrong and leaves render **solid black** or **disappear**.

**In Blender, per foliage material:**
1. **Alpha → MASK, not BLEND.** Wire the leaf texture's alpha into Principled BSDF **`Alpha`**, then
   set the material **Blend Mode = Alpha Clip** (Eevee material settings). The glTF exporter then
   writes `"alphaMode":"MASK"` + `alphaCutoff`. MASK keeps depth writes → no transparency sorting
   glitches and lets ogre2 use Early-Z (fast with many leaves). **Avoid BLEND** — ogre2 disables
   depth writes for it → out-of-order/popping leaves.
2. **Double-sided.** **Uncheck Backface Culling** in material settings → exporter writes
   `"doubleSided":true` → ogre2 disables culling for that material → leaves visible from behind.
   Fallback if ignored: duplicate + flip leaf faces in Blender (2× tris, guaranteed).
3. **Real alpha channel.** The leaf texture must be a **PNG with an actual alpha channel** (not JPG)
   or the card background renders black.
4. **Trunk/rock PBR:** standard Principled BSDF with albedo/normal/roughness; no special handling.
5. **Unlit not supported:** gz `gz-rendering` ignores `KHR_materials_unlit`. Don't rely on it; if a
   material must read flat, use an `<emissive>` override in the model SDF.

**Verify each `.glb` before gz:** open in the [Khronos glTF Viewer](https://gltf-viewer.donmccurdy.com/)
— if leaves are transparent there, the glTF is correct and any remaining issue is gz-side.

**gz-side debugging:** if foliage still fails in gz, (a) check `~/.gz/rendering/ogre2.log`, and
(b) try `GZ_MESH_FORCE_ASSIMP=1` — forces the Assimp mesh loader, which maps glTF alpha/PBR into
ogre2 HLMS differently than the native tinygltf loader (a known escape hatch).

**Shakiest claim to validate in P1:** *"ogre2 respects glTF `doubleSided` natively"* — this is the
historically flaky bit in gz-rendering and the whole §4 chain leans on it. Treat it as a **hypothesis**,
not fact; have the **face-flip fallback** (duplicate+flip leaf faces) ready if backfaces render black.
The §4 list overall comes from a light-model web summary cross-checked against domain knowledge —
P1 is what turns it from "should work" into "verified on this machine."

**Foliage may be less critical than it looks** — look again at the savanna reference
(`Screenshot from 2026-01-08 23-56-51.png`): those acacias are **mostly bare branches with sparse
leaves** = solid geometry that survives decimation and **sidesteps the alpha-MASK/doubleSided problem
entirely**. (The denser olive tree in `blender2Gazebo.png` *is* leaf-card-heavy, so the real set is
mixed.) **Implication:** in P1, source a **branch-dominant / sparse-foliage tree first** — it de-risks
faster and may already match the look; only escalate to leaf-card-dense trees if needed.

**De-risk first:** run **one** real tree all the way through (Blender → `convert` → place in front of
the rig → `gz` headless → `spike/capture_cam.py`) and confirm it renders textured + upright, foliage
(if any) transparent with sky visible *between* leaves — the smallest-scene discipline that worked in
the spike. Only then batch the rest.

---

## 5. Terrain texturing (grey → grass/soil)

Forest3D already supports this; we just never fed it a texture. `core/terrain.py` builds a PBR
ground material (`_create_sdf_file`, lines 239–273: `albedo_map`/`normal_map`/`roughness_map` under
`model://ground/texture/`) and `terrain --texture <soil.blend>` extracts maps from a Blender file
(`extract_terrain_texture`).

- **Path A (use as designed):** build a small `soil.blend` whose material has ambientCG grass/dirt
  image textures (albedo+normal+roughness), then `forest3d terrain --dem dem/terrain.tif --texture
  soil.blend`. Confirm the maps land in `models/ground/texture/` and the SDF references them.
- **Path B (simpler, fork):** add a `--texture-dir` option that drops albedo/normal/roughness PNGs
  straight into `models/ground/texture/` and skips Blender extraction — fewer moving parts, and
  ambientCG already ships exactly those maps. *Recommended* if Path A's extractor proves fiddly.
- **UV tiling:** terrain spans ~215 m; a single texture stretched over it looks blurry. Use a tiling
  UV scale (the commented `--uv-tile`, terrain.py:45/62) so the ground texture repeats at a realistic
  ~2–5 m period. May need to re-enable that flag in our fork.
- **Texture variation (Q7):** swap the ground set per seed for the "Soil 1/2/3" effect.

---

## 6. LODs, footprint & performance (the "balanced" budget)

**Honest caveat:** gz Sim does **not** do automatic per-mesh LOD on glTF. "LODs" here is a budget
discipline, not a magic flag:
- **Poly/texture caps:** target ≤ ~5–15 k tris per tree visual after gentle decimation, **2K**
  textures (albedo) / 1K (normal+roughness). Rocks ≤ ~5 k. This alone keeps the scene tractable.
- **Instancing is free-ish:** placement uses `<include>model://tree/treeN</include>` → each unique
  model's mesh+textures load **once** and instance many times. So footprint scales with **# unique
  assets (3–5)**, not # placements (40+). A 40-tree world stays small.
- **Coarse "LOD" options if needed:** (a) a low-poly/billboard variant placed for far rings (requires
  a placement change to choose variant by distance — not in Forest3D today), or (b) the **gz Sim
  Levels** feature to load/cull regions by camera proximity. Treat both as *later* optimizations;
  start with capped moderate poly.
- **Footprint guard:** measure `du -sh models/` after adoption; with 2K textures + ~5 assets expect
  tens of MB per biome — fine for generate→use→prune. Log it in the registry.

---

## 7. Acceptance checks (how we know a real asset "passes")

Reuse the spike harness (`spike/capture_*.py`, `merge_world.py`). An asset is **USED** only if:
1. `convert` produces `*.glb` + a **sensible collision** primitive (not a leaf-shaped hull).
2. Khronos glTF Viewer shows correct textures + **transparent** foliage.
3. Headless gz render (GPU, `GL_RENDERER=NVIDIA`) shows it textured, upright, foliage transparent
   (sky visible between leaves) — not black, not a solid blob.
4. `gpu_lidar` returns come off the canopy at sane ranges. (Note: `gpu_lidar` is a *rendering*
   sensor — it samples the **visual** mesh, **not** collision — so canopy returns are expected
   regardless of the collision shape. The simple-collision change in §2 is justified by **physics +
   footprint** (clean drive-through, no exploded hull), not by lidar.)
5. Footprint within budget (§6).
Otherwise → **REJECTED** row + reason, next asset.

A good automated proxy (extend `capture_multi.py`): assert foliage pixels have **high local variance**
(texture detail) and the frame contains both green (leaves) and sky-between-leaves — distinguishes a
real canopy from a flat green blob.

---

## 8. Phased rollout

| phase | work | exit criterion | est. |
|---|---|---|---|
| **P0 — fork convert** | per-category decimation + foliage skip + primitive collision (§2); behind config | low-poly spike assets still convert unchanged; new knobs work | **~1 day** |
| **P1 — one hero tree** | source 1 BlenderKit/Fab tree, prep materials (§4), convert, render-verify (§7) | one photoreal tree renders with transparent foliage in gz on GPU | **~0.5–1 day** (1st time; pipeline learning) |
| **P2 — terrain texture** | ambientCG grass set → `--texture`/`--texture-dir` (§5) + UV tiling | terrain renders as tiled grass, not grey | **~0.5 day** |
| **P3 — asset set** | 3–5 trees, 2–3 rocks, 2–3 bushes, grass; each logged in registry | a generated world matches the reference look in the overview + ground shots | **~2–3 days** (sourcing+vetting dominated) |
| **P4 — polish/perf** | UV/lighting/shadow tuning, footprint check, optional billboards/Levels | balanced budget met; batch-render viable | **~1 day** |

**Total ≈ 5–7 days**, sourcing/vetting-dominated. P0 + P1 are the **de-risking** half — do them first
and we'll know within ~2 days whether photoreal foliage flows cleanly through gz on this machine.

---

## 9. Top risks

1. **Alpha foliage in gz/ogre2 (highest, but dodgeable).** If MASK + `doubleSided` don't render
   cleanly headless (the `doubleSided` support is the shaky part), foliage goes black/sorted-wrong.
   Mitigations: §4 checklist, glTF-viewer pre-check, `GZ_MESH_FORCE_ASSIMP=1`, face-flip fallback —
   **and the big one: start with sparse-foliage / branch-dominant trees** (like the reference acacias),
   which may avoid alpha foliage altogether. **P1 surfaces this on day one.**
2. **`convert` decimation/collision mangling real assets.** Mitigated by the P0 fork; until then,
   real assets are unusable. Don't skip P0.
3. **Footprint/perf creep** with many high-res assets. Mitigated by instancing + 2K caps + the
   registry footprint column; revisit Levels only if batch render is too slow.
4. **License drift if this ever goes public.** Fab/BlenderKit-RF forbid raw redistribution; the
   registry's `license` column is the audit trail — swap to CC0 before any publish.

---

## 10. Immediate next actions (when we execute)
1. Branch the fork; implement P0 convert changes behind config.
2. Grab **one** Poly Haven CC0 rock (no alpha — easiest) to validate the textured-PBR path end to
   end, then **one** BlenderKit tree to validate the alpha-foliage path.
3. Build one ambientCG terrain texture; render a single hero shot (1 tree + 1 rock on textured
   terrain) and compare side-by-side with `Screenshot from 2026-01-08 23-56-51.png`.
4. If the hero shot holds up, scale to the full set (P3) and re-shoot the `spike/forest_*` views.
