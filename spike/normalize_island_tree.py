"""Normalize Poly Haven island_tree_01 into a Forest3D-ready hero asset.

Poly Haven tree blends ship multiple LODs + kit source pieces in one file, and
wire foliage through a custom node GROUP the glTF exporter can't read. This script:
  1. keeps ONE coherent tree object (LOD1) and deletes the rest,
  2. rebuilds the leaf material as a standard Principled BSDF with the leaf
     alpha mask -> Alpha Clip (so glTF writes alphaMode=MASK, double-sided),
  3. marks branch/trunk materials OPAQUE (they are solid geometry),
  4. downscales normal/rough maps to 1K (plan budget), packs textures,
  5. saves a self-contained Blender-Assets/tree/island_tree_01.blend.

Run: blender -b --python spike/normalize_island_tree.py
"""
import bpy

RAW = "/workspace/Blender-Assets/tree/_raw_island_tree_01/island_tree_01_2k.blend"
OUT = "/workspace/Blender-Assets/tree/island_tree_01.blend"
KEEP = "island_tree_01_LOD1"   # full assembled medium-LOD tree (all 3 materials)

bpy.ops.wm.open_mainfile(filepath=RAW)

# 1. keep only the chosen tree object
for o in list(bpy.data.objects):
    if o.name != KEEP:
        bpy.data.objects.remove(o, do_unlink=True)
obj = bpy.data.objects[KEEP]
if obj.name not in bpy.context.scene.collection.all_objects:
    try:
        bpy.context.scene.collection.objects.link(obj)
    except Exception:
        pass
obj.hide_set(False)
obj.hide_viewport = False
obj.hide_render = False


def find_img(substr):
    for i in bpy.data.images:
        if i.name == "Render Result":
            continue
        if substr in i.name:
            return i
    return None


# 2. rebuild the leaf material as a plain Principled BSDF (glTF-friendly)
m = bpy.data.materials["island_tree_01_leaves"]
m.use_nodes = True
nt = m.node_tree
nt.nodes.clear()
out = nt.nodes.new("ShaderNodeOutputMaterial"); out.location = (600, 0)
bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled"); bsdf.location = (200, 0)
nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])


def tex(image, x, y, noncolor=False):
    t = nt.nodes.new("ShaderNodeTexImage")
    t.image = image
    t.location = (x, y)
    if noncolor:
        image.colorspace_settings.name = "Non-Color"
    return t


diff = find_img("leaves_diff")
alpha = find_img("leaves_alpha")
rough = find_img("leaves_rough")
nor = find_img("leaves_nor")
if diff:
    nt.links.new(tex(diff, -500, 200).outputs["Color"], bsdf.inputs["Base Color"])
if alpha:
    # Blender 4.2's glTF exporter decides alphaMode from the NODE setup, not
    # blend_method (EEVEE-Next dropped CLIP). A Math:Greater-Than(0.5) on the
    # alpha is the pattern detect_alpha_clip() recognises -> alphaMode=MASK.
    ta = tex(alpha, -700, -120, noncolor=True)
    clip = nt.nodes.new("ShaderNodeMath")
    clip.operation = "GREATER_THAN"
    clip.location = (-300, -120)
    clip.inputs[1].default_value = 0.5
    nt.links.new(ta.outputs["Color"], clip.inputs[0])
    nt.links.new(clip.outputs["Value"], bsdf.inputs["Alpha"])
if rough:
    nt.links.new(tex(rough, -500, -420, noncolor=True).outputs["Color"], bsdf.inputs["Roughness"])
if nor:
    tnor = tex(nor, -900, -700, noncolor=True)
    nm = nt.nodes.new("ShaderNodeNormalMap"); nm.location = (-500, -700)
    nt.links.new(tnor.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])

# Alpha Clip -> glTF MASK; double-sided so leaves show from behind.
m.blend_method = "CLIP"
m.alpha_threshold = 0.5
m.use_backface_culling = False
try:
    m.surface_render_method = "DITHERED"   # 4.2 EEVEE-Next: clip/dither path
except Exception:
    pass
print("LEAF_ALPHA_WIRED:", bsdf.inputs["Alpha"].is_linked)

# 3. branch + trunk are solid geometry -> opaque
for nm2 in ("island_tree_01_branches", "island_tree_01"):
    mm = bpy.data.materials.get(nm2)
    if mm:
        mm.blend_method = "OPAQUE"
        mm.use_backface_culling = False

# 4. downscale normal/rough maps to 1K (albedo stays 2K), then pack
for i in list(bpy.data.images):
    if i.name == "Render Result":
        continue
    if any(k in i.name.lower() for k in ("nor", "rough", "arm", "_ao", "disp")):
        if i.size[0] > 1024 or i.size[1] > 1024:
            try:
                i.scale(1024, 1024)
            except Exception as e:
                print("scale failed", i.name, e)
bpy.ops.file.pack_all()

# 5. save self-contained
bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("SAVED", OUT)
print("OBJECTS:", [o.name for o in bpy.data.objects])
print("LEAF_POLYS:", len(obj.data.polygons), "MATSLOTS:", [s.material.name for s in obj.material_slots])
