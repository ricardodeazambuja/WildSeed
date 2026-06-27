"""Build a close-up hero world: terrain + the generated hero trees + one camera
framed on a single tree (sky behind) to show transparent foliage detail."""
import xml.etree.ElementTree as ET
import math

SRC = "/workspace/worlds/forest_world.world"
OUT = "/workspace/worlds/hero_closeup.world"

includes = ET.parse(SRC).getroot().find("world").findall("include")
trees = []
for inc in includes:
    if "model://tree" in inc.findtext("uri", ""):
        p = inc.findtext("pose", "0 0 0 0 0 0").split()
        trees.append((float(p[0]), float(p[1]), float(p[2])))

# pick the tree nearest the cluster centroid for a clean hero framing
cx = sum(t[0] for t in trees) / len(trees)
cy = sum(t[1] for t in trees) / len(trees)
hero = min(trees, key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)
hx, hy, hz = hero
# camera 11 m away (south-west), eye 2.2 m above tree base, look at canopy ~2.5 m up
dist, ex, ey = 11.0, hx - 8.0, hy - 7.5
ez = hz + 2.2
aim = (hx, hy, hz + 2.5)
yaw = math.atan2(aim[1] - ey, aim[0] - ex)
pitch = -math.atan2(aim[2] - ez, math.hypot(aim[0] - ex, aim[1] - ey))
print(f"hero tree at ({hx:.1f},{hy:.1f},{hz:.1f}); cam ({ex:.1f},{ey:.1f},{ez:.1f}) yaw={yaw:.2f} pitch={pitch:.2f}")

SHELL = f'''<?xml version='1.0' encoding='ASCII'?>
<sdf version='1.8'>
  <world name='hero_closeup'>
    <physics name='1ms' type='ode'><max_step_size>0.003</max_step_size><real_time_factor>1.0</real_time_factor></physics>
    <plugin name='gz::sim::systems::Physics'          filename='gz-sim-physics-system'/>
    <plugin name='gz::sim::systems::UserCommands'     filename='gz-sim-user-commands-system'/>
    <plugin name='gz::sim::systems::SceneBroadcaster' filename='gz-sim-scene-broadcaster-system'/>
    <plugin name='gz::sim::systems::Sensors'          filename='gz-sim-sensors-system'><render_engine>ogre2</render_engine></plugin>
    <scene><ambient>0.55 0.55 0.55 1</ambient><background>0.78 0.86 0.94 1</background><grid>false</grid></scene>
    <light name='sun' type='directional'><cast_shadows>1</cast_shadows><pose>0 0 50 0 0 0</pose>
      <diffuse>1 1 1 1</diffuse><specular>0.2 0.2 0.2 1</specular><direction>-0.4 0.3 -0.9</direction></light>
'''

parts = [SHELL]
for inc in includes:
    parts.append("    " + ET.tostring(inc, encoding="unicode").strip() + "\n")
parts.append(
    f"    <model name='cam_hero'><static>true</static><pose>{ex:.3f} {ey:.3f} {ez:.3f} 0 {pitch:.4f} {yaw:.4f}</pose>"
    f"<link name='link'><sensor name='cam_hero' type='camera'><topic>cam_hero</topic>"
    f"<always_on>1</always_on><update_rate>5</update_rate>"
    f"<camera><horizontal_fov>1.05</horizontal_fov><image><width>1000</width><height>750</height></image>"
    f"<clip><near>0.1</near><far>3000</far></clip></camera></sensor></link></model>\n")
parts.append("  </world>\n</sdf>\n")
open(OUT, "w").write("".join(parts))
print("wrote", OUT)
