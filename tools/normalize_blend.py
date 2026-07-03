"""Blender: open a Poly Haven native .blend, normalize, save a self-contained
.blend ready for `forest3d convert`.

  blender -b <in.blend> --python tools/normalize_blend.py -- <out_blend> [scale] [variant]

Poly Haven kit .blends ship many variants (a,b,c,...) x several LODs; only the LOD0
objects are linked to the view layer. We keep a single LOD (the lowest-numbered LOD
present in the view layer) and a single variant (default the first; pass `variant` to
pick another, e.g. 'c') so each download yields one clean, scatter-ready model.

Same normalization as tools/import_gltf.py (recenter footprint to XY origin, base to
z=0, optional uniform scale, pack textures, alpha->MASK node wiring for the glTF
exporter) but the source is a native .blend whose foliage materials already wire
their opacity map -- so the alpha->MASK pattern triggers automatically and leaves
export with alphaMode=MASK (no separate alpha map to hunt for). See the foliage memory
note [[blender42-gltf-mask-foliage]] and ASSET_REGISTRY.md.
"""
import re
import sys
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out_blend = argv[0]
extra_scale = float(argv[1]) if len(argv) > 1 else 1.0
want_variant = argv[2] if len(argv) > 2 and argv[2] not in ("-", "") else None
# Target LOD: an int (use that _LODn level), or "-"/absent = highest detail available.
want_lod = int(argv[3]) if len(argv) > 3 and argv[3] not in ("-", "") else None

scene_coll = bpy.context.scene.collection
# Consider ALL mesh objects in the file (Poly Haven links only one LOD set to the view
# layer, but ships LOD0..LOD3 in data); link any we may pick so view-layer ops work.
# EXCLUDE helper objects: some Poly Haven grass/bush kits ship a "preview sphere" (a
# material-preview ball, e.g. `grass_medium_02_sphere`) that carries a `_LOD<n>` suffix
# with no variant letter -> the assembled-object filter below would otherwise KEEP it,
# and it exports as an untextured near-black OPAQUE mesh that renders as a solid BLACK
# BLOB scattered through scenes. Drop these by name before any selection.
HELPER_RE = re.compile(r"(sphere|preview|proxy|placeholder|backdrop|^empty)", re.IGNORECASE)
all_meshes = [o for o in bpy.data.objects
              if o.type == "MESH" and not HELPER_RE.search(o.name)]
if not all_meshes:
    raise SystemExit("no mesh objects in .blend")

# Keep a single LOD. Default = lowest-numbered _LODn present (highest detail);
# pass want_lod to trade quality for size (LOD1/2 are far lighter for trees).
lod_re = re.compile(r"_LOD(\d+)$")
var_re = re.compile(r"_([a-z])_LOD\d+$")   # kit-part suffix, e.g. _leaves_a_LOD1
lods = sorted({int(m.group(1)) for o in all_meshes if (m := lod_re.search(o.name))})
if lods:
    keep_lod = want_lod if (want_lod in lods) else lods[0]
    at_lod = [o for o in all_meshes
              if (m := lod_re.search(o.name)) and int(m.group(1)) == keep_lod]
    print(f"LODS {lods} -> keeping LOD{keep_lod}")
else:
    at_lod = all_meshes

# Poly Haven tree blends ship the ASSEMBLED tree (`<id>_LOD<n>`) AND the individual kit
# pieces used to build it (`<id>_branches_a_LOD<n>`, `<id>_leaves_b_LOD<n>`, ...). Prefer
# the assembled object (a complete tree). Only when there is NO assembled object is this a
# pure kit (shrub/grass clumps a..i) -> pick one variant. (Earlier bug: the variant filter
# kept just one tiny kit piece and dropped the 490k-tri assembled tree -> 551-tri "trees".)
assembled = [o for o in at_lod if lod_re.search(o.name) and not var_re.search(o.name)]
if assembled:
    vl_meshes = assembled
    print(f"ASSEMBLED -> {[o.name for o in assembled]}")
else:
    variants = sorted({m.group(1) for o in at_lod if (m := var_re.search(o.name))})
    if variants:
        pick = want_variant if (want_variant in variants) else variants[0]
        vl_meshes = [o for o in at_lod
                     if (m := var_re.search(o.name)) and m.group(1) == pick]
        print(f"KIT_VARIANTS {variants} -> picked {pick!r}")
    else:
        vl_meshes = at_lod

# Ensure the kept objects are linked into the active view layer (some LODs aren't).
for o in vl_meshes:
    if o.name not in bpy.context.view_layer.objects:
        try:
            scene_coll.objects.link(o)
        except RuntimeError:
            pass

keep = set(o.name for o in vl_meshes)
# Drop everything we are not keeping (other LODs, other variants, helper objects).
for o in list(bpy.data.objects):
    if o.name not in keep:
        bpy.data.objects.remove(o, do_unlink=True)

meshes = [o for o in bpy.data.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no mesh objects after LOD/variant selection")

# Strip helper MATERIAL slots: some Poly Haven grass/bush kits put the preview-sphere
# material (`<id>_sphere`, an untextured near-black OPAQUE ball) on a kept
# geometry-nodes object that ALSO holds real grass, so dropping the object isn't an
# option and the HELPER_RE object-name filter above can't see it. Delete the faces
# assigned to any `*_sphere`/preview/proxy material -> the exporter emits no primitive
# for the empty slot, so the black blob disappears while the real foliage stays.
import bmesh  # noqa: E402
MAT_HELPER_RE = re.compile(r"(_sphere$|preview|proxy|placeholder)", re.IGNORECASE)
for o in meshes:
    drop = {i for i, ms in enumerate(o.material_slots)
            if ms.material and MAT_HELPER_RE.search(ms.material.name)}
    if not drop:
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bm.faces.ensure_lookup_table()
    dead = [f for f in bm.faces if f.material_index in drop]
    if dead:
        bmesh.ops.delete(bm, geom=dead, context="FACES")
        bm.to_mesh(o.data)
        print(f"STRIP_HELPER {o.name}: removed {len(dead)} faces "
              f"({[o.material_slots[i].material.name for i in drop]})")
    bm.free()

bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# combined world-space bounds
mn = Vector((1e18, 1e18, 1e18))
mx = Vector((-1e18, -1e18, -1e18))
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        mn = Vector((min(mn[i], w[i]) for i in range(3)))
        mx = Vector((max(mx[i], w[i]) for i in range(3)))
cx = (mn[0] + mx[0]) / 2.0
cy = (mn[1] + mx[1]) / 2.0
zmin = mn[2]

for o in meshes:
    o.location.x -= cx
    o.location.y -= cy
    o.location.z -= zmin
bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
if extra_scale != 1.0:
    for o in meshes:
        o.scale = (extra_scale, extra_scale, extra_scale)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

print(f"NORMALIZED size x={mx[0]-mn[0]:.2f} y={mx[1]-mn[1]:.2f} z={(mx[2]-zmin):.2f} m "
      f"(x{extra_scale}) materials={[m.name for m in bpy.data.materials]}")

# Foliage -> alphaMode=MASK. Poly Haven foliage materials wire transparency through a
# custom node GROUP the glTF exporter can't read, so it defaults to alphaMode=BLEND ->
# dense double-sided leaves form a dark depth-sort blob. Fix (generalises the proven
# tools/normalize_island_tree.py): for foliage materials, REBUILD as a plain Principled
# BSDF and splice the leaf alpha image through Math:Greater-Than(0.5) into Alpha. That
# node pattern is what Blender 4.2's exporter reads as MASK. Solid materials (trunk/
# branch/rock) keep their nodes and are just forced OPAQUE. See [[blender42-gltf-mask-foliage]].
FOLIAGE_KW = ("leaf", "leaves", "foliage", "frond", "needle", "canopy", "grass",
              "fern", "shrub", "bush", "flower", "plant", "twig", "blade")


def collect_images(nt, seen=None):
    seen = seen if seen is not None else set()
    out = []
    for n in nt.nodes:
        if n.type == "TEX_IMAGE" and n.image:
            out.append(n.image)
        elif n.type == "GROUP" and n.node_tree and id(n.node_tree) not in seen:
            seen.add(id(n.node_tree))
            out += collect_images(n.node_tree, seen)
    return out


def classify(images):
    alb = alpha = rough = nor = None
    for im in images:
        nm = im.name.lower()
        if "nor" in nm and nor is None:
            nor = im
        elif "rough" in nm and rough is None:
            rough = im
        elif ("alpha" in nm or "opacity" in nm) and alpha is None:
            alpha = im
        elif (("diff" in nm or "albedo" in nm or "color" in nm or "_col" in nm)
              and "arm" not in nm and alb is None):
            alb = im
    if alb is None:  # fallback: first image that isn't a known data map
        for im in images:
            nm = im.name.lower()
            if not any(k in nm for k in ("nor", "rough", "alpha", "opacity", "ao",
                                         "disp", "arm")):
                alb = im
                break
    return alb, alpha, rough, nor


def rebuild_foliage(m):
    images = collect_images(m.node_tree)
    alb, alpha, rough, nor = classify(images)
    if alb is None:
        return False
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

    talb = tex(alb, -500, 200)
    nt.links.new(talb.outputs["Color"], bsdf.inputs["Base Color"])
    asrc = tex(alpha, -700, -120, noncolor=True).outputs["Color"] if alpha \
        else talb.outputs["Alpha"]            # fall back to albedo's alpha channel
    clip = nt.nodes.new("ShaderNodeMath")
    clip.operation = "GREATER_THAN"
    clip.inputs[1].default_value = 0.5
    clip.location = (-300, -120)
    nt.links.new(asrc, clip.inputs[0])
    nt.links.new(clip.outputs["Value"], bsdf.inputs["Alpha"])
    if rough:
        nt.links.new(tex(rough, -500, -420, noncolor=True).outputs["Color"],
                     bsdf.inputs["Roughness"])
    if nor:
        tn = tex(nor, -900, -700, noncolor=True)
        nm = nt.nodes.new("ShaderNodeNormalMap"); nm.location = (-500, -700)
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    m.blend_method = "CLIP"
    m.alpha_threshold = 0.5
    m.use_backface_culling = False
    try:
        m.surface_render_method = "DITHERED"
    except Exception:
        pass
    return True


def has_alpha_map(m):
    """Species-named materials (e.g. `dandelion_01`, `jacaranda_tree`) carry no
    FOLIAGE_KW keyword but DO ship an alpha/opacity map — that map only exists for
    cutout foliage (bark/rock/trunk materials never have one), so its presence is a
    reliable foliage signal."""
    return any("alpha" in im.name.lower() or "opacity" in im.name.lower()
               for im in collect_images(m.node_tree))


for m in bpy.data.materials:
    if not m.use_nodes or not m.node_tree:
        continue
    is_foliage = (any(k in m.name.lower() for k in FOLIAGE_KW)
                  or has_alpha_map(m))
    if is_foliage and rebuild_foliage(m):
        print("ALPHA_MASK_WIRED:", m.name)
    else:
        m.blend_method = "OPAQUE"               # solid geometry (trunk/branch/rock)
        m.use_backface_culling = False

try:
    bpy.ops.file.pack_all()
except Exception as e:
    print("pack_all warn:", e)
bpy.ops.wm.save_as_mainfile(filepath=out_blend)
print("SAVED", out_blend)
