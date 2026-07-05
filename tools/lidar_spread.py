#!/usr/bin/env python3
"""LIDAR range-spread / roughness metric (option (c)/(d) validation gate V3).

The camera-only vio_bench cannot see the axis LIO cares about: does the ground actually
produce RANGE VARIATION the LIDAR can lock onto? Flat, smooth ground gives a gpu_lidar a
boringly predictable return — each ring is a near-perfect circle, azimuthally constant
range — so ICP/LIO has no along-track geometry to register against (it slides). Clutter
(rocks/bushes) or geometric relief (bumps/ruts) breaks that: adjacent beams jump in range
where an object or a rise interrupts the ground, giving registrable structure.

This launches a real gz server on the current rig world (build with `generate --rig
--rig-pose 0,0,2`), grabs a few gpu_lidar scans (16 ch × 360, from core/rig.py), and
reports:

  ring_roughness_m   mean over rings of std(Δrange) between ADJACENT azimuth beams — the
                     core LIO signal. ~0 over flat ground; rises with clutter/relief.
  range_std_m        overall std of finite ranges (gross spread; also rises with relief).
  near_frac          fraction of returns closer than the flat-ground expectation at that
                     ring (i.e. beams that hit an object standing above the ground).
  finite_frac        fraction of beams that returned at all (clutter can also drop beams
                     into the sky between objects).

Higher ring_roughness_m / range_std_m == more LIO-registrable geometry. Read alongside the
RTF cost (tools/rtf_bench.py) and the camera gain (tools/vio_bench.py).

USAGE (inside wildseed:egl, GPU; needs a rig world with the lidar near the ground)
  python3 tools/lidar_spread.py --tag clutter --scans 5
Outputs: printed JSON summary + frames/lidar_spread_<tag>.json.
"""
import argparse
import json
import os
import subprocess
import time

import numpy as np

WS = os.environ.get("WS", os.getcwd())
FR = os.path.join(WS, "frames")


def scan_metrics(m, channels):
    """One PointCloudPacked -> per-scan roughness metrics (sensor-frame ranges)."""
    off = {f.name: f.offset for f in m.field}
    n = m.width * m.height
    buf = np.frombuffer(m.data, dtype=np.uint8).reshape(n, m.point_step)

    def f32(name):
        return buf[:, off[name]:off[name] + 4].copy().view(np.float32).ravel()

    x, y, z = f32("x"), f32("y"), f32("z")
    rng = np.sqrt(x * x + y * y + z * z)
    finite = np.isfinite(rng)
    finite_frac = float(finite.mean())

    # Organize into (rings, azimuth). gpu_lidar packs width=azimuth, height=channels.
    H = m.height if m.height in (channels,) else channels
    W = n // H if H else n
    if H * W != n:
        # fall back to unorganized stats only
        r = rng[finite]
        return dict(ring_roughness_m=float("nan"),
                    range_std_m=float(r.std()) if r.size else float("nan"),
                    near_frac=float("nan"), finite_frac=finite_frac)
    R = rng.reshape(H, W)

    ring_rough = []
    near = []
    for ring in R:
        fin = np.isfinite(ring)
        if fin.sum() < 8:
            continue
        rr = ring.copy()
        # adjacent-azimuth range delta, only where BOTH beams returned.
        d = np.diff(rr)
        both = np.isfinite(d)
        if both.sum() >= 4:
            ring_rough.append(float(np.nanstd(d[both])))
        # near = below this ring's median finite range (objects above ground read closer)
        med = float(np.nanmedian(rr[fin]))
        near.append(float(np.mean(rr[fin] < 0.85 * med)))

    r = rng[finite]
    return dict(
        ring_roughness_m=float(np.mean(ring_rough)) if ring_rough else float("nan"),
        range_std_m=float(r.std()) if r.size else float("nan"),
        near_frac=float(np.mean(near)) if near else float("nan"),
        finite_frac=finite_frac,
    )


def main():
    ap = argparse.ArgumentParser(description="LIDAR range-spread / roughness metric.")
    ap.add_argument("--world", default="forest_world")
    ap.add_argument("--world-file", default=None)
    ap.add_argument("--tag", default="lidar")
    ap.add_argument("--lidar-topic", default="rig/lidar/points")
    ap.add_argument("--channels", type=int, default=16)
    ap.add_argument("--scans", type=int, default=5, help="Scans to average.")
    ap.add_argument("--settle", type=float, default=7.0,
                    help="Extra warm-up after the first scan arrives, wall s.")
    ap.add_argument("--load-timeout", type=float, default=240.0,
                    help="Max wall s to wait for the first scan (big worlds load slowly).")
    args = ap.parse_args()

    world_file = args.world_file or f"{WS}/worlds/{args.world}.world"
    if not os.path.exists(world_file):
        raise SystemExit(f"world file not found: {world_file} (run `generate --rig` first)")

    env = dict(os.environ)
    models = f"{WS}/models"
    prev = env.get("GZ_SIM_RESOURCE_PATH", "")
    env["GZ_SIM_RESOURCE_PATH"] = f"{models}:{prev}" if prev else models

    os.makedirs(FR, exist_ok=True)
    log = open(f"{FR}/gz_lidar_{args.tag}.log", "w")
    gz = subprocess.Popen(
        ["gz", "sim", "-s", "-r", "--headless-rendering", world_file],
        stdout=log, stderr=subprocess.STDOUT, env=env)

    from gz.msgs10.pointcloud_packed_pb2 import PointCloudPacked
    from gz.transport13 import Node
    node = Node()
    scans = []

    # Gate capture so we don't average scans taken mid-load (partial returns).
    cap = {"on": False, "seen": 0}

    def cb(m):
        cap["seen"] += 1
        if cap["on"] and len(scans) < args.scans:
            scans.append(scan_metrics(m, args.channels))

    node.subscribe(PointCloudPacked, args.lidar_topic, cb)

    try:
        # Wait for the FIRST scan (big worlds load slowly; no scan until the
        # sim steps + renders), then warm up, then capture fresh scans.
        t0 = time.time()
        while cap["seen"] == 0 and time.time() - t0 < args.load_timeout:
            time.sleep(0.2)
        time.sleep(args.settle)
        cap["on"] = True
        t1 = time.time()
        while len(scans) < args.scans and time.time() - t1 < 30:
            time.sleep(0.2)
    finally:
        gz.terminate()
        try:
            gz.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gz.kill()
        log.close()

    if not scans:
        raise SystemExit("no lidar scans captured (rig lidar enabled? topic correct?)")

    def agg(key):
        vals = [s[key] for s in scans if not (isinstance(s[key], float) and np.isnan(s[key]))]
        return round(float(np.mean(vals)), 4) if vals else None

    out = {
        "tag": args.tag,
        "world": args.world,
        "n_scans": len(scans),
        "ring_roughness_m": agg("ring_roughness_m"),
        "range_std_m": agg("range_std_m"),
        "near_frac": agg("near_frac"),
        "finite_frac": agg("finite_frac"),
    }
    print(json.dumps(out, indent=2), flush=True)
    json.dump(out, open(f"{FR}/lidar_spread_{args.tag}.json", "w"), indent=2)
    print(f"wrote {FR}/lidar_spread_{args.tag}.json", flush=True)


if __name__ == "__main__":
    main()
