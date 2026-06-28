"""Render a seeded gallery of terraingen presets through the full pipeline and
compose one PNG. Runs inside forest3d:egl with --gpus all.

For each preset: terraingen -> terrain (mesh) -> ground (uniform) ->
[water plane for lakeland, at the sidecar's suggested level] -> render oblique
(+ top-down for lakeland) -> save frames. Then tile into spike/terrain_gallery.png.
"""
import json
import os
import subprocess
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CLI = ["python3", "-m", "forest3d.cli.main"]
SEED = 7
PRESETS = ["flat", "hilly", "valley", "mountainous", "lakeland"]


def run(cmd, **env):
    e = dict(os.environ)
    e.update(env)
    return subprocess.run(cmd, env=e, capture_output=True, text=True)


def render(world, cams):
    g = subprocess.Popen(["gz", "sim", "-s", "-r", "--headless-rendering", world],
                         stdout=open("/workspace/frames/gz.log", "w"), stderr=subprocess.STDOUT)
    try:
        subprocess.run(["python3", "/workspace/spike/capture_cams.py", ",".join(cams)],
                       timeout=70)
    finally:
        g.terminate()
        try:
            g.wait(timeout=10)
        except subprocess.TimeoutExpired:
            g.kill()


panels = []
for p in PRESETS:
    dem = f"dem/synth_{p}.tif"
    print(f"=== {p} ===", flush=True)
    r = run(CLI + ["terraingen", "--preset", p, "--seed", str(SEED), "--size", "192", "-o", dem])
    print(r.stdout.strip()[-300:], flush=True)
    run(CLI + ["terrain", "--dem", dem])
    run(CLI + ["ground", "--mode", "uniform",
               "--biome", "snow" if p == "mountainous" else ("desert" if p == "flat" else "grassland")])

    water = "0"
    level = None
    sidecar = f"dem/synth_{p}.lakes.json"
    if os.path.exists(sidecar):
        lakes = json.load(open(sidecar))["lakes"]
        if lakes:
            level = min(l["suggested_water_level"] for l in lakes)
            run(CLI + ["ground", "--mode", "uniform", "--biome", "grassland",
                       "--water-level", str(level)])
            water = "1"
            print(f"  water plane @ {level}", flush=True)

    cams = ["cam_oblique", "cam_top"] if p == "lakeland" else ["cam_oblique"]
    run(["python3", "/workspace/spike/terrain_scene.py"], WATER=water)
    render("/workspace/worlds/terrain_scene.world", cams)
    time.sleep(0.5)
    for c in cams:
        f = f"/workspace/frames/{c}.npy"
        if os.path.exists(f):
            label = p if c == "cam_oblique" else f"{p} (top, water z={level})"
            panels.append((label, np.load(f)))


# compose: scale panels to a common width, stack vertically in two columns
def fit(a, w, h):
    img = Image.fromarray(a).convert("RGB")
    img.thumbnail((w, h))
    canvas = Image.new("RGB", (w, h), (222, 233, 244))
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return canvas


PW, PH = 640, 440
cols = 2
rows = (len(panels) + cols - 1) // cols
gallery = Image.new("RGB", (cols * PW, rows * PH), (240, 244, 248))
draw = ImageDraw.Draw(gallery)
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
except Exception:
    font = ImageFont.load_default()
for i, (label, a) in enumerate(panels):
    r, c = divmod(i, cols)
    x, y = c * PW, r * PH
    gallery.paste(fit(a, PW, PH), (x, y))
    draw.rectangle([x + 8, y + 8, x + 18 + draw.textlength(label, font=font), y + 40], fill=(0, 0, 0))
    draw.text((x + 13, y + 10), label, fill=(255, 255, 255), font=font)

out = "/workspace/spike/terrain_gallery.png"
gallery.save(out)
print(f"wrote {out}  ({len(panels)} panels)", flush=True)
