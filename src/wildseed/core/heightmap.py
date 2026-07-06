"""Heightmap relief ground (option d2) — cm–dm surface roughness on a flat macro.

The WildSeed mesh path (``terraingen`` + ``terrain``, option d1) is Nyquist-limited
to ≳1.2 m relief, so making surface *texture* there forces amplitude → slope → an
un-drivable macro. A gz ``<heightmap>`` (Ogre2 Terra: GPU-tessellated + LOD'd
render, one static collision surface) instead carries **cm–dm roughness on an
otherwise-flat surface** — VIO/LIO texture without touching the macro slope — at
one-mesh cost (RTF 1.0 measured at 1025²; see ``docs/GROUND_CLUTTER.md``).

This module builds the hi-res heightmap (multi-octave value noise with the LOW
frequencies removed, so there is no macro tilt — pure roughness) and the gz world
skinned with the ground texture, optionally injecting the sensor rig. Exposed as
``wildseed heightmap`` and kept behind ``tools/heightmap_relief.py``.
"""

import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import numpy as np


def is_pow2_plus_1(n: int) -> bool:
    """gz heightmaps require a 2^n+1 side (e.g. 129, 513, 1025)."""
    return n >= 2 and (n - 1) & (n - 2) == 0 and bin(n - 1).count("1") == 1


def fractal_relief(res: int, seed: int) -> np.ndarray:
    """Multi-octave value noise, macro-FLAT (low frequencies skipped), normalized 0..1.

    Same ``(res, seed)`` -> byte-identical array. The lowest octaves (which would
    tilt the whole surface) are skipped so the result is pure roughness on a flat
    macro; that is what keeps the ground drivable while still textured.
    """
    from PIL import Image

    rng = np.random.default_rng(seed)
    acc = np.zeros((res, res), np.float64)
    total = 0.0
    amp = 1.0
    # start at ~res/64 features (skip the low freqs that would tilt the surface)
    # down to a few px.
    for div in (64, 32, 16, 8, 4):
        f = max(res // div, 2)
        coarse = rng.random((f + 1, f + 1))
        img = np.asarray(Image.fromarray((coarse * 255).astype(np.uint8)).resize(
            (res, res), Image.BICUBIC), np.float64) / 255.0
        acc += amp * img
        total += amp
        amp *= 0.6
    acc /= total
    acc -= acc.min()
    acc /= acc.max()
    return acc


def slope_stats(relief_norm: np.ndarray, extent: float, relief: float) -> dict:
    """Surface-slope report for a normalized (0..1) heightmap scaled to `relief` m."""
    res = relief_norm.shape[0]
    dz = relief_norm * relief
    px = extent / (res - 1)
    gy, gx = np.gradient(dz, px)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    return {
        "cm_per_px": float(px * 100.0),
        "relief_m": float(np.ptp(dz)),
        "mean_slope_deg": float(slope.mean()),
        "p95_slope_deg": float(np.percentile(slope, 95)),
    }


def write_heightmap_png(relief_norm: np.ndarray, png_path) -> Path:
    """Write a normalized 0..1 heightmap to an 8-bit grayscale PNG."""
    from PIL import Image
    png_path = Path(png_path)
    png_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((relief_norm * 255).astype(np.uint8), mode="L").save(str(png_path))
    return png_path


def build_heightmap_world(
        png_path,
        world_path,
        extent: float,
        relief: float,
        models_dir,
        rig: bool = False,
        rig_z: float = 2.0,
) -> Path:
    """Write a gz ``<heightmap>`` world skinned with the ground texture.

    ``png_path`` is the heightmap image (already written), ``models_dir`` supplies
    the ground texture (``ground/texture/ground_Color.png`` + ``_NormalGL.png``)
    and, when ``rig`` is set, the sensor-rig models injected at ``(0, 0, rig_z)``.
    Uses the bullet collision detector (heightmaps prefer it) at RTF 1.0.
    """
    png_path = Path(png_path)
    world_path = Path(world_path)
    models_dir = Path(models_dir)
    world_path.parent.mkdir(parents=True, exist_ok=True)

    color = f"file://{models_dir}/ground/texture/ground_Color.png"
    normal = f"file://{models_dir}/ground/texture/ground_NormalGL.png"
    world_name = world_path.stem

    sdf = ET.Element("sdf", version="1.9")
    world = ET.SubElement(sdf, "world", name=world_name)
    phys = ET.SubElement(world, "physics", name="1ms", type="ignored")
    dart = ET.SubElement(phys, "dart")
    ET.SubElement(dart, "collision_detector").text = "bullet"  # heightmaps prefer bullet
    ET.SubElement(phys, "max_step_size").text = "0.003"
    ET.SubElement(phys, "real_time_factor").text = "1.0"
    sun = ET.SubElement(world, "light", type="directional", name="sun")
    ET.SubElement(sun, "cast_shadows").text = "true"
    ET.SubElement(sun, "pose").text = "0 0 10 0 0 0"
    ET.SubElement(sun, "diffuse").text = "0.9 0.9 0.9 1"
    ET.SubElement(sun, "specular").text = "0.3 0.3 0.3 1"
    ET.SubElement(sun, "direction").text = "0.4 0.3 -0.86"
    scene = ET.SubElement(world, "scene")
    ET.SubElement(scene, "ambient").text = "0.35 0.37 0.4 1"
    ET.SubElement(scene, "background").text = "0.7 0.8 0.9 1"
    ET.SubElement(scene, "sky")

    model = ET.SubElement(world, "model", name="heightmap_terrain")
    ET.SubElement(model, "static").text = "true"
    link = ET.SubElement(model, "link", name="link")
    for kind in ("collision", "visual"):
        el = ET.SubElement(link, kind, name=kind)
        hm = ET.SubElement(ET.SubElement(el, "geometry"), "heightmap")
        ET.SubElement(hm, "uri").text = f"file://{png_path}"
        ET.SubElement(hm, "size").text = f"{extent} {extent} {relief}"
        ET.SubElement(hm, "pos").text = "0 0 0"
        if kind == "visual":
            tex = ET.SubElement(hm, "texture")
            ET.SubElement(tex, "size").text = "2"
            ET.SubElement(tex, "diffuse").text = color
            ET.SubElement(tex, "normal").text = normal
            ET.SubElement(hm, "sampling").text = "2"

    ET.indent(sdf, space="  ")
    ET.ElementTree(sdf).write(str(world_path), encoding="unicode", xml_declaration=True)

    if rig:
        from wildseed.core.rig import RigConfig, inject_rig_into_world
        inject_rig_into_world(world_path, RigConfig(), models_dir,
                              rig_pose=(0.0, 0.0, rig_z, 0.0, 0.0, 0.0))
    return world_path


def generate_heightmap_world(
        world_path,
        png_path,
        extent: float = 60.0,
        relief: float = 0.35,
        res: int = 1025,
        seed: int = 7,
        models_dir=None,
        rig: bool = False,
        rig_z: float = 2.0,
) -> dict:
    """End-to-end: fractal relief -> PNG + gz heightmap world. Returns a report dict.

    ``models_dir`` defaults to ``<world_path>/../../models`` (repo layout). Same
    ``(res, seed)`` -> identical PNG; the world file references it by absolute path.
    """
    world_path = Path(world_path)
    png_path = Path(png_path)
    if models_dir is None:
        models_dir = world_path.parent.parent / "models"
    models_dir = Path(models_dir)

    relief_norm = fractal_relief(res, seed)
    write_heightmap_png(relief_norm, png_path)
    stats = slope_stats(relief_norm, extent, relief)
    build_heightmap_world(png_path, world_path, extent, relief, models_dir,
                          rig=rig, rig_z=rig_z)
    return {
        "world": str(world_path),
        "png": str(png_path),
        "res": int(res),
        "extent": float(extent),
        "relief": float(relief),
        "seed": int(seed),
        "rig": bool(rig),
        "pow2_plus_1": is_pow2_plus_1(res),
        **stats,
    }
