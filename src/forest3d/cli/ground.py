"""Procedural ground material CLI subcommand."""

import click
from pathlib import Path

from forest3d.config.loader import load_config
from forest3d.config.schema import GroundConfig


@click.command()
@click.option("--ground-dir", "-g", type=click.Path(), default="./models/ground",
              help="Terrain model dir (must already contain mesh/terrain.obj). Default: ./models/ground")
@click.option("--texture-root", "-t", type=click.Path(), default="./Blender-Assets/soil",
              help="Directory of CC0 ground texture packs. Default: ./Blender-Assets/soil")
@click.option("--mode", type=click.Choice(["uniform", "patchy"]), default=None,
              help="uniform (crisp tiled) or patchy (seeded baked composite).")
@click.option("--biome", type=click.Choice(["grassland", "desert", "gravel", "snow"]), default=None,
              help="Biome preset.")
@click.option("--seed", type=int, default=None, help="RNG seed (same seed -> same ground).")
@click.option("--res", "resolution", type=int, default=None, help="Patchy bake resolution px (default 4096).")
@click.option("--base", "base_material", default=None, help="Override biome base material key.")
@click.option("--uniform-tile", type=float, default=None, help="Uniform-mode UV tiling.")
@click.option("--no-randomize", is_flag=True, default=False, help="Disable per-seed patch jitter.")
@click.option("--tile-warp", type=float, default=None,
              help="Patchy-mode domain warp of the tiling grid (tile units; ~40 m wobble). Breaks visible tiling for VIO. 0 = off (sharp grid). Default 1.3.")
@click.option("--water-level", type=float, default=None, help="Add a single flat water plane at this terrain-Z (m).")
@click.option("--auto-water", is_flag=True, default=False,
              help="Place one water plane PER basin at its own level (reads <dem>.lakes.json).")
@click.option("--dem", "dem_path", type=click.Path(), default=None,
              help="Synth DEM path; its <stem>.lakes.json drives --auto-water.")
@click.option("--models-dir", type=click.Path(), default="./models", help="Models root (for water). Default: ./models")
@click.pass_context
def ground(ctx, ground_dir, texture_root, mode, biome, seed, resolution, base_material,
           uniform_tile, no_randomize, tile_warp, water_level, auto_water, dem_path, models_dir):
    """Generate the terrain ground PBR material (uniform or patchy/seeded).

    Operates on an already-generated terrain (run `forest3d terrain` first).
    Reproducible: the same --seed yields the same ground, so randomized worlds
    for VIO/lidar testing can be regenerated exactly.

    \b
    Examples:
        # crisp uniform grass
        forest3d ground --mode uniform --biome grassland
        # seeded patchy scenario (trails + sand/gravel/pebble patches)
        forest3d ground --mode patchy --biome grassland --seed 42
        # a different random scenario, same biome
        forest3d ground --mode patchy --biome grassland --seed 99
        # snow biome with a flooded low area
        forest3d ground --mode patchy --biome snow --seed 7 --water-level 5.0
    """
    console = ctx.obj["console"]
    logger = ctx.obj["logger"]
    config = load_config(ctx.obj.get("config_path"))

    gc = config.terrain.ground or GroundConfig()
    if mode is not None:
        gc.mode = mode
    if biome is not None:
        gc.biome = biome
    if seed is not None:
        gc.seed = seed
    if resolution is not None:
        gc.resolution = resolution
    if base_material is not None:
        gc.base_material = base_material
    if uniform_tile is not None:
        gc.uniform_tile = uniform_tile
    if no_randomize:
        gc.randomize = False
    if tile_warp is not None:
        gc.tile_warp = tile_warp
    if water_level is not None:
        gc.water_level = water_level

    gdir = Path(ground_dir)
    if not (gdir / "mesh" / "terrain.obj").exists():
        raise click.ClickException(
            f"{gdir}/mesh/terrain.obj not found. Run `forest3d terrain --dem ...` first."
        )
    troot = Path(gc.texture_root) if gc.texture_root else Path(texture_root)
    if not troot.exists():
        raise click.ClickException(f"Texture root not found: {troot}")

    from forest3d.core.ground import GroundCompositor, write_water_model, write_basin_water_models

    console.print(f"[bold]Ground material[/bold]  mode=[cyan]{gc.mode}[/cyan] biome=[cyan]{gc.biome}[/cyan] "
                  f"seed=[cyan]{gc.seed}[/cyan]")
    comp = GroundCompositor(ground_dir=gdir, texture_root=troot, config=gc)
    try:
        info = comp.generate()
    except FileNotFoundError as e:
        raise click.ClickException(str(e))

    if auto_water:
        import json
        if not dem_path:
            raise click.ClickException("--auto-water needs --dem <synth.tif> to find <stem>.lakes.json")
        sidecar = Path(dem_path).parent / (Path(dem_path).stem + ".lakes.json")
        if not sidecar.exists():
            raise click.ClickException(f"No lake sidecar found: {sidecar} (run terraingen with basins).")
        lakes = json.loads(sidecar.read_text()).get("lakes", [])
        if not lakes:
            console.print("  [yellow]no basins in sidecar; no water placed[/yellow]")
        else:
            dirs = write_basin_water_models(Path(models_dir), lakes)
            for i, (lk, d) in enumerate(zip(lakes, dirs)):
                console.print(f"  water_{i} @ z={lk['suggested_water_level']} center={lk['center_xy_m']} "
                              f"-> [cyan]{d}[/cyan]")
            console.print(f"  [dim]add one include per basin: "
                          f"{' '.join('model://water_%d' % i for i in range(len(dirs)))}[/dim]")
    elif gc.water_level is not None:
        ex = comp._extent_m()
        wdir = write_water_model(Path(models_dir), ex, gc.water_level)
        console.print(f"  water plane @ z={gc.water_level} -> [cyan]{wdir}[/cyan] "
                      f"(add <include><uri>model://water</uri></include> to your world)")

    console.print(f"[green]Success![/green] {info}")
    console.print(f"[dim]Textures -> {gdir}/texture/ ; SDF updated.[/dim]")
