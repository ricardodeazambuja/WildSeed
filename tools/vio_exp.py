"""VIO-pose ground-crispness experiment: patchy vs uniform on savanna_flats.

Builds terrain + placement ONCE, then swaps ONLY the ground material and renders
the real sensor-rig VIO cameras (vio_drone 12 m AGL, vio_ground 2 m; both 640x480,
57 deg FOV per core/rig.py) at the actual operating poses (cli/fly.py --agl 12,
gentle down-pitch). Measures GROUND-region feature density + tiling + high-frequency
energy -- the crispness axis the oblique/720p gallery-cam harness (compare.py on
cam_hero/oblique) structurally cannot see.

Question: does crisp draw-time tiling (uniform) beat the blurry baked composite
(patchy, 4096 px over ~307 m = 7.5 cm/texel) at the GSD VIO actually resolves?

Run in wildseed:egl (GPU), from /workspace:
  python3 tools/vio_exp.py
"""
import json
import os
import shutil
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cv2  # noqa: E402  (in :egl)
from compare import (feature_metrics, coverage_metrics, tiling_metrics,  # noqa: E402
                     to_common, load_rgb, _gray)

WS = os.environ.get("WS", os.getcwd())
CLI = ["python3", "-m", "wildseed.cli.main"]
FR = os.path.join(WS, "frames")

# savanna_flats config (verbatim from tools/build_scenarios.py SCN); flat + ground-
# dominated = the worst-case tiling scene and the most VIO-relevant.
TG = ["--preset", "hilly", "--seed", "3", "--amplitude", "12", "--feature", "140"]
DENS = {"tree": 60, "rock": 42, "bush": 200, "grass": 380}
GROUND_BIOME = "desert"
PIXEL = "1.6"
CAMS = ["vio_drone", "vio_ground"]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        print("ERR", " ".join(cmd[:6]), (r.stderr or "")[-400:], flush=True)
    return r


# (tag, ground --mode, extra ground args). uniform_t1 = the plan's ACTUAL Tier-1:
# small crisp tile (~5 m: 307 m / 60) + domain warp (de-alias), vs the confounded
# default-uniform (38 m tile, no warp) and the current patchy baseline.
CONFIGS = [
    ("patchy", "patchy", []),
    ("uniform", "uniform", []),
    ("uniform_t1", "uniform", ["--uniform-tile", "60", "--tile-warp", "1.3"]),
]


def render(tag, mode, extra):
    # idempotent: skip the (slow) build+render if both frames are already captured
    if all(os.path.exists(f"{FR}/{c}_{tag}.npy") for c in CAMS):
        print(f"  {tag}: frames present, skipping render", flush=True)
        return
    run(CLI + ["ground", "--mode", mode, "--biome", GROUND_BIOME,
               "--seed", "7", "--res", "4096"] + extra)
    env = dict(os.environ, FOREST="1", VIO_CAMS="1")
    run(["python3", f"{WS}/tools/terrain_scene.py"], env=env)
    g = subprocess.Popen(
        ["gz", "sim", "-s", "-r", "--headless-rendering",
         f"{WS}/worlds/terrain_scene.world"],
        stdout=open(f"{FR}/gz_vioexp_{mode}.log", "w"), stderr=subprocess.STDOUT)
    try:
        run(["python3", f"{WS}/tools/capture_cams.py", ",".join(CAMS)], timeout=180)
    finally:
        g.terminate()
        try:
            g.wait(timeout=10)
        except subprocess.TimeoutExpired:
            g.kill()
    for c in CAMS:
        f = f"{FR}/{c}.npy"
        if os.path.exists(f):
            shutil.copy(f, f"{FR}/{c}_{tag}.npy")


def ground_region(img):
    """Lower 60% of frame ~= ground for these forward-slightly-down poses."""
    h = img.shape[0]
    return img[int(0.40 * h):, :, :]


def measure(tag):
    out = {}
    for c in CAMS:
        p = f"{FR}/{c}_{tag}.npy"
        if not os.path.exists(p):
            out[c] = None
            continue
        g = ground_region(to_common(load_rgb(p)))
        fm, pts = feature_metrics(g)
        cm = coverage_metrics(g.shape[:2], pts)
        tm = tiling_metrics(g)
        # variance-of-Laplacian: high-frequency energy. Crisp texture -> high;
        # blurry oversampled bake -> low. The direct crispness proxy.
        hf = float(cv2.Laplacian(_gray(g), cv2.CV_64F).var())
        out[c] = dict(fast_pmp=fm["fast_pmp"], orb_pmp=fm["orb_pmp"],
                      coverage=cm["coverage"],
                      tiling_peak=tm["tiling_peak"], tiling_period=tm["tiling_period"],
                      hf=hf)
    return out


# 1. terrain + placement ONCE (shared by both ground modes)
run(CLI + ["terraingen"] + TG + ["--size", "192", "--pixel", PIXEL, "-o", "dem/synth.tif"])
run(CLI + ["terrain", "--dem", "dem/synth.tif"])
run(CLI + ["generate", "--density", json.dumps(DENS), "--seed", "7"])

# 2. render + measure each ground config
res = {}
TAGS = [t for (t, _, _) in CONFIGS]
for tag, mode, extra in CONFIGS:
    print(f"=== rendering {tag} ({mode} {' '.join(extra)}) ===", flush=True)
    render(tag, mode, extra)
    res[tag] = measure(tag)

print("\n==== VIO ground-region metrics (lower 60% of frame) ====", flush=True)
for c in CAMS:
    print(f"\n-- {c} --")
    for tag in TAGS:
        m = res[tag].get(c)
        if m:
            print(f"  {tag:11} FAST/MP={m['fast_pmp']:7.0f} ORB/MP={m['orb_pmp']:6.0f} "
                  f"cov={m['coverage']:.2f} tilePk={m['tiling_peak']:.3f}@{m['tiling_period']:.0f}px "
                  f"HF={m['hf']:8.0f}")
json.dump(res, open(f"{FR}/vio_exp_metrics.json", "w"), indent=2)
print("\nwrote frames/vio_exp_metrics.json", flush=True)
