# WildSeed — reproducible wilderness for robot perception

**One seed, a whole wilderness.** WildSeed generates randomized, feature-rich outdoor
Gazebo worlds for testing VIO / LIO / SLAM algorithms — procedural terrain, seeded
ground materials, lakes, and hundreds of placed CC0 plants and rocks — and every
world is **reproducible from a single master seed**, so a failing odometry run
can name the exact world it saw and anyone can regenerate it.

**Scope: worlds only.** Robots, sensors and autonomy stacks are deliberately out of
scope and live in a separate repository — WildSeed generates the environments they
are spawned into. (The only sensor-adjacent piece here is a printable lens-flare
camera-plugin snippet, see `wildseed weather --show-lens-flare-snippet`.)

[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

![master-seed scenarios](tools/scenario_seeds_gallery.png)

*Three master seeds, three worlds: `--seed 101` grows a lakeland wetland,
`--seed 107` rolling temperate hills, `--seed 108` an alpine massif. Same seed →
identical world, always.*

## Pipeline

WildSeed follows a 4-step pipeline to generate simulation environments:

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   1. TERRAIN    │     │   2. CONVERT    │     │   3. GENERATE   │     │   4. LAUNCH     │
│                 │     │                 │     │                 │     │                 │
│  DEM (GeoTIFF)  │────►│ Blender Assets  │────►│  Place Models   │────►│ Open Gazebo     │
│       ↓         │     │       ↓         │     │       ↓         │     │       ↓         │
│  models/ground/ │     │ models/{tree,   │     │ worlds/forest_  │     │  Simulation     │
│                 │     │  rock,bush,...} │     │    world.world  │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘
```

| Step | Command | Input | Output |
|------|---------|-------|--------|
| 1 | `wildseed terrain` | DEM file (.tif) | Terrain mesh + SDF model |
| 2 | `wildseed convert` | Blender files (.blend) | Gazebo models (glTF + SDF) |
| 3 | `wildseed generate` | models/ directory | World file (.world) |
| 4 | `wildseed launch` | World file | Gazebo simulation |

**Example workflow:**
```bash
# Step 1: Generate terrain from DEM
wildseed terrain --dem ./dem/terrain.tif

# Step 2: Convert Blender assets (auto-detects categories from subfolders)
wildseed convert -i ./Blender-Assets -o ./models

# Step 3: Generate forest world (places models on terrain)
wildseed generate --density '{"tree": 50, "rock": 10, "bush": 20}'

# Step 4: Launch Gazebo to view the result
wildseed launch
```

## Procedural terrain & seeded scenarios

Beyond meshing a fixed DEM, WildSeed can **synthesize** varied, seeded landforms —
rolling hills, mountains, valleys, flatlands, basins→lakes, creeks — and randomize
whole scenarios reproducibly (same `--seed` → same world) for VIO/lidar testing.

**One command, one master seed** — `wildseed scenario` chains every stage
(landform → mesh → ground material → water → model placement), deriving each
stage's seed from the master seed and drawing the biome, terrain shape and
densities from per-biome envelopes. Eight biomes: six wilderness (temperate,
savanna, wetland, alpine, winter, coastal) + two structured plantations
(`orchard`, `vineyard` — repetitive rows, the loop-closure stress test). Every
world ships with `scenario_<seed>.yaml` (the full resolved recipe — any world
reproduces from its seed alone) and `scenario_<seed>.instances.json`
(per-instance ground truth: model, category, pose, scale):

```bash
wildseed scenario --seed 42                      # fully random, byte-reproducible
wildseed scenario --seed 42 --biome alpine       # fix the biome, randomize the rest
wildseed scenario --seed 7  --density-scale 1.5  # denser variant of seed 7
wildseed scenario --seed 7  --dry-run            # print the resolved recipe only
```

The individual stages remain available for manual control:

```bash
wildseed terraingen --preset lakeland --seed 7 -o dem/synth.tif   # synth landform
wildseed terrain    --dem dem/synth.tif                           # mesh it
wildseed ground     --mode patchy --biome grassland --auto-water --dem dem/synth.tif
wildseed generate   --density '{"tree":35,"rock":12}' --seed 7    # populate
```

![demo scenarios](tools/scenarios_gallery.png)

Six ready-made demo scenarios (two snow) — **temperate hills, savanna flats,
lakeland wetland, alpine snow, winter forest, coastal dune** — each with a 3-layer
structure (canopy trees / understory shrubs / grass + flowers) built from **CC0
Poly Haven assets** and reproduced with **no account or login**:

```bash
# NOTE: the demo renderer needs a GPU (ogre2/EGL). Run inside the wildseed:egl image with
# --gpus all; see "Gotchas, best practices & caveats" below. Asset build needs Blender only.
python3 tools/build_assets.py       # fetch+convert the CC0 asset set (idempotent)
python3 tools/build_scenarios.py    # build all 6 + render tools/scenarios_gallery.png
```

Density is fully tunable per category — `wildseed generate --density
'{"tree":80,"rock":6,"bush":40,"grass":120}' --seed 7` — same `--seed` → identical world.

**Docs:**

- **[docs/TUTORIAL.md](docs/TUTORIAL.md)** — build & randomize a world in 5 minutes
- **[docs/TERRAIN_GENERATOR.md](docs/TERRAIN_GENERATOR.md)** — `terraingen` reference (presets, all knobs, lakes)
- **[docs/SCENARIOS.md](docs/SCENARIOS.md)** — the 6 demo scenarios + density tuning
- **[docs/REALISTIC_DEMOS_PLAN.md](docs/REALISTIC_DEMOS_PLAN.md)** — how the reproducible CC0 asset set is sourced
- **[docs/DEMO_REALISM_V2_REPORT.md](docs/DEMO_REALISM_V2_REPORT.md)** — how the demos were made VIO/LIO-usable + measurably closer to the reference screenshots (the honest CC0 ceiling)
- **[docs/baseline_metrics.md](docs/baseline_metrics.md)** — the image-level metric harness (`tools/compare.py`) + before/after numbers per phase
- **[docs/history/](docs/history/)** — superseded planning notes, kept for provenance

### Reproducibility

The Docker image is **version-pinned** so a rebuild can't drift when an upstream
library changes: base image by digest, `gz-harmonic`=1.0.0-1~jammy + Blender 4.2.3
(checksum-verified) + all Python deps frozen in
[`docker/constraints.txt`](docker/constraints.txt) (PyPI keeps old versions, so these
are durable). The demo asset set is pinned in
[`assets/manifest.yaml`](assets/manifest.yaml) with source sha256s in
`assets/manifest.lock.yaml`, fetched **credential-free** from Poly Haven (all CC0;
credits in [tools/ASSET_REGISTRY.md](tools/ASSET_REGISTRY.md)).

> **Residual apt risk — archive the image for a true freeze.** The OSRF (`gz-harmonic`)
> and Ubuntu (`gdal-bin`, etc.) apt repos serve only the *current* version, so a far-future
> `docker build` can fail if they drop `1.0.0-1~jammy` / bump GDAL (which could also break
> the numpy-1.26 ABI pairing). A Dockerfile can't pin a repo that deletes old debs. For a
> guaranteed-reproducible artifact, **save the built image**, don't rely on rebuilding:
> `docker save wildseed:egl | gzip > wildseed-egl-v1.tar.gz` (or push to a registry).

## Gotchas, best practices & caveats

Hard-won lessons (and the cheapest way to avoid each). These cost real debugging time — read
them before the demo/realism pipeline surprises you.

- **Rendering needs a real GPU (ogre2/EGL).** The scenario/metric renders use the `ogre2`
  engine via EGL. Run them in the `wildseed:egl` image with `--gpus all` and
  `NVIDIA_DRIVER_CAPABILITIES=all`. On CPU/llvmpipe you get blank or wrong frames. The plain
  pipeline (`terrain`/`convert`/`generate`) does **not** need a GPU; only the render step does.
  ```bash
  docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -e PYTHONPATH=/workspace/src \
    -v "$PWD:/workspace" --entrypoint bash wildseed:egl -c 'cd /workspace && python3 tools/build_scenarios.py'
  ```
- **Editing the library inside the container? Shadow the installed package.** `wildseed` is
  **pip-installed** into the image, so `python3 -m wildseed ...` imports the *baked-in* copy and
  silently ignores your edits to `src/wildseed/**`. Pass `-e PYTHONPATH=/workspace/src` to make
  the workspace source win. Symptom if you forget: metrics/output identical after a "change."
  (CLI flags and the `tools/*.py` scripts take effect without this — they read the live files.)
- **Determinism is a feature — use `--seed`.** Same `--seed` + preset → byte-identical DEM and
  identical placement. The 6 demo scenarios reproduce exactly from a clean build (verified: the
  rendered PNGs are byte-identical across rebuilds). Vary the seed to get a fresh-but-reproducible
  world for VIO/LIO test runs.
- **Single-scene builds leave the gallery with one panel.** `FOREST_SCN=savanna_flats python3
  tools/build_scenarios.py` renders only that scene, so the 6-panel `tools/scenarios_gallery.png`
  ends up with a single panel. Rebuild the galleries from the frames on disk with
  `python3 tools/regen_galleries.py` (no re-render needed).
- **CC0 ceiling — what "realistic" does and doesn't mean here.** The demo assets are free **CC0**
  (Poly Haven), *not* the commercial Maxtree foliage / Megascans scans in the reference
  screenshots. So the demos match **composition, density, variety, terrain shape and ground
  non-repetition** — not per-asset fidelity: CC0 foliage reads darker/sparser at distance, and
  bare-sand biomes keep genuine surface relief. The gap is measured, not hidden — see
  [docs/DEMO_REALISM_V2_REPORT.md](docs/DEMO_REALISM_V2_REPORT.md).
- **Foliage must export as `alphaMode=MASK`, or you get black blobs.** Poly Haven foliage wires
  leaf transparency through a custom node group the glTF exporter can't read → it exports
  `alphaMode=BLEND` → dense double-sided leaves render as dark depth-sorted blobs.
  `tools/normalize_blend.py` rebuilds the leaf material as a plain Principled BSDF with
  `Math:GreaterThan(0.5)→Alpha` so Blender 4.2 writes `MASK`. **Verify:** the `.glb` material's
  `alphaMode` must be `MASK` (not `BLEND`). Also prefer the *assembled* `<id>_LOD<n>` tree object
  (>100k tris), not the kit pieces (a few hundred tris → flat cards).
- **The metric harness lives in-container.** `tools/compare.py` (needs `opencv-python-headless`,
  already in `:egl`) quantifies the realism gap against the 3 reference screenshots. Crop the
  Gazebo GUI (toolbar/playbar) from screenshots first — it does this for the bundled originals.
  `tools/quickmetric.py <scene>` gives a fast single-scene readout.
- **For a *true* freeze, save the image, don't rebuild it** (see the apt caveat above).

## Features

- **Terrain Generation**: DEM processing with resolution enhancement and Gaussian smoothing
- **Procedural Terrain**: seeded synthesis of hills/mountains/valleys/lakes/creeks (`terraingen`)
- **Asset Processing**: Automatic Blender to Gazebo conversion with optimized collision meshes
- **Forest Population**: Intelligent procedural placement with natural clustering patterns
- **Row Plantations**: orchards/vineyards — structured, repetitive rows (spacing, jitter,
  missing plants, waviness), the loop-closure stress test wilderness scatter can't produce
- **Ground Truth**: every world ships a `.instances.json` sidecar (model, category, pose,
  scale per placed instance) + per-category `laser_retro` labels so lidar intensity doubles
  as a semantic class channel (experimental)
- **Passable Understory**: robots drive through grass/bushes (no physics blow-ups) while
  lidar still returns hits from them
- **Density-Map Placement**: steer vegetation layout with a grayscale image
  (white=dense, black=never) instead of uniform randomness — `generate --density-maps`
  ([docs](docs/DOMAIN_RANDOMIZATION.md))
- **Texture Domain Randomization**: seeded recolouring of model textures
  (`wildseed randomize`, alpha cutouts preserved) and ground (`--hsv-jitter`, plus a fully
  procedural unrealistic `--mode wild`) ([docs](docs/DOMAIN_RANDOMIZATION.md))
- **Procedural Assets**: `wildseed assetgen` synthesizes seeded parametric rocks, boulders,
  trees, conifers, bushes and grass in headless Blender — tiny models, no downloads
  ([docs](docs/DOMAIN_RANDOMIZATION.md))
- **Weather**: `wildseed weather` presets — overcast, fog, rain, snow, sun glare
  (particle emitters + sun/scene rewrite, idempotent) ([docs](docs/DOMAIN_RANDOMIZATION.md))
- **Unified CLI**: Simple `wildseed` command with subcommands for each operation
- **Docker Support**: Pre-built images with GDAL for easy deployment

## Quick Start

### Option 1: Docker (Recommended)

The Docker image includes everything you need: Python, GDAL, Blender 4.2, and Gazebo Harmonic.

```bash
# Build the image (downloads Blender + Gazebo, ~2GB)
cd WildSeed
docker build -t wildseed -f docker/Dockerfile .

# Generate a forest world
docker run -v $(pwd):/workspace wildseed generate

# Convert Blender assets to Gazebo models
docker run -v $(pwd):/workspace wildseed convert \
  -i /workspace/Blender-Assets -o /workspace/models -c tree

# Launch Gazebo to view the world (requires X11)
xhost +local:docker  # Allow Docker to access display
docker run -e DISPLAY=$DISPLAY \
           -v /tmp/.X11-unix:/tmp/.X11-unix \
           -v $(pwd):/workspace \
           --network host \
           wildseed launch
```

### Option 2: pip install

```bash
# Clone and install
git clone https://github.com/ricardodeazambuja/WildSeed.git
cd WildSeed
pip install -e .

# For terrain generation, also install GDAL:
# Ubuntu/Debian:
sudo apt install python3-gdal gdal-bin libgdal-dev
pip install "pygdal==$(gdal-config --version).*"
```

## Usage

### Generate Forest World

```bash
# Use default settings
wildseed generate

# Custom density
wildseed generate --density '{"tree": 100, "rock": 20, "bush": 30}'

# Use a preset configuration
wildseed -c configs/examples/dense_forest.yaml generate
```

### Generate Terrain from DEM

```bash
wildseed terrain --dem ./dem/terrain.tif

# With texture from Blender
wildseed terrain --dem ./dem/terrain.tif --texture ./Blender-Assets/soil/soil.blend

# With options
wildseed terrain --dem ./dem/terrain.tif --scale 2.0 --smooth 1.5 --enhance
```

### Convert Blender Assets

```bash
# Auto-detect categories from subfolders (tree/, rock/, bush/, etc.)
wildseed convert -i ./Blender-Assets -o ./models

# Or specify category manually
wildseed convert -i ./Blender-Assets/tree -o ./models -c tree
```

### Launch Gazebo

```bash
# Using the CLI (auto-configures model path)
wildseed launch

# Or manually with Gazebo Sim (Harmonic)
export GZ_SIM_RESOURCE_PATH=$GZ_SIM_RESOURCE_PATH:$(pwd)/models
gz sim worlds/forest_world.world
```

## CLI Reference

```
wildseed --help                    # Show all commands
wildseed terrain --help            # Terrain generation help
wildseed convert --help            # Asset conversion help
wildseed generate --help           # Forest generation help
wildseed launch --help             # Launch Gazebo help

# Global options
wildseed -v ...                    # Verbose output
wildseed -vv ...                   # Debug output
wildseed -c config.yaml ...        # Use config file
```

## Configuration

Create `wildseed.yaml` in your project directory:

```yaml
terrain:
  scale_factor: 1.0
  smooth_sigma: 1.0
  enhance: false

density:
  tree: 50
  bush: 10
  rock: 5
  grass: 50
  sand: 5

blender:
  visual_decimation: 0.1
  collision_decimation: 0.01
```

See `configs/examples/` for preset configurations.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `WILDSEED_BLENDER_PATH` | Path to Blender executable |
| `WILDSEED_BASE_PATH` | Project base directory |
| `WILDSEED_MODELS_PATH` | Models output directory |

## Project Structure

```
WildSeed/
├── src/wildseed/          # Python package (the installed `wildseed` CLI) — independent of tools/
│   ├── cli/               # Command-line interface
│   ├── core/              # Core modules (terrain, terraingen, converter, forest, ground)
│   ├── config/            # Configuration handling (pydantic schema, loader)
│   └── utils/             # Shared utilities
├── tools/                 # Dev/build tooling for the reproducible demos (NOT the library)
│   ├── build_assets.py    #   fetch + convert the CC0 Poly Haven asset set
│   ├── build_scenarios.py #   build + render all 6 demo scenarios
│   ├── compare.py         #   image-level metric harness vs the reference screenshots
│   ├── normalize_blend.py #   Blender asset normalizer (MASK foliage, LOD/variant pick)
│   ├── ASSET_REGISTRY.md  #   per-asset source + license credits
│   └── archive/           #   one-off spike-era diagnostic renders (historical)
├── dem/                   # DEM files (GeoTIFF); bundled samples + seeded synth_*.tif (gitignored)
├── Blender-Assets/        # Source .blend files (gitignored; .gitkeep per category)
│   ├── tree/  rock/  bush/  grass/  soil/
├── models/                # Generated Gazebo models (gitignored)
│   ├── ground/            #   terrain model
│   └── tree/, rock/, etc. #   asset models
├── worlds/                # Generated world files (gitignored)
├── configs/               # Configuration presets (default.yaml, realism.yaml, examples/)
├── assets/                # Demo asset manifest + source-hash lock (manifest.yaml, .lock.yaml)
├── docs/                  # Tutorials, terrain/scenario refs, realism report + metrics
│   └── history/           #   superseded planning notes, kept for provenance
├── tests/                 # pytest suite
└── docker/                # Dockerfiles (base + .egl GPU render), constraints, compose
```

## Asset Categories

| Category | Description | Default Count |
|----------|-------------|---------------|
| tree | Large vegetation | 50 |
| bush | Small vegetation/shrubs | 10 |
| rock | Rock formations | 5 |
| grass | Ground cover | 50 |
| sand | Sand dunes/patches | 5 |

## Adding Custom Assets

1. Place `.blend` files in category subfolders:
   ```
   Blender-Assets/
   ├── tree/your_tree.blend
   ├── rock/your_rock.blend
   └── bush/your_bush.blend
   ```
2. Convert to Gazebo format:
   ```bash
   wildseed convert -i ./Blender-Assets -o ./models
   ```
3. Models will be available for forest generation

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/

# Lint
pylint src/wildseed/
```

## Docker Compose

```bash
# Development environment (with Blender + GDAL + Gazebo)
docker compose -f docker/docker-compose.yml run wildseed-dev

# Convert Blender assets
docker compose -f docker/docker-compose.yml run convert \
  -i /workspace/Blender-Assets -o /workspace/models -c tree

# Generate terrain from DEM
docker compose -f docker/docker-compose.yml run terrain --dem terrain.tif

# Generate forest world
docker compose -f docker/docker-compose.yml run generate

# Launch Gazebo to view world (requires X11)
xhost +local:docker
docker compose -f docker/docker-compose.yml run launch
```

## Troubleshooting

### GDAL Not Found
Use Docker or install GDAL system packages:
```bash
# Ubuntu/Debian
sudo apt install python3-gdal gdal-bin libgdal-dev
pip install "pygdal==$(gdal-config --version).*"
```

### Blender Not Found
Set the path explicitly:
```bash
export WILDSEED_BLENDER_PATH=/path/to/blender
# or
wildseed convert --blender /path/to/blender ...
```

### Model Path Issues
Ensure Gazebo Sim can find models:
```bash
export GZ_SIM_RESOURCE_PATH=$GZ_SIM_RESOURCE_PATH:$(pwd)/models
```

## License

This project is licensed under the **AGPL-3.0** — see the [LICENSE](LICENSE) file for
details. Portions derive from the upstream Forest3D project (see Credits below),
which shipped the same AGPL-3.0 license file.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Credits

WildSeed began as a fork of
**[Forest3D](https://github.com/unitsSpaceLab/Forest3D)** by Khalid Bourr
(AI4Forest / unitsSpaceLab) — the original DEM-terrain → Blender-asset-convert →
procedural-placement pipeline for Gazebo is his work, and that project's commit
history (authors, dates, messages) is preserved in this repository (asset binaries
under the gitignored `models/` and `Blender-Assets/` paths were scrubbed from history
because some were commercial and not redistributable). The three reference
screenshots the metric harness compares against (`Screenshot from 2026-01-*.png`)
are renders from that project and are **not** distributed here (gitignored) —
drop your own copies in the repo root to run `tools/compare.py`. Thank you, Khalid.

On top of that foundation, WildSeed added the seeded procedural terrain synthesizer,
the seeded patchy-ground compositor with per-basin water, the master-seed `scenario`
orchestrator, the manifest-driven CC0 asset pipeline, the image-level realism metric
harness, and the reproducibility guarantees (pinned Docker, sha256-locked assets,
byte-identical worlds per seed). Documents under [docs/history/](docs/history/) and
the realism reports predate the rename and refer to the project as Forest3D.

Several capabilities are adapted from
**[CropCraft](https://github.com/ricardodeazambuja/cropcraft)** (INRAE,
Apache-2.0), a crop-field generator for agricultural robotics: the structured
row-planting engine (orchard/vineyard biomes, `--rows`), the per-instance
ground-truth export, per-category `laser_retro` semantic lidar labels, and
passable-understory collisions (`collide_without_contact`). No CropCraft code
or assets are bundled — the ideas were reimplemented against WildSeed's
terrain-following, master-seeded pipeline.

## Asset credits

Every 3D model and texture WildSeed ships or downloads is **CC0 (public domain)** —
no account, no login, no attribution required. Credit is appreciated nonetheless, so
here is everything the demo worlds reuse (full per-asset provenance, licenses and
evaluation notes live in [tools/ASSET_REGISTRY.md](tools/ASSET_REGISTRY.md); the
buildable list with pinned sha256s is [assets/manifest.yaml](assets/manifest.yaml) +
`assets/manifest.lock.yaml`).

**3D models — [Poly Haven](https://polyhaven.com) (CC0).** Each id resolves as
`https://polyhaven.com/a/<id>`:

| category | assets |
|----------|--------|
| trees (15) | `island_tree_01` `island_tree_02` `island_tree_03` `jacaranda_tree` `tree_small_02` `quiver_tree_01` `quiver_tree_02` `searsia_burchellii` `dead_quiver_trunk` `fir_tree_01` `pine_tree_01` `fir_sapling` `fir_sapling_medium` `pine_sapling_medium` `dead_tree_trunk_02` |
| rocks (6) | `boulder_01` `rock_07` `namaqualand_boulder_04` `namaqualand_rocks_01` `coast_rocks_01` `sand_rocks_small_01` |
| bushes (9) | `shrub_01` `shrub_02` `shrub_03` `shrub_04` `fern_02` `wild_rooibos_bush` `crystalline_iceplant` `othonna_cerarioides` `nettle_plant` |
| grass / ground cover (7) | `grass_medium_01` `grass_medium_02` `grass_bermuda_01` `flower_gazania` `flower_ursinia` `dandelion_01` `dry_branches_medium_01` |

**Ground textures — [ambientCG](https://ambientcg.com) (CC0).** Each id resolves as
`https://ambientcg.com/view?id=<id>`: `Grass004` (base grass), `Ground027` (sand),
`Ground054` (dirt/trail), `Gravel023`, `Rocks023` (pebbles), `Snow006`, `Ground037`
(bare ground). These feed the seeded ground compositor (`wildseed ground`).

**Other bundled data.** The sample DEMs in `dem/` (`terrain.tif`, `demgazebo.dem`, …)
and the three reference screenshots come from the upstream Forest3D project (see
Credits above); the screenshots are used only as metric-harness reference images —
the commercial Maxtree/Megascans assets *shown in them* are not included in, nor
downloadable through, WildSeed. The procedural landforms (`wildseed terraingen`) are
self-authored math — no external asset involved.

