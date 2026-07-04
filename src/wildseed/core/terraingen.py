"""Seeded procedural terrain (DEM) synthesizer for WildSeed.

Synthesizes a heightfield and writes it as a GeoTIFF so it can be fed to the
existing, proven ``wildseed terrain --dem <synth.tif>`` pipeline **unchanged** --
the mesh, UVs, ground compositor, water plane and seeded placement all already
work on any DEM. This is the last missing piece of the "randomize a whole
scenario for VIO/lidar testing" goal: the same ``seed`` gives the same landform,
a new seed a new one.

Landform vocabulary: rolling hills (fBm), peaks/mounts, ridged valleys, gentle
flatlands, basins (mini-lakes) and meandering creeks. Features compose additively
in *metres* on top of an fBm base so physical depths (lake/creek carve) stay
meaningful -- important because the water plane is placed by absolute Z.

Coordinate contract (matches ``core/terrain.py``):
  - The terrain pipeline shifts the meshed Z so ``min == 0`` and (by default,
    ``scale_factor == z_scale == 1``) keeps Z in metres. So we likewise emit a
    heightfield with ``min == 0`` in metres. A basin floor at height ``f`` in our
    array therefore lands at mesh Z ``f``, and the recommended ``--water-level``
    we report is in that same post-shift frame (``floor + freeboard``).
  - The pipeline reads only the geotransform *pixel size* (and ``abs()``-es it),
    so a bare north-up geotransform is enough; CRS is optional (set for parity).
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.ndimage import gaussian_filter, zoom

try:
    from osgeo import gdal, osr
    GDAL_AVAILABLE = True
except ImportError:
    GDAL_AVAILABLE = False

logger = logging.getLogger("wildseed.terraingen")


# --------------------------------------------------------------------------- #
# Presets: feature-parameter bundles, like ``core/ground.py::BIOMES``. Any field
# the CLI/config sets explicitly overrides the preset; everything is seeded.
# Distances are in metres. Tuple fields are (min, max) sampled per feature.
# Keep the key set in sync with ``schema.PRESET_NAMES``.
# --------------------------------------------------------------------------- #
PRESETS: Dict[str, dict] = {
    "hilly": dict(
        amplitude_m=30.0, roughness=0.5, octaves=5, feature_m=90.0, ridged=0.0,
        slope_m=0.0, valley=False,
        n_peaks=0, n_basins=0, n_creeks=0,
    ),
    "flat": dict(
        amplitude_m=4.0, roughness=0.35, octaves=4, feature_m=150.0, ridged=0.0,
        slope_m=4.0, valley=False,
        n_peaks=0, n_basins=0, n_creeks=0,
    ),
    "mountainous": dict(
        amplitude_m=85.0, roughness=0.65, octaves=6, feature_m=70.0, ridged=0.5,
        slope_m=0.0, valley=False,
        n_peaks=3, peak_h_m=(25.0, 55.0), peak_r_m=(28.0, 55.0),
        n_basins=0, n_creeks=0,
    ),
    "valley": dict(
        amplitude_m=45.0, roughness=0.45, octaves=5, feature_m=85.0, ridged=0.35,
        slope_m=0.0, valley=True,
        n_peaks=0, n_basins=0,
        n_creeks=1, creek_depth_m=5.0, creek_width_m=24.0,
    ),
    "lakeland": dict(
        amplitude_m=22.0, roughness=0.45, octaves=5, feature_m=110.0, ridged=0.0,
        slope_m=0.0, valley=False, edge_taper=0.05,  # less taper -> no flooded perimeter ring
        n_peaks=0,
        n_basins=2, basin_depth_m=(7.0, 11.0), basin_r_m=(30.0, 48.0),
        n_creeks=1, creek_depth_m=3.5, creek_width_m=18.0,
    ),
}

# Defaults for feature params that not every preset names.
_FEATURE_DEFAULTS = dict(
    peak_h_m=(20.0, 45.0), peak_r_m=(25.0, 50.0),
    basin_depth_m=(6.0, 10.0), basin_r_m=(28.0, 45.0),
    creek_depth_m=3.5, creek_width_m=18.0,
    edge_taper=0.12, smooth_sigma=0.8, detail=1.0,
)


class TerrainSynthesizer:
    """Build a seeded heightfield and write it as a GeoTIFF DEM.

    Config is duck-typed (mirrors ``core/ground.py``): any attribute left as
    ``None`` falls back to the preset, then to ``_FEATURE_DEFAULTS``.
    """

    def __init__(self, config=None):
        self.cfg = config

    # ---- param resolution ------------------------------------------------- #
    def _preset(self) -> dict:
        name = getattr(self.cfg, "preset", "hilly") or "hilly"
        return PRESETS.get(name, PRESETS["hilly"])

    def _p(self, key, default=None):
        """Resolve a param: explicit config override > preset > feature default."""
        v = getattr(self.cfg, key, None) if self.cfg is not None else None
        if v is not None:
            return v
        preset = self._preset()
        if key in preset:
            return preset[key]
        return _FEATURE_DEFAULTS.get(key, default)

    # ---- noise primitives ------------------------------------------------- #
    # Octaves kept at full weight before `detail` starts attenuating (these carry
    # the macro/meso landform -- mountains, hills, rolling undulation).
    _MACRO_OCTAVES = 3

    @staticmethod
    def _fbm01(res: int, rng: np.random.Generator, octaves: int,
               feature_m: float, pixel_m: float, roughness: float,
               detail: float = 1.0) -> np.ndarray:
        """fBm value noise in [0,1]. Coarse-then-zoom (full-res filter is slow).

        `detail` (0..1) scales only the FINE octaves (index >= _MACRO_OCTAVES),
        leaving the macro/meso octaves untouched -- so it controls local surface
        smoothness ("sponginess") while preserving the global hill/mountain
        pattern. `detail == 1.0` reproduces the plain fBm exactly. `roughness`
        (persistence) instead attenuates *all* octaves above the first, so it
        flattens the rolling mid-scale character along with the fine bumps.
        """
        octaves = max(int(octaves), 1)
        macro = min(TerrainSynthesizer._MACRO_OCTAVES, octaves)
        detail = float(np.clip(detail, 0.0, 1.0))
        work = int(min(res, 256))
        # feature size of the coarsest octave, in working-grid pixels
        sigma = max(feature_m / pixel_m * work / res, 1.0)
        # Generate each octave on a grid padded by ~3*sigma and crop the centre.
        # gaussian_filter's boundary handling (reflect/etc.) makes a large-sigma
        # blur converge symmetrically toward the grid centre -> a faint radial
        # "star" in shaded renders (busy presets like mountainous). Padding pushes
        # all boundary effects outside the kept region, independent of mode.
        pad = int(min(work, np.ceil(3.0 * sigma)))
        out = np.zeros((work, work), np.float32)
        amp, total = 1.0, 0.0
        for i in range(octaves):
            base = rng.standard_normal((work + 2 * pad, work + 2 * pad)).astype(np.float32)
            n = gaussian_filter(base, sigma=max(sigma, 0.8))[pad:pad + work, pad:pad + work]
            w = amp if i < macro else amp * detail  # attenuate fine octaves only
            out += w * n
            total += w
            amp *= roughness
            sigma *= 0.5
        out /= total if total > 0 else 1.0
        out -= out.min()
        mx = out.max()
        if mx > 0:
            out /= mx
        if work != res:
            # cubic (order=3) upscale: bilinear (order=1) leaves axis-aligned
            # interpolation streaks that stack into a faint radial "star" in the
            # grid centre on busy presets (mountainous). mode='nearest' avoids
            # cubic edge ringing/darkening at the borders.
            out = zoom(out, res / work, order=3, mode="nearest").astype(np.float32)
            out = np.clip(out, 0.0, 1.0)
            if out.shape[0] >= res:
                out = out[:res, :res]
            else:
                out = np.pad(out, ((0, res - out.shape[0]), (0, res - out.shape[1])), mode="edge")
        return out

    @staticmethod
    def _bump(res: int, cx: float, cy: float, sigma_px: float) -> np.ndarray:
        yy, xx = np.mgrid[0:res, 0:res]
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        return np.exp(-d2 / (2.0 * max(sigma_px, 1.0) ** 2)).astype(np.float32)

    @staticmethod
    def _polyline_dist(res: int, pts_px: np.ndarray) -> np.ndarray:
        """Min distance (in px) from every cell to a polyline (same math as the
        ground trail mask, but used to carve height rather than texture)."""
        yy, xx = np.mgrid[0:res, 0:res]
        dist = np.full((res, res), 1e9, np.float32)
        for i in range(len(pts_px) - 1):
            p, q = pts_px[i], pts_px[i + 1]
            seg = q - p
            L2 = float((seg ** 2).sum()) or 1.0
            t = np.clip(((xx - p[0]) * seg[0] + (yy - p[1]) * seg[1]) / L2, 0.0, 1.0)
            px = p[0] + t * seg[0]
            py = p[1] + t * seg[1]
            dist = np.minimum(dist, np.sqrt((xx - px) ** 2 + (yy - py) ** 2))
        return dist

    @staticmethod
    def _meander_px(rng: np.random.Generator, res: int, n: int = 7, margin: float = 0.1) -> np.ndarray:
        """Meandering waypoints across the map (px), like ground._random_walk_uv."""
        horizontal = rng.random() < 0.5
        a = rng.uniform(margin, 1 - margin)
        pts = []
        for i in range(n):
            t = margin + (1 - 2 * margin) * i / (n - 1)
            a = float(np.clip(a + rng.uniform(-0.18, 0.18), margin, 1 - margin))
            uv = (a, t) if horizontal else (t, a)
            pts.append((uv[0] * res, uv[1] * res))
        return np.array(pts, np.float32)

    # ---- synthesis -------------------------------------------------------- #
    def synthesize(self) -> Tuple[np.ndarray, List[dict]]:
        """Return (heightfield in metres with min==0, list of lake dicts)."""
        res = int(self._p("resolution", 192))
        pixel_m = float(self._p("pixel_m", 2.5))
        scale = float(getattr(self.cfg, "scale_factor", 1.0) or 1.0)  # informational, for lake XY
        rng = np.random.default_rng(int(self._p("seed", 0)))

        amplitude = float(self._p("amplitude_m"))
        roughness = float(self._p("roughness"))
        octaves = int(self._p("octaves"))
        feature_m = float(self._p("feature_m"))
        ridged = float(self._p("ridged", 0.0))
        slope_m = float(self._p("slope_m", 0.0))
        valley = bool(self._p("valley", False))
        detail = float(self._p("detail", 1.0))

        # 1. base field in [0,1]
        g = self._fbm01(res, rng, octaves, feature_m, pixel_m, roughness, detail)
        if ridged > 0.0:
            g = (1.0 - ridged) * g + ridged * (1.0 - np.abs(2.0 * g - 1.0))
        if valley:
            yy, xx = np.mgrid[0:res, 0:res]
            horizontal = rng.random() < 0.5
            coord = (xx if horizontal else yy).astype(np.float32)
            c = res * float(rng.uniform(0.4, 0.6))
            halfw = res * 0.30
            trough = np.clip(1.0 - ((coord - c) / halfw) ** 2, 0.0, 1.0)
            g = np.clip(g - 0.7 * trough, 0.0, None)
        # gentle edge taper of the relief so the terrain doesn't end on a cliff
        taper = float(self._p("edge_taper", 0.12))
        if taper > 0.0:
            ramp = np.clip(np.linspace(0.0, 1.0, res) / max(taper, 1e-3), 0.0, 1.0)
            win = np.minimum(ramp, ramp[::-1])
            window = np.outer(win, win)
            lo = 0.55  # how far edges relax toward the floor (not all the way -> no moat)
            g = g * (lo + (1.0 - lo) * window)
        # renormalize to [0,1]
        g -= g.min()
        mx = g.max()
        if mx > 0:
            g /= mx

        # 2. to metres + optional planar slope (flatlands)
        H = g * amplitude
        if slope_m > 0.0:
            ramp = np.linspace(0.0, slope_m, res, dtype=np.float32)
            if rng.random() < 0.5:
                H = H + ramp[None, :]
            else:
                H = H + ramp[:, None]

        # 3. peaks / mounts (add metres)
        n_peaks = int(self._p("n_peaks", 0))
        if n_peaks > 0:
            ph = self._p("peak_h_m")
            pr = self._p("peak_r_m")
            for _ in range(n_peaks):
                cx = rng.uniform(0.2, 0.8) * res
                cy = rng.uniform(0.2, 0.8) * res
                h = rng.uniform(ph[0], ph[1])
                r_m = rng.uniform(pr[0], pr[1])
                H = H + h * self._bump(res, cx, cy, r_m / pixel_m)

        # 4. basins -> mini-lakes (carve metres); record floor for water level
        lakes: List[dict] = []
        n_basins = int(self._p("n_basins", 0))
        basin_centers = []
        if n_basins > 0:
            bd = self._p("basin_depth_m")
            br = self._p("basin_r_m")
            for _ in range(n_basins):
                cx = rng.uniform(0.25, 0.75) * res
                cy = rng.uniform(0.25, 0.75) * res
                depth = rng.uniform(bd[0], bd[1])
                r_m = rng.uniform(br[0], br[1])
                H = H - depth * self._bump(res, cx, cy, r_m / pixel_m)
                basin_centers.append((cx, cy, depth, r_m))

        # 5. creeks (carve a channel; v1: no water ribbon)
        n_creeks = int(self._p("n_creeks", 0))
        if n_creeks > 0:
            cdepth = float(self._p("creek_depth_m"))
            cwidth = float(self._p("creek_width_m"))
            half_px = max(cwidth / pixel_m / 2.0, 3.0)  # flat-bed half-width
            bank_px = max(half_px * 0.8, 2.0)           # sloped banks beyond the bed
            for _ in range(n_creeks):
                pts = self._meander_px(rng, res)
                dist = self._polyline_dist(res, pts)
                # flat-bottomed channel: full depth within the bed, linear banks out.
                # A flat bed reads as a creek far better than a thin V that the two
                # downstream smoothing passes (ours + the terrain pipeline's) erode.
                carve = cdepth * np.clip((half_px + bank_px - dist) / bank_px, 0.0, 1.0)
                carve = gaussian_filter(carve, sigma=0.5)  # soften shoulders only
                H = H - carve

        # 6. anti-facet smooth + shift so min == 0 (the coordinate contract)
        smooth_sigma = float(self._p("smooth_sigma", 0.8))
        if smooth_sigma > 0.0:
            H = gaussian_filter(H, sigma=smooth_sigma)
        H = H - float(H.min())

        # 6b. ground-robot slope cap. A preset can draw amplitude ~ feature
        # wavelength (alpine drew A/λ ≈ 1.2 for seed 42 → mean mesh slope 52°,
        # >90 % of the map steeper than a UGV can climb — nothing natural looks
        # like that at metre scale). Mean slope is LINEAR in the height scale,
        # so one rescale meets the target exactly; applied after smoothing
        # (which changes gradients) and before the lake-floor readback (which
        # must see final heights). 0 = off.
        max_slope = float(self._p("max_mean_slope_deg", 0.0))
        if max_slope > 0.0:
            gy, gx = np.gradient(H, pixel_m)
            mean_grad = float(np.mean(np.hypot(gx, gy)))
            target = float(np.tan(np.radians(max_slope)))
            if mean_grad > target:
                k = target / mean_grad
                H *= k
                logger.info(
                    f"terraingen: mean slope "
                    f"{np.degrees(np.arctan(mean_grad)):.1f}° > cap "
                    f"{max_slope:.0f}° — relief scaled by {k:.2f} "
                    f"(z extent {float(np.ptp(H)):.1f} m)")

        # 7. read back lake floor levels in the final (post-shift) frame
        cx_mid = (res - 1) / 2.0
        for (cx, cy, depth, r_m) in basin_centers:
            ri = int(round(np.clip(cy, 0, res - 1)))
            ci = int(round(np.clip(cx, 0, res - 1)))
            floor_z = float(H[ri, ci])
            # enough to read as water in the basin, low enough not to flood
            # surrounding ground (single global plane floods anything below it)
            freeboard = max(0.5, min(0.3 * depth, 1.5))
            level = floor_z + freeboard
            lakes.append({
                "center_px": [ci, ri],
                "center_xy_m": [round((ci - cx_mid) * pixel_m * scale, 3),
                                round((ri - cx_mid) * pixel_m * scale, 3)],
                "radius_m": round(float(r_m), 3),
                "floor_z": round(floor_z, 3),
                "suggested_water_level": round(level, 3),
            })

        return H.astype(np.float32), lakes

    # ---- geotiff ---------------------------------------------------------- #
    def write_geotiff(self, H: np.ndarray, out_tif: Path,
                      lakes: Optional[List[dict]] = None) -> Path:
        if not GDAL_AVAILABLE:
            raise ImportError("GDAL is required to write a DEM. Install with: pip install GDAL")
        out_tif = Path(out_tif)
        out_tif.parent.mkdir(parents=True, exist_ok=True)
        pixel_m = float(self._p("pixel_m", 2.5))
        rows, cols = H.shape
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(str(out_tif), cols, rows, 1, gdal.GDT_Float32)
        # origin arbitrary; north-up; pixel size is all the pipeline reads
        ds.SetGeoTransform((0.0, pixel_m, 0.0, 0.0, 0.0, -pixel_m))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(32633)  # arbitrary UTM, for georef parity with bundled DEM
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.WriteArray(H.astype("float32"))
        band.FlushCache()
        ds = None  # noqa: F841  (closes/flushes the dataset)

        if lakes:
            sidecar = out_tif.parent / (out_tif.stem + ".lakes.json")
            sidecar.write_text(json.dumps({"lakes": lakes}, indent=2))
            logger.info(f"terraingen: wrote {len(lakes)} lake(s) -> {sidecar}")
        return out_tif


def synthesize_dem(config, out_tif: Path) -> dict:
    """Synthesize and write a DEM; return stats + lakes (CLI convenience)."""
    synth = TerrainSynthesizer(config)
    H, lakes = synth.synthesize()
    synth.write_geotiff(H, out_tif, lakes)
    pixel_m = float(synth._p("pixel_m", 2.5))
    rows, cols = H.shape
    return {
        "out": str(out_tif),
        "preset": getattr(config, "preset", "hilly"),
        "seed": int(synth._p("seed", 0)),
        "resolution": int(rows),
        "pixel_m": pixel_m,
        "extent_m": round(cols * pixel_m, 2),
        "z_min": round(float(H.min()), 3),
        "z_max": round(float(H.max()), 3),
        "z_extent": round(float(np.ptp(H)), 3),
        "lakes": lakes,
    }
