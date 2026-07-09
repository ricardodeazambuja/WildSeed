#!/usr/bin/env python3
"""End-to-end VIO/LIO validation (Phase C) — turn the vio_bench / lidar_spread PROXIES into
real trajectory-drift (ATE) numbers on a recorded ground-robot dataset.

A lightweight, self-contained reference estimator (no ROS, runs in wildseed:egl):
  VIO  monocular ORB + essential-matrix recoverPose, chained with GT per-step SCALE (so the
       only error source is rotation / translation-DIRECTION — exactly the data-association
       quality vio_bench measures). Failed steps (too few matches / degenerate E) fall back to
       a constant-velocity model → they show up as drift (that IS the failure mode).
  LIO  point-to-point ICP (scipy cKDTree + SVD) between consecutive gpu_lidar scans, chained →
       a metric trajectory; drift reflects whether the ground gives ICP geometry to lock onto.
Both trajectories are Umeyama-aligned (SE3, no scale) to the TUM ground truth and scored as
ATE RMSE. Run it on the recipe world AND the bare-uniform baseline; recipe ATE < baseline ATE
confirms the proxies predict real drift.

Dataset layout (from `wildseed record --dataset --keep-frames`):
  runs/<name>/frames/frame_XXXXXX.png + frames/frames.csv (idx,t)
  runs/<name>/dataset/lidar_XXXXXX.npz (t,x,y,z) + dataset/groundtruth.txt (TUM)
  runs/<name>/dataset/seg_XXXXXX.png + seg.csv   (segmentation, label = ch 2)

Two axis-specific switches:
  --mask-label N   dynamics axis: mask ORB features on pixels whose recorded
                   segmentation class == N (distractor movers are 8) — the
                   with/without-motion-mask comparison the gate needs.
  --calib PATH     instrument axis: build K from rig_calibration.json's TRUE
                   cam_left calibration instead of the nominal constants —
                   truth-fed (clean) vs nominal-fed (mismatch) comparison.

USAGE (inside wildseed:egl)
  python3 tools/vio_validate.py runs/recipe runs/baseline
Outputs: printed ATE table + frames/vio_validate.json.
"""
import argparse
import csv
import glob
import json
import math
import os

import numpy as np
import cv2
from scipy.spatial import cKDTree

W, H, FOV = 640, 480, 1.0
FX = (W / 2.0) / math.tan(FOV / 2.0)
K_NOMINAL = np.array([[FX, 0, W / 2.0], [0, FX, H / 2.0], [0, 0, 1.0]],
                     np.float64)
SEG_TOL_S = 0.35     # max |t_cam - t_seg| to use a seg frame as a mask (5 Hz)


def calib_K(path):
    """K from a rig_calibration.json (TRUE cam_left values)."""
    cam = json.load(open(path))["cameras"]["cam_left"]
    w, h = cam["width"], cam["height"]
    fx = (w / 2.0) / math.tan(cam["horizontal_fov_true"] / 2.0)
    return np.array([[fx, 0, w / 2.0], [0, fx, h / 2.0], [0, 0, 1.0]],
                    np.float64)


# ------------------------------------------------------------------- io ----
def load_gt(path):
    rows = []
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            v = [float(x) for x in line.split()]
            rows.append(v)
    a = np.asarray(rows, np.float64)
    return a[:, 0], a[:, 1:4]  # t, xyz


def gt_at(gt_t, gt_xyz, times):
    """Linear-interp GT position at each query time (clamped to GT span)."""
    times = np.clip(times, gt_t[0], gt_t[-1])
    return np.stack([np.interp(times, gt_t, gt_xyz[:, k]) for k in range(3)], axis=1)


def load_frames(run, step):
    fp = sorted(glob.glob(f"{run}/frames/frame_*.png"))
    times = {}
    csvp = f"{run}/frames/frames.csv"
    if os.path.exists(csvp):
        with open(csvp) as f:
            for r in csv.DictReader(f):
                times[int(r["idx"])] = float(r["t"])
    idxs = list(range(0, len(fp), step))
    return [(i, fp[i], times.get(i)) for i in idxs]


def load_seg_index(run):
    """(times, paths) of the recorded segmentation frames, or None."""
    csvp = f"{run}/dataset/seg.csv"
    if not os.path.exists(csvp):
        return None
    times, paths = [], []
    with open(csvp) as f:
        for r in csv.DictReader(f):
            p = f"{run}/dataset/seg_{int(r['idx']):06d}.png"
            if os.path.exists(p):
                times.append(float(r["t"]))
                paths.append(p)
    if not paths:
        return None
    return np.asarray(times), paths


def motion_mask(seg_index, t, label, dilate_px=24):
    """ORB feature mask (255 = usable) from the seg frames bracketing t.

    Recorded seg PNGs round-trip the raw labels_map bytes, so the class label
    sits in channel 2 (spike-verified). Segmentation runs at 5 Hz while the
    camera runs at 10 Hz, and a nearby mover crosses tens of pixels between
    seg frames — one nearest seg frame leaves the mover half-unmasked at
    off-phase cam times (measured). So: UNION the moving regions of the two
    seg frames bracketing t, then dilate, then invert. Returns None when no
    seg frame is close enough (frame skipped -> no masking).
    """
    if seg_index is None or t is None:
        return None
    times, paths = seg_index
    near = np.argsort(np.abs(times - t))[:2]
    moving = None
    for i in near:
        if abs(times[i] - t) > SEG_TOL_S:
            continue
        seg = cv2.imread(paths[int(i)])
        if seg is None:
            continue
        m = (seg[:, :, 2] == label).astype(np.uint8) * 255
        moving = m if moving is None else cv2.bitwise_or(moving, m)
    if moving is None:
        return None
    if dilate_px > 0:
        kernel = np.ones((dilate_px, dilate_px), np.uint8)
        moving = cv2.dilate(moving, kernel)
    return cv2.bitwise_not(moving)


def load_scans(run, step):
    sp = sorted(glob.glob(f"{run}/dataset/lidar_*.npz"))
    out = []
    for p in sp[::step]:
        d = np.load(p)
        xyz = np.stack([d["x"], d["y"], d["z"]], axis=1).astype(np.float64)
        fin = np.isfinite(xyz).all(axis=1)
        out.append((float(d["t"]), xyz[fin]))
    return out


# -------------------------------------------------------------- estimators ----
def umeyama_se3(src, dst):
    """Rigid (R,t) aligning src->dst (no scale). Returns aligned src + ATE RMSE."""
    mu_s, mu_d = src.mean(0), dst.mean(0)
    S, D = src - mu_s, dst - mu_d
    Cov = D.T @ S / len(src)
    U, _, Vt = np.linalg.svd(Cov)
    d = np.sign(np.linalg.det(U @ Vt))
    R = U @ np.diag([1, 1, d]) @ Vt
    t = mu_d - R @ mu_s
    aligned = (R @ src.T).T + t
    rmse = float(np.sqrt(np.mean(np.sum((aligned - dst) ** 2, axis=1))))
    return aligned, rmse


def seg_drift(est, gt, seg):
    """Segment/relative drift: independently SE3-align each non-overlapping window of `seg`
    poses to GT and average the residual RMSE. The standard metric for OPEN-LOOP odometry —
    it does NOT compound global drift, so it isolates local tracking quality."""
    errs = []
    for a in range(0, len(est) - seg, seg):
        _, r = umeyama_se3(est[a:a + seg], gt[a:a + seg])
        errs.append(r)
    return float(np.mean(errs)) if errs else float("nan")


def vio_traj(frames, gt_t, gt_xyz, K, seg_index=None, mask_label=None):
    orb = cv2.ORB_create(nfeatures=1500)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    valid = [(i, p, t) for (i, p, t) in frames if t is not None]
    times = np.array([t for (_, _, t) in valid])
    gt_pts = gt_at(gt_t, gt_xyz, times)

    T = np.eye(4)
    centers = [np.zeros(3)]
    prev = None
    prev_mask = None
    last_rel = np.eye(4)
    fails = 0
    inlier_fracs = []
    for n in range(1, len(valid)):
        g = cv2.cvtColor(cv2.imread(valid[n - 1][1]), cv2.COLOR_BGR2GRAY) if prev is None else prev
        g2 = cv2.cvtColor(cv2.imread(valid[n][1]), cv2.COLOR_BGR2GRAY)
        m0 = motion_mask(seg_index, valid[n - 1][2], mask_label) \
            if mask_label is not None and prev_mask is None else prev_mask
        m1 = motion_mask(seg_index, valid[n][2], mask_label) \
            if mask_label is not None else None
        prev, prev_mask = g2, m1
        step_d = float(np.linalg.norm(gt_pts[n] - gt_pts[n - 1]))
        rel = None
        k0, d0 = orb.detectAndCompute(g, m0)
        k1, d1 = orb.detectAndCompute(g2, m1)
        if d0 is not None and d1 is not None and len(d0) >= 8 and len(d1) >= 8:
            knn = bf.knnMatch(d0, d1, k=2)
            good = [m for pr in knn if len(pr) == 2 for (m, nn) in [pr] if m.distance < 0.75 * nn.distance]
            if len(good) >= 12:
                p0 = np.float32([k0[m.queryIdx].pt for m in good])
                p1 = np.float32([k1[m.trainIdx].pt for m in good])
                E, mask = cv2.findEssentialMat(p0, p1, K, cv2.RANSAC, 0.999, 1.0)
                if E is not None and E.shape == (3, 3):
                    n_in, R, tvec, _ = cv2.recoverPose(E, p0, p1, K, mask=mask)
                    inlier_fracs.append(n_in / len(good))
                    rel = np.eye(4)
                    rel[:3, :3] = R
                    rel[:3, 3] = (tvec.ravel() * step_d)
        if rel is None:
            fails += 1
            rel = last_rel.copy()
            rel[:3, 3] = rel[:3, 3] * (step_d / (np.linalg.norm(rel[:3, 3]) + 1e-9))
        last_rel = rel
        T = rel @ T                     # world(=cam0) -> cam_n
        Rn, tn = T[:3, :3], T[:3, 3]
        centers.append(-Rn.T @ tn)      # camera centre in world
    est = np.asarray(centers)
    inlier_frac = float(np.mean(inlier_fracs)) if inlier_fracs else float("nan")
    return est, gt_pts, len(valid), fails, inlier_frac


def icp(src, dst, iters=18, max_d=1.0):
    """Point-to-point ICP: returns 4x4 T mapping src->dst."""
    T = np.eye(4)
    s = src.copy()
    tree = cKDTree(dst)
    for _ in range(iters):
        dist, idx = tree.query(s, k=1)
        m = dist < max_d
        if m.sum() < 10:
            break
        A, B = s[m], dst[idx[m]]
        mu_a, mu_b = A.mean(0), B.mean(0)
        Cov = (B - mu_b).T @ (A - mu_a) / len(A)
        U, _, Vt = np.linalg.svd(Cov)
        dd = np.sign(np.linalg.det(U @ Vt))
        R = U @ np.diag([1, 1, dd]) @ Vt
        t = mu_b - R @ mu_a
        s = (R @ s.T).T + t
        step = np.eye(4)
        step[:3, :3], step[:3, 3] = R, t
        T = step @ T
    return T


def _voxel(p, v=0.5):
    if len(p) == 0:
        return p
    key = np.floor(p / v).astype(np.int64)
    _, uniq = np.unique(key, axis=0, return_index=True)
    return p[uniq]


def lio_traj(scans, gt_t, gt_xyz):
    times = np.array([t for (t, _) in scans])
    gt_pts = gt_at(gt_t, gt_xyz, times)
    clouds = [_voxel(p) for (_, p) in scans]
    T = np.eye(4)
    centers = [T[:3, 3].copy()]
    fails = 0
    for n in range(1, len(clouds)):
        if len(clouds[n]) < 30 or len(clouds[n - 1]) < 30:
            fails += 1
            centers.append(centers[-1].copy())
            continue
        rel = icp(clouds[n], clouds[n - 1])     # maps scan_n -> scan_{n-1}
        T = T @ rel                              # sensor pose in world
        centers.append(T[:3, 3].copy())
    est = np.asarray(centers)
    return est, gt_pts, len(scans), fails


# ------------------------------------------------------------------- main ----
def run_one(run, fstep, sstep, vseg, lseg, K, mask_label=None):
    gt_t, gt_xyz = load_gt(f"{run}/dataset/groundtruth.txt")
    path_len = float(np.sum(np.linalg.norm(np.diff(gt_xyz, axis=0), axis=1)))
    frames = load_frames(run, fstep)
    scans = load_scans(run, sstep)
    seg_index = load_seg_index(run) if mask_label is not None else None
    if mask_label is not None and seg_index is None:
        print(f"WARNING: {run}: --mask-label set but no dataset/seg.csv — "
              "features are NOT being masked")
    v_est, v_gt, v_n, v_fail, v_inl = vio_traj(frames, gt_t, gt_xyz, K,
                                               seg_index, mask_label)
    l_est, l_gt, l_n, l_fail = lio_traj(scans, gt_t, gt_xyz)
    _, v_ate = umeyama_se3(v_est, v_gt)
    _, l_ate = umeyama_se3(l_est, l_gt)
    return {
        "run": run, "path_len_m": round(path_len, 1),
        "mask_label": mask_label,
        "vio_ate_rmse_m": round(v_ate, 3), "vio_seg_drift_m": round(seg_drift(v_est, v_gt, vseg), 3),
        "vio_frames": v_n, "vio_fail_steps": v_fail,
        "vio_inlier_frac": round(v_inl, 3) if math.isfinite(v_inl) else None,
        "lio_ate_rmse_m": round(l_ate, 3), "lio_seg_drift_m": round(seg_drift(l_est, l_gt, lseg), 3),
        "lio_scans": l_n, "lio_fail_steps": l_fail,
    }


def main():
    ap = argparse.ArgumentParser(description="End-to-end VIO/LIO ATE validation (Phase C).")
    ap.add_argument("runs", nargs="+", help="Run dirs (e.g. runs/recipe runs/baseline).")
    ap.add_argument("--frame-step", type=int, default=2, help="Use every Nth cam frame.")
    ap.add_argument("--scan-step", type=int, default=3, help="Use every Nth lidar scan.")
    ap.add_argument("--vio-seg", type=int, default=25, help="VIO segment length (frames) for seg drift.")
    ap.add_argument("--lio-seg", type=int, default=17, help="LIO segment length (scans) for seg drift.")
    ap.add_argument("--mask-label", type=int, default=None,
                    help="Mask ORB features where recorded segmentation class == N "
                         "(distractors are 8) — the dynamics-gate comparison.")
    ap.add_argument("--calib", default=None,
                    help="rig_calibration.json: build K from the TRUE cam_left "
                         "calibration (clean run) instead of the nominals (mismatch).")
    ap.add_argument("--tag", default=None,
                    help="Output suffix: frames/vio_validate_<tag>.json.")
    args = ap.parse_args()

    K = calib_K(args.calib) if args.calib else K_NOMINAL
    if args.calib:
        print(f"K from {args.calib}: fx={K[0, 0]:.2f} (nominal {FX:.2f})")
    results = [run_one(r, args.frame_step, args.scan_step, args.vio_seg,
                       args.lio_seg, K, args.mask_label)
               for r in args.runs]
    print("\n==== End-to-end VIO/LIO validation vs ground truth ====")
    print("seg drift = mean local drift over ~25 m windows (open-loop metric; ATE compounds over the full path)")
    hdr = ("| run       | path m | VIO seg | VIO ATE | VIO fails | VIO inl | "
           "LIO seg | LIO ATE | LIO fails |")
    print(hdr + "\n|" + "-" * (len(hdr) - 2) + "|")
    for m in results:
        inl = f"{m['vio_inlier_frac']:.3f}" if m["vio_inlier_frac"] is not None else "  --  "
        print(f"| {os.path.basename(m['run']):<9} | {m['path_len_m']:6.1f} | "
              f"{m['vio_seg_drift_m']:7.3f} | {m['vio_ate_rmse_m']:7.2f} | {m['vio_fail_steps']:4d}/{m['vio_frames']:<4d} | {inl:>7} | "
              f"{m['lio_seg_drift_m']:7.3f} | {m['lio_ate_rmse_m']:7.2f} | {m['lio_fail_steps']:4d}/{m['lio_scans']:<4d} |")
    tag = f"_{args.tag}" if args.tag else ""
    out = f"{os.environ.get('WS', os.getcwd())}/frames/vio_validate{tag}.json"
    json.dump(results, open(out, "w"), indent=2)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
