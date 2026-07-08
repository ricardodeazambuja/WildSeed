#!/usr/bin/env python3
"""VIO data-association benchmark for WildSeed-generated worlds.

WHAT IT MEASURES (and why it's different from feature count)
-----------------------------------------------------------
A VIO front-end must continuously acquire NEW landmarks as the robot moves and then
correctly ASSOCIATE them across frames. It fails in two ways, neither about feature
*count*:
  (1) featureless -> nothing to track -> drift on IMU;
  (2) PERCEPTUAL ALIASING -> plenty of features, but many are indistinguishable to the
      descriptor (ORB/FAST) and lie close enough that the matcher associates the WRONG
      ones -> false correspondences -> drift / divergence. This is the dominant
      simulator-VIO failure mode, and repeated/self-similar ground texture (gravel,
      ripples, tiles, foliage) is its classic cause.

Feature-count, high-frequency energy, tiling-autocorrelation and KLT track-length all
MISS aliasing: KLT is a local tracker (follows a patch even when it is one of a thousand
look-alikes), and a non-periodic gravel field has low autocorrelation yet swarms of
mutually-confusable descriptors. This tool instead asks the question that predicts
VIO data-association failure: *is the texture self-distinguishing UNDER MOTION?*

HOW
---
Renders the real sensor-rig camera (640x480, 57 deg FOV; core/rig.py) along a canonical,
deterministic translation+yaw trajectory over the CURRENT world in models/ (whatever any
generation path produced), then, per consecutive frame pair, matches ORB descriptors and
reports:

  putative/frame   mean # matches surviving Lowe's ratio test (raw matchability)
  ratio_reject     fraction of candidate matches KILLED by the ratio test == a direct
                   AMBIGUITY meter: high => 2nd-nearest descriptor almost as close as the
                   1st => confusable features (aliasing).
  inlier_ratio     fraction of putative matches that are geometrically consistent under an
                   essential-matrix RANSAC (known intrinsics). LOW => the front-end is
                   forming many false associations == the VIO-breaking signal.
  inliers/frame    absolute # of reliable correspondences (constraints VIO actually gets).
  self_ambiguity   within a single frame, fraction of features with a near-duplicate
                   descriptor elsewhere in the SAME frame (independent aliasing view).

INTERPRETATION (guidance, not a hard gate -- calibrate against a real dataset, below)
  GOOD:     inlier_ratio>=0.65 and inliers/pair>=100 and ratio_reject<=0.85.
  MARGINAL: ratio_reject>0.85 or inliers/pair<100 -- ground strongly ambiguous; VIO viable
            but LEANING ON LANDMARKS (trees/rocks); risky if a world is landmark-sparse.
  ALIASING RISK: inlier_ratio<0.5 (wrong matches survive) OR inliers/pair<40 (aliasing-
            driven starvation) OR self_ambiguity>0.15 (hard duplicate descriptors).
  KEY EMPIRICAL FINDING: in these physically-lit worlds, self-similar ground rarely makes
  bit-identical descriptors (lighting/normals/AO/perspective break tile identity), so
  aliasing shows up as the Lowe test REJECTING ground matches -> `ratio_reject` is the
  ambiguity gauge (0.5 mixed -> 0.8 ground -> 0.92 nadir gravel), and the ground then adds
  few confident matches. VIO robustness therefore hinges on LANDMARK DENSITY, not ground
  texture. Read the --viz: coherent parallel flow = good; matches only on landmarks with a
  blank ambiguous ground = starvation-prone. A real end-to-end VIO+ATE run is the arbiter.
These thresholds are heuristic. To anchor them, run this tool's metric on frames from a
real VIO dataset (EuRoC / TUM-VI) with `frames_from_dir()` and compare.

USAGE (inside wildseed:egl, GPU)
  # benchmark the world currently built in models/ :
  python3 tools/vio_bench.py --tag myworld
  # A/B two ground materials on the same terrain+placement:
  python3 tools/vio_bench.py --ground-modes patchy,uniform_t1 --biome desert
  # knobs:
  python3 tools/vio_bench.py --frames 14 --step 0.6 --yaw-amp-deg 8 --region full
  # option d2 — benchmark a gz <heightmap> instead of the mesh ground:
  python3 tools/vio_bench.py --heightmap dem/hm_d2.png,60,0.35 --agl 2 --pitch 0.35 --step 2.0
Outputs: printed table, frames/vio_bench_<tag>.json, frames/vio_bench_<tag>_matches.png.

Assumes terrain+placement already built (e.g. via `wildseed scenario` / build_scenarios /
vio_exp.py). `--ground-modes` rebuilds only the ground material between runs. Deterministic:
same world + same args -> same trajectory -> same numbers.
"""
import argparse
import json
import math
import os
import subprocess

import numpy as np
import cv2

WS = os.environ.get("WS", os.getcwd())
CLI = ["python3", "-m", "wildseed.cli.main"]
FR = os.path.join(WS, "frames")
OBJ = os.path.join(WS, "models", "ground", "mesh", "terrain.obj")


# ---------------------------------------------------------------- geometry ----
def read_terrain(obj_path):
    """Return (verts Nx3, extent_m, center_xy). Ground z looked up by nearest vertex."""
    vs = []
    with open(obj_path) as f:
        for line in f:
            if line.startswith("v "):
                p = line.split()
                vs.append((float(p[1]), float(p[2]), float(p[3])))
    v = np.asarray(vs, np.float32)
    ext = float(max(v[:, 0].ptp(), v[:, 1].ptp()))
    return v, ext, (float(v[:, 0].mean()), float(v[:, 1].mean()))


def terrain_z(verts, x, y):
    d = (verts[:, 0] - x) ** 2 + (verts[:, 1] - y) ** 2
    return float(verts[int(d.argmin()), 2])


def read_heightmap(spec, grid=160):
    """Option d2: derive (verts, extent, center) from a gz heightmap PNG so the same
    trajectory/z-lookup machinery works without a WildSeed mesh. spec = 'PNG,EXTENT_m,Z_m'.
    Image is north-up (gz): row 0 = +Y edge, col 0 = -X edge."""
    from PIL import Image
    png, ext_s, z_s = spec.split(",")
    ext, zmax = float(ext_s), float(z_s)
    hm = np.asarray(Image.open(png).convert("L"), np.float32) / 255.0 * zmax
    n = hm.shape[0]
    half = ext / 2.0
    idx = np.linspace(0, n - 1, grid).astype(int)
    vs = []
    for r in idx:
        y = half - (r / (n - 1)) * ext
        for c in idx:
            x = -half + (c / (n - 1)) * ext
            vs.append((x, y, float(hm[r, c])))
    return np.asarray(vs, np.float32), ext, (0.0, 0.0)


def trajectory(verts, ext, n, step, agl, pitch, yaw_amp_deg, yaw_period):
    """Canonical benchmark path: start near -X edge, translate +X (forward look dir) so
    features flow through and out of frame (forcing re-acquisition), with a sinusoidal yaw
    oscillation to stress rotation-driven matching. Terrain-following AGL. Deterministic."""
    x0 = -0.32 * ext
    poses = []
    for i in range(n):
        x = x0 + i * step
        y = 0.0
        z = terrain_z(verts, x, y) + agl
        yaw = math.radians(yaw_amp_deg) * math.sin(2 * math.pi * i / max(yaw_period, 1))
        poses.append((x, y, z, pitch, yaw))
    return poses


def intrinsics(w, h, fov):
    fx = (w / 2.0) / math.tan(fov / 2.0)
    return np.array([[fx, 0, w / 2.0], [0, fx, h / 2.0], [0, 0, 1.0]], np.float64)


# ----------------------------------------------------------------- render ----
def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        print("ERR", " ".join(cmd[:6]), (r.stderr or "")[-300:], flush=True)
    return r


def render_trajectory(poses, fov):
    """Render all poses in ONE gz session (one vio_cam_<i> per pose). Returns list of RGB
    frames (uint8, H x W x 3), None for any that failed to capture."""
    traj = ";".join(f"{x:.4f},{y:.4f},{z:.4f},{p:.5f},{ya:.5f}" for (x, y, z, p, ya) in poses)
    # HEIGHTMAP mode (option d2) renders a bare gz <heightmap>; don't graft forest placement.
    env = dict(os.environ, VIO_TRAJ=traj, VIO_FOV=str(fov))
    env["FOREST"] = "0" if os.environ.get("HEIGHTMAP") else "1"
    run(["python3", f"{WS}/tools/terrain_scene.py"], env=env)
    cams = [f"vio_cam_{i}" for i in range(len(poses))]
    # stale per-cam captures from a PREVIOUS run must not survive: if gz fails
    # to load (e.g. a bad world), the loop below would silently re-score the
    # old frames as if they were this run's (measured failure mode).
    for c in cams:
        try:
            os.remove(f"{FR}/{c}.npy")
        except FileNotFoundError:
            pass
    g = subprocess.Popen(
        ["gz", "sim", "-s", "-r", "--headless-rendering", f"{WS}/worlds/terrain_scene.world"],
        stdout=open(f"{FR}/gz_bench.log", "w"), stderr=subprocess.STDOUT)
    try:
        run(["python3", f"{WS}/tools/capture_cams.py", ",".join(cams)], timeout=240)
    finally:
        g.terminate()
        try:
            g.wait(timeout=10)
        except subprocess.TimeoutExpired:
            g.kill()
    frames = []
    for c in cams:
        p = f"{FR}/{c}.npy"
        if os.path.exists(p):
            a = np.load(p)
            frames.append((a[..., :3] if a.shape[-1] == 4 else a).astype(np.uint8))
        else:
            frames.append(None)
    if all(f is None for f in frames):
        raise SystemExit("no frames captured — gz failed to render (bad world? "
                         f"duplicate model names?). See {FR}/gz_bench.log")
    return frames


# ---------------------------------------------------------------- metrics ----
def _region(gray, region):
    if region == "ground":
        return gray[int(0.40 * gray.shape[0]):, :]
    return gray


def da_metrics(frames, K, region="full", orb_n=1500, ratio=0.75, viz_path=None):
    """Descriptor-matchability / aliasing metrics across the frame sequence."""
    orb = cv2.ORB_create(nfeatures=orb_n)
    kps, dess, grays = [], [], []
    for f in frames:
        if f is None:
            kps.append(None); dess.append(None); grays.append(None); continue
        g = _region(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), region)
        kp, des = orb.detectAndCompute(g, None)
        kps.append(kp); dess.append(des); grays.append(g)

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    per_frame_feat, self_amb = [], []
    for des in dess:
        if des is None or len(des) < 3:
            continue
        per_frame_feat.append(len(des))
        # self-ambiguity: nearest OTHER descriptor within the same frame; count near-dupes.
        m = bf.knnMatch(des, des, k=2)  # 1st neighbour is self (dist 0)
        nd = [pair[1].distance for pair in m if len(pair) == 2]
        self_amb.append(float(np.mean(np.asarray(nd) < 24)) if nd else float("nan"))

    puts, rejects, iratios, icounts = [], [], [], []
    first_pair_viz = None
    for i in range(len(frames) - 1):
        d0, d1, k0, k1 = dess[i], dess[i + 1], kps[i], kps[i + 1]
        if d0 is None or d1 is None or len(d0) < 8 or len(d1) < 8:
            continue
        knn = bf.knnMatch(d0, d1, k=2)
        cand = [pair for pair in knn if len(pair) == 2]
        good = [m for (m, n) in cand if m.distance < ratio * n.distance]
        if cand:
            rejects.append(1.0 - len(good) / len(cand))
        puts.append(len(good))
        if len(good) >= 15:
            p0 = np.float32([k0[m.queryIdx].pt for m in good])
            p1 = np.float32([k1[m.trainIdx].pt for m in good])
            E, mask = cv2.findEssentialMat(p0, p1, K, method=cv2.RANSAC,
                                           prob=0.999, threshold=1.0)
            if mask is not None:
                inl = int(mask.sum())
                iratios.append(inl / len(good))
                icounts.append(inl)
                if viz_path and first_pair_viz is None and grays[i] is not None:
                    vis = cv2.drawMatches(
                        grays[i], k0, grays[i + 1], k1, good, None,
                        matchesMask=mask.ravel().tolist(),
                        matchColor=(0, 255, 0), singlePointColor=(0, 0, 255),
                        flags=cv2.DrawMatchesFlags_NOT_DRAW_SINGLE_POINTS)
                    cv2.imwrite(viz_path, vis)
                    first_pair_viz = True

    def _m(a):
        return float(np.nanmean(a)) if len(a) else float("nan")

    return {
        "orb_per_frame": _m(per_frame_feat),
        "self_ambiguity": _m(self_amb),
        "putative_per_pair": _m(puts),
        "ratio_reject": _m(rejects),
        "inlier_ratio": _m(iratios),
        "inliers_per_pair": _m(icounts),
        "n_pairs_scored": len(iratios),
    }


def verdict(m):
    """How aliasing actually manifests here (learned empirically, savanna+gravel renders):
    self-similar ground rarely produces bit-identical descriptors (per-fragment lighting /
    normal maps / AO + perspective break tile identity, so `self_ambiguity` seldom fires);
    instead the Lowe ratio test correctly REJECTS the ambiguous ground matches, so
    `ratio_reject` rises (0.5 mixed scene -> 0.8 ground -> 0.92 near-nadir gravel) and the
    ground contributes few confident matches. VIO is then carried by distinctive LANDMARKS
    (trees/rocks). => the failure is aliasing-driven STARVATION: high ratio_reject AND few
    surviving inliers. So:
      ALIASING RISK  wrong matches survive (inlier_ratio<0.5), starved (inliers/pair<40),
                     or hard duplicates (self_ambiguity>0.15);
      MARGINAL       ground strongly ambiguous (ratio_reject>0.85) or thin constraints
                     (inliers/pair<100) -> viable but leaning on sparse landmarks;
      GOOD           inlier_ratio>=0.65 and inliers/pair>=100 and ratio_reject<=0.85.
    Advisory only -- always read the numbers + the --viz (coherent flow vs criss-cross)."""
    ir, ic, sa, rr = (m["inlier_ratio"], m["inliers_per_pair"],
                      m["self_ambiguity"], m["ratio_reject"])
    if any(math.isnan(x) for x in (ir, ic)):
        return "INSUFFICIENT (too few matches -- near featureless?)"
    if ic < 40 or ir < 0.5 or (not math.isnan(sa) and sa > 0.15):
        return "ALIASING RISK"
    if rr > 0.85 or ic < 100:
        return "MARGINAL (ambiguity/landmark-reliant)"
    if ir >= 0.65 and ic >= 100:
        return "GOOD"
    return "MARGINAL"


# ------------------------------------------------------------------- main ----
def bench_one(tag, poses, K, args):
    def fpath(i):
        return f"{FR}/vbf_{tag}_{i}.npy"
    if args.no_render and all(os.path.exists(fpath(i)) for i in range(len(poses))):
        frames = [np.load(fpath(i)) for i in range(len(poses))]
        print(f"  [{tag}] reusing {len(frames)} cached frames (--no-render)", flush=True)
    else:
        frames = render_trajectory(poses, args.fov)
        for i, f in enumerate(frames):
            if f is not None:
                np.save(fpath(i), f)
    ok = sum(f is not None for f in frames)
    print(f"  [{tag}] captured {ok}/{len(frames)} frames", flush=True)
    viz = f"{FR}/vio_bench_{tag}_matches.png" if args.viz else None
    m = da_metrics(frames, K, region=args.region, orb_n=args.orb, ratio=args.ratio, viz_path=viz)
    m["verdict"] = verdict(m)
    m["tag"] = tag
    return m


def main():
    ap = argparse.ArgumentParser(description="VIO data-association (aliasing) benchmark.")
    ap.add_argument("--tag", default="bench", help="Name for outputs.")
    ap.add_argument("--ground-modes", default=None,
                    help="Comma list to A/B (rebuilds ground each). e.g. patchy,uniform_t1.")
    ap.add_argument("--biome", default="desert", help="Ground biome for --ground-modes.")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--step", type=float, default=0.6, help="Forward m/frame.")
    ap.add_argument("--agl", type=float, default=12.0, help="Height above ground, m.")
    ap.add_argument("--pitch", type=float, default=0.35, help="Down-pitch, rad.")
    ap.add_argument("--yaw-amp-deg", type=float, default=6.0)
    ap.add_argument("--yaw-period", type=float, default=6.0, help="Frames per yaw cycle.")
    ap.add_argument("--fov", type=float, default=1.0, help="Horizontal FOV, rad (rig=1.0).")
    ap.add_argument("--region", choices=["full", "ground"], default="full",
                    help="Analyze whole frame (world benchmark) or ground only (texture).")
    ap.add_argument("--orb", type=int, default=1500)
    ap.add_argument("--ratio", type=float, default=0.75, help="Lowe ratio.")
    ap.add_argument("--viz", action="store_true", help="Save an inlier-match visualization.")
    ap.add_argument("--no-render", action="store_true",
                    help="Reuse cached frames (frames/vbf_<tag>_<i>.npy) from a prior run "
                         "-- re-analyze a different --region/--orb/--ratio for free.")
    ap.add_argument("--heightmap", default=None,
                    help="Option d2: benchmark a gz <heightmap> instead of the mesh ground. "
                         "Format 'PNG,EXTENT_m,Z_m' (e.g. dem/hm_d2.png,60,0.35).")
    ap.add_argument("--world", default=None,
                    help="Placement world FILE stem under worlds/ to graft objects "
                         "from (e.g. vio_lio_7). Default: worlds/forest_world.world "
                         "(the `generate` output). Terrain is always the current "
                         "models/ground; this only selects which objects are placed.")
    ap.add_argument("--world-sun", action="store_true",
                    help="Render under the --world file's sun/scene/weather (the "
                         "photometric stage) instead of the harness default sun. "
                         "REQUIRED to measure the photometric/weather axes; off by "
                         "default so baseline numbers keep their fixed lighting.")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.world_sun:
        os.environ["GRAFT_SUN"] = "1"

    if args.world:
        # terrain_scene grafts placement from this file instead of the default
        # forest_world.world, so a scenario-named world can be benchmarked directly.
        if args.world.endswith(".world") or os.path.isabs(args.world):
            wf = args.world
        else:
            wf = f"{WS}/worlds/{args.world}.world"
        if not os.path.exists(wf):
            raise SystemExit(f"world file not found: {wf}")
        os.environ["FOREST_WORLD"] = wf

    if args.heightmap:
        os.environ["HEIGHTMAP"] = args.heightmap
        verts, ext, _ = read_heightmap(args.heightmap)
    else:
        verts, ext, _ = read_terrain(OBJ)
    poses = trajectory(verts, ext, args.frames, args.step, args.agl, args.pitch,
                       args.yaw_amp_deg, args.yaw_period)
    K = intrinsics(640, 480, args.fov)
    print(f"trajectory: {args.frames} poses, {args.step} m/frame, yaw +-{args.yaw_amp_deg} deg, "
          f"AGL {args.agl} m over extent {ext:.0f} m", flush=True)

    # tag -> (ground --mode, extra flags). uniform_t1 = de-aliased crisp tile (the Tier-1
    # candidate); `periodic` = crisp tile with warp OFF -> strongly periodic ground, a
    # deliberate ALIASING case to confirm the benchmark DETECTS the failure it targets.
    GROUND_CFG = {
        "patchy": ("patchy", []),
        "uniform": ("uniform", []),
        "uniform_t1": ("uniform", ["--uniform-tile", "60", "--tile-warp", "1.3"]),
        "periodic": ("uniform", ["--uniform-tile", "100", "--tile-warp", "0"]),
    }
    results = []
    modes = args.ground_modes.split(",") if args.ground_modes else [None]
    for mode in modes:
        tag = args.tag if mode is None else f"{args.tag}_{mode}"
        if mode is not None:
            gmode, extra = GROUND_CFG.get(mode, (mode, []))
            print(f"=== ground={mode} ({gmode} {' '.join(extra)}) ===", flush=True)
            run(CLI + ["ground", "--mode", gmode, "--biome", args.biome,
                       "--seed", "7", "--res", "4096"] + extra)
        results.append(bench_one(tag, poses, K, args))

    print("\n==== VIO data-association benchmark ({} region) ====".format(args.region))
    hdr = ("| config        | ORB/fr | putative | ratio_reject | inlier_ratio | "
           "inliers/pair | self_amb | verdict |")
    print(hdr)
    print("|" + "-" * (len(hdr) - 2) + "|")
    for m in results:
        print(f"| {m['tag']:<13} | {m['orb_per_frame']:6.0f} | {m['putative_per_pair']:8.0f} | "
              f"{m['ratio_reject']:12.2f} | {m['inlier_ratio']:12.2f} | "
              f"{m['inliers_per_pair']:12.0f} | {m['self_ambiguity']:8.2f} | {m['verdict']} |")

    out = args.out or f"{FR}/vio_bench_{args.tag}.json"
    json.dump({"args": vars(args), "results": results}, open(out, "w"), indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
