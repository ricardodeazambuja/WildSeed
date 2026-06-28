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

## Open items carried into later phases (not Phase 0 bugs)

- **Black blobs in temperate_hills** (round dark dots): **verified NOT the BLEND-foliage
  gotcha** — every foliage GLB checked is `alphaMode=MASK` (shrub_01 8.8k tris, shrub_03 2.4k,
  grass MASK) and `island_tree_01` is the 519k-tri assembled tree, not a kit piece. Cause is
  likely distant instances silhouetted / a placement-quality issue → diagnose in Phase C.
- **Trails** (the straight tan paths) are present in every scene and in zero originals →
  removed in Phase B.
- **Sub-metre terrain lumpiness** (alpine/winter especially) → smoothed in Phase A.
