# Forest3D - Terrain and Forest Generation for Gazebo

Forest3D eliminates the manual overhead of building realistic simulation environments. Using DEM terrain data and Blender assets, it automatically generates collision-accurate Gazebo worlds with procedurally placed vegetation, rocks, and trees—ensuring both visual realism and physical fidelity for simulation.

| Forest Environment – Soil 1 | Forest Environment – Soil 2 | Forest Environment – Soil 3 |
|-----------------|-------------|-------------------|
| ![](https://raw.githubusercontent.com/unitsSpaceLab/Forest3D/feature/terrain-texture/Screenshot%20from%202026-01-08%2023-56-51.png) | ![](https://raw.githubusercontent.com/unitsSpaceLab/Forest3D/feature/terrain-texture/Screenshot%20from%202026-01-09%2000-01-54.png) | ![](https://raw.githubusercontent.com/unitsSpaceLab/Forest3D/feature/terrain-texture/Screenshot%20from%202026-01-09%2000-04-26.png) |



[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

## Demo

LiDAR point cloud (RViz) accurately captures the 3D assets, confirming Forest3D outputs are ready for real sensor-based simulation workflows.
<video src="https://github.com/user-attachments/assets/952f6a1d-dbc8-47dd-bce7-383bfa85e7ca" autoplay loop muted playsinline width="100%"/>

> **Need wheel-soil terramechanics?** A terramechanics-aware version
> (real-time Bekker-Wong wheel-soil forces, used in the IFIT 2026 paper)
> lives on the [`IFIT-2026` branch](https://github.com/unitsSpaceLab/Forest3D/tree/IFIT-2026).
> This `main` branch is the lighter environment-generation pipeline (no terramechanics).

## Tutorial

[![Watch the tutorial](https://img.youtube.com/vi/fLvci8LoMeY/maxresdefault.jpg)](https://youtu.be/fLvci8LoMeY)

## Pipeline

Forest3D follows a 4-step pipeline to generate simulation environments:

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
| 1 | `forest3d terrain` | DEM file (.tif) | Terrain mesh + SDF model |
| 2 | `forest3d convert` | Blender files (.blend) | Gazebo models (glTF + SDF) |
| 3 | `forest3d generate` | models/ directory | World file (.world) |
| 4 | `forest3d launch` | World file | Gazebo simulation |

**Example workflow:**
```bash
# Step 1: Generate terrain from DEM
forest3d terrain --dem ./dem/terrain.tif

# Step 2: Convert Blender assets (auto-detects categories from subfolders)
forest3d convert -i ./Blender-Assets -o ./models

# Step 3: Generate forest world (places models on terrain)
forest3d generate --density '{"tree": 50, "rock": 10, "bush": 20}'

# Step 4: Launch Gazebo to view the result
forest3d launch
```

## Procedural terrain & seeded scenarios

Beyond meshing a fixed DEM, Forest3D can **synthesize** varied, seeded landforms —
rolling hills, mountains, valleys, flatlands, basins→lakes, creeks — and randomize
whole scenarios reproducibly (same `--seed` → same world) for VIO/lidar testing:

```bash
forest3d terraingen --preset lakeland --seed 7 -o dem/synth.tif   # synth landform
forest3d terrain    --dem dem/synth.tif                           # mesh it
forest3d ground     --mode patchy --biome grassland --auto-water --dem dem/synth.tif
forest3d generate   --density '{"tree":35,"rock":12}' --seed 7    # populate
```

![demo scenarios](tools/scenarios_gallery.png)

Six ready-made demo scenarios (two snow) — **temperate hills, savanna flats,
lakeland wetland, alpine snow, winter forest, coastal dune** — each with a 3-layer
structure (canopy trees / understory shrubs / grass + flowers) built from **CC0
Poly Haven assets** and reproduced with **no account or login**:

```bash
# NOTE: the demo renderer needs a GPU (ogre2/EGL). Run inside the forest3d:egl image with
# --gpus all; see "Gotchas, best practices & caveats" below. Asset build needs Blender only.
python3 tools/build_assets.py       # fetch+convert the CC0 asset set (idempotent)
python3 tools/build_scenarios.py    # build all 6 + render tools/scenarios_gallery.png
```

Density is fully tunable per category — `forest3d generate --density
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
> `docker save forest3d:egl | gzip > forest3d-egl-v1.tar.gz` (or push to a registry).

## Gotchas, best practices & caveats

Hard-won lessons (and the cheapest way to avoid each). These cost real debugging time — read
them before the demo/realism pipeline surprises you.

- **Rendering needs a real GPU (ogre2/EGL).** The scenario/metric renders use the `ogre2`
  engine via EGL. Run them in the `forest3d:egl` image with `--gpus all` and
  `NVIDIA_DRIVER_CAPABILITIES=all`. On CPU/llvmpipe you get blank or wrong frames. The plain
  pipeline (`terrain`/`convert`/`generate`) does **not** need a GPU; only the render step does.
  ```bash
  docker run --rm --gpus all -e NVIDIA_DRIVER_CAPABILITIES=all -e PYTHONPATH=/workspace/src \
    -v "$PWD:/workspace" --entrypoint bash forest3d:egl -c 'cd /workspace && python3 tools/build_scenarios.py'
  ```
- **Editing the library inside the container? Shadow the installed package.** `forest3d` is
  **pip-installed** into the image, so `python3 -m forest3d ...` imports the *baked-in* copy and
  silently ignores your edits to `src/forest3d/**`. Pass `-e PYTHONPATH=/workspace/src` to make
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
- **Unified CLI**: Simple `forest3d` command with subcommands for each operation
- **Docker Support**: Pre-built images with GDAL for easy deployment

## Quick Start

### Option 1: Docker (Recommended)

The Docker image includes everything you need: Python, GDAL, Blender 4.2, and Gazebo Harmonic.

```bash
# Build the image (downloads Blender + Gazebo, ~2GB)
cd Forest3D
docker build -t forest3d -f docker/Dockerfile .

# Generate a forest world
docker run -v $(pwd):/workspace forest3d generate

# Convert Blender assets to Gazebo models
docker run -v $(pwd):/workspace forest3d convert \
  -i /workspace/Blender-Assets -o /workspace/models -c tree

# Launch Gazebo to view the world (requires X11)
xhost +local:docker  # Allow Docker to access display
docker run -e DISPLAY=$DISPLAY \
           -v /tmp/.X11-unix:/tmp/.X11-unix \
           -v $(pwd):/workspace \
           --network host \
           forest3d launch
```

### Option 2: pip install

```bash
# Clone and install
git clone https://github.com/khalidbourr/Forest3D.git
cd Forest3D
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
forest3d generate

# Custom density
forest3d generate --density '{"tree": 100, "rock": 20, "bush": 30}'

# Use a preset configuration
forest3d -c configs/examples/dense_forest.yaml generate
```

### Generate Terrain from DEM

```bash
forest3d terrain --dem ./dem/terrain.tif

# With texture from Blender
forest3d terrain --dem ./dem/terrain.tif --texture ./Blender-Assets/soil/soil.blend

# With options
forest3d terrain --dem ./dem/terrain.tif --scale 2.0 --smooth 1.5 --enhance
```

### Convert Blender Assets

```bash
# Auto-detect categories from subfolders (tree/, rock/, bush/, etc.)
forest3d convert -i ./Blender-Assets -o ./models

# Or specify category manually
forest3d convert -i ./Blender-Assets/tree -o ./models -c tree
```

### Launch Gazebo

```bash
# Using the CLI (auto-configures model path)
forest3d launch

# Or manually with Gazebo Sim (Harmonic)
export GZ_SIM_RESOURCE_PATH=$GZ_SIM_RESOURCE_PATH:$(pwd)/models
gz sim worlds/forest_world.world
```

## CLI Reference

```
forest3d --help                    # Show all commands
forest3d terrain --help            # Terrain generation help
forest3d convert --help            # Asset conversion help
forest3d generate --help           # Forest generation help
forest3d launch --help             # Launch Gazebo help

# Global options
forest3d -v ...                    # Verbose output
forest3d -vv ...                   # Debug output
forest3d -c config.yaml ...        # Use config file
```

## Configuration

Create `forest3d.yaml` in your project directory:

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
| `FOREST3D_BLENDER_PATH` | Path to Blender executable |
| `FOREST3D_BASE_PATH` | Project base directory |
| `FOREST3D_MODELS_PATH` | Models output directory |

## Project Structure

```
Forest3D/
├── src/forest3d/          # Python package (the installed `forest3d` CLI) — independent of tools/
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
   forest3d convert -i ./Blender-Assets -o ./models
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
pylint src/forest3d/
```

## Docker Compose

```bash
# Development environment (with Blender + GDAL + Gazebo)
docker compose -f docker/docker-compose.yml run forest3d-dev

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
export FOREST3D_BLENDER_PATH=/path/to/blender
# or
forest3d convert --blender /path/to/blender ...
```

### Model Path Issues
Ensure Gazebo Sim can find models:
```bash
export GZ_SIM_RESOURCE_PATH=$GZ_SIM_RESOURCE_PATH:$(pwd)/models
```

## License

This project is licensed under the AGPL-3.0 - see the LICENSE file for details.


> **Need Custom Environments & Commercial Use ?**
> Forest3D ships natural/forest environments out of the box. Need a different one: vineyard, orchard, agricultural row crops, urban, lunar, or a custom site? Custom environment builds are available.
> Contact the authors

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

