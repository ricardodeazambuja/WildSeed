#!/usr/bin/env python3
"""Corridor density-map generator (option (c) c1) — thin shim over the core.

The logic now lives in ``wildseed.core.density_maps`` and is exposed as the CLI
``wildseed corridor-map``; this script is kept so the study's reproduction
commands (``python3 tools/corridor_map.py ...``) keep working unchanged.

Concentrate the object budget into the band the vehicle actually drives: a small
TOTAL object count (RTF-bounded) still gives HIGH LOCAL density in view. Paints a
white driving corridor onto a black field; feed the PNG to
``wildseed generate --density-maps`` (white=dense, black=never — placement is
intensity-proportional, so every requested instance lands in the white band).

USAGE
  python3 tools/corridor_map.py --out corridor.png --half-width 6 --soft
  python3 tools/corridor_map.py --out c.png --y0 0 --half-width 10 --res 512 --extent 305.6
Then:
  wildseed generate --density-maps '{"rock":"corridor.png","bush":"corridor.png"}' \
      --density '{"rock":200,"bush":300,"tree":0,"grass":0,"sand":0}'
"""
import argparse
import os

from wildseed.core.density_maps import (
    build_corridor_map, save_png, terrain_extent_y, white_fraction,
)

WS = os.environ.get("WS", os.getcwd())
OBJ = os.path.join(WS, "models", "ground", "mesh", "terrain.obj")


def main():
    ap = argparse.ArgumentParser(description="Corridor density map for steered scatter.")
    ap.add_argument("--out", required=True, help="Output PNG path.")
    ap.add_argument("--half-width", type=float, default=6.0,
                    help="Corridor half-width in metres (full width = 2x).")
    ap.add_argument("--y0", type=float, default=0.0,
                    help="Corridor centre-line world Y (m). Default 0 = vio_bench drive line.")
    ap.add_argument("--extent", type=float, default=None,
                    help="Terrain side length (m). Default: read models/ground/mesh/terrain.obj.")
    ap.add_argument("--res", type=int, default=512, help="Output image side (px).")
    ap.add_argument("--soft", action="store_true",
                    help="Gaussian taper to corridor edges (else a hard-edged white band).")
    args = ap.parse_args()

    if args.extent is not None:
        extent_m = float(args.extent)
    else:
        min_y, max_y = terrain_extent_y(OBJ)
        extent_m = max_y - min_y

    img8 = build_corridor_map(extent_m, args.half_width, y0=args.y0,
                              res=args.res, soft=args.soft)
    save_png(img8, args.out)
    frac = white_fraction(img8)
    print(f"wrote {args.out} ({args.res}x{args.res}); corridor y0={args.y0} "
          f"half-width={args.half_width} m over extent {extent_m:.1f} m; "
          f"white/soft area frac ~{frac:.3f}", flush=True)


if __name__ == "__main__":
    main()
