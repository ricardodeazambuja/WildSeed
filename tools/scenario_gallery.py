"""Build + render N master-seed scenarios into a diversity gallery.

Proves `wildseed scenario --seed N` end-to-end: each seed yields a different
biome/landform/population, each world renders from its hero + oblique cams.
Runs inside wildseed:egl with --gpus all (same harness as build_scenarios.py).

  python3 tools/scenario_gallery.py [seed ...]      # default: 101 107 108

Output: frames/seed_<n>_{hero,oblique}.npy and tools/scenario_seeds_gallery.png.
"""
import os
import shutil
import subprocess
import sys

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

WS = "/workspace"
CLI = ["python3", "-m", "wildseed.cli.main"]
SEEDS = [int(a) for a in sys.argv[1:]] or [101, 107, 108]


def run(cmd, **kw):
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        sys.stdout.write(p.stdout[-2000:])
        sys.stderr.write(p.stderr[-2000:])
        raise SystemExit(f"FAILED: {' '.join(cmd)}")
    return p


def rows_hero_env(spec):
    """For structured (rows) scenarios, aim the hero cam INTO the planted
    block: stand just off the rows centroid looking across it, instead of the
    default boulder-framing (which happily frames a rock in an empty corner).
    Centroid comes from the ground-truth instances sidecar."""
    if not spec.get("rows"):
        return {}
    import json
    gt_path = f"{WS}/worlds/scenario_{spec['seed']}.instances.json"
    if not os.path.exists(gt_path):
        return {}
    cats = set(spec["rows"])
    pts = [(i["pose"]["x"], i["pose"]["y"])
           for i in json.load(open(gt_path))["instances"] if i["category"] in cats]
    if not pts:
        return {}
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    ext = spec["size"] * spec["pixel_m"]
    off = 0.55 * float(list(spec["rows"].values())[0].get("field_size", 60))
    return {"HERO_EX": (cx - off) / ext, "HERO_EY": (cy - off * 0.4) / ext,
            "HERO_AX": cx / ext, "HERO_AY": cy / ext, "HERO_EYE": 3.5}


def render(tag, water, extra_env=None):
    env = dict(os.environ, FOREST="1", **({"WATER": "1"} if water else {}))
    if extra_env:
        env.update({k: str(v) for k, v in extra_env.items()})
    run(["python3", f"{WS}/tools/terrain_scene.py"], env=env)
    g = subprocess.Popen(["gz", "sim", "-s", "-r", "--headless-rendering",
                          f"{WS}/worlds/terrain_scene.world"],
                         stdout=open(f"{WS}/frames/gz_{tag}.log", "w"),
                         stderr=subprocess.STDOUT)
    try:
        subprocess.run(["python3", f"{WS}/tools/capture_cams.py", "cam_hero,cam_oblique"],
                       timeout=120)
    finally:
        g.terminate()
        try:
            g.wait(timeout=10)
        except subprocess.TimeoutExpired:
            g.kill()
    for c in ("cam_hero", "cam_oblique"):
        src = f"{WS}/frames/{c}.npy"
        if os.path.exists(src):
            shutil.copy(src, f"{WS}/frames/seed_{tag}_{c.split('_')[1]}.npy")


specs = []
for seed in SEEDS:
    print(f"=== scenario --seed {seed} ===", flush=True)
    run(CLI + ["scenario", "--seed", str(seed)], cwd=WS)
    spec = yaml.safe_load(open(f"{WS}/worlds/scenario_{seed}.yaml"))
    specs.append(spec)
    # terrain_scene grafts from forest_world.world; point it at this scenario
    shutil.copy(f"{WS}/worlds/scenario_{seed}.world", f"{WS}/worlds/forest_world.world")
    render(str(seed), water=spec["outputs"]["lakes"] > 0, extra_env=rows_hero_env(spec))

# compose gallery: rows = seeds, cols = hero | oblique
tiles, W, H = [], 900, 560
for spec in specs:
    seed = spec["seed"]
    row = []
    for cam in ("hero", "oblique"):
        f = f"{WS}/frames/seed_{seed}_{cam}.npy"
        img = Image.fromarray(np.load(f)) if os.path.exists(f) else Image.new("RGB", (W, H), (30, 30, 30))
        row.append(img.resize((W, H)))
    tiles.append((seed, spec, row))

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
except OSError:
    font = ImageFont.load_default()
LBL = 44
sheet = Image.new("RGB", (2 * W, len(tiles) * (H + LBL)), (16, 20, 26))
d = ImageDraw.Draw(sheet)
for i, (seed, spec, row) in enumerate(tiles):
    y = i * (H + LBL)
    dens = spec["density"]
    d.text((12, y + 9),
           f"--seed {seed}  ->  {spec['biome']} / {spec['preset']}   "
           f"trees {dens['tree']}  bush {dens['bush']}  grass {dens['grass']}  "
           f"rocks {dens['rock']}" + (f"   lakes {spec['outputs']['lakes']}"
                                      if spec['outputs']['lakes'] else ""),
           fill=(235, 240, 245), font=font)
    for j, img in enumerate(row):
        sheet.paste(img, (j * W, y + LBL))
out = f"{WS}/tools/scenario_seeds_gallery.png"
sheet.save(out)
print(f"wrote {out}", flush=True)
