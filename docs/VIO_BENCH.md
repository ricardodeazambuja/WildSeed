# VIO benchmarking for generated worlds

`tools/vio_bench.py` answers the question that matters when you generate a random world
for Visual-Inertial Odometry testing: **will VIO actually work here, or will its front-end
mis-associate features and drift?**

## Why feature count is the wrong metric

A VIO front-end continuously **acquires new landmarks** as the robot moves and old ones
leave the field of view, then **associates** them across frames. It fails two ways, and
*neither is about how many features there are*:

1. **Featureless** — nothing to track → the estimator coasts on the IMU and drifts.
2. **Perceptual aliasing** — plenty of features, but many are **indistinguishable to the
   descriptor** (ORB/FAST) and lie **close enough** that the matcher pairs the wrong ones.
   Those false correspondences inject inconsistent geometric constraints → drift or
   divergence. Repetitive / self-similar ground (gravel, ripples, tiles, dense foliage)
   is the classic cause, and it is the dominant **simulator**-VIO failure mode.

"Identical" means identical *to the descriptor's discriminative power*, not pixel-identical.
A gravel field can be **feature-rich and hostile to VIO at the same time**.

### What the other metrics miss

| metric | what it sees | why it misses aliasing |
|---|---|---|
| FAST/ORB count (`vio_exp.py`) | abundance | a field of look-alike pebbles scores *high* |
| high-frequency energy | texture sharpness | sharp ≠ distinctive |
| tiling autocorrelation | **periodic** repetition | non-periodic gravel has low autocorrelation yet many confusable descriptors |
| KLT track length (`vio_seq.py`) | local temporal persistence | KLT is a *local* tracker — it follows a patch even when it is one of a thousand look-alikes; long tracks do **not** rule out aliasing |

`vio_bench.py` instead measures whether the texture is **self-distinguishing under motion**.

## What it measures

Renders the real rig camera (640×480, 57° FOV) along a **canonical, deterministic
translation + yaw trajectory** over the current `models/` world, then matches ORB
descriptors between consecutive frames and reports:

| metric | meaning | direction |
|---|---|---|
| `ORB/fr` | features detected per frame | context |
| `putative` | matches surviving Lowe's ratio test, per pair | higher better |
| `ratio_reject` | fraction of candidate matches **killed** by the ratio test — a direct **ambiguity meter** (2nd-nearest descriptor almost as close as the 1st) | **lower better** |
| `inlier_ratio` | fraction of putative matches geometrically consistent under **essential-matrix RANSAC** (known intrinsics) — the front-end's true association quality | **higher better** |
| `inliers/pair` | absolute reliable correspondences (constraints VIO actually gets) | higher better |
| `self_ambiguity` | within one frame, fraction of features with a near-duplicate descriptor elsewhere in the same frame | lower better |

The essential-matrix inlier ratio is the headline: a **high feature count with a low
inlier ratio is the aliasing trap** — feature-rich but confusable.

## How to read it (heuristic thresholds)

| verdict | condition |
|---|---|
| **GOOD** | `inlier_ratio ≥ 0.65` and `inliers/pair ≥ 100` and `ratio_reject ≤ 0.85` |
| **MARGINAL** | `ratio_reject > 0.85` **or** `inliers/pair < 100` — ground strongly ambiguous; VIO viable but **leaning on landmarks** |
| **ALIASING RISK** | `inlier_ratio < 0.5` (wrong matches survive) **or** `inliers/pair < 40` (aliasing-driven starvation) **or** `self_ambiguity > 0.15` (hard duplicates) |
| INSUFFICIENT | too few matches — near-featureless |

### How aliasing actually manifests (learned from the savanna + gravel renders)

The intuitive picture — "repeated ground → identical descriptors → they get matched to
each other" — is **not** how it usually shows up in a physically-lit sim. Per-fragment
lighting, normal maps, ambient occlusion and perspective **break tile-to-tile descriptor
identity**, so `self_ambiguity` (bit-identical duplicates) rarely fires even over
deliberately periodic ground viewed near-nadir. Instead:

- **`ratio_reject` is the ambiguity gauge.** It rose monotonically with ground
  self-similarity across the tests: **0.50** (mixed scene) → **0.80** (savanna ground) →
  **0.92** (near-nadir gravel). High ratio_reject means Lowe's test is *rejecting* the
  ambiguous ground matches — the ground contributes few confident correspondences.
- **VIO is then carried by distinctive LANDMARKS** (trees, rocks). In the nadir-gravel viz
  the verified matches sit almost entirely on a tree and its shadow; the gravel field is
  blank. So the real failure mode is **aliasing-driven starvation**: high `ratio_reject`
  **and** few surviving `inliers/pair` — which happens in **landmark-sparse** worlds.

**Practical rule:** VIO robustness in these worlds depends on **landmark density**, not
ground texture. Watch `ratio_reject` (is the ground ambiguous?) *together with*
`inliers/pair` (do enough reliable matches survive anyway?). The `--viz` is the tie-breaker:
coherent parallel green flow = good; matches only on landmarks over a blank ambiguous ground
= starvation-prone.

These are **heuristics, not a certified gate**. To calibrate, run the same metric on frames
from a real VIO dataset (EuRoC / TUM-VI) and compare — a world scoring near real-data
numbers is trustworthy; far below is a red flag. The definitive test remains an end-to-end
VIO run (OpenVINS / VINS-Fusion) on a recorded flight with ground-truth ATE; `vio_bench.py`
is the fast, per-world screen that predicts it.

## Worked example: what actually improves the score

Measured with this tool (`tools/vio_clutter_exp.py`) — same terrain, same de-tiled patchy
ground, **only the placement density varied**, benchmarked at the 12 m drone pose:

| world | `ratio_reject` (ambiguity) | **`inliers/pair`** (confident matches) |
|---|---|---|
| bare ground | 0.80 | **200** |
| + trees | 0.60 | **417** |
| + full clutter (trees/rocks/bushes/grass) | 0.46 | **604** |

Adding **distributed distinct objects tripled the confident matches and halved the
ambiguity** — with the ground *texture unchanged*. The `--viz` confirms it: bare gives only
a thin near-field ground band (smooth mid/far ground contributes nothing); full-clutter
fills the frame with matches along the treeline and the ground.

**Takeaway — how to improve a world's VIO score:**

- **Do:** raise the density of **distinct landmarks / ground clutter** (trees, rocks,
  bushes, and — ideally — dense scattered pebbles/tussocks/debris), especially so open
  areas aren't landmark-starved. This is a **placement/generation** change.
- **Don't:** chase crisper or higher-frequency *ground texture*. Measured to raise feature
  *count* without adding confident matches — uniform micro-texture (e.g. gravel) stays
  ambiguous (`ratio_reject` up to 0.92) and the ratio test discards it.
- **Watch:** `inliers/pair` (up) and `ratio_reject` (down) as you add structure; verify with
  the `--viz`. Caveat: even bare ground scored GOOD at 12 m (near-field ground + horizon
  carry it) — the landmark benefit grows at higher altitude / faster motion / low-texture
  biomes, so stress those with `--agl`/`--step`/`--pitch`.

## Usage

Run inside `wildseed:egl` (GPU), after a world is built in `models/`
(`wildseed scenario …`, `tools/build_scenarios.py`, or `tools/vio_exp.py`):

```bash
# benchmark the current world
python3 tools/vio_bench.py --tag myworld

# A/B two ground materials on the same terrain+placement, with a match visualization
python3 tools/vio_bench.py --ground-modes patchy,uniform_t1 --biome desert --viz

# analyze the ground region only (isolate the texture) and stress rotation
python3 tools/vio_bench.py --region ground --yaw-amp-deg 8 --tag stress
```

Key flags: `--frames`, `--step` (m/frame forward), `--yaw-amp-deg`, `--agl`, `--region
full|ground` (whole frame = realistic world benchmark; ground = isolates the texture),
`--orb`, `--ratio` (Lowe), `--viz`. Deterministic: same world + args → same trajectory →
same numbers.

Outputs: a printed table, `frames/vio_bench_<tag>.json`, and (with `--viz`) an
inlier-match image `frames/vio_bench_<tag>_matches.png` (green = geometrically-verified
matches, i.e. the correspondences VIO can trust).

## Companion tools

- `tools/vio_exp.py` — per-frame ground-region feature *density* (FAST/coverage/tiling/HF).
- `tools/vio_seq.py` — temporal KLT *track length* (persistence; see the caveat above).
- `terrain_scene.py` hooks: `VIO_CAMS=1` (drone+ground cams), `VIO_TRAJ="…"` (one camera
  per pose → whole trajectory in a single gz session).
