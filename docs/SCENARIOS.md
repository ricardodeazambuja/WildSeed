# Forest3D demo scenarios

Six complete, **reproducible** outdoor scenarios built entirely from the seeded
pipeline (`terraingen → terrain → ground → generate`) and **CC0 Poly Haven assets**
(credential-free — no account/login needed). Two are snow scenes. Every command below
is copy-pasteable inside the `forest3d:egl` container (prefix with the Docker wrapper
from `docs/TUTORIAL.md`).

## Reproduce everything in two steps

```bash
# 1. Build the CC0 asset set (fetch -> normalize -> convert; idempotent, ~20 assets)
python3 spike/build_assets.py

# 2. Build all six scenarios + render the galleries
python3 spike/build_scenarios.py    # writes spike/scenarios_gallery.png + _overview.png
```

`build_assets.py` reads `assets/manifest.yaml` (the asset list + per-biome palettes)
and writes `assets/manifest.lock.yaml` with each source's sha256. All assets are CC0
(Poly Haven, https://polyhaven.com) — see `spike/ASSET_REGISTRY.md` for full credits.

## Adjusting density (trees, rocks, bushes, grass)

Density is the main knob and is fully user-tunable. Each scenario sets per-category
counts; override them per run without touching anything else:

```bash
# More trees, fewer rocks, dense understory:
forest3d generate --density '{"tree":80,"rock":6,"bush":40,"grass":120}' --seed 7
```

Categories: `tree`, `bush`, `rock`, `grass`, `sand` (bounds in
`src/forest3d/config/schema.py`: e.g. tree 0–1000, grass 0–2000). Same `--seed` →
identical placement. Each scenario constrains *species* to its biome palette (the
builder stashes models not in `assets/manifest.yaml`'s `biomes.<name>`), so changing a
count rescatters that biome's plants, not a random global mix.

Each scenario uses seed 7 for ground; terrain/placement seeds are per scenario below.

---

## 1. Temperate hills  🌳
Rolling green hills, broadleaf forest (island/jacaranda) with shrub + grass understory.

```bash
forest3d terraingen --preset hilly --seed 7 --detail 0.5 -o dem/synth.tif
forest3d terrain    --dem dem/synth.tif
forest3d ground     --mode patchy --biome grassland --seed 7
forest3d generate   --density '{"tree":40,"rock":12,"bush":24,"grass":60}' --seed 7
```

## 2. Savanna flats  🏜️
Arid flats: sparse quiver trees, dry scrub, desert bloom, lots of rock.

```bash
forest3d terraingen --preset hilly --seed 3 --amplitude 14 --detail 0.4 -o dem/synth.tif
forest3d terrain    --dem dem/synth.tif
forest3d ground     --mode patchy --biome desert --seed 7
forest3d generate   --density '{"tree":6,"rock":22,"bush":12,"grass":30}' --seed 7
```

## 3. Lakeland wetland  💧
Basins that hold water at their own levels, ferns/reeds + dense grass along the shores.

```bash
forest3d terraingen --preset lakeland --seed 7 -o dem/synth.tif
forest3d terrain    --dem dem/synth.tif
forest3d ground     --mode patchy --biome grassland --seed 7
forest3d ground     --mode patchy --biome grassland --seed 7 --auto-water --dem dem/synth.tif
forest3d generate   --density '{"tree":26,"rock":8,"bush":28,"grass":50}' --seed 7
```
(The second `ground` call adds one water plane per basin; see `docs/TUTORIAL.md` §4.)

## 4. Alpine snow  ❄️  *(snow)*
Rugged snowy massif, conifers (fir/pine) and many boulders — high-relief alpine.

```bash
forest3d terraingen --preset mountainous --seed 7 --ridged 0.2 --detail 0.6 -o dem/synth.tif
forest3d terrain    --dem dem/synth.tif
forest3d ground     --mode patchy --biome snow --seed 7
forest3d generate   --density '{"tree":16,"rock":26,"bush":8,"grass":18}' --seed 7
```

## 5. Winter forest  ❄️  *(snow)*
A snowy valley with conifers and dead trunks.

```bash
forest3d terraingen --preset valley --seed 5 --detail 0.6 -o dem/synth.tif
forest3d terrain    --dem dem/synth.tif
forest3d ground     --mode patchy --biome snow --seed 7
forest3d generate   --density '{"tree":35,"rock":10,"bush":0,"grass":22}' --seed 7
```

## 6. Coastal dune  🏖️
Low windswept dunes: marram-style grass, dune shrubs/iceplant, coastal rocks.

```bash
forest3d terraingen --preset hilly --seed 11 --amplitude 9 --detail 0.35 -o dem/synth.tif
forest3d terrain    --dem dem/synth.tif
forest3d ground     --mode patchy --biome desert --seed 7
forest3d generate   --density '{"tree":8,"rock":14,"bush":20,"grass":45}' --seed 7
```

---

### Notes
- Render any scenario with the harness in `docs/TUTORIAL.md` §2 (`FOREST=1
  python3 spike/terrain_scene.py` then `gz sim ...`). Add `WATER=1` for lakeland.
- Species per scenario come from `assets/manifest.yaml` → `biomes.<name>`. Add a
  Poly Haven id to the `assets` list + a biome palette, run `build_assets.py`, and it
  joins the scatter.
- Heights/relief, surface smoothness, biome, and density are independent knobs — mix
  freely to derive new scenarios.
