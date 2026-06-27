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
with open(OBJ) as f:
    for line in f:
        if line.startswith("v "):
            p = line.split()
            x, y, z = float(p[1]), float(p[2]), float(p[3])
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
    parts.append("    <include><name>water</name><uri>model://water</uri></include>\n")
if os.environ.get("FOREST") == "1" and os.path.exists("/workspace/worlds/forest_world.world"):
    incs = ET.parse("/workspace/worlds/forest_world.world").getroot().find("world").findall("include")
    for inc in incs:
        parts.append("    " + ET.tostring(inc, encoding="unicode").strip() + "\n")
    print(f"grafted {len(incs)} forest includes")


def cam(name, x, y, z, pit, ya, fov=1.1, w=1100, h=750):
    return (f"    <model name='{name}'><static>true</static><pose>{x:.3f} {y:.3f} {z:.3f} 0 {pit:.4f} {ya:.4f}</pose>"
            f"<link name='link'><sensor name='{name}' type='camera'><topic>{name}</topic>"
            f"<always_on>1</always_on><update_rate>5</update_rate>"
            f"<camera><horizontal_fov>{fov}</horizontal_fov><image><width>{w}</width><height>{h}</height></image>"
            f"<clip><near>0.1</near><far>6000</far></clip></camera></sensor></link></model>\n")


parts.append(cam("cam_oblique", cx, cy, cz, pitch, yaw))
parts.append(cam("cam_top", 0.0, 0.0, tz, 1.5708, 0.0, fov=1.2, w=900, h=900))
parts.append("  </world>\n</sdf>\n")
open(OUT, "w").write("".join(parts))
print(f"wrote {OUT}  oblique cam=({cx:.0f},{cy:.0f},{cz:.0f}) pitch={pitch:.2f} yaw={yaw:.2f}")
