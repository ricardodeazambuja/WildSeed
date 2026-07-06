#!/usr/bin/env python3
"""Option (d2) — gz <heightmap> ground with cm–dm relief; thin shim over the core.

The logic now lives in ``wildseed.core.heightmap`` and is exposed as
``wildseed heightmap``; this script is kept so the study's reproduction commands
(``python3 tools/heightmap_relief.py ...``) keep working unchanged.

Writes a hi-res heightmap PNG (multi-octave value noise, low freqs removed → no
macro tilt) + a gz world skinned with the ground texture, then injects the rig.
Measure with the existing gates:
  python3 tools/heightmap_relief.py --out-world worlds/heightmap_d2.world
  python3 tools/rtf_bench.py    --world heightmap_d2 --tag d2   # RTF (V2)
  python3 tools/lidar_spread.py --world heightmap_d2 --tag d2   # LIO roughness (V3)
  python3 tools/vio_bench.py --heightmap dem/hm_d2.png,60,0.35 --tag d2 --agl 2 --pitch 0.35 \
      --step 2.0 --region full --viz                            # camera VIO (V1)
Run inside wildseed:egl from /workspace.
"""
import argparse
import os

from wildseed.core.heightmap import generate_heightmap_world, is_pow2_plus_1

WS = os.environ.get("WS", "/workspace")


def main():
    ap = argparse.ArgumentParser(description="Option d2: hi-res heightmap relief ground.")
    ap.add_argument("--res", type=int, default=1025, help="Heightmap side (must be 2^n+1).")
    ap.add_argument("--extent", type=float, default=60.0, help="Patch side length, m.")
    ap.add_argument("--relief", type=float, default=0.35, help="Max relief height, m.")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out-png", default=f"{WS}/dem/hm_d2.png")
    ap.add_argument("--out-world", default=f"{WS}/worlds/heightmap_d2.world")
    ap.add_argument("--rig-z", type=float, default=2.0, help="Rig height AGL, m.")
    ap.add_argument("--no-rig", action="store_true", help="Skip rig injection (bare world).")
    args = ap.parse_args()

    if not is_pow2_plus_1(args.res):
        print(f"warning: --res {args.res} is not 2^n+1; gz heightmaps require 2^n+1", flush=True)

    info = generate_heightmap_world(
        args.out_world, args.out_png, extent=args.extent, relief=args.relief,
        res=args.res, seed=args.seed, models_dir=f"{WS}/models",
        rig=not args.no_rig, rig_z=args.rig_z)

    print(f"heightmap {args.res}x{args.res} over {args.extent} m ({info['cm_per_px']:.1f} cm/px), "
          f"relief {info['relief_m']:.3f} m, mean_slope {info['mean_slope_deg']:.1f} deg, "
          f"p95 {info['p95_slope_deg']:.1f} deg", flush=True)
    print(f"wrote {args.out_world}", flush=True)
    if not args.no_rig:
        print(f"rig injected at 0,0,{args.rig_z}", flush=True)


if __name__ == "__main__":
    main()
