"""Build a water demo: terrain + vegetation + a flat water plane flooding the
low areas, viewed by an elevated oblique camera."""
import xml.etree.ElementTree as ET

SRC = "/workspace/worlds/forest_world.world"
OUT = "/workspace/worlds/water_scene.world"
includes = ET.parse(SRC).getroot().find("world").findall("include")

SHELL = '''<?xml version='1.0' encoding='ASCII'?>
<sdf version='1.8'>
  <world name='water_scene'>
    <physics name='1ms' type='ode'><max_step_size>0.003</max_step_size><real_time_factor>1.0</real_time_factor></physics>
    <plugin name='gz::sim::systems::Physics' filename='gz-sim-physics-system'/>
    <plugin name='gz::sim::systems::UserCommands' filename='gz-sim-user-commands-system'/>
    <plugin name='gz::sim::systems::SceneBroadcaster' filename='gz-sim-scene-broadcaster-system'/>
    <plugin name='gz::sim::systems::Sensors' filename='gz-sim-sensors-system'><render_engine>ogre2</render_engine></plugin>
    <scene><ambient>0.5 0.5 0.5 1</ambient><background>0.78 0.86 0.94 1</background><grid>false</grid></scene>
    <light name='sun' type='directional'><cast_shadows>1</cast_shadows><pose>0 0 50 0 0 0</pose>
      <diffuse>1 1 1 1</diffuse><specular>0.2 0.2 0.2 1</specular><direction>-0.4 0.3 -0.9</direction></light>
'''
parts = [SHELL]
for inc in includes:
    parts.append("    " + ET.tostring(inc, encoding="unicode").strip() + "\n")
parts.append("    <include><name>water</name><uri>model://water</uri></include>\n")
# elevated oblique camera looking across the terrain toward the hill centre
import math
cx, cy, cz = 150.0, 150.0, 70.0
ax, ay, az = 0.0, 0.0, 8.0
yaw = math.atan2(ay - cy, ax - cx)
pitch = -math.atan2(az - cz, math.hypot(ax - cx, ay - cy))
parts.append(
    f"    <model name='cam_water'><static>true</static><pose>{cx} {cy} {cz} 0 {pitch:.4f} {yaw:.4f}</pose>"
    f"<link name='link'><sensor name='cam_water' type='camera'><topic>cam_water</topic>"
    f"<always_on>1</always_on><update_rate>5</update_rate>"
    f"<camera><horizontal_fov>1.2</horizontal_fov><image><width>1100</width><height>700</height></image>"
    f"<clip><near>0.1</near><far>3000</far></clip></camera></sensor></link></model>\n")
parts.append("  </world>\n</sdf>\n")
open(OUT, "w").write("".join(parts))
print("wrote", OUT)
