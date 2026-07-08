"""Weather post-processor for generated worlds (sun, fog, rain, snow, glare).

Applies a weather preset to an already-generated .world file:

- **sun**: elevation/azimuth/intensity of the directional ``sun`` light —
  ``sunglare`` puts a very bright sun a few degrees above the horizon (plus an
  emissive sun disk model) so forward-facing cameras get real glare/bloom.
- **scene**: ambient + background tint (overcast greys, snow whites).
- **precipitation**: rain/snow/fog as SDF ``<particle_emitter>`` models sized
  to the terrain extent, driven by gz-sim's ``ParticleEmitter`` system (present
  in gz-sim 8 'Harmonic'; the fog approach follows gz's own fog_generator demo,
  since ogre2 has no fixed-function scene fog).

True lens flare is a CAMERA plugin in gz (``gz-sim-lens-flare-system`` attaches
to a ``<sensor>``), and sensors/robots live outside this repo by design — use
:func:`lens_flare_snippet` to get the XML to paste into a camera sensor there.

Emitter orientation gotcha: gz particle emitters emit along the emitter's +X
axis, so the emitter pose pitches ±90° to emit straight down (rain/snow) or up
(fog), exactly like gz's fog_generator example.
"""

import logging
import math
from pathlib import Path
from typing import Dict, Optional, Tuple
from xml.etree import ElementTree as ET

logger = logging.getLogger("wildseed.weather")

WEATHER_PRESETS = ("clear", "overcast", "fog", "rain", "snow", "sunglare")

# Per-preset defaults. Any WeatherConfig field set by the user overrides these.
_PRESETS: Dict[str, dict] = {
    "clear": dict(
        sun_elevation_deg=55.0, sun_azimuth_deg=120.0, sun_intensity=1.0,
        sun_diffuse=(1.0, 1.0, 0.95), sun_specular=(0.3, 0.3, 0.3),
        ambient=(0.4, 0.4, 0.4), background=(0.7, 0.8, 0.9),
        emitter=None),
    "overcast": dict(
        sun_elevation_deg=55.0, sun_azimuth_deg=120.0, sun_intensity=0.35,
        sun_diffuse=(0.75, 0.77, 0.8), sun_specular=(0.05, 0.05, 0.05),
        ambient=(0.55, 0.56, 0.58), background=(0.63, 0.65, 0.68),
        emitter=None),
    "fog": dict(
        sun_elevation_deg=50.0, sun_azimuth_deg=120.0, sun_intensity=0.25,
        sun_diffuse=(0.7, 0.7, 0.72), sun_specular=(0.02, 0.02, 0.02),
        ambient=(0.6, 0.6, 0.62), background=(0.72, 0.73, 0.75),
        emitter=dict(kind="fog", rate=6.0, velocity=(0.03, 0.1), lifetime=40.0,
                     particle_size=5.0, scale_rate=1.0, height=6.0,
                     color=(0.78, 0.79, 0.81))),
    "rain": dict(
        sun_elevation_deg=45.0, sun_azimuth_deg=120.0, sun_intensity=0.25,
        sun_diffuse=(0.55, 0.57, 0.62), sun_specular=(0.05, 0.05, 0.05),
        ambient=(0.45, 0.46, 0.5), background=(0.5, 0.52, 0.56),
        emitter=dict(kind="rain", rate=600.0, velocity=(7.0, 10.0),
                     particle_size=0.06, scale_rate=0.0,
                     color=(0.75, 0.8, 0.88))),
    "snow": dict(
        sun_elevation_deg=40.0, sun_azimuth_deg=120.0, sun_intensity=0.45,
        sun_diffuse=(0.85, 0.86, 0.88), sun_specular=(0.1, 0.1, 0.1),
        ambient=(0.62, 0.63, 0.65), background=(0.78, 0.79, 0.81),
        emitter=dict(kind="snow", rate=400.0, velocity=(0.5, 1.2),
                     particle_size=0.12, scale_rate=0.0,
                     color=(1.0, 1.0, 1.0))),
    "sunglare": dict(
        sun_elevation_deg=10.0, sun_azimuth_deg=120.0, sun_intensity=5.0,
        sun_diffuse=(1.0, 0.98, 0.92), sun_specular=(1.0, 1.0, 1.0),
        ambient=(0.42, 0.42, 0.44), background=(0.82, 0.86, 0.92),
        emitter=None, sun_disk=True),
}


def sun_direction(elevation_deg: float, azimuth_deg: float) -> Tuple[float, float, float]:
    """Unit vector the sunLIGHT travels along (from sun towards the scene).

    Azimuth is measured from +X (east) counter-clockwise, elevation above the
    horizon; the returned direction points down into the scene.
    """
    el = math.radians(elevation_deg)
    az = math.radians(azimuth_deg)
    return (-math.cos(el) * math.cos(az),
            -math.cos(el) * math.sin(az),
            -math.sin(el))


def lens_flare_snippet(scale: float = 1.0,
                       color: Tuple[float, float, float] = (1.0, 0.9, 0.8)) -> str:
    """XML to paste inside a ``<sensor type="camera">`` in the robot repo.

    gz's lens flare is a per-camera plugin, so it cannot live in the world file
    this repo generates; pair it with the ``sunglare`` preset.
    """
    return (f'<plugin filename="gz-sim-lens-flare-system" '
            f'name="gz::sim::systems::LensFlare">\n'
            f'    <scale>{scale:g}</scale>\n'
            f'    <color>{color[0]:g} {color[1]:g} {color[2]:g}</color>\n'
            f'</plugin>')


def _terrain_extent_m(models_dir: Path) -> Tuple[float, float]:
    """Terrain XY extent from models/ground/mesh/terrain.stl (fallback 160x160)."""
    stl_path = Path(models_dir) / "ground" / "mesh" / "terrain.stl"
    if stl_path.exists():
        from stl import mesh as stl_mesh
        pts = stl_mesh.Mesh.from_file(str(stl_path)).vectors.reshape(-1, 3)
        return (float(pts[:, 0].max() - pts[:, 0].min()),
                float(pts[:, 1].max() - pts[:, 1].min()))
    return (160.0, 160.0)


def _particle_texture(kind: str, path: Path) -> None:
    """Write the billboard texture: rain = vertical streak, snow/fog = soft blob."""
    import numpy as np
    from PIL import Image
    n = 64
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    cx = (xx - n / 2 + 0.5) / (n / 2)
    cy = (yy - n / 2 + 0.5) / (n / 2)
    if kind == "rain":
        # thin bright vertical streak, feathered ends
        alpha = np.exp(-(cx / 0.12) ** 2) * np.exp(-(cy / 0.9) ** 4)
    else:
        r = np.sqrt(cx ** 2 + cy ** 2)
        alpha = np.clip(1.0 - r, 0.0, 1.0) ** (2.0 if kind == "snow" else 1.2)
    a8 = (alpha * 255).astype(np.uint8)
    rgba = np.dstack([np.full_like(a8, 255)] * 3 + [a8])
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba, "RGBA").save(path)


def write_weather_model(models_dir: Path, preset: str, spec: dict,
                        extent_m: Tuple[float, float],
                        fall_height_m: float = 20.0,
                        rate: Optional[float] = None) -> Path:
    """Write a ``models/weather_<preset>`` particle-emitter model dir."""
    name = f"weather_{preset}"
    wdir = Path(models_dir) / name
    tex_rel = "materials/textures/particle.png"
    _particle_texture(spec["kind"], wdir / tex_rel)

    ex, ey = extent_m
    vmin, vmax = spec["velocity"]
    use_rate = float(rate if rate is not None else spec["rate"])
    psize = float(spec["particle_size"])
    c = spec["color"]

    if spec["kind"] == "fog":
        # ground-hugging volume, drifting up (gz fog_generator pattern):
        # pitch -90 deg maps emitter +X (emit axis) to world +Z.
        pose = f"0 0 0 0 {-math.pi / 2:.5f} 0"
        size = f"{spec['height']:g} {ey:g} {ex:g}"
        lifetime = spec["lifetime"]
    else:
        # thin sheet at altitude, emitting straight DOWN (pitch +90 deg).
        pose = f"0 0 {fall_height_m:g} 0 {math.pi / 2:.5f} 0"
        size = f"1 {ey:g} {ex:g}"
        lifetime = fall_height_m / vmin + 1.0

    (wdir / "model.config").write_text(
        f'<?xml version="1.0"?>\n<model>\n  <name>{name}</name>\n'
        f'  <version>1.0</version>\n  <sdf version="1.8">model.sdf</sdf>\n'
        f'  <description>WildSeed weather: {preset} particle emitter</description>\n</model>\n')
    (wdir / "model.sdf").write_text(f'''<?xml version="1.0" ?>
<sdf version="1.8">
    <model name="{name}">
        <static>true</static>
        <link name="link">
            <particle_emitter name="{name}_emitter" type="box">
                <emitting>true</emitting>
                <pose>{pose}</pose>
                <size>{size}</size>
                <particle_size>{psize:g} {psize:g} {psize:g}</particle_size>
                <lifetime>{lifetime:g}</lifetime>
                <rate>{use_rate:g}</rate>
                <min_velocity>{vmin:g}</min_velocity>
                <max_velocity>{vmax:g}</max_velocity>
                <scale_rate>{spec["scale_rate"]:g}</scale_rate>
                <material>
                    <diffuse>{c[0]:g} {c[1]:g} {c[2]:g}</diffuse>
                    <pbr><metal><albedo_map>{tex_rel}</albedo_map></metal></pbr>
                </material>
            </particle_emitter>
        </link>
    </model>
</sdf>''')
    return wdir


def _set_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = parent.find(tag)
    if el is None:
        el = ET.SubElement(parent, tag)
    el.text = text
    return el


def apply_weather(world_path: Path, preset: str, models_dir: Path,
                  sun_elevation_deg: Optional[float] = None,
                  sun_azimuth_deg: Optional[float] = None,
                  sun_intensity: Optional[float] = None,
                  particle_rate: Optional[float] = None,
                  fall_height_m: float = 20.0,
                  sun_disk: Optional[bool] = None,
                  out_path: Optional[Path] = None) -> dict:
    """Apply a weather preset to a generated world (idempotent, re-runnable).

    Rewrites the ``sun`` light + ``<scene>``, removes any previous
    ``weather_*`` include, and (for fog/rain/snow) writes the particle-emitter
    model and includes it. Returns a summary dict.
    """
    if preset not in _PRESETS:
        raise ValueError(f"unknown weather preset {preset!r}; expected one of {WEATHER_PRESETS}")
    p = dict(_PRESETS[preset])
    elev = sun_elevation_deg if sun_elevation_deg is not None else p["sun_elevation_deg"]
    azim = sun_azimuth_deg if sun_azimuth_deg is not None else p["sun_azimuth_deg"]
    inten = sun_intensity if sun_intensity is not None else p["sun_intensity"]

    world_path = Path(world_path)
    tree = ET.parse(world_path)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        raise ValueError(f"{world_path}: no <world> element")

    # --- sun -------------------------------------------------------------- #
    sun = None
    for light in world.findall("light"):
        if light.get("name") == "sun":
            sun = light
            break
    if sun is None:
        sun = ET.SubElement(world, "light", {"name": "sun", "type": "directional"})
        _set_text(sun, "cast_shadows", "true")
        _set_text(sun, "pose", "0 0 50 0 0 0")
    d = sun_direction(elev, azim)
    _set_text(sun, "direction", f"{d[0]:.4f} {d[1]:.4f} {d[2]:.4f}")
    sd, ss = p["sun_diffuse"], p["sun_specular"]
    _set_text(sun, "diffuse", f"{sd[0]:g} {sd[1]:g} {sd[2]:g} 1")
    _set_text(sun, "specular", f"{ss[0]:g} {ss[1]:g} {ss[2]:g} 1")
    _set_text(sun, "intensity", f"{inten:g}")

    # --- scene ------------------------------------------------------------ #
    scene = world.find("scene")
    if scene is None:
        scene = ET.SubElement(world, "scene")
    amb, bg = p["ambient"], p["background"]
    _set_text(scene, "ambient", f"{amb[0]:g} {amb[1]:g} {amb[2]:g} 1")
    _set_text(scene, "background", f"{bg[0]:g} {bg[1]:g} {bg[2]:g} 1")

    # --- clear previous weather artifacts (idempotence) -------------------- #
    for inc in list(world.findall("include")):
        uri = inc.findtext("uri", "")
        if uri.startswith("model://weather_"):
            world.remove(inc)
    for model in list(world.findall("model")):
        if (model.get("name") or "").startswith("weather_"):
            world.remove(model)

    # --- precipitation emitter --------------------------------------------- #
    emitted = None
    if p.get("emitter"):
        # the ParticleEmitter system must be loaded for emitters to run
        have_plugin = any("particle-emitter" in (pl.get("filename") or "")
                          for pl in world.findall("plugin"))
        if not have_plugin:
            plug = ET.SubElement(world, "plugin")
            plug.set("filename", "gz-sim-particle-emitter-system")
            plug.set("name", "gz::sim::systems::ParticleEmitter")
        extent = _terrain_extent_m(models_dir)
        wdir = write_weather_model(models_dir, preset, p["emitter"], extent,
                                   fall_height_m=fall_height_m, rate=particle_rate)
        inc = ET.SubElement(world, "include")
        ET.SubElement(inc, "uri").text = f"model://{wdir.name}"
        ET.SubElement(inc, "name").text = wdir.name
        ET.SubElement(inc, "pose").text = "0 0 0 0 0 0"
        emitted = str(wdir)

    # --- emissive sun disk (visible glare source for cameras) -------------- #
    use_disk = sun_disk if sun_disk is not None else p.get("sun_disk")
    if use_disk:
        dist = 500.0
        sx, sy, sz = (-d[0] * dist, -d[1] * dist, -d[2] * dist)
        disk = ET.SubElement(world, "model", {"name": "weather_sun_disk"})
        _set_text(disk, "static", "true")
        _set_text(disk, "pose", f"{sx:.1f} {sy:.1f} {sz:.1f} 0 0 0")
        link = ET.SubElement(disk, "link", {"name": "link"})
        vis = ET.SubElement(link, "visual", {"name": "visual"})
        geom = ET.SubElement(vis, "geometry")
        sph = ET.SubElement(geom, "sphere")
        _set_text(sph, "radius", "20")
        mat = ET.SubElement(vis, "material")
        _set_text(mat, "ambient", "1 1 0.95 1")
        _set_text(mat, "diffuse", "1 1 0.95 1")
        _set_text(mat, "emissive", "1 1 0.9 1")
        ET.SubElement(vis, "cast_shadows").text = "false"

    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    out = Path(out_path) if out_path else world_path
    tree.write(str(out), encoding="utf-8", xml_declaration=True)
    info = {"preset": preset, "world": str(out), "sun_elevation_deg": elev,
            "sun_azimuth_deg": azim, "sun_intensity": inten, "emitter": emitted}
    logger.info(f"weather: {info}")
    return info
