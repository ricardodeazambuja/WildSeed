"""Density-map generators for steered scatter placement.

A grayscale density map steers `generate --density-maps`: pixel intensity is
placement probability (white = dense, black = never), stretched over the full
terrain extent north-up (row 0 = +Y edge, col 0 = -X edge — see
``core/forest._sample_map_position``). The classic use is a *driving corridor*:
concentrate a small (RTF-bounded) TOTAL object budget into the narrow strip a
ground robot's camera/LIDAR actually see, giving high LOCAL density in view.

The shape is fully determined by its geometry args (no RNG); the OBJECTS placed
into it are seeded by ``generate --seed``. See ``docs/GROUND_CLUTTER.md`` (option
(c), steered scatter) and the thin CLI ``wildseed corridor-map``.
"""

from pathlib import Path
from typing import Tuple

import numpy as np

# intensity <= this fraction of the corridor half-width edge for the soft taper;
# 1.517 puts the Gaussian at ~0.1 at the nominal half-width (kept from the study).
_SOFT_SIGMA_DIVISOR = 1.517


def terrain_extent_y(obj_path) -> Tuple[float, float]:
    """Return (min_y, max_y) span of a terrain OBJ's vertices.

    Reads ``models/ground/mesh/terrain.obj`` (or any wavefront OBJ); used to
    stretch a density map over the actual generated terrain.
    """
    ys = []
    with open(obj_path) as f:
        for line in f:
            if line.startswith("v "):
                ys.append(float(line.split()[2]))
    if not ys:
        raise ValueError(f"no vertices in {obj_path}")
    a = np.asarray(ys, np.float64)
    return float(a.min()), float(a.max())


def build_corridor_map(
        extent_m: float,
        half_width_m: float,
        y0: float = 0.0,
        res: int = 512,
        soft: bool = False,
) -> np.ndarray:
    """Paint a driving-corridor density map.

    A white band of half-width ``half_width_m`` metres runs along the +X drive
    line at world Y = ``y0``, over a square terrain of side ``extent_m`` (assumed
    centred at the origin, matching generated terrains). ``soft`` tapers the band
    to its edges with a Gaussian instead of a hard edge.

    Returns a ``(res, res)`` uint8 array, north-up (row 0 = +Y edge). Shape is
    deterministic — no RNG.
    """
    min_y, max_y = -extent_m / 2.0, extent_m / 2.0
    span = max_y - min_y

    h = w = int(res)
    rows = np.arange(h)
    v = (rows + 0.5) / h
    world_y = max_y - v * span                 # (h,) — row 0 -> +Y
    d = np.abs(world_y - y0)                    # metres from corridor centre-line

    if soft:
        sigma = half_width_m / _SOFT_SIGMA_DIVISOR
        col = np.exp(-0.5 * (d / sigma) ** 2)
    else:
        col = (d <= half_width_m).astype(np.float64)

    img = np.repeat(col[:, None], w, axis=1)   # constant along X (whole drive line)
    return np.clip(img * 255.0, 0, 255).astype(np.uint8)


def white_fraction(img8: np.ndarray, thresh: int = 12) -> float:
    """Fraction of the map above ``thresh`` (the placeable corridor area)."""
    return float((img8 > thresh).mean())


def save_png(img8: np.ndarray, path) -> Path:
    """Write a uint8 grayscale array to ``path`` as an 8-bit PNG."""
    from PIL import Image
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(img8, mode="L").save(str(path))
    return path
