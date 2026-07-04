# Realistic demos — development plan

Goal: bring the shipped demo scenarios up to the realism/variety of the upstream
screenshots (`Screenshot from 2026-01-*.png`), which were rendered from **commercial**
assets we cannot ship (Maxtree Plant Models Vol. 60 + Quixel Megascans — see
`tools/ASSET_REGISTRY.md`). We match the *look* with assets that are reproducible for
every user, and keep nicer non-redistributable assets for local-only hero renders.

The realism gap is **variety**, not the pipeline. Today every scenario uses only
1–2 tree species, 3 rocks, and `bush:0` — the understory is empty.

---

## 1. The binding constraint: reproducibility by *credentials*, not license

A shipped demo asset must satisfy one of:
- **(A) credential-free fetch** — Docker pulls it by pinned ID over a public API, no login; or
- **(B) generated in-container** — procedural, zero download; or
- **(C) re-hosted by us** — we mirror a CC0 asset to a pinned GitHub Release and fetch from there.

License is *necessary* (we may only re-host/ship CC0) but not the gate — even a paid
asset would qualify for (A) if it had a credential-free pinned download, which it doesn't.

| tier | source | mechanism | use |
|------|--------|-----------|-----|
| **Reproducible** | Poly Haven, ambientCG | (A) fetch-by-ID, CC0, no auth | rocks, ground textures, hero trunks/veg |
| **Reproducible** | Sapling Tree Gen, geometry-nodes grass | (B) in-container, output owned → CC0 | dense ground cover, understory mass, windswept trees |
| **Reproducible** | ffish.asia / floraZia (Sketchfab) | (C) **re-host our CC0 picks** to a pinned Release | real plant/grass/shrub species variety |
| **Local-only** | Megascans, BlenderKit-RF, recovered Maxtree | none — license forbids re-host / account-gated | the user's own nicer renders; **never** in a shipped demo or a reproducible screenshot |

**Resolved decision (re-host):** ffish.asia is CC0 but Sketchfab downloads are
account-gated + ~50/day rate-limited → cannot be Docker-fetched per-user. We will
**mirror ~20–40 curated CC0 picks to a pinned GitHub Release** (`forest3d-assets-vN`)
and Docker fetches from there. Legal under CC0; it is us re-hosting, accepted on
2026-06-28. Each re-hosted asset keeps its source URL + CC0 note in the manifest and
`ASSET_REGISTRY.md`.

**Screenshot provenance rule (enforces "100% reproducible"):**
- Every README / demo screenshot is rendered from the **reproducible tier only**.
- Any hero render that uses a local-only asset is labelled *"illustrative — requires
  assets you supply"* and is kept out of the demo gallery.

---

## 2. Asset architecture

### 2.1 `assets/manifest.yaml` — single source of truth
One file drives both the local harvest and the Docker freeze. Per asset:
`id, category, source (polyhaven|ambientcg|release|procedural), ref (poly id / release
filename / generator script), resolution, sha256, license, scale_hint, biomes[]`.
The fetcher, the normalizer, and the repro test all read this. Checksums make "frozen"
real — a changed upstream asset fails the hash, not silently drifts.

### 2.2 Fetch tooling (extend what exists)
- `tools/fetch_polyhaven.py` — already credential-free CC0 fetch-by-ID. Keep; drive from manifest.
- `tools/fetch_ambientcg.py` — analogous, for ground PBR packs (already used ad hoc; formalize).
- `tools/fetch_release.py` — **new**: pull our pinned `forest3d-assets-vN` tarball
  (the ffish.asia CC0 picks) from the GitHub Release, verify sha256, unpack to `Blender-Assets/`.
- `tools/harvest_sketchfab.py` — **new, LOCAL/maintainer-only**: download a curated
  ffish.asia model list via the user's Sketchfab token. Used **once** by us to build the
  Release tarball; never run by end users. Output then uploaded as `forest3d-assets-vN`.

### 2.3 Procedural generators (in-container, zero download)
- `tools/gen_grass.py` — Blender geometry-nodes grass/sedge clumps → glb. Several
  silhouettes (fine turf, tall tussock, marram-style blades). Output CC0.
- `tools/gen_tree_sapling.py` — Sapling Tree Gen presets for windswept/coastal +
  generic broadleaf/conifer fillers → glb. Output CC0.
  > Procedural carries zero licensing/repro risk and is the most reliable ground-cover
  > mass. Prefer it for dense filler; reserve photoscanned picks for hero specimens.

### 2.4 Normalization (reuse)
All assets (fetched or generated) go through `tools/import_gltf.py`:
recenter, base→z0, foliage alpha→`Math:GreaterThan(0.5)`→MASK (Blender-4.2 EEVEE-Next
gotcha — see memory `blender42-gltf-mask-foliage`), nor/rough downscale. Then
`forest3d convert -c configs/realism.yaml`.
> Budget for ffish.asia variance: 3k crowd-sourced scans differ wildly in scale/poly/
> material. **Curate a small set per biome and hand-check each** (scale, upright, poly
> budget, MASK render on GPU) — do not bulk-import.

### 2.5 Docker freeze
- Add a build (or first-run) step that runs the manifest-driven fetch with everything pinned:
  Poly Haven IDs+resolution+sha256, the `forest3d-assets-vN` Release tag+sha256.
- **Pin `gz-harmonic`** to an explicit apt version (currently unpinned in `docker/Dockerfile`).
- Blender **4.2.3 already pinned** and load-bearing for the foliage-MASK behavior — keep it.
- Models stay gitignored/regenerable; the manifest + scripts are the reproducible recipe.

---

## 3. Per-biome species palettes (6 demos)

Keep the existing 5 (enriched) + add the coastal/Mediterranean dune that matches the
upstream theme. Each demo gains a **3-layer structure**: canopy (trees), understory
(shrubs/bushes — currently empty), ground cover (grass/herb clumps + flowers).

| # | demo | canopy | understory | ground cover | rock/ground |
|---|------|--------|-----------|--------------|-------------|
| 1 | **Temperate hills** | 2–3 broadleaf (island_tree + sapling variants) | shrubs (ffish picks) | turf + wildflowers (gen_grass + ffish) | boulders; grassland patchy |
| 2 | **Savanna flats** | sparse acacia | dry scrub | tussock/dry grass tufts | many boulders; desert patchy |
| 3 | **Lakeland wetland** | willow-ish broadleaf near shore | reeds/sedges (ffish) | wet grass + shore plants | few rocks; grassland + per-basin water |
| 4 | **Alpine snow** | multiple conifers | snow-laden low shrub | sparse snow grass | many exposed boulders; snow patchy |
| 5 | **Winter forest** | bare broadleaf + conifer | dead trunks, low shrub | snow grass tufts | rocks; snow patchy |
| 6 | **Coastal dune** *(new)* | windswept/agave (sapling + ffish) | rockrose / dune shrub | marram grass (gen_grass) + dune herbs | coastal boulders; sand patchy |

Placement uses the existing `generate` density knobs plus new populated `bush`/`grass`
categories. Slope/elevation-aware and clumped placement is **Phase 4** (deferred — see below).

---

## 4. Build sequence (cheapest visible win first)

**Phase 0 — Asset harvest + manifest (foundation).**
Author `assets/manifest.yaml`; curate ~20–40 ffish.asia CC0 picks (grasses/shrubs per
biome) + Poly Haven rocks/trees; build & upload `forest3d-assets-v1`; wire
`fetch_release.py`. Add `gen_grass.py` + `gen_tree_sapling.py`. Normalize + convert all.

**Phase 1 — Populate the understory (biggest realism jump, lowest cost).**
Today's scenarios are `bush:0` with no ground cover. Just adding procedural ground cover +
a few understory species across the existing 5 demos is the largest realism gain, 100%
reproducible, zero new licensing. Do this before anything fancy. Update
`build_scenarios.py` densities to use the new `bush`/`grass` categories.

**Phase 2 — Per-biome palettes + the coastal demo.**
Apply the §3 table: per-demo species constraints (extend the builder's variant-stashing),
add the Coastal dune scenario, tune densities. Update `docs/SCENARIOS.md` recipes.

**Phase 3 — Render + gallery.**
Multi-cam per demo (oblique + top + one ground-level hero), reproducible tier only.
Regenerate `tools/scenarios_gallery.png` + README section. Optionally one local-only
hero render, clearly labelled illustrative.

**Phase 4 — Placement realism (deferred; bigger lift, must not gate Phase 1).**
Clumping/clustering instead of uniform random; slope-aware (no trees on cliffs);
elevation/water-aware (shore plants near water, snow grass only above snowline);
canopy-vs-ground-cover layering at different densities. Fold into `forest3d generate`.

---

## 5. Verification — test the actual claim

The repro claim is *"100% reproducible with no per-user credentials."* A test on the
maintainer's machine (assets cached, full network, Sketchfab token present) **falsely
passes**. Real test:
- fresh environment, **no cached assets**, **no credentialed network** (no Sketchfab token);
- only credential-free sources reachable (Poly Haven API + our GitHub Release);
- `docker build` → run each §3 recipe → assets resolve by sha256 → render each scenario.

Per-asset gate (the existing §6/§7 checks in `ASSET_REGISTRY.md`): poly/size budget,
convex-hull/cylinder collision, foliage renders MASK on GPU (not llvmpipe), upright, base
at z0. Log every shipped asset in the `USED` table with source + license + sha256.

---

## 6. Risks
- **ffish.asia scan variance** — scale/poly/material inconsistency; mitigate by curating
  small + hand-checking, leaning procedural for mass.
- **Release re-host maintenance** — a pinned `forest3d-assets-vN` is ours to keep alive;
  bump the version + checksums when the pick set changes.
- **Procedural realism ceiling** — geo-nodes grass/Sapling are good filler but not
  photoreal hero specimens; pair with photoscanned picks for foreground.
- **Render reproducibility** — GPU vs llvmpipe changes foliage MASK; document the
  `forest3d:egl` + `--gpus all` requirement for matching the gallery.

## 7. Local-only tier (the user's nicer renders)
You keep Megascans / BlenderKit-RF / the recovered Maxtree assets **locally** for your own
experimentation and any illustrative hero shots. They are never fetched by Docker, never
in a shipped demo recipe, and never in a reproducible gallery image. A `Blender-Assets/
_local_only/` dir (gitignored) holds them; the manifest does not list them.
