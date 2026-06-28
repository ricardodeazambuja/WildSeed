"""Build a minimal render world for a meshed terrain (models/ground): an oblique
overview camera + a top-down camera. Optionally include the water plane
(model://water) and graft placed forest models (worlds/forest_world.world).

Env:
  OUT      output world path (default worlds/terrain_scene.world)
  WATER=1  include model://water
  FOREST=1 graft includes from worlds/forest_world.world (trees/rocks/bushes)

Top-down camera looks DOWN with pitch +1.5708 (NOT -1.5708, which looks at sky).
"""
import math
import os
import xml.etree.ElementTree as ET

OBJ = "/workspace/models/ground/mesh/terrain.obj"
OUT = os.environ.get("OUT", "/workspace/worlds/terrain_scene.world")

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

# hero camera: a CLOSER, elevated 3/4 view (vs the far overview) so trees/rocks
# read at scale while looking down ~30 deg keeps the ground green (a grazing,
# near-horizontal view reflects the bright sky and washes the ground out). Elevated
# placement is also robustly above the terrain -> the camera always renders.
hx, hy = -0.20 * ext, -0.22 * ext
hz = maxz + 0.16 * ext
haim_x, haim_y, haim_z = 0.06 * ext, 0.04 * ext, (minz + maxz) / 2.0
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
    <include><name>terrain</name><uri>model://ground</uri></include>
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
if os.environ.get("FOREST") == "1" and os.path.exists("/workspace/worlds/forest_world.world"):
    incs = ET.parse("/workspace/worlds/forest_world.world").getroot().find("world").findall("include")
    n = 0
    for inc in incs:
        uri = inc.findtext("uri", "")
        if "model://ground" in uri or "model://water" in uri:
            continue  # we add terrain/water ourselves; avoid duplicate model names
        parts.append("    " + ET.tostring(inc, encoding="unicode").strip() + "\n")
        n += 1
    print(f"grafted {n} forest includes")


def cam(name, x, y, z, pit, ya, fov=1.1, w=1100, h=750):
    return (f"    <model name='{name}'><static>true</static><pose>{x:.3f} {y:.3f} {z:.3f} 0 {pit:.4f} {ya:.4f}</pose>"
            f"<link name='link'><sensor name='{name}' type='camera'><topic>{name}</topic>"
            f"<always_on>1</always_on><update_rate>5</update_rate>"
            f"<camera><horizontal_fov>{fov}</horizontal_fov><image><width>{w}</width><height>{h}</height></image>"
            f"<clip><near>0.1</near><far>6000</far></clip></camera></sensor></link></model>\n")


parts.append(cam("cam_oblique", cx, cy, cz, pitch, yaw))
parts.append(cam("cam_top", 0.0, 0.0, tz, 1.5708, 0.0, fov=1.2, w=900, h=900))
parts.append(cam("cam_hero", hx, hy, hz, hpitch, hyaw, fov=1.25, w=1280, h=720))
parts.append("  </world>\n</sdf>\n")
open(OUT, "w").write("".join(parts))
print(f"wrote {OUT}  oblique cam=({cx:.0f},{cy:.0f},{cz:.0f}) pitch={pitch:.2f} yaw={yaw:.2f}")
