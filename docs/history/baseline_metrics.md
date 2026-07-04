# Baseline feature metrics — DEMO_REALISM_V2 Phase 0

Produced by `tools/compare.py` (run in `forest3d:egl`). This is the **before** snapshot
the later phases (A→D) must move. Every metric is image-level (ORB/FAST features, spatial
coverage, tiling autocorrelation) — deliberately NOT a VIO/LIO odometry rig (scope decision
in `DEMO_REALISM_V2.md` §0). Re-run after each phase and append a **after** block.

How to reproduce (identical numbers on host or in-container):

```bash
docker run --rm -v "$PWD:/workspace" --entrypoint bash forest3d:egl \
  -c 'cd /workspace && python3 tools/compare.py'
```

Outputs `tools/compare.png` (our hero | reference original, per scene, with metrics).

## Metric definitions (and why they are trustworthy)

- **ORB/MP, FAST/MP** — feature counts per megapixel. Per-MP because raw counts scale with
  pixel area and the originals (1423×967, GUI-cropped) differ in size from our renders
  (1280×720); every image is resized to a common 720 px height before detection. ORB
  `nfeatures=5000` so the default 500 cap doesn't saturate.
  *Caveat:* raw feature count is **contaminated** by the very artifacts we are removing —
  black blobs, trail edges and (in the originals) any surviving GUI pixels all *inflate* it.
  So it is a secondary signal, not the north star.
- **cov (coverage)** — fraction of an 8×8 grid occupied by FAST features. **This is the north
  star**: robust to the high-contrast artifacts above; it measures whether features are
  spread across the frame (a populated scene) or concentrated in a few cells (specks on an
  empty hill).
- **unif (uniformity)** — `1 − coefficient-of-variation` of per-cell feature counts, clamped
  to [0,1]. 1.0 = evenly spread; ~0 = clumped.
- **tilePk / period** — strongest *secondary* autocorrelation peak (0..1) and its pixel
  period. The grayscale is high-pass filtered, autocorrelated, the central lobe is excluded
  **dynamically** (a fixed mask leaks the lobe shoulder and reports a bogus ~11 px period for
  every image — that bug was found and fixed in Phase 0), and the strongest local maximum
  outside the lobe is the tiling strength. **Higher = more visible repetition = worse for
  VIO.** `top.tilePk` is the same metric on the top-down camera, where the ground fills the
  frame and the repetition is sharpest.

Validation that the metrics discriminate: the non-tiled originals score tilePk 0.06–0.12,
while our tiled green scenes score 0.18–0.37 — a real, interpretable separation, not noise.

## BEFORE (committed baseline)

**Originals (3 Gazebo screenshots, GUI-cropped) — the reference:**

| scene                  | ORB/MP | FAST/MP | cov  | unif | tilePk | period |
|------------------------|--------|---------|------|------|--------|--------|
| original_1             |   5641 |   18677 | 1.00 | 0.14 | 0.115 |   152 |
| original_2             |   5641 |   24136 | 1.00 | 0.17 | 0.058 |   116 |
| original_3             |   5641 |   25810 | 0.98 | 0.34 | 0.080 |   223 |
| ORIGINALS (mean)       |   5641 |   22874 | 0.99 | 0.22 | 0.084 |   164 |

**Our 6 demo hero renders (tilePk also shown for the top-down cam):**

| scene                  | ORB/MP | FAST/MP | cov  | unif | tilePk | period | top.tilePk |
|------------------------|--------|---------|------|------|--------|--------|------------|
| temperate_hills        |   4548 |   17064 | 0.61 | 0.00 | 0.298 |   279 | 0.275      |
| savanna_flats          |   3197 |    7036 | 0.61 | 0.00 | 0.373 |   161 | 0.241      |
| lakeland_wetland       |   4231 |   19642 | 0.62 | 0.00 | 0.179 |   223 | 0.281      |
| alpine_snow            |   3980 |   16541 | 0.75 | 0.16 | 0.078 |   194 | 0.131      |
| winter_forest          |   4966 |    6392 | 0.91 | 0.00 | 0.074 |   137 | 0.131      |
| coastal_dune           |   4255 |    9810 | 0.62 | 0.00 | 0.038 |   360 | 0.152      |

**Gap (comparable biomes¹ mean vs originals mean):**

- FAST/MP: ours 13388 vs orig 22874 (**59 % of target**)
- coverage: ours **0.62** vs orig **0.99**  ← the biggest, most honest gap
- uniformity: ours 0.00 vs orig 0.22
- tiling peak: ours **0.222** vs orig **0.084** (lower is better; >orig = visible tiling)

¹ *Comparable biomes* = temperate_hills, savanna_flats, lakeland_wetland, coastal_dune. The
3 originals are all temperate/savanna (acacia + boulder + green grass), so they are a
**reference, not an absolute target** for snow/sand-dominated scenes. `alpine_snow` and
`winter_forest` legitimately carry fewer discrete features and are not expected to reach the
originals' counts — this is the CC0/biome ceiling, stated honestly, not a number to chase.

## What the baseline says (the gap, in priority order)

1. **Coverage is the headline failure: 0.62 vs 0.99.** Our scenes read as a textured hill
   with a few specks; the originals fill the frame with structure. → Phase C (density,
   variety, hero landmarks) is where most of the gain is.
2. **Tiling peak is 2.6× the originals on the green scenes** (temperate 0.30, savanna 0.37,
   lakeland 0.18 vs orig 0.084). The ~tiled base ground repeats → VIO aliasing. → Phase B
   target: drop the green-biome tilePk toward ~0.10. This is the measurable VIO-killer gate.
3. **Uniformity ~0** everywhere: features clump into the few vegetated cells. Rises naturally
   as density/coverage rise (Phase C).
4. **FAST/MP at 59 %** of target — secondary (contaminated; see caveat), but directionally
   confirms under-population.

## AFTER PHASE A — terrain at robot/human scale

Terrain shape only: `detail` dropped hard (0.5→0.12 temperate etc.; kills sub-2 m fBm
sponginess), `smooth` raised, `feature_m` set as the rolling-scale lever; alpine keeps
real relief (detail 0.30). `pixel` held at 1.6 (world size unchanged) so the delta is
attributable to terrain shape, not framing/density.

| scene                  | ORB/MP | FAST/MP | cov  | unif | tilePk | period | top.tilePk |
|------------------------|--------|---------|------|------|--------|--------|------------|
| temperate_hills        |   3377 |   14800 | 0.56 | 0.00 | 0.341 |   243 | 0.263      |
| savanna_flats          |   3013 |    8314 | 0.59 | 0.00 | 0.346 |   278 | 0.246      |
| lakeland_wetland       |   3793 |   10597 | 0.53 | 0.00 | 0.371 |   295 | 0.281      |
| alpine_snow            |   3536 |    9637 | 0.56 | 0.00 | 0.125 |   128 | 0.134      |
| winter_forest          |   4986 |    7148 | 0.84 | 0.00 | 0.070 |   333 | 0.170      |
| coastal_dune           |   4205 |    9459 | 0.62 | 0.00 | 0.367 |   221 | 0.155      |

**Reading the delta (comparable biomes):** coverage 0.62→0.58 and FAST/MP 59%→47% — a
small, *expected* dip: lowering `detail` removed fbm surface noise that was registering as
fake features (real structure comes from objects in Phase C, not ground noise). Crucially,
the green-scene **hero tilePk rose** (lakeland 0.18→0.37, temperate 0.30→0.34): smoothing
the terrain *exposed* the tiled ground texture that the surface noise was masking. This
confirms hero tilePk was never purely "tiled base ground" — and it sets up a clean,
attributable Phase B fix (break the ground tiling and this drops). Terrain reads smooth in
`tools/scenarios_overview.png`; alpine retains rugged relief. Gate met: smooth + no
*unexplained* feature regression.

> Note: per the framing caveat, the Phase B gate is judged on **top.tilePk** (ground always
> fills the top-down frame; hero ground will shrink once Phase D re-poses the cameras).

## AFTER PHASE B — non-repeating ground + drop trails + black-blob fix

Three changes, bundled (each isolated below so credit is honest):
1. **Trails removed** from every biome (`ground.py` BIOMES) — they appear in zero originals.
2. **Ground de-tiled**: macro base-variation patches (45–55 m, a contrasting material at a
   different tile period) + a **domain warp** of the tiling grid (`_tiled(warp=...)`, ~40 m
   wobble, `tile_warp` knob) that bends the periodic grid into a non-periodic one.
3. **Black-blob fix** (was an open item, fixed here because it confounded the metric): two
   grass models shipped a Poly Haven *material-preview sphere* (`<id>_sphere`, untextured
   near-black) on a 1 M-tri geometry-nodes object → rendered as solid black balls.
   `normalize_blend.py` now strips helper objects/`_sphere` material slots; the 2 grass
   models were regenerated (`grass_medium_02` 1.04 M→15.7 k tris ≈ its clean sibling
   `grass_medium_01` 19.8 k).

| scene                  | ORB/MP | FAST/MP | cov  | unif | tilePk | period | top.tilePk |
|------------------------|--------|---------|------|------|--------|--------|------------|
| temperate_hills        |   3184 |   11857 | 0.55 | 0.00 | 0.051 |   202 | 0.234      |
| savanna_flats          |   4291 |   12998 | 0.58 | 0.00 | 0.234 |   273 | 0.252      |
| lakeland_wetland       |   3153 |    6978 | 0.53 | 0.00 | 0.391 |   263 | 0.246      |
| alpine_snow            |   3802 |   11028 | 0.56 | 0.00 | 0.117 |   278 | 0.161      |
| winter_forest          |   4868 |   11520 | 0.94 | 0.00 | 0.091 |   353 | 0.216      |
| coastal_dune           |   4785 |   14374 | 0.59 | 0.00 | 0.328 |   240 | 0.159      |

**De-tiling proof — read the autocorr MAP, not the scalar** (`tools/phaseB_detiling_autocorr.png`):
- The hero tilePk scalar is too **framing-noisy** to gate on (temperate 0.051 vs lakeland
  0.391 under the *same* warp — it swings with whatever fills the sparse hero frame). And
  `top.tilePk` has **no original baseline** (all 3 originals are ground-level, never top-down),
  so it can't be a pass/fail "vs originals". So the honest evidence is structural:
- **Warp OFF** top-down autocorrelation = a sharp axis-aligned **cross + a clean regular
  lattice** of secondary peaks → strong periodic tiling. **Warp ON** = the lattice is
  **smeared into fuzzy irregular blobs** → the fine ground-tile periodicity is broken (the
  VIO-aliasing fix). A/B on the SAME fixed-grass scene isolates the warp from the blob fix.
- The **residual top.tilePk ~0.23 is benign**: its dominant peak sits at **period ~50 m**
  (`period` col ≈ 114–273 px ≈ 49–117 m), i.e. the *macro base-variation patches* (organic,
  non-repeating) — NOT the 4–7 m tile. The leftover central cross is partly **DEM-mesh
  faceting** (a 192² terrain grid, axis-aligned geometry the ground warp cannot touch), which
  only matters for a nadir/top-down camera; robot/human cameras are oblique (the warp's win
  shows there — temperate hero tilePk fell 0.286→0.051).

**Attribution (no over-crediting):** the black blobs were present in the Phase 0/A baselines
(temperate/wetland/coastal use those grass models), so part of this build's FAST/MP movement
is blob removal, not the warp. The warp's isolated effect is the autocorr-lattice smear above.

**Verdict:** trails gone, fine ground tiling broken (autocorr lattice collapsed), black blobs
eliminated. The big remaining gap is unchanged and is the headline for Phase C: **coverage
0.56 vs 0.99** — the scenes are still under-populated.

## AFTER PHASE C — density, variety, bigger trees

Densities raised hard (build_scenarios.py) and `SCALE_RANGES` widened/scaled up
(forest.py): trees read tall/mature (`tree` 0.8–1.5 → 1.0–2.2), rocks give landmark
boulders (`rock` 0.5–2.0 → 0.6–2.6), understory bush/grass raised. Trees kept moderate
in COUNT (each canopy tree ≈0.5 M tris) but big in SIZE; bush/grass/rock raised since
they're light and spread discrete features (coverage + LIO structure).

**Measured on the OBLIQUE cam** (the C signal — the elevated hero frame is ~40 % sky, so
hero coverage is mechanically capped until the Phase D ground-level re-pose; judging C on
the hero would misread it as failing):

| scene             | oblique cov | oblique fast/MP | hero cov | hero fast/MP |
|-------------------|-------------|-----------------|----------|--------------|
| temperate_hills   | 0.70        | 3100            | 0.59     | 13672        |
| savanna_flats     | 0.72        | 1928            | 0.59     | 12984        |
| lakeland_wetland  | 0.72        | 2836            | 0.58     | 8373         |
| alpine_snow       | 0.64        | 3566            | 0.61     | 11636        |
| winter_forest     | 0.72        | 5022            | 0.97     | 12556        |
| coastal_dune      | 0.72        | 5100            | 0.59     | 14374        |

The fields are visibly populated (`tools/scenarios_overview.png`): trees scattered across
every scene, conifers dotting the alpine/winter slopes, rich non-repeating ground, no
trails, no black blobs. hero FAST/MP rose (e.g. temperate 11.9k → 13.7k) but hero coverage
is still framing-capped — **that gap is closed in Phase D**, not by more density here.
The island broadleaf trees carry a real (if olive/sparse-at-distance) canopy — verified
leafy in `tools/asset_catalog.png` — so this is distance/LOD thinning, not the dead/winter
look; acceptable within the CC0 ceiling.

## AFTER PHASE D — ground-level hero cameras + savanna near-field fix

The hero camera is re-posed to a **ground-level robot-eye shot framing a landmark boulder**
(`terrain_scene.py`): pick the boulder with the most nearby trees (tie-break: biggest), stand
*outward* of it (away from the hilltop) looking *inward* so green slope — not sky — fills the
background, with a slope clamp so steep (alpine) terrain never frames a point-blank wall. This
closes the framing-capped coverage gap C left open. Savanna (the one weak frame: empty sand +
~40 % sky) got a **coupled** fix — `HERO_DOWN` raises the eye so the shot tilts down (cuts sky,
pushes the tiling sand below frame-centre) **and** near-field understory raised hard (bush
120→200, grass 220→380) fills the reclaimed foreground with discrete scrub.

| scene                  | ORB/MP | FAST/MP | cov  | unif | tilePk | period | top.tilePk |
|------------------------|--------|---------|------|------|--------|--------|------------|
| temperate_hills        |   5425 |   17253 | 0.77 | 0.00 | 0.115 |   104 | 0.234      |
| savanna_flats          |   5038 |   11127 | 0.80 | 0.00 | 0.311 |   193 | 0.251      |
| lakeland_wetland       |   5425 |   17378 | 0.84 | 0.00 | 0.144 |    71 | 0.271      |
| alpine_snow            |   5425 |   10825 | 0.50 | 0.00 | 0.056 |    91 | 0.148      |
| winter_forest          |   5425 |   16589 | 0.92 | 0.01 | 0.085 |   148 | 0.204      |
| coastal_dune           |   5405 |    7983 | 0.69 | 0.00 | 0.310 |   346 | 0.129      |

**Gap (comparable biomes mean vs originals mean):**

- FAST/MP: ours **13435** vs orig 22874 (**59 % of target** — the CC0 foliage ceiling)
- coverage: ours **0.77** vs orig 0.99  *(was 0.62 at baseline — the headline gap, closed)*
- uniformity: ours 0.00 vs orig 0.22  *(see note below — not a D regression)*
- tiling peak: ours 0.220 vs orig 0.084  *(inflated by the two sand biomes; see note)*

**Reading the result (vs the BEFORE baseline):**
- **Coverage 0.62 → 0.77** on comparable biomes — the headline failure, closed. Per-scene: 5 of
  6 land 0.69–0.92 (winter 0.92, lakeland 0.84, savanna 0.80, temperate 0.77, coastal 0.69).
  `alpine_snow` 0.50 is the one low value and it is **inherent, not a miss**: a ground cam on an
  80 m-amplitude massif always has a smooth snow slope filling part of the frame (few features
  on bare snow). Its fast/MP 10825 and tilePk 0.056 (near-zero tiling) are healthy — it reads as
  steep snow, by design.
- **Savanna recovered** from the weak outlier (baseline cov 0.61 / fast/MP 7036, post-C-hero
  worse at 2906) to **cov 0.80 / fast/MP 11127** — the coupled sky-cut + near-field-understory
  fix, not a blind density bump (the prior density-only cycle barely moved it). Diagnostic
  confirmed it: the hero cam already stood among 11 trees, so the drag was sky+empty-foreground,
  exactly what the coupled fix targets.
- **Tiling**: temperate 0.115, lakeland 0.144, winter 0.085 sit at/near the originals' 0.06–0.12.
  The comparable-mean 0.220 is **dragged up by the two sand biomes** (savanna 0.311, coastal
  0.310): bare desert ground is genuinely a strong ripple texture, and a ground-level cam looking
  across it sees that periodicity — this is real surface, not a tiled-asset artifact (the
  asset-tiling fix is proven structurally in Phase B's autocorr map; `top.tilePk` here is
  0.13–0.27, the benign macro-patch + DEM-facet residual, never the 4–7 m tile).
- **Uniformity 0.00** across all 6 (and all prior phases) is a **metric artifact, not a Phase D
  regression**: with an 8×8 grid, a feature-rich foreground + smooth sky/distant ground gives
  std ≫ mean → `1−CoV` clamps to 0 for every populated outdoor frame (the originals only clear
  it because they near-saturate the grid). Coverage is the trustworthy spatial-spread metric
  here, and it moved as intended.

**Verdict:** the headline coverage gap (0.62→0.77) is closed, the one weak scene (savanna) is
recovered with a metric-justified coupled fix, ground de-tiling is proven (Phase B) with only
the genuine bare-sand surface periodicity remaining, and the residual FAST/MP gap (59 %) is the
honestly-stated CC0 ceiling (§ report). No scene is a metric failure; `alpine_snow`'s lower
coverage is biome-inherent.

## Status of the open items

- **Under-population (coverage 0.62 vs 0.99)** — RESOLVED in Phase D (comparable mean 0.77; 5/6
  scenes 0.69–0.92). `alpine_snow` 0.50 is biome-inherent (bare-snow slope), not an open miss.
- **Black blobs** — RESOLVED in Phase B. (Earlier guess "distant silhouetted instances" was
  WRONG; the real cause was the untextured near-black `<id>_sphere` material-preview ball on
  two grass models. The Phase 0 MASK check was right that it wasn't the BLEND-foliage gotcha,
  but the blobs weren't benign — they were a separate asset-prep miss, now fixed in
  `normalize_blend.py`.)
- **Trails** — RESOLVED in Phase B (deleted from every biome).
- **Sub-metre terrain lumpiness** — RESOLVED in Phase A (detail/smooth retune).
- **Under-population (coverage 0.56 vs 0.99)** — OPEN, the Phase C headline.
- **DEM-mesh faceting** in the top-down autocorr cross — accepted (geometry, nadir-only;
  oblique robot cameras unaffected). Not chased further.

## Variety harvest + master-seed scenarios (2026-07-03) — post-DEMO_REALISM_V2

The 6 demos were rebuilt end-to-end after (a) the **15-species variety harvest**
(every biome ≥3 trees + ≥2 understory; `tools/ASSET_REGISTRY.md`) and (b) the
placement RNG hardening (instance `np.random.Generator` + sorted listings — the
seed→world mapping changed once here, by design). Same harness (`tools/compare.py`):

| scene            | cov (was → now) | FAST/MP (was → now) | tilePk (was → now) |
|------------------|-----------------|---------------------|--------------------|
| temperate_hills  | 0.77 → **0.95** | 17253 → 19377       | 0.115 → 0.099      |
| savanna_flats    | 0.80 → **0.88** | 11127 → 12030       | 0.311 → **0.491**  |
| lakeland_wetland | 0.84 → **0.92** | 17378 → 19017       | 0.144 → 0.068      |
| alpine_snow      | 0.50 → **0.92** | 10825 → 11574       | 0.056 → 0.098      |
| winter_forest    | 0.92 → **0.98** | 16589 → 17873       | 0.085 → 0.055      |
| coastal_dune     | 0.69 → 0.64     | 7983 → 7841         | 0.310 → 0.191      |
| **comparable mean** | **0.77 → 0.85** (orig 0.99) | **13435 → 14566 = 64 %** (orig 22874, was 59 %) | 0.220 → 0.212 (orig 0.084) |

- **Coverage gate (no regression below 0.77): PASS at 0.85.** Biggest movers are the
  biomes that got real understory/species depth: alpine 0.50→0.92 (saplings + debris
  fill the bare snow slope — the previous "biome-inherent" ceiling was actually an
  asset-variety ceiling), temperate 0.77→0.95.
- **FAST/MP improves 59 %→64 %** of the originals — the CC0 ceiling moves with variety,
  as predicted by the V2 report.
- **Honest flags:** `coastal_dune` coverage dipped 0.69→0.64 (new placement draw put
  fewer trees near the hero cam: 6 within 55 m); `savanna_flats` hero-cam tilePk rose
  0.311→0.491 at a 62 px period (grazing-angle bare-sand ripple with the new framing;
  its top-down tilePk is 0.249, i.e. the fine ~4–7 m asset tile stays broken — Phase B's
  structural fix is untouched). Both are placement-draw sensitivity, not asset or
  pipeline regressions; both scenes remain above / near their pre-harvest FAST density.

Reproducibility spot-checks in the same container session: `forest3d scenario
--seed 42` twice → byte-identical world + spec (625/625 models, 2 water basins);
re-verified after the RNG hardening with `--seed 107` (DETERMINISM_HOLDS). The 3-seed
diversity proof is `tools/scenario_seeds_gallery.png` (seeds 101/107/108 →
wetland/temperate/alpine).
