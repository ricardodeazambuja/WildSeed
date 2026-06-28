"""Build the 6 Forest3D demo scenarios end-to-end and render galleries.

Runs inside forest3d:egl with --gpus all. For each scenario:
  terraingen -> terrain -> ground (patchy biome [+auto-water]) -> generate (seeded)
  -> terrain_scene (graft placed models + cameras) -> render hero + oblique + top.

SPECIES are constrained per scenario from the per-biome palettes in
assets/manifest.yaml. `generate` picks a random variant per slot from whatever is in
models/<cat>/, so for each scenario we stash every model NOT in that biome's palette
(across tree/bush/rock/grass), generate, then restore. Density (the tree/rock/bush/
grass counts) is the user-tunable knob: edit it here, or override per run with
`forest3d generate --density '{"tree":80,...}'`.

Output: frames/scn_<name>_{hero,oblique,top}.npy and:
  spike/scenarios_gallery.png   (hero, human-scale)
  spike/scenarios_overview.png  (oblique, aerial)
"""
import json
import os
import shutil
import subprocess

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFont

CLI = ["python3", "-m", "forest3d.cli.main"]
WS = "/workspace"
MODELS = os.path.join(WS, "models")
CATS = ["tree", "bush", "rock", "grass"]
STASH = os.path.join(MODELS, "_demo_stash")

BIOMES = yaml.safe_load(open(os.path.join(WS, "assets/manifest.yaml")))["biomes"]

# name, terraingen flags, biome(palette+ground), density, water, blurb
SCN = [
    dict(name="temperate_hills", biome="temperate",
         tg=["--preset", "hilly", "--seed", "7", "--detail", "0.5"],
         density={"tree": 90, "rock": 18, "bush": 70, "grass": 180}, water=False,
         blurb="Rolling green hills, broadleaf forest + understory"),
    dict(name="savanna_flats", biome="savanna",
         tg=["--preset", "hilly", "--seed", "3", "--amplitude", "14", "--detail", "0.4"],
         density={"tree": 16, "rock": 34, "bush": 48, "grass": 140}, water=False,
         blurb="Arid flats, quiver trees + scrub + dry bloom"),
    dict(name="lakeland_wetland", biome="wetland",
         tg=["--preset", "lakeland", "--seed", "7"],
         density={"tree": 60, "rock": 14, "bush": 75, "grass": 150}, water=True,
         blurb="Basins holding water, reeds/ferns along the shores"),
    dict(name="alpine_snow", biome="alpine",
         tg=["--preset", "mountainous", "--seed", "7", "--ridged", "0.2", "--detail", "0.6"],
         density={"tree": 40, "rock": 40, "bush": 24, "grass": 60}, water=False,
         blurb="SNOW - rugged massif, conifers + boulders"),
    dict(name="winter_forest", biome="winter",
         tg=["--preset", "valley", "--seed", "5", "--detail", "0.6"],
         density={"tree": 80, "rock": 18, "bush": 0, "grass": 70}, water=False,
         blurb="SNOW - snowy valley, conifers + dead trunks"),
    dict(name="coastal_dune", biome="coastal",
         tg=["--preset", "hilly", "--seed", "11", "--amplitude", "9", "--detail", "0.35"],
         density={"tree": 18, "rock": 24, "bush": 60, "grass": 140}, water=False,
         blurb="Coastal dune, marram grass + dune shrubs + coast rocks"),
]

# FOREST_SCN=name1,name2 renders only those scenarios (fast iteration).
_only = os.environ.get("FOREST_SCN")
if _only:
    SCN = [s for s in SCN if s["name"] in _only.split(",")]


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def render(cams, tag, water):
    env = dict(os.environ, FOREST="1")
    if water:
        env["WATER"] = "1"
    run(["python3", f"{WS}/spike/terrain_scene.py"], env=env)
    g = subprocess.Popen(["gz", "sim", "-s", "-r", "--headless-rendering",
                          f"{WS}/worlds/terrain_scene.world"],
                         stdout=open(f"{WS}/frames/gz_{tag}.log", "w"),
                         stderr=subprocess.STDOUT)
    try:
        run(["python3", f"{WS}/spike/capture_cams.py", ",".join(cams)], timeout=120)
    finally:
        g.terminate()
        try:
            g.wait(timeout=10)
        except subprocess.TimeoutExpired:
            g.kill()
    for c in cams:
        f = f"{WS}/frames/{c}.npy"
        if os.path.exists(f):
            shutil.copy(f, f"{WS}/frames/scn_{tag}_{c}.npy")


def constrain(palette):
    """Stash every model NOT in this biome's palette, across all categories.

    palette: {trees:[...], bushes:[...], grasses:[...], rocks:[...]}.
    Restores anything previously stashed first, so scenarios don't leak into each other.
    """
    key = {"tree": "trees", "bush": "bushes", "rock": "rocks", "grass": "grasses"}
    os.makedirs(STASH, exist_ok=True)
    # restore all stashed first
    for cat in CATS:
        st = os.path.join(STASH, cat)
        if os.path.isdir(st):
            for d in os.listdir(st):
                shutil.move(os.path.join(st, d), os.path.join(MODELS, cat, d))
    # stash disallowed per category
    for cat in CATS:
        allowed = set(palette.get(key[cat], []))
        catdir = os.path.join(MODELS, cat)
        if not os.path.isdir(catdir):
            continue
        st = os.path.join(STASH, cat)
        os.makedirs(st, exist_ok=True)
        for d in os.listdir(catdir):
            if os.path.isdir(os.path.join(catdir, d)) and d not in allowed:
                shutil.move(os.path.join(catdir, d), os.path.join(st, d))


def restore_all():
    for cat in CATS:
        st = os.path.join(STASH, cat)
        if os.path.isdir(st):
            for d in os.listdir(st):
                shutil.move(os.path.join(st, d), os.path.join(MODELS, cat, d))
    shutil.rmtree(STASH, ignore_errors=True)


for s in SCN:
    name, biome = s["name"], s["biome"]
    pal = BIOMES[biome]
    ground = pal.get("ground", "grassland")
    print(f"=== {name} (biome={biome}, ground={ground}) ===", flush=True)
    # --pixel 1.6 -> ~307 m world (vs 480 m at the 2.5 default): same plant sizes read
    # bigger/denser, so scenes look populated rather than a few specks on a vast hill.
    run(CLI + ["terraingen"] + s["tg"] + ["--size", "192", "--pixel", "1.6",
               "-o", "dem/synth.tif"])
    run(CLI + ["terrain", "--dem", "dem/synth.tif"])
    run(CLI + ["ground", "--mode", "patchy", "--biome", ground, "--seed", "7", "--res", "4096"])
    for d in os.listdir(MODELS):
        if d.startswith("water"):
            shutil.rmtree(os.path.join(MODELS, d), ignore_errors=True)
    if s["water"]:
        run(CLI + ["ground", "--mode", "patchy", "--biome", ground, "--seed", "7",
                   "--res", "256", "--auto-water", "--dem", "dem/synth.tif"])
        run(CLI + ["ground", "--mode", "patchy", "--biome", ground, "--seed", "7", "--res", "4096"])
    constrain(pal)
    run(CLI + ["generate", "--density", json.dumps(s["density"]), "--seed", "7"])
    render(["cam_hero", "cam_oblique", "cam_top"], name, s["water"])
    print(f"  rendered {name}", flush=True)

restore_all()


# ---- galleries (6 panels, 2 cols x 3 rows) ----
def lab(img, t):
    d = ImageDraw.Draw(img)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
    except Exception:
        f = ImageFont.load_default()
    d.rectangle([8, 8, 18 + d.textlength(t, font=f), 44], fill=(0, 0, 0))
    d.text((13, 11), t, fill=(255, 255, 255), font=f)
    return img


def fit(a, w, h):
    im = Image.fromarray(a).convert("RGB")
    im.thumbnail((w, h))
    c = Image.new("RGB", (w, h), (222, 233, 244))
    c.paste(im, ((w - im.width) // 2, (h - im.height) // 2))
    return c


def make_gallery(cam, outfile, PW=720, PH=420):
    cols, rows = 2, 3
    G = Image.new("RGB", (cols * PW, rows * PH), (240, 244, 248))
    for i, s in enumerate(SCN):
        f = f"{WS}/frames/scn_{s['name']}_{cam}.npy"
        if not os.path.exists(f):
            continue
        r, c = divmod(i, cols)
        G.paste(lab(fit(np.load(f), PW, PH), f"{i+1}. {s['name']}"), (c * PW, r * PH))
    G.save(outfile)
    print("wrote", outfile, flush=True)


make_gallery("cam_hero", f"{WS}/spike/scenarios_gallery.png")
make_gallery("cam_oblique", f"{WS}/spike/scenarios_overview.png")
