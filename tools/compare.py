"""tools/compare.py — Phase 0 metric harness for DEMO_REALISM_V2.

Quantifies the gap between our 6 demo hero renders and the 3 original Gazebo
screenshots using IMAGE-LEVEL feature metrics (this is deliberately NOT a VIO/LIO
odometry rig — scope decision in docs/history/DEMO_REALISM_V2.md §0):

  - ORB + FAST feature counts. Reported per-megapixel (raw counts scale with pixel
    area, so they are not comparable across resolutions). ORB nfeatures is raised to
    5000 so the default 500 cap does not saturate and stop discriminating.
  - Spatial coverage: fraction of an 8x8 grid occupied by FAST features + a
    uniformity score (1 - coefficient-of-variation of per-cell counts, clamped to
    [0,1]). Coverage is the north star: it is robust to the high-contrast artifacts
    (black BLEND blobs, trail edges) that *inflate* raw feature counts as a scene
    gets worse.
  - Tiling autocorrelation peak: the grayscale is high-pass filtered (subtract a
    heavy Gaussian blur) so smooth gradients do not register, then autocorrelated via
    FFT. We report the strongest non-DC peak (0..1, normalized to zero-lag) and its
    pixel period. A strong peak at a fixed offset = visible tiling => VIO aliasing.

Why the care (see advisor notes in DEMO_REALISM_V2 history):
  #1 resolution-normalize or counts are meaningless across 1423x967 originals vs
     1280x720 renders;
  #2 raw counts are contaminated by exactly the artifacts we remove -> lean on
     coverage + tiling, not raw count;
  #3 the 3 originals are temperate/savanna (acacia + boulder + green) -> they are a
     reference, not an absolute target for snow/sand biomes. Gate the relative gap on
     the comparable biomes; snow/sand sit lower by nature (CC0 ceiling).

The Gazebo toolbar (top) + playbar (bottom) are cropped from the originals FIRST, else
GUI corners count as strong features.

Run (in the container, where the metrics gate lives):
  docker run --rm -v "$PWD:/workspace" --entrypoint bash wildseed:egl \\
    -c 'cd /workspace && python3 tools/compare.py'

Outputs:
  tools/compare.png        our hero | reference original, per scene, with metrics
  stdout                   a markdown metric table (originals + 6 scenes + gap)
  --md PATH                also write the table to PATH (e.g. docs/history/baseline_metrics.md)
"""
import argparse
import glob
import os

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import maximum_filter

WS = os.environ.get("WS", os.getcwd())
COMMON_H = 720          # resize every image to this height before detection
GRID = 8                # spatial-coverage grid is GRID x GRID
LOBE_FLOOR = 0.02       # ring-mean threshold that ends the autocorrelation central lobe

# The 3 originals (cropped of GUI). All are temperate/savanna acacia+boulder scenes.
ORIGINALS = sorted(glob.glob(os.path.join(WS, "Screenshot from 2026-*.png")))

# Our 6 demo hero frames + which reference original to pair each with in compare.png.
SCENES = [
    "temperate_hills", "savanna_flats", "lakeland_wetland",
    "alpine_snow", "winter_forest", "coastal_dune",
]
# Biomes whose feature richness is fairly comparable to the originals (green/arid with
# trees + boulders). snow/sand-dominated scenes legitimately sit lower (stated in the
# report, not chased).
COMPARABLE = {"temperate_hills", "savanna_flats", "lakeland_wetland", "coastal_dune"}


# ----------------------------------------------------------------------------- io
def load_rgb(path):
    """Return an HxWx3 uint8 RGB image from a .npy render or an image file."""
    if path.endswith(".npy"):
        a = np.load(path)
        return np.ascontiguousarray(a[:, :, :3].astype(np.uint8))
    bgr = cv2.imread(path)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def crop_gui(img, top=95, bottom=40):
    """Strip the Gazebo toolbar (top) + playbar (bottom) from an original."""
    h = img.shape[0]
    return img[top:h - bottom, :, :]


def to_common(img):
    """Resize to COMMON_H height (preserve aspect) with area interpolation."""
    h, w = img.shape[:2]
    if h == COMMON_H:
        return img
    nw = max(1, int(round(w * COMMON_H / h)))
    return cv2.resize(img, (nw, COMMON_H), interpolation=cv2.INTER_AREA)


# ------------------------------------------------------------------------ metrics
def _gray(img):
    return cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)


def feature_metrics(img):
    """ORB + FAST counts (raw + per-megapixel) and FAST keypoint pixel coords."""
    g = _gray(img)
    mp = (g.shape[0] * g.shape[1]) / 1e6
    orb = cv2.ORB_create(nfeatures=5000)
    orb_kp = orb.detect(g, None)
    fast = cv2.FastFeatureDetector_create()  # default threshold 10, NMS on
    fast_kp = fast.detect(g, None)
    pts = np.array([k.pt for k in fast_kp]) if fast_kp else np.zeros((0, 2))
    return {
        "orb": len(orb_kp), "orb_pmp": len(orb_kp) / mp,
        "fast": len(fast_kp), "fast_pmp": len(fast_kp) / mp,
    }, pts


def coverage_metrics(shape_hw, pts, grid=GRID):
    """Fraction of grid cells occupied by FAST features + a uniformity score."""
    h, w = shape_hw
    counts = np.zeros((grid, grid), dtype=np.int64)
    for x, y in pts:
        gx = min(grid - 1, int(x * grid / w))
        gy = min(grid - 1, int(y * grid / h))
        counts[gy, gx] += 1
    occupied = float((counts > 0).mean())
    mean = counts.mean()
    # uniformity = 1 - coefficient of variation, clamped. 1.0 => features spread
    # evenly across the frame; ~0 => clumped into a few cells.
    uni = 0.0 if mean == 0 else max(0.0, 1.0 - counts.std() / mean)
    return {"coverage": occupied, "uniformity": uni}


def tiling_metrics(img):
    """Strongest secondary autocorrelation peak (0..1) + its pixel period.

    Tiling = periodic repetition: the autocorrelation dips after the central lobe and
    then rises again at the tile period (a true local maximum offset from the centre).
    Smooth/varied content decays monotonically to noise. So we:
      1. high-pass (subtract a heavy Gaussian blur) so smooth gradients don't register;
      2. FFT-autocorrelate, normalize zero-lag to 1;
      3. find the central-lobe radius DYNAMICALLY (ring-mean falls below LOBE_FLOOR) and
         exclude it — a fixed small mask leaks the lobe shoulder and reports a bogus
         ~11 px period for every image (the failure this replaces);
      4. take the strongest *local maximum* outside that lobe -> the tiling peak.

    Validated to separate the non-tiled originals (~0.06-0.12) from our tiled green
    scenes (~0.18-0.37). Phase B target: drop the green-biome peak toward the
    originals' level (<~0.10).
    """
    g = _gray(img).astype(np.float32)
    g = g - cv2.GaussianBlur(g, (0, 0), g.shape[0] / 16.0)  # high-pass
    g -= g.mean()
    F = np.fft.fft2(g)
    ac = np.fft.fftshift(np.fft.ifft2(F * np.conj(F)).real)
    if ac.max() <= 0:
        return {"tiling_peak": 0.0, "tiling_period": 0.0}
    ac = ac / ac.max()
    h, w = ac.shape
    cy, cx = h // 2, w // 2
    Y, X = np.indices((h, w))
    R = np.hypot(Y - cy, X - cx)
    Ri = R.astype(int)
    maxr = min(cy, cx)
    # dynamic central-lobe radius: walk out until the ring mean falls below the floor
    lobe = 4
    while lobe < maxr - 1 and ac[Ri == lobe].mean() > LOBE_FLOOR:
        lobe += 1
    localmax = ac == maximum_filter(ac, size=5)
    cand = (R > lobe) & (R < maxr) & localmax
    if not cand.any():
        return {"tiling_peak": 0.0, "tiling_period": 0.0}
    vals = np.where(cand, ac, -1.0)
    iy, ix = np.unravel_index(int(np.argmax(vals)), vals.shape)
    return {"tiling_peak": float(ac[iy, ix]),
            "tiling_period": float(np.hypot(iy - cy, ix - cx))}


def all_metrics(img_common):
    """All metrics for an already-common-height RGB image."""
    feats, pts = feature_metrics(img_common)
    cov = coverage_metrics(img_common.shape[:2], pts)
    til = tiling_metrics(img_common)
    return {**feats, **cov, **til}


# -------------------------------------------------------------------------- report
def fmt_row(label, m):
    return (f"| {label:<22} | {m['orb_pmp']:6.0f} | {m['fast_pmp']:7.0f} | "
            f"{m['coverage']:.2f} | {m['uniformity']:.2f} | "
            f"{m['tiling_peak']:.3f} | {m['tiling_period']:5.0f} |")


HEADER = ("| scene                  | ORB/MP | FAST/MP | cov  | unif | "
          "tilePk | period |")
SEP = ("|------------------------|--------|---------|------|------|"
       "--------|--------|")


def build_table(orig_metrics, scene_metrics, scene_top_metrics):
    """Return the markdown table lines (originals avg, each scene, gap on comparable)."""
    lines = []
    oa = {k: np.mean([m[k] for m in orig_metrics]) for k in orig_metrics[0]}
    lines.append("**Originals (3 Gazebo screenshots, GUI-cropped) — the reference:**")
    lines.append("")
    lines.append(HEADER)
    lines.append(SEP)
    for i, m in enumerate(orig_metrics):
        lines.append(fmt_row(f"original_{i + 1}", m))
    lines.append(fmt_row("ORIGINALS (mean)", oa))
    lines.append("")
    lines.append("**Our 6 demo hero renders (tiling also shown for the top-down cam, "
                 "where the ground fills the frame and the ~tile period is sharpest):**")
    lines.append("")
    lines.append(HEADER + " top.tilePk |")
    lines.append(SEP + "------------|")
    for name in SCENES:
        m = scene_metrics.get(name)
        if m is None:
            continue
        tm = scene_top_metrics.get(name, {})
        row = fmt_row(name, m)
        row += f" {tm.get('tiling_peak', float('nan')):.3f}      |"
        lines.append(row)
    lines.append("")
    # gap on the comparable biomes (north-star metrics): coverage + fast/MP
    comp = [scene_metrics[n] for n in SCENES if n in COMPARABLE and n in scene_metrics]
    if comp:
        ca = {k: np.mean([m[k] for m in comp]) for k in comp[0]}
        lines.append("**Gap (comparable biomes mean vs originals mean):**")
        lines.append("")
        lines.append(f"- FAST/MP: ours {ca['fast_pmp']:.0f} vs orig {oa['fast_pmp']:.0f} "
                     f"({100 * ca['fast_pmp'] / oa['fast_pmp']:.0f}% of target)")
        lines.append(f"- coverage: ours {ca['coverage']:.2f} vs orig {oa['coverage']:.2f}")
        lines.append(f"- uniformity: ours {ca['uniformity']:.2f} vs orig {oa['uniformity']:.2f}")
        lines.append(f"- tiling peak: ours {ca['tiling_peak']:.3f} vs orig "
                     f"{oa['tiling_peak']:.3f} (lower is better; >orig => visible tiling)")
    return lines, oa


# --------------------------------------------------------------------- compare.png
def _font(sz):
    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", sz)
    except Exception:
        return ImageFont.load_default()


def panel(img_common, title, m, pw, ph):
    im = Image.fromarray(img_common).convert("RGB")
    im.thumbnail((pw, ph))
    c = Image.new("RGB", (pw, ph), (24, 28, 34))
    c.paste(im, ((pw - im.width) // 2, (ph - im.height) // 2))
    d = ImageDraw.Draw(c)
    f = _font(22)
    fs = _font(16)
    d.rectangle([6, 6, 14 + d.textlength(title, font=f), 36], fill=(0, 0, 0))
    d.text((10, 8), title, fill=(255, 255, 255), font=f)
    if m is not None:
        cap = (f"FAST/MP {m['fast_pmp']:.0f}  cov {m['coverage']:.2f}  "
               f"unif {m['uniformity']:.2f}  tilePk {m['tiling_peak']:.3f}")
        d.rectangle([6, ph - 30, 14 + d.textlength(cap, font=fs), ph - 6],
                    fill=(0, 0, 0))
        d.text((10, ph - 28), cap, fill=(220, 230, 120), font=fs)
    return c


def build_compare_png(scene_imgs, scene_metrics, orig_imgs, orig_metrics, outfile):
    """Grid: one row per scene = [our hero | reference original], with metrics."""
    pw, ph = 720, 405
    rows = len(SCENES)
    G = Image.new("RGB", (2 * pw, rows * ph), (16, 18, 22))
    for r, name in enumerate(SCENES):
        if name in scene_imgs:
            G.paste(panel(scene_imgs[name], f"ours: {name}", scene_metrics.get(name),
                          pw, ph), (0, r * ph))
        oi = r % len(orig_imgs)
        G.paste(panel(orig_imgs[oi], f"original_{oi + 1}", orig_metrics[oi], pw, ph),
                (pw, r * ph))
    G.save(outfile)


# --------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", default=None, help="also write the table to this path")
    ap.add_argument("--frames", default=os.path.join(WS, "frames"))
    args = ap.parse_args()

    if not ORIGINALS:
        raise SystemExit(
            "no originals found (Screenshot from 2026-*.png): the upstream "
            "Forest3D reference screenshots are not distributed with WildSeed "
            "(gitignored); drop them in the repo root (or set WS) to compare")

    # originals: crop GUI -> common height -> metrics
    orig_imgs, orig_metrics = [], []
    for p in ORIGINALS:
        ic = to_common(crop_gui(load_rgb(p)))
        orig_imgs.append(ic)
        orig_metrics.append(all_metrics(ic))

    # our scenes: hero (metrics + image) and top-down (tiling only)
    scene_imgs, scene_metrics, scene_top_metrics = {}, {}, {}
    for name in SCENES:
        hp = os.path.join(args.frames, f"scn_{name}_cam_hero.npy")
        if os.path.exists(hp):
            ic = to_common(load_rgb(hp))
            scene_imgs[name] = ic
            scene_metrics[name] = all_metrics(ic)
        tp = os.path.join(args.frames, f"scn_{name}_cam_top.npy")
        if os.path.exists(tp):
            scene_top_metrics[name] = tiling_metrics(to_common(load_rgb(tp)))

    lines, _ = build_table(orig_metrics, scene_metrics, scene_top_metrics)
    table = "\n".join(lines)
    print(table)

    out_png = os.path.join(WS, "tools", "compare.png")
    build_compare_png(scene_imgs, scene_metrics, orig_imgs, orig_metrics, out_png)
    print(f"\nwrote {out_png}")

    if args.md:
        with open(args.md, "w") as f:
            f.write("# Baseline feature metrics (DEMO_REALISM_V2 Phase 0)\n\n")
            f.write(table + "\n")
        print(f"wrote {args.md}")


if __name__ == "__main__":
    main()
