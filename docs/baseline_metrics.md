# Baseline feature metrics — DEMO_REALISM_V2 Phase 0

Produced by `spike/compare.py` (run in `forest3d:egl`). This is the **before** snapshot
the later phases (A→D) must move. Every metric is image-level (ORB/FAST features, spatial
coverage, tiling autocorrelation) — deliberately NOT a VIO/LIO odometry rig (scope decision
in `DEMO_REALISM_V2.md` §0). Re-run after each phase and append a **after** block.

How to reproduce (identical numbers on host or in-container):

```bash
docker run --rm -v "$PWD:/workspace" --entrypoint bash forest3d:egl \
  -c 'cd /workspace && python3 spike/compare.py'
```

Outputs `spike/compare.png` (our hero | reference original, per scene, with metrics).

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
`spike/scenarios_overview.png`; alpine retains rugged relief. Gate met: smooth + no
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

**De-tiling proof — read the autocorr MAP, not the scalar** (`spike/phaseB_detiling_autocorr.png`):
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

## Status of the open items

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
