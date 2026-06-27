"""Seeded procedural ground compositor for Forest3D terrain.

Reproduces the original Forest3D look (single PBR material from a ground texture,
the Soil 1/2/3 approach) AND extends it with controllable patchiness the original
lacks: trails (explicit waypoints or seeded random walk) and scattered sand /
gravel / pebble patches. Output is one PBR material set (albedo/normal/roughness),
i.e. the exact rendering path P2 already proved in gz.

Modes:
  uniform  - tile a single ground texture at --tile m/period (crisp; feed a
             naturally-varied texture at a low tile to match the originals).
  patchy   - bake a 1:1 composite: base + overlay patches + trails.
  debug    - off-centre sand band + corner gravel square, to validate UV mapping.

Run on the host (numpy/scipy/PIL). Writes models/ground/texture/*, rewrites the
terrain UVs (0..1 for patchy/debug, x tile for uniform), and regenerates model.sdf.
"""
import argparse
import glob
import os

import numpy as np
from scipy.ndimage import gaussian_filter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GROUND = os.path.join(ROOT, "models", "ground")
TEXDIR = os.path.join(GROUND, "texture")
OBJ = os.path.join(GROUND, "mesh", "terrain.obj")
RAW = os.path.join(ROOT, "Blender-Assets", "soil")

# ground material library (CC0): name -> (color, normalGL, roughness, default tile_m)
LIB = {
    "grass":   ("Grass004_2K-PNG_Color.png", "Grass004_2K-PNG_NormalGL.png", "Grass004_2K-PNG_Roughness.png", 4.0),
    "sand":    ("Ground027_1K-PNG_Color.png", "Ground027_1K-PNG_NormalGL.png", "Ground027_1K-PNG_Roughness.png", 3.0),
    "trail":   ("Ground054_1K-PNG_Color.png", "Ground054_1K-PNG_NormalGL.png", "Ground054_1K-PNG_Roughness.png", 3.0),
    "gravel":  ("Gravel023_1K-PNG_Color.png", "Gravel023_1K-PNG_NormalGL.png", "Gravel023_1K-PNG_Roughness.png", 2.0),
    "pebbles": ("Rocks023_1K-PNG_Color.png", "Rocks023_1K-PNG_NormalGL.png", "Rocks023_1K-PNG_Roughness.png", 2.5),
}


def _load(name):
    from PIL import Image
    base = None
    for d in glob.glob(os.path.join(RAW, "_raw_*")):
        p = os.path.join(d, name)
        if os.path.exists(p):
            base = p
            break
    if base is None:  # grass lives in _raw_grass
        for d in glob.glob(os.path.join(RAW, "_raw_*")):
            cand = glob.glob(os.path.join(d, name))
            if cand:
                base = cand[0]
                break
    if base is None:
        raise FileNotFoundError(name)
    return np.asarray(Image.open(base).convert("RGB"), dtype=np.float32) / 255.0


def terrain_extent():
    minx = miny = 1e18
    maxx = maxy = -1e18
    for line in open(OBJ):
        if line.startswith("v "):
            _, x, y, _z = line.split()[:4]
            x, y = float(x), float(y)
            minx, maxx = min(minx, x), max(maxx, x)
            miny, maxy = min(miny, y), max(maxy, y)
    return minx, maxx, miny, maxy


def tiled(tex, res, extent_m, tile_m):
    """Sample tex tiled across res x res covering extent_m, repeating every tile_m."""
    h, w = tex.shape[:2]
    ex, ey = extent_m
    ux = ((np.arange(res) / res) * (ex / tile_m)) % 1.0
    uy = ((np.arange(res) / res) * (ey / tile_m)) % 1.0
    cols = (ux * w).astype(int) % w
    rows = (uy * h).astype(int) % h
    return tex[np.ix_(rows, cols)]


def blend_normal(a, b, m):
    """Lerp two GL normal maps then renormalize. m is (R,R) in [0,1]."""
    da = a * 2.0 - 1.0
    db = b * 2.0 - 1.0
    out = da * (1 - m[..., None]) + db * m[..., None]
    n = np.linalg.norm(out, axis=2, keepdims=True)
    n[n == 0] = 1
    return (out / n) * 0.5 + 0.5


def soft_blobs(res, n, r_frac_range, rng, sharp=0.6):
    """N organic patches: gaussian blobs jittered by noise, thresholded soft."""
    m = np.zeros((res, res), np.float32)
    yy, xx = np.mgrid[0:res, 0:res]
    for _ in range(n):
        cy, cx = rng.uniform(0, res, 2)
        r = rng.uniform(*r_frac_range) * res
        d = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / r
        m = np.maximum(m, np.clip(1.0 - d, 0, 1))
    # irregular edges via smoothed noise
    noise = gaussian_filter(rng.random((res, res)).astype(np.float32), sigma=res / 120)
    m = np.clip(m * (0.6 + 0.8 * noise), 0, 1)
    m = gaussian_filter(m, sigma=res / 400)
    return np.clip((m - (1 - sharp)) / sharp, 0, 1)


def trail_mask(res, waypoints_uv, width_m, extent_m, feather=0.4):
    """Rasterize a soft trail through waypoints (normalized 0..1 coords)."""
    ex, ey = extent_m
    pts = np.array(waypoints_uv) * res
    m = np.zeros((res, res), np.float32)
    yy, xx = np.mgrid[0:res, 0:res]
    wpx = width_m / ((ex + ey) / 2) * res / 2.0
    for i in range(len(pts) - 1):
        p, q = pts[i], pts[i + 1]
        seg = q - p
        L2 = (seg ** 2).sum() or 1.0
        t = np.clip(((xx - p[0]) * seg[0] + (yy - p[1]) * seg[1]) / L2, 0, 1)
        px, py = p[0] + t * seg[0], p[1] + t * seg[1]
        dist = np.sqrt((xx - px) ** 2 + (yy - py) ** 2)
        m = np.maximum(m, np.clip(1.0 - (dist - wpx) / (wpx * feather + 1e-3), 0, 1))
    return m


def random_walk_uv(rng, n=6, margin=0.1):
    """A meandering path across the terrain (normalized coords)."""
    x = rng.uniform(margin, 1 - margin)
    pts = [(x, margin)]
    for i in range(1, n):
        x = np.clip(x + rng.uniform(-0.25, 0.25), margin, 1 - margin)
        pts.append((x, margin + (1 - 2 * margin) * i / (n - 1)))
    return pts


def composite(spec, res, rng):
    """spec: {'base':name, 'overlays':[(name, mask), ...]}. Returns albedo,normal,rough (uint8)."""
    minx, maxx, miny, maxy = terrain_extent()
    extent = (maxx - minx, maxy - miny)

    def mat(name):
        c, nrm, r, tile = LIB[name]
        return tiled(_load(c), res, extent, tile), tiled(_load(nrm), res, extent, tile), tiled(_load(r), res, extent, tile)

    alb, nor, rgh = mat(spec["base"])
    for name, m in spec["overlays"]:
        oa, on, orr = mat(name)
        m3 = m[..., None]
        alb = alb * (1 - m3) + oa * m3
        rgh = rgh * (1 - m3) + orr * m3
        nor = blend_normal(nor, on, m)
    to8 = lambda a: (np.clip(a, 0, 1) * 255).astype(np.uint8)
    return to8(alb), to8(nor), to8(rgh)


def write_textures(alb, nor, rgh):
    from PIL import Image
    for f in glob.glob(os.path.join(TEXDIR, "*.png")) + glob.glob(os.path.join(TEXDIR, "*.jpg")):
        os.remove(f)
    os.makedirs(TEXDIR, exist_ok=True)
    Image.fromarray(alb).save(os.path.join(TEXDIR, "ground_Color.png"))
    Image.fromarray(nor).save(os.path.join(TEXDIR, "ground_NormalGL.png"))
    Image.fromarray(rgh).save(os.path.join(TEXDIR, "ground_Roughness.png"))


def set_uv(scale):
    """Rewrite terrain.obj UVs. scale=None -> 0..1 from vertex XY (baked); else x scale."""
    verts, lines = [], []
    for line in open(OBJ):
        lines.append(line)
        if line.startswith("v "):
            p = line.split()
            verts.append((float(p[1]), float(p[2])))
    vx = np.array([v[0] for v in verts]); vy = np.array([v[1] for v in verts])
    minx, maxx, miny, maxy = vx.min(), vx.max(), vy.min(), vy.max()
    u = (vx - minx) / (maxx - minx); v = (vy - miny) / (maxy - miny)
    if scale is not None:
        u = u * scale; v = v * scale
    out, vi = [], 0
    for line in lines:
        if line.startswith("vt "):
            out.append(f"vt {u[vi]:.6f} {v[vi]:.6f}\n"); vi += 1
        else:
            out.append(line)
    # ensure count matches (vt count == v count in this pipeline)
    open(OBJ, "w").writelines(out)


def write_sdf():
    sdf = '''<?xml version="1.0" ?>
<sdf version="1.8">
    <model name="terrain">
        <static>true</static>
        <link name="link">
            <collision name="collision">
                <geometry><mesh><uri>model://ground/mesh/terrain.stl</uri></mesh></geometry>
            </collision>
            <visual name="visual">
                <geometry><mesh><uri>model://ground/mesh/terrain.obj</uri></mesh></geometry>
                <material>
                    <ambient>1.0 1.0 1.0 1</ambient>
                    <diffuse>1.0 1.0 1.0 1</diffuse>
                    <specular>0.1 0.1 0.1 1</specular>
                    <pbr><metal>
                        <albedo_map>model://ground/texture/ground_Color.png</albedo_map>
                        <normal_map>model://ground/texture/ground_NormalGL.png</normal_map>
                        <roughness_map>model://ground/texture/ground_Roughness.png</roughness_map>
                        <metalness>0.0</metalness>
                    </metal></pbr>
                </material>
            </visual>
        </link>
    </model>
</sdf>'''
    open(os.path.join(GROUND, "model.sdf"), "w").write(sdf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["uniform", "patchy", "debug"], default="patchy")
    ap.add_argument("--res", type=int, default=4096)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tile", type=float, default=8.0, help="uniform mode tiles/terrain-span")
    ap.add_argument("--base", default="grass")
    args = ap.parse_args()
    rng = np.random.default_rng(args.seed)

    if args.mode == "uniform":
        c, nrm, r, _ = LIB[args.base]
        from PIL import Image
        alb, nor, rgh = _load(c), _load(nrm), _load(r)
        to8 = lambda a: (np.clip(a, 0, 1) * 255).astype(np.uint8)
        write_textures(to8(alb), to8(nor), to8(rgh))
        set_uv(args.tile)
        write_sdf()
        print(f"UNIFORM base={args.base} tile=x{args.tile}")
        return

    res = args.res
    if args.mode == "debug":
        # off-centre sand band (v 0.55-0.75) + corner gravel square (u,v 0.1-0.25)
        band = np.zeros((res, res), np.float32)
        band[int(0.55 * res):int(0.75 * res), :] = 1.0
        sq = np.zeros((res, res), np.float32)
        sq[int(0.10 * res):int(0.25 * res), int(0.10 * res):int(0.25 * res)] = 1.0
        spec = {"base": "grass", "overlays": [("sand", band), ("gravel", sq)]}
    else:  # patchy
        spec = {"base": "grass", "overlays": [
            ("sand", soft_blobs(res, 3, (0.05, 0.12), rng)),
            ("gravel", soft_blobs(res, 2, (0.04, 0.09), rng)),
            ("pebbles", soft_blobs(res, 4, (0.02, 0.05), rng)),
            ("trail", trail_mask(res, random_walk_uv(rng), width_m=2.5, extent_m=_extent())),
            ("trail", trail_mask(res, [(0.05, 0.5), (0.4, 0.55), (0.7, 0.45), (0.95, 0.6)],
                                 width_m=2.0, extent_m=_extent())),
        ]}
    alb, nor, rgh = composite(spec, res, rng)
    write_textures(alb, nor, rgh)
    set_uv(None)
    write_sdf()
    # also dump a small preview of the albedo for offline verification
    from PIL import Image
    Image.fromarray(alb).resize((512, 512)).save(os.path.join(ROOT, "spike", f"ground_{args.mode}_preview.png"))
    print(f"{args.mode.upper()} res={res} seed={args.seed} -> ground_Color/NormalGL/Roughness.png + 0..1 UV")


def _extent():
    minx, maxx, miny, maxy = terrain_extent()
    return (maxx - minx, maxy - miny)


if __name__ == "__main__":
    main()
