#!/usr/bin/env python3
"""RTF-under-load harness — the COST gauge for ground-clutter / relief options.

WHY
---
`tools/vio_bench.py` renders one-shot (per-pose cameras in a paused-ish capture) and so
carries NO real-time-factor (RTF) signal. But the binding constraint for the whole
ground-clutter effort is RTF: when the sim falls behind wall-clock (trouble ≲0.3), ROS 2
nodes advance timers on `sim_time` while DDS delivery is wall-clock → desync → message-
filter / TF timeouts → failures. So every clutter/relief choice must be judged by
(VIO+LIDAR feature gain) / (RTF cost), and the RTF cost has to be MEASURED UNDER LOAD:
the sensor rig actually rendering (camera 10 Hz + gpu_lidar 16 ch × 360 × 10 Hz, from
core/rig.py) with real consumers attached, while physics steps.

WHAT IT DOES
------------
Launches a real `gz sim -s -r` server on a rig world (build with `wildseed generate --rig`),
attaches subscribers to the camera + lidar topics (a stand-in VIO/LIO consumer, so the
sensors are genuinely on the render path), then samples `real_time_factor` off
`/world/<world>/stats` for a measurement window and reports:

  window_rtf   sim-time advanced / wall-time elapsed over the window (ground-truth RTF).
  rtf_median   median of the instantaneous real_time_factor field (gz reports ~5 Hz).
  rtf_min/p10  worst-case — the value that actually breaks ROS 2 timing.

Call it once per scene-complexity level (bare → clutter density / relief resolution) and
keep the operating point where rtf_min stays ≥ ~0.5.

USAGE (inside wildseed:egl, GPU; needs a rig world already built)
  wildseed generate --rig --rig-pose 0,0,2 --density '{...}'   # build the world first
  python3 tools/rtf_bench.py --tag bare --secs 20
  python3 tools/rtf_bench.py --tag dense --secs 20             # after rebuilding denser
Outputs: printed JSON summary + frames/rtf_bench_<tag>.json (+ gz_rtf_<tag>.log).
"""
import argparse
import json
import os
import subprocess
import time

import numpy as np

WS = os.environ.get("WS", os.getcwd())
FR = os.path.join(WS, "frames")


def main():
    ap = argparse.ArgumentParser(description="RTF-under-load harness (sensor rig active).")
    ap.add_argument("--world", default="forest_world", help="Running world's <world name>.")
    ap.add_argument("--world-file", default=None,
                    help="Path to the .world (default worlds/<world>.world).")
    ap.add_argument("--tag", default="rtf", help="Name for outputs.")
    ap.add_argument("--secs", type=float, default=20.0, help="Measurement window, wall s.")
    ap.add_argument("--settle", type=float, default=6.0,
                    help="Warm-up AFTER stepping begins, wall s (sensor init).")
    ap.add_argument("--load-timeout", type=float, default=240.0,
                    help="Max wall s to wait for the sim clock to start advancing "
                         "(large instance counts load slowly); else report stalled.")
    ap.add_argument("--no-sensor-subs", action="store_true",
                    help="Don't attach cam/lidar subscribers (pure always_on rendering).")
    ap.add_argument("--cam-topic", default="rig/cam_left")
    ap.add_argument("--lidar-topic", default="rig/lidar/points")
    args = ap.parse_args()

    world_file = args.world_file or f"{WS}/worlds/{args.world}.world"
    if not os.path.exists(world_file):
        raise SystemExit(f"world file not found: {world_file} (run `generate --rig` first)")

    env = dict(os.environ)
    models = f"{WS}/models"
    prev = env.get("GZ_SIM_RESOURCE_PATH", "")
    env["GZ_SIM_RESOURCE_PATH"] = f"{models}:{prev}" if prev else models

    os.makedirs(FR, exist_ok=True)
    log = open(f"{FR}/gz_rtf_{args.tag}.log", "w")
    gz = subprocess.Popen(
        ["gz", "sim", "-s", "-r", "--headless-rendering", world_file],
        stdout=log, stderr=subprocess.STDOUT, env=env)

    subs = []
    if not args.no_sensor_subs:
        # Real consumers force the sensors onto the render path (not just always_on).
        for topic in (args.cam_topic, args.lidar_topic):
            subs.append(subprocess.Popen(
                ["gz", "topic", "-e", "-t", topic],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env))

    # /stats reader (sim clock + instantaneous RTF), same path as core/fly.py.
    from gz.msgs10.world_stats_pb2 import WorldStatistics
    from gz.transport13 import Node
    node = Node()
    st = {"sim_t": None, "rtf": None}

    def cb(msg):
        st["sim_t"] = msg.sim_time.sec + msg.sim_time.nsec * 1e-9
        if msg.real_time_factor > 0:
            st["rtf"] = msg.real_time_factor

    node.subscribe(WorldStatistics, f"/world/{args.world}/stats", cb)

    try:
        t0 = time.time()
        while st["sim_t"] is None:
            if time.time() - t0 > 40:
                raise RuntimeError(
                    f"no sim clock on /world/{args.world}/stats in 40 s "
                    "(server running with -r? correct --world name?)")
            time.sleep(0.1)

        # CRITICAL: /stats publishes a FROZEN clock while the world is still
        # loading (hundreds of instance meshes + collisions can take minutes),
        # so measuring on a fixed settle can catch pure load time and report a
        # bogus RTF of ~0. Wait until sim_time actually ADVANCES (stepping has
        # begun) before the window opens; record the load wait as a byproduct.
        load_t0 = time.time()
        s0 = st["sim_t"]
        while st["sim_t"] - s0 < 0.05:
            if time.time() - load_t0 > args.load_timeout:
                stalled = True
                break
            time.sleep(0.2)
        else:
            stalled = False
        load_wait = round(time.time() - load_t0, 1)
        if not stalled:
            time.sleep(args.settle)   # let RTF settle after stepping starts

        samples = []
        start_sim, start_wall = st["sim_t"], time.time()
        while time.time() - start_wall < args.secs:
            if st["rtf"] is not None:
                samples.append(st["rtf"])
            time.sleep(0.2)
        end_sim, end_wall = st["sim_t"], time.time()
    finally:
        for s in subs:
            s.terminate()
        gz.terminate()
        try:
            gz.wait(timeout=10)
        except subprocess.TimeoutExpired:
            gz.kill()
        log.close()

    arr = np.asarray(samples, float)
    window_rtf = ((end_sim - start_sim) / (end_wall - start_wall)
                  if end_wall > start_wall else float("nan"))
    out = {
        "tag": args.tag,
        "world": args.world,
        "window_rtf": round(window_rtf, 3),
        "rtf_mean": round(float(arr.mean()), 3) if len(arr) else None,
        "rtf_median": round(float(np.median(arr)), 3) if len(arr) else None,
        "rtf_min": round(float(arr.min()), 3) if len(arr) else None,
        "rtf_p10": round(float(np.percentile(arr, 10)), 3) if len(arr) else None,
        "sim_advanced_s": round(end_sim - start_sim, 2),
        "wall_elapsed_s": round(end_wall - start_wall, 2),
        "load_wait_s": load_wait,
        "stalled": stalled,
        "n_samples": len(arr),
        "sensor_subs": not args.no_sensor_subs,
    }
    print(json.dumps(out, indent=2), flush=True)
    json.dump(out, open(f"{FR}/rtf_bench_{args.tag}.json", "w"), indent=2)
    print(f"wrote {FR}/rtf_bench_{args.tag}.json", flush=True)


if __name__ == "__main__":
    main()
