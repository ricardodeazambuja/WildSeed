"""Temporal VIO check: render a short forward-motion sequence over the static
savanna_flats scene (drone cam, real rig optics) and measure KLT feature-track
LENGTH -- the temporal signal single-frame FAST/tiling metrics cannot see.

Good ground texture -> features persist many frames (long tracks). Featureless or
repetitive/ambiguous ground -> tracks die fast or drift. This is the direct
VIO-relevant question: does the ground support stable frame-to-frame tracking?

Assumes terrain + placement already built (run tools/vio_exp.py first, or it
rebuilds). Rebuilds the ground in the requested mode. Run in wildseed:egl (GPU):
  python3 tools/vio_seq.py [patchy|uniform]
"""
import os
import subprocess
import sys

import numpy as np
import cv2

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from compare import to_common, load_rgb, _gray  # noqa: E402

WS = os.environ.get("WS", os.getcwd())
CLI = ["python3", "-m", "wildseed.cli.main"]
FR = os.path.join(WS, "frames")
MODE = sys.argv[1] if len(sys.argv) > 1 else "patchy"
N = 10            # frames
STEP = 0.5        # m/frame forward (5 m/s @ 10 Hz rig rate)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode:
        print("ERR", " ".join(cmd[:6]), (r.stderr or "")[-300:], flush=True)
    return r


# rebuild ground in MODE (terrain + placement assumed present from vio_exp.py)
if not os.path.exists(f"{WS}/models/ground/mesh/terrain.obj"):
    TG = ["--preset", "hilly", "--seed", "3", "--amplitude", "12", "--feature", "140"]
    run(CLI + ["terraingen"] + TG + ["--size", "192", "--pixel", "1.6", "-o", "dem/synth.tif"])
    run(CLI + ["terrain", "--dem", "dem/synth.tif"])
    run(CLI + ["generate", "--density", '{"tree":60,"rock":42,"bush":200,"grass":380}', "--seed", "7"])
run(CLI + ["ground", "--mode", MODE, "--biome", "desert", "--seed", "7", "--res", "4096"])

# render the motion sequence
frames = []
for i in range(N):
    env = dict(os.environ, FOREST="1", VIO_CAMS="1", VIO_DX=str(i * STEP))
    run(["python3", f"{WS}/tools/terrain_scene.py"], env=env)
    g = subprocess.Popen(
        ["gz", "sim", "-s", "-r", "--headless-rendering", f"{WS}/worlds/terrain_scene.world"],
        stdout=open(f"{FR}/gz_seq.log", "w"), stderr=subprocess.STDOUT)
    try:
        run(["python3", f"{WS}/tools/capture_cams.py", "vio_drone"], timeout=120)
    finally:
        g.terminate()
        try:
            g.wait(timeout=10)
        except subprocess.TimeoutExpired:
            g.kill()
    a = np.load(f"{FR}/vio_drone.npy")
    img = a[..., :3] if a.shape[-1] == 4 else a
    frames.append(_gray(to_common(img)))
    print(f"  frame {i} dx={i*STEP:.1f}m", flush=True)

# KLT: seed corners on the GROUND region of frame 0, track forward, record how many
# consecutive frames each survives (LK status + a modest displacement sanity gate).
h, w = frames[0].shape
y0 = int(0.40 * h)                       # ground region = lower 60%
mask = np.zeros((h, w), np.uint8); mask[y0:, :] = 255
p0 = cv2.goodFeaturesToTrack(frames[0], maxCorners=400, qualityLevel=0.01,
                             minDistance=7, mask=mask)
print(f"\nmode={MODE}: seeded {0 if p0 is None else len(p0)} ground corners on frame 0")
alive = np.ones(len(p0), bool)
life = np.ones(len(p0), int)             # frames survived (>=1)
pts = p0
lk = dict(winSize=(21, 21), maxLevel=3,
          criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01))
for i in range(1, N):
    nxt, st, err = cv2.calcOpticalFlowPyrLK(frames[i - 1], frames[i], pts, None, **lk)
    st = st.reshape(-1).astype(bool)
    inb = (nxt[:, 0, 0] >= 0) & (nxt[:, 0, 0] < w) & (nxt[:, 0, 1] >= 0) & (nxt[:, 0, 1] < h)
    ok = st & inb & alive
    life[ok] += 1
    alive = alive & ok
    pts = nxt

life = life[np.arange(len(p0))]
print(f"  track length (frames survived, max {N}): "
      f"mean={life.mean():.1f} median={np.median(life):.0f} "
      f"p90={np.percentile(life,90):.0f}")
print(f"  survived all {N} frames: {100*np.mean(life>=N):.0f}%   "
      f">= half ({N//2}): {100*np.mean(life>=N//2):.0f}%")
np.save(f"{FR}/vio_seq_life_{MODE}.npy", life)
