"""Blender to Gazebo asset converter."""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from forest3d.config.schema import BlenderConfig

logger = logging.getLogger("forest3d.converter")


def find_blender() -> Optional[Path]:
    """Auto-detect Blender installation."""
    blender_in_path = shutil.which("blender")
    if blender_in_path:
        return Path(blender_in_path)

    common_paths = [
        Path("/usr/bin/blender"),
        Path("/usr/local/bin/blender"),
        Path("/snap/bin/blender"),
        Path("/opt/blender/blender"),
        Path.home() / "blender" / "blender",
    ]

    for base in [Path.home() / "Downloads", Path("/opt"), Path.home()]:
        if base.exists():
            try:
                for item in base.iterdir():
                    if item.is_dir() and item.name.lower().startswith("blender"):
                        blender_exec = item / "blender"
                        if blender_exec.exists() and blender_exec.is_file():
                            common_paths.append(blender_exec)
            except PermissionError:
                continue

    for path in common_paths:
        if path.exists() and path.is_file():
            return path
    return None


class AssetExporter:
    """Export Blender assets to Gazebo models with glTF format."""

    def __init__(
        self,
        blender_path: Optional[Path] = None,
        output_path: Optional[Path] = None,
        config: Optional[BlenderConfig] = None,
    ):
        self.config = config or BlenderConfig()

        if blender_path:
            self._blender_path = Path(blender_path)
        elif self.config.path:
            self._blender_path = self.config.path
        else:
            detected = find_blender()
            if detected:
                self._blender_path = detected
                logger.info(f"Auto-detected Blender at: {detected}")
            else:
                raise RuntimeError("Blender not found. Install from https://www.blender.org/download/")

        if not self._blender_path.exists():
            raise FileNotFoundError(f"Blender not found at: {self._blender_path}")

        self.output_path = Path(output_path) if output_path else Path.cwd() / "models"
        self.visual_decimation = self.config.visual_decimation
        self.collision_decimation = self.config.collision_decimation

    def process_asset(
        self,
        blend_file: Path,
        category: str = "tree",
        progress_callback: Optional[callable] = None,
    ) -> Path:
        """Process a single Blender asset to Gazebo model."""
        blend_file = Path(blend_file)
        if not blend_file.exists():
            raise FileNotFoundError(f"Blend file not found: {blend_file}")

        base_name = blend_file.stem
        logger.info(f"Processing: {base_name}")

        asset_dir = self.output_path / category / base_name
        mesh_dir = asset_dir / "mesh"
        for d in [mesh_dir, asset_dir / "textures", asset_dir / "materials"]:
            d.mkdir(parents=True, exist_ok=True)

        if progress_callback:
            progress_callback(20, "Exporting glTF...")

        glb_path = mesh_dir / f"{base_name}.glb"
        collision_path = mesh_dir / f"{base_name}_collision.glb"
        resolved = self.config.resolve_category(category)
        logger.info(
            f"  [{category}] visual_dec={resolved.visual_decimation} "
            f"collision={resolved.collision_strategy} "
            f"skip_foliage={resolved.skip_foliage_decimation}"
        )
        self._export_glb(blend_file, glb_path, collision_path, resolved)

        if progress_callback:
            progress_callback(80, "Creating model files...")

        self._create_sdf_file(base_name, asset_dir)
        self._create_config_file(base_name, asset_dir)
        self._create_test_world(base_name, asset_dir, category)

        if progress_callback:
            progress_callback(100, "Complete")

        logger.info(f"Done: {base_name}")
        return asset_dir

    def _export_glb(
        self,
        blend_file: Path,
        output_path: Path,
        collision_path: Path,
        resolved=None,
    ) -> None:
        """Export glTF binary (.glb) for visual and collision meshes.

        ``resolved`` is a ResolvedCategory; if None, falls back to the global
        decimation ratios with legacy decimated-mesh collision (backward compat).
        """
        if resolved is None:
            visual_dec = self.visual_decimation
            collision_dec = self.collision_decimation
            collision_strategy = "mesh"
            skip_foliage = False
        else:
            visual_dec = resolved.visual_decimation
            collision_dec = resolved.collision_decimation
            collision_strategy = resolved.collision_strategy
            skip_foliage = resolved.skip_foliage_decimation

        blender_script = f'''
import bpy

FOLIAGE_KEYWORDS = ("leaf", "leaves", "foliage", "frond", "needle", "alpha", "canopy")


def obj_has_alpha(obj):
    """True if any material slot signals transparency (foliage leaf cards).

    Version-stable on Blender 4.2 EEVEE-Next: leads with the Principled BSDF
    Alpha socket (linked or <1) rather than the deprecated blend_method.
    """
    for slot in obj.material_slots:
        m = slot.material
        if not m:
            continue
        if getattr(m, "use_nodes", False) and m.node_tree:
            bsdf = m.node_tree.nodes.get("Principled BSDF")
            if bsdf and "Alpha" in bsdf.inputs:
                a = bsdf.inputs["Alpha"]
                if a.is_linked or a.default_value < 1.0:
                    return True
        if any(k in (m.name or "").lower() for k in FOLIAGE_KEYWORDS):
            return True
    if any(k in (obj.name or "").lower() for k in FOLIAGE_KEYWORDS):
        return True
    return False


def _unhide_meshes():
    objs = []
    for obj in bpy.data.objects:
        if obj.type == 'MESH':
            obj.hide_set(False)
            obj.hide_viewport = False
            obj.hide_render = False
            if obj.name not in bpy.context.view_layer.objects:
                try:
                    bpy.context.collection.objects.link(obj)
                except Exception:
                    pass
            objs.append(obj)
    return objs


def export_visual(filepath, decimate_ratio, skip_foliage):
    bpy.ops.object.select_all(action='DESELECT')
    for obj in _unhide_meshes():
        if skip_foliage and obj_has_alpha(obj):
            print("SKIP_DECIMATE_FOLIAGE:", obj.name)
            continue
        if decimate_ratio >= 1.0:
            continue  # 1.0 = keep full visual detail (real high-poly assets)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        dec = obj.modifiers.new(name="Decimate", type='DECIMATE')
        dec.ratio = decimate_ratio
        bpy.ops.object.modifier_apply(modifier="Decimate")
    bpy.ops.export_scene.gltf(
        filepath=filepath, export_format='GLB', use_selection=False,
        export_apply=True, export_texcoords=True, export_normals=True,
        export_materials='EXPORT', export_image_format='AUTO', export_yup=False,
    )


def _world_verts():
    import mathutils  # noqa: F401
    coords = []
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        mw = obj.matrix_world
        for v in obj.data.vertices:
            coords.append(mw @ v.co)
    return coords


def _clear_all():
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()


def build_collision(strategy, decimate_ratio):
    coords = _world_verts()
    if not coords:
        raise RuntimeError("no mesh geometry for collision")
    xs = [c.x for c in coords]; ys = [c.y for c in coords]; zs = [c.z for c in coords]
    xmin, xmax = min(xs), max(xs); ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)
    cx = (xmin + xmax) / 2.0; cy = (ymin + ymax) / 2.0; cz = (zmin + zmax) / 2.0
    h = max(zmax - zmin, 1e-3)

    if strategy == 'mesh':
        # legacy: decimated copy of the visual geometry
        bpy.ops.object.select_all(action='DESELECT')
        for obj in _unhide_meshes():
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            dec = obj.modifiers.new(name="Decimate", type='DECIMATE')
            dec.ratio = decimate_ratio
            bpy.ops.object.modifier_apply(modifier="Decimate")
        return

    if strategy == 'trunk_cylinder':
        # fit a thin upright cylinder to the base footprint (bottom 15% band)
        band = zmin + 0.15 * h
        base = [c for c in coords if c.z <= band] or coords
        bx = sum(c.x for c in base) / len(base)
        by = sum(c.y for c in base) / len(base)
        r = max((((c.x - bx) ** 2 + (c.y - by) ** 2) ** 0.5) for c in base)
        r = max(r, 0.05)
        _clear_all()
        bpy.ops.mesh.primitive_cylinder_add(
            vertices=24, radius=r, depth=h, location=(bx, by, zmin + h / 2.0))
        return

    if strategy == 'convex_hull':
        _clear_all()
        me = bpy.data.meshes.new("collision")
        me.from_pydata([(c.x, c.y, c.z) for c in coords], [], [])
        o = bpy.data.objects.new("collision", me)
        bpy.context.collection.objects.link(o)
        bpy.context.view_layer.objects.active = o
        o.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.mesh.convex_hull()
        bpy.ops.object.mode_set(mode='OBJECT')
        return

    if strategy == 'box':
        _clear_all()
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(cx, cy, cz))
        ob = bpy.context.object
        ob.scale = (max(xmax - xmin, 1e-3), max(ymax - ymin, 1e-3), h)
        bpy.ops.object.transform_apply(scale=True)
        return

    if strategy == 'sphere':
        _clear_all()
        r = max(((c.x - cx) ** 2 + (c.y - cy) ** 2 + (c.z - cz) ** 2) ** 0.5 for c in coords)
        bpy.ops.mesh.primitive_uv_sphere_add(
            segments=16, ring_count=8, radius=max(r, 0.05), location=(cx, cy, cz))
        return

    raise RuntimeError("unknown collision strategy: " + strategy)


def export_collision(filepath, strategy, decimate_ratio):
    build_collision(strategy, decimate_ratio)
    bpy.ops.object.select_all(action='DESELECT')
    bpy.ops.export_scene.gltf(
        filepath=filepath, export_format='GLB', use_selection=False,
        export_apply=True, export_texcoords=False, export_normals=True,
        export_materials='NONE', export_image_format='NONE', export_yup=False,
    )


bpy.ops.wm.open_mainfile(filepath="{blend_file}")
export_visual("{output_path}", {visual_dec}, {skip_foliage})

bpy.ops.wm.open_mainfile(filepath="{blend_file}")
export_collision("{collision_path}", "{collision_strategy}", {collision_dec})
'''

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(blender_script)
            script_path = f.name

        try:
            result = subprocess.run(
                [str(self._blender_path), "--background", "--python", script_path],
                capture_output=True, text=True, timeout=300,
            )
            if not (output_path.exists() and collision_path.exists()):
                logger.error("glTF export failed")
                logger.debug(f"stdout: {result.stdout}")
                logger.debug(f"stderr: {result.stderr}")
                raise RuntimeError("Blender glTF export failed")
        except subprocess.TimeoutExpired:
            raise RuntimeError("Blender export timed out")
        finally:
            os.unlink(script_path)

    def _create_sdf_file(self, model_name: str, model_dir: Path) -> Path:
        """Create SDF file using glTF meshes."""
        sdf_content = f'''<?xml version="1.0" ?>
<sdf version="1.8">
    <model name="{model_name}">
        <static>true</static>
        <link name="link">
            <collision name="collision">
                <geometry>
                    <mesh><uri>mesh/{model_name}_collision.glb</uri></mesh>
                </geometry>
            </collision>
            <visual name="visual">
                <geometry>
                    <mesh><uri>mesh/{model_name}.glb</uri></mesh>
                </geometry>
            </visual>
        </link>
    </model>
</sdf>'''
        sdf_path = model_dir / "model.sdf"
        sdf_path.write_text(sdf_content)
        return sdf_path

    def _create_config_file(self, model_name: str, model_dir: Path) -> Path:
        """Create model.config file."""
        config_content = f'''<?xml version="1.0"?>
<model>
    <name>{model_name}</name>
    <version>1.0</version>
    <sdf version="1.8">model.sdf</sdf>
    <author>
        <name>AI4Forest</name>
        <email>khalid.bourr@gmail.com</email>
    </author>
    <description>{model_name} model</description>
</model>'''
        config_path = model_dir / "model.config"
        config_path.write_text(config_content)
        return config_path

    def _create_test_world(self, model_name: str, model_dir: Path, category: str) -> Path:
        """Create test world file."""
        from xml.etree import ElementTree as ET
        from forest3d.utils.sdf import create_world_base, add_ground_plane, write_world_file

        sdf_root, world = create_world_base("asset_test")
        add_ground_plane(world)

        include = ET.SubElement(world, "include")
        ET.SubElement(include, "name").text = model_name
        ET.SubElement(include, "pose").text = "0 0 0 0 0 0"
        ET.SubElement(include, "uri").text = f"model://{category}/{model_name}"

        world_path = model_dir / "test.world"
        write_world_file(sdf_root, world_path)
        return world_path

    def process_directory(
        self,
        input_dir: Path,
        category: Optional[str] = None,
        progress_callback: Optional[callable] = None,
    ) -> List[Path]:
        """Process all .blend files in a directory."""
        input_dir = Path(input_dir)
        blend_files = list(input_dir.glob("*.blend"))

        if not blend_files:
            logger.warning(f"No .blend files found in {input_dir}")
            return []

        logger.info(f"Found {len(blend_files)} .blend files")

        results = []
        for i, blend_file in enumerate(blend_files):
            try:
                if progress_callback:
                    progress_callback(int((i / len(blend_files)) * 100), f"Processing {blend_file.name}...")
                cat = category or "tree"
                result = self.process_asset(blend_file, cat)
                results.append(result)
            except Exception as e:
                logger.error(f"Failed: {blend_file.name}: {e}")
        return results