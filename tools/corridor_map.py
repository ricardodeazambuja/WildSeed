#!/usr/bin/env python3
"""Corridor density-map generator (option (c) c1) — concentrate the object budget
into the band the vehicle actually drives.

The whole point of steered scatter: a ground robot's camera/LIDAR only see a narrow
strip around its path, so a small TOTAL object count (RTF-bounded) can still give a HIGH
LOCAL density in view. This paints a white driving corridor onto a black field; feed the
PNG to `wildseed generate --density-maps` (white=dense, black=never — placement is
intensity-proportional, so every requested instance lands in the white band).

The image is stretched over the FULL terrain extent, north-up (row 0 = +Y edge, col 0 =
-X edge — see core/forest._sample_map_position). By default the corridor runs straight
along the +X drive line at y=0 (matching tools/vio_bench.py's canonical trajectory), with
`--soft` tapering density to the corridor edges (Gaussian) so it reads naturally.

USAGE
  python3 tools/corridor_map.py --out corridor.png --half-width 6 --soft
  python3 tools/corridor_map.py --out c.png --y0 0 --half-width 10 --res 512 --extent 305.6
Then:
  wildseed generate --density-maps '{"rock":"corridor.png","bush":"corridor.png"}' \
      --density '{"rock":200,"bush":300,"tree":0,"grass":0,"sand":0}'
"""
import argparse
import os

import numpy as np

WS = os.environ.get("WS", os.getcwd())
OBJ = os.path.join(WS, "models", "ground", "mesh", "terrain.obj")


def terrain_extent(obj_path):
    """Return (min_y, max_y) span of the terrain OBJ (assumed square, centred)."""
    ys = []
    with open(obj_path) as f:
        for line in f:
            if line.startswith("v "):
                ys.append(float(line.split()[2]))
    a = np.asarray(ys, np.float64)
    return float(a.min()), float(a.max())


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
        min_y, max_y = -args.extent / 2.0, args.extent / 2.0
    else:
        min_y, max_y = terrain_extent(OBJ)
    span = max_y - min_y

    h = w = args.res
    # Row -> world Y (north-up): row 0 maps to +Y (max_y).
    rows = np.arange(h)
    v = (rows + 0.5) / h
    world_y = max_y - v * span                 # (h,)
    d = np.abs(world_y - args.y0)              # metres from corridor centre-line

    if args.soft:
        # sigma chosen so intensity ~0.1 at the nominal half-width edge.
        sigma = args.half_width / 1.517
        col = np.exp(-0.5 * (d / sigma) ** 2)
    else:
        col = (d <= args.half_width).astype(np.float64)

    img = np.repeat(col[:, None], w, axis=1)   # constant along X (whole drive line)
    img8 = np.clip(img * 255.0, 0, 255).astype(np.uint8)

    from PIL import Image
    Image.fromarray(img8, mode="L").save(args.out)
    frac = float((img8 > 12).mean())
    print(f"wrote {args.out} ({w}x{h}); corridor y0={args.y0} half-width={args.half_width} m "
          f"over extent {span:.1f} m; white/soft area frac ~{frac:.3f}", flush=True)


if __name__ == "__main__":
    main()
