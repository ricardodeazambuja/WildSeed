"""Build a minimal render world for a meshed terrain (models/ground): an oblique
overview camera + a top-down camera. Optionally include the water plane
(model://water) and graft placed forest models (worlds/forest_world.world).

Env:
  OUT      output world path (default worlds/terrain_scene.world)
  WATER=1  include model://water
  FOREST=1 graft includes from worlds/forest_world.world (trees/rocks/bushes)

Top-down camera looks DOWN with pitch +1.5708 (NOT -1.5708, which looks at sky).
"""
import json
import math
import os
import struct
import xml.etree.ElementTree as ET

OBJ = "/workspace/models/ground/mesh/terrain.obj"
OUT = os.environ.get("OUT", "/workspace/worlds/terrain_scene.world")

# Ground source: a meshed OBJ (default) OR a gz <heightmap> (HEIGHTMAP env, option d2).
# HEIGHTMAP="PNG,EXTENT_m,Z_m" renders a hi-res heightmap instead of the WildSeed mesh —
# carries cm relief (Terra GPU-tessellates + LODs) at one-mesh cost. The rest of the file
# (cameras, VIO_TRAJ) is unchanged; only the ground include + height lookup differ.
HEIGHTMAP = os.environ.get("HEIGHTMAP")
if HEIGHTMAP:
    from PIL import Image
    _hp, _he, _hz = HEIGHTMAP.split(",")
    ext = float(_he)
    _hz = float(_hz)
    import numpy as _np
    _hm = _np.asarray(Image.open(_hp).convert("L"), float) / 255.0 * _hz
    _hn = _hm.shape[0]
    half = ext / 2.0
    minx = miny = -half
    maxx = maxy = half
    minz, maxz = float(_hm.min()), float(_hm.max())
    verts = None

    def _terrain_z(qx, qy):
        # heightmap image is north-up (gz): row 0 = +Y edge, col 0 = -X edge.
        u = (qx + half) / ext
        v = (half - qy) / ext
        c = min(max(int(round(u * (_hn - 1))), 0), _hn - 1)
        r = min(max(int(round(v * (_hn - 1))), 0), _hn - 1)
        return float(_hm[r, c])

    _tex = ("<texture><size>2</size>"
            "<diffuse>file:///workspace/models/ground/texture/ground_Color.png</diffuse>"
            "<normal>file:///workspace/models/ground/texture/ground_NormalGL.png</normal>"
            "</texture><sampling>2</sampling>")
    _GROUND_INC = (
        "<model name='heightmap_terrain'><static>true</static><link name='link'>"
        + "".join(
            f"<{k} name='{k}'><geometry><heightmap>"
            f"<uri>file://{_hp}</uri><size>{ext} {ext} {_hz}</size><pos>0 0 0</pos>"
            + (_tex if k == "visual" else "")
            + "</heightmap></geometry></" + k + ">"
            for k in ("collision", "visual"))
        + "</link></model>")
    print(f"HEIGHTMAP {_hn}x{_hn} ext={ext:.1f} m  z={minz:.2f}..{maxz:.2f}")
else:
    # terrain extent from the meshed OBJ (centred at origin)
    minx = miny = 1e18
    maxx = maxy = maxz = -1e18
    minz = 1e18
    verts = []
    with open(OBJ) as f:
        for line in f:
            if line.startswith("v "):
                p = line.split()
                x, y, z = float(p[1]), float(p[2]), float(p[3])
                verts.append((x, y, z))
                minx, maxx = min(minx, x), max(maxx, x)
                miny, maxy = min(miny, y), max(maxy, y)
                minz, maxz = min(minz, z), max(maxz, z)
    ext = max(maxx - minx, maxy - miny)
    half = ext / 2.0

    def _terrain_z(qx, qy):
        bz, best = minz, 1e18
        for (x, y, z) in verts:
            d = (x - qx) ** 2 + (y - qy) ** 2
            if d < best:
                best, bz = d, z
        return bz

    _GROUND_INC = "<include><name>terrain</name><uri>model://ground</uri></include>"
    print(f"terrain extent={ext:.1f} m  z={minz:.1f}..{maxz:.1f}")

# oblique overview: stand off a corner, elevated, look at the centre/hilltop
cx = -0.62 * ext
cy = -0.62 * ext
cz = maxz + 0.55 * ext
ax, ay, az = 0.0, 0.0, (minz + maxz) / 2.0
yaw = math.atan2(ay - cy, ax - cx)
# gz: looking DOWN is POSITIVE pitch (top-down == +1.5708)
pitch = math.atan2(cz - az, math.hypot(ax - cx, ay - cy))

# top-down
tz = maxz + 0.95 * ext

# hero camera: a GROUND-LEVEL robot-eye view among the vegetation (vs the aerial
# overview) so trees/bushes tower in frame and the scene reads as a populated
# environment, not a textured hill. Sample the terrain height under the eye and aim
# so the camera sits ~3 m above real ground and looks slightly down across a
# populated swath. HERO_* env vars allow quick reframing without code edits.
hex_ = float(os.environ.get("HERO_EX", "-0.28"))
hey_ = float(os.environ.get("HERO_EY", "-0.10"))
hax_ = float(os.environ.get("HERO_AX", "0.05"))
hay_ = float(os.environ.get("HERO_AY", "0.02"))
heye = float(os.environ.get("HERO_EYE", "4.0"))
hx, hy = hex_ * ext, hey_ * ext          # stand inside the field, off-centre
haim_x, haim_y = hax_ * ext, hay_ * ext   # look toward the centre
gz_eye = _terrain_z(hx, hy)
gz_aim = _terrain_z(haim_x, haim_y)
# Eye sits `heye` above the HIGHER of the cam-ground and aim-ground, so on steep
# (mountainous) terrain the camera never ends up buried in / staring into a slope;
# on gentle terrain it stays a few metres up -> a robot-eye view. Always looks
# slightly down (eye above aim), so it never frames into a hillside.
hz = max(gz_eye, gz_aim) + heye
haim_z = gz_aim + 1.5
hyaw = math.atan2(haim_y - hy, haim_x - hx)
hpitch = math.atan2(hz - haim_z, math.hypot(haim_x - hx, haim_y - hy))

SHELL = f'''<?xml version='1.0' encoding='ASCII'?>
<sdf version='1.8'>
  <world name='terrain_scene'>
    <physics name='1ms' type='ode'><max_step_size>0.003</max_step_size><real_time_factor>1.0</real_time_factor></physics>
    <plugin name='gz::sim::systems::Physics'          filename='gz-sim-physics-system'/>
    <plugin name='gz::sim::systems::UserCommands'     filename='gz-sim-user-commands-system'/>
    <plugin name='gz::sim::systems::SceneBroadcaster' filename='gz-sim-scene-broadcaster-system'/>
    <plugin name='gz::sim::systems::Sensors'          filename='gz-sim-sensors-system'><render_engine>ogre2</render_engine></plugin>
    <scene><ambient>0.5 0.5 0.5 1</ambient><background>0.78 0.86 0.94 1</background><grid>false</grid></scene>
    <light name='sun' type='directional'><cast_shadows>1</cast_shadows><pose>0 0 {tz:.1f} 0 0 0</pose>
      <diffuse>1 1 1 1</diffuse><specular>0.2 0.2 0.2 1</specular><direction>-0.4 0.3 -0.9</direction></light>
    {_GROUND_INC}
'''
parts = [SHELL]
if os.environ.get("WATER") == "1":
    # include every water* model dir (single 'water' or per-basin water_0/water_1/...)
    mroot = "/workspace/models"
    waters = sorted(d for d in os.listdir(mroot)
                    if d.startswith("water") and os.path.isdir(os.path.join(mroot, d)))
    for w in waters:
        parts.append(f"    <include><name>{w}</name><uri>model://{w}</uri></include>\n")
    print(f"water models: {waters}")
hero_rocks, hero_trees = [], []  # (x, y, z, scale) of grafted rocks/trees, for the hero cam
# FOREST_WORLD selects which placement world to graft objects from (default the
# `generate` output). vio_bench sets it from --world so a scenario-named world
# (e.g. worlds/vio_lio_7.world) can be benchmarked without renaming files.
_FOREST_WORLD = os.environ.get("FOREST_WORLD", "/workspace/worlds/forest_world.world")
if os.environ.get("FOREST") == "1" and os.path.exists(_FOREST_WORLD):
    incs = ET.parse(_FOREST_WORLD).getroot().find("world").findall("include")
    n = 0
    for inc in incs:
        uri = inc.findtext("uri", "")
        if "model://ground" in uri or "model://water" in uri:
            continue  # we add terrain/water ourselves; avoid duplicate model names
        if uri.startswith("model://weather_"):
            # weather emitters are photometric state, not placement: they render
            # only under GRAFT_SUN (which grafts them itself) — copying them here
            # too made gz abort on the duplicate model name and kill the render.
            continue
        parts.append("    " + ET.tostring(inc, encoding="unicode").strip() + "\n")
        n += 1
        p = inc.findtext("pose", "0 0 0 0 0 0").split()
        try:
            scl = float((inc.findtext("scale", "1 1 1").split() or ["1"])[0])
            pose = (float(p[0]), float(p[1]), float(p[2]), scl)
        except (ValueError, IndexError):
            continue
        if "model://rock" in uri:
            hero_rocks.append(pose + (uri.rstrip("/").rsplit("/", 1)[-1],))
        elif "model://tree" in uri:
            hero_trees.append(pose + (uri.rstrip("/").rsplit("/", 1)[-1],))
    print(f"grafted {n} forest includes ({len(hero_rocks)} rocks, {len(hero_trees)} trees)")


def cam(name, x, y, z, pit, ya, fov=1.1, w=1100, h=750):
    return (f"    <model name='{name}'><static>true</static><pose>{x:.3f} {y:.3f} {z:.3f} 0 {pit:.4f} {ya:.4f}</pose>"
            f"<link name='link'><sensor name='{name}' type='camera'><topic>{name}</topic>"
            f"<always_on>1</always_on><update_rate>5</update_rate>"
            f"<camera><horizontal_fov>{fov}</horizontal_fov><image><width>{w}</width><height>{h}</height></image>"
            f"<clip><near>0.1</near><far>6000</far></clip></camera></sensor></link></model>\n")


# Phase D (DEMO_REALISM_V2): re-pose cam_hero to a GROUND-LEVEL shot framing a landmark
# boulder (foreground) with the populated scene receding behind it + slightly down --
# echoing the originals' composition (big rock fills part of the frame, forest beyond).
# Pick the boulder with the most nearby trees (and, tie-break, the biggest) so the shot
# pairs a hero rock with real midground/background content (depth -> coverage, not a lens
# jammed against one asset). Stand OUTWARD of it (away from the hilltop) looking INWARD so
# the green slope -- not sky -- fills the background. HERO_EX (explicit override) keeps the
# old fixed pose; if no rocks were placed, fall back to the elevated pose computed above.
if hero_rocks and "HERO_EX" not in os.environ:
    def _near(r, radius=55.0):
        return [t for t in hero_trees if math.hypot(t[0] - r[0], t[1] - r[1]) < radius]

    # Real per-model footprint from the GLB bbox (metres, before placement scale).
    # The 1.9-unit heuristic assumed single boulders; the palette now also holds
    # multi-rock SETS tens of metres wide (coast_rocks_*, rock_moss_set_01) whose
    # <scale> says nothing about physical size -- framing one from 6 m fills the
    # lens with rock. Measure, don't assume; fall back to the heuristic on any
    # read failure.
    def _glb_radius(cat, mid):
        try:
            p = f"/workspace/models/{cat}/{mid}/mesh/{mid}.glb"
            with open(p, "rb") as f:
                head = f.read(20)
                jl = struct.unpack("<I", head[12:16])[0]
                g = json.loads(f.read(jl))
            vs = [a for a in g["accessors"]
                  if a.get("type") == "VEC3" and "min" in a and "max" in a]
            dx = max(a["max"][0] for a in vs) - min(a["min"][0] for a in vs)
            dy = max(a["max"][1] for a in vs) - min(a["min"][1] for a in vs)
            return max(dx, dy) / 2.0
        except Exception:
            return None

    _radcache = {}
    def _model_rad(cat, mid):
        if (cat, mid) not in _radcache:
            _radcache[(cat, mid)] = _glb_radius(cat, mid)
        return _radcache[(cat, mid)]

    def _rad_m(r):
        base = _model_rad("rock", r[4])
        return (base if base is not None else 1.9 * 0.6) * r[3]

    def _tree_block_rad(t):
        # How far a tree's foliage reaches from its trunk: half the mesh's XY
        # extent times placement scale (fir/pine canopies are 10+ m wide raw),
        # halved again since bboxes overshoot the visually dense core, plus a
        # 2 m buffer. The sight line must clear this per tree, not a constant.
        base = _model_rad("tree", t[4])
        return 2.0 + 0.5 * (base if base is not None else 3.0) * t[3]

    # Hero candidates: landmark-sized boulders only (sets/slabs excluded), best
    # tree company first. The whole view corridor (camera -> boulder segment)
    # must stay >4 m clear of tree trunks -- a canopy anywhere along the sight
    # line, not just at the lens, blacks out the frame.
    HERO_MAX_RAD = float(os.environ.get("HERO_MAX_RAD", "4.0"))
    ranked = sorted([r for r in hero_rocks if _rad_m(r) <= HERO_MAX_RAD],
                    key=lambda r: (len(_near(r)), _rad_m(r)), reverse=True) \
        or sorted(hero_rocks, key=_rad_m)[:1]   # all huge: least-huge, still framed

    def _corridor(cand):
        rx, ry = cand[0], cand[1]
        rad = _rad_m(cand)
        onorm = math.hypot(rx, ry) or 1.0
        ox, oy = rx / onorm, ry / onorm
        cx_ = rx + ox * (6.0 + rad) - oy * 2.0
        cy_ = ry + oy * (6.0 + rad) + ox * 2.0
        dx, dy = rx - cx_, ry - cy_
        seg2 = dx * dx + dy * dy or 1.0
        margin = 1e9
        for t in hero_trees:
            s = max(0.0, min(1.0, ((t[0] - cx_) * dx + (t[1] - cy_) * dy) / seg2))
            d = math.hypot(t[0] - (cx_ + dx * s), t[1] - (cy_ + dy * s))
            margin = min(margin, d - _tree_block_rad(t))
        return margin, (cx_, cy_)

    R, (clear, cam_pos) = ranked[0], _corridor(ranked[0])
    for cand in ranked:
        c, pos = _corridor(cand)
        if c > 0.0:                            # sight line clears every canopy
            R, clear, cam_pos = cand, c, pos
            break
        if c > clear:                          # keep the least-blocked as fallback
            R, clear, cam_pos = cand, c, pos
    rx, ry, rz, rs = R[:4]
    rad = _rad_m(R)
    local = _near(R) or hero_trees or [R]
    tx = sum(t[0] for t in local) / len(local)
    ty = sum(t[1] for t in local) / len(local)
    onorm = math.hypot(rx, ry) or 1.0
    ox, oy = rx / onorm, ry / onorm           # outward from the hill centre
    hcx, hcy = cam_pos
    # HERO_DOWN raises the eye on FLAT scenes (savanna/coastal) so the shot tilts DOWN
    # into the near field instead of staring level across the horizon -> cuts dead sky
    # (the coverage drag on arid flats) and pushes the tiling-prone foreground sand below
    # the frame centre. No-op on steep terrain (alpine), which is already clamped below.
    hero_down = float(os.environ.get("HERO_DOWN", "0"))
    hcz = max(_terrain_z(hcx, hcy), rz) + 1.6 + hero_down  # eye height above real ground
    hax = rx - ox * 6.0 + (tx - rx) * 0.25     # aim just past the boulder toward the trees
    hay = ry - oy * 6.0 + (ty - ry) * 0.25
    # Never look UP into a slope: keep the aim at least 0.4 m below the eye so on steep
    # (alpine) terrain the shot frames the scene + ground, not a point-blank rock wall.
    # On gentle terrain the aim is already below the eye, so this is a no-op there.
    haz = min(rz + 1.0, hcz - 0.4)
    hx, hy, hz = hcx, hcy, hcz
    hyaw = math.atan2(hay - hcy, hax - hcx)
    # Cap the down-tilt: on steep terrain the eye can sit metres above the rock
    # and the raw geometry stares into bare ground -- keep the receding scene
    # (and some sky) in the upper frame. 0.40 rad preserves HERO_DOWN's intent.
    hpitch = min(0.40, math.atan2(hz - haz, math.hypot(hax - hcx, hay - hcy)))
    print(f"PhaseD hero cam frames boulder scale={rs:.2f} ({len(_near(R))} trees within 55 m)")

parts.append(cam("cam_oblique", cx, cy, cz, pitch, yaw))
parts.append(cam("cam_top", 0.0, 0.0, tz, 1.5708, 0.0, fov=1.2, w=900, h=900))
parts.append(cam("cam_hero", hx, hy, hz, hpitch, hyaw, fov=1.25, w=1280, h=720))

# VIO_CAMS=1: two cameras at the REAL sensor-rig optics (640x480, 57 deg FOV,
# core/rig.py) at the actual operating poses (cli/fly.py: --agl 12 default, gentle
# ~20 deg down-pitch). vio_drone = 12 m AGL forward-look; vio_ground = 2 m ground-
# robot eye. These isolate GROUND texture crispness at the GSD VIO actually resolves
# -- the axis the oblique/720p gallery-cam harness cannot see. Ground-following z.
# VIO_TRAJ="x,y,z,pitch,yaw;x,y,z,pitch,yaw;..." places one 'vio_cam_<i>' at each pose,
# all in a SINGLE world, so tools/vio_bench.py renders a whole benchmark trajectory in one
# gz session (one startup, not N). Real rig optics 640x480/57 deg unless VIO_FOV set.
# Takes precedence over VIO_CAMS.
_traj = os.environ.get("VIO_TRAJ")
if _traj:
    _fov = float(os.environ.get("VIO_FOV", "1.0"))
    _poses = [p for p in _traj.split(";") if p.strip()]
    for _i, _p in enumerate(_poses):
        _x, _y, _z, _pit, _ya = (float(t) for t in _p.split(","))
        parts.append(cam(f"vio_cam_{_i}", _x, _y, _z, _pit, _ya, fov=_fov, w=640, h=480))
    print(f"VIO_TRAJ: {len(_poses)} cams (fov={_fov} 640x480)")
elif os.environ.get("VIO_CAMS") == "1":
    # VIO_DX sweeps the drone forward (+X, its look direction) to render a motion
    # sequence for temporal feature-track-length (KLT) measurement.
    vx, vy = -0.30 * ext + float(os.environ.get("VIO_DX", "0")), 0.0
    gz_ = _terrain_z(vx, vy)
    parts.append(cam("vio_drone",  vx, vy, gz_ + 12.0, 0.35, 0.0, fov=1.0, w=640, h=480))
    parts.append(cam("vio_ground", vx, vy, gz_ + 2.0,  0.20, 0.0, fov=1.0, w=640, h=480))
    print(f"VIO cams: drone@{gz_+12:.1f}m ground@{gz_+2:.1f}m pitch=0.35/0.20 640x480 fov1.0")
parts.append("  </world>\n</sdf>\n")
xml = "".join(parts)

# GRAFT_SUN=1: render under the PLACEMENT WORLD's photometric state -- its
# <light name='sun'>, <scene>, weather_* models/includes (sun disk, emitters)
# and the particle-emitter plugin -- instead of this harness's fixed sun.
# Required for the photometric/weather stress axes to be measurable by
# vio_bench (--world-sun); OFF by default so all previously measured baselines
# keep their lighting. (vio_bench sets it from --world-sun.)
if os.environ.get("GRAFT_SUN") == "1" and os.path.exists(_FOREST_WORLD):
    src = ET.parse(_FOREST_WORLD).getroot().find("world")
    dst_root = ET.fromstring(xml)
    dst = dst_root.find("world")

    def _swap(tag, match=lambda e: True):
        s = next((el for el in src.findall(tag) if match(el)), None)
        if s is None:
            return 0
        for el in [el for el in dst.findall(tag) if match(el)]:
            dst.remove(el)
        dst.append(s)
        return 1

    swapped = _swap("light", lambda e: e.get("name") == "sun")
    swapped += _swap("scene")
    extras = 0
    for el in src.findall("model"):
        if (el.get("name") or "").startswith("weather_"):
            dst.append(el)
            extras += 1
    for el in src.findall("include"):
        if el.findtext("uri", "").startswith("model://weather_"):
            dst.append(el)
            extras += 1
    for el in src.findall("plugin"):
        if "particle-emitter" in (el.get("filename") or ""):
            dst.append(el)
            extras += 1
    xml = ET.tostring(dst_root, encoding="unicode")
    print(f"GRAFT_SUN: {swapped} sun/scene + {extras} weather elements from {_FOREST_WORLD}")

open(OUT, "w").write(xml)
print(f"wrote {OUT}  oblique cam=({cx:.0f},{cy:.0f},{cz:.0f}) pitch={pitch:.2f} yaw={yaw:.2f}")
