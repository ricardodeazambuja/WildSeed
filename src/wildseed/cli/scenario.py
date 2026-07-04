"""Master-seed randomized scenario CLI subcommand."""

import click
from pathlib import Path

from wildseed.config.schema import PRESET_NAMES
from wildseed.core.scenario import BIOME_NAMES, resolve_scenario


@click.command()
@click.option("--seed", type=int, required=True,
              help="Master seed. Drives EVERY stage (landform, ground, placement) "
                   "and the randomized parameters; same seed -> identical world.")
@click.option("--biome", type=click.Choice(BIOME_NAMES + ("random",)), default="random",
              help="Biome (palette + ground + terrain envelope). Default: seed-random.")
@click.option("--preset", type=click.Choice(PRESET_NAMES + ("random",)), default="random",
              help="Terraingen preset. Default: seed-random from the biome's presets.")
@click.option("--density-scale", type=float, default=1.0,
              help="Multiply all model counts (0.5 = sparse, 2.0 = dense). Default 1.0.")
@click.option("--size", type=int, default=192, help="DEM pixels per side. Default 192.")
@click.option("--pixel", "pixel_m", type=float, default=1.6,
              help="Metres per DEM pixel (default 1.6, the demos' robot-scale value).")
@click.option("--max-slope", "max_slope_deg", type=float, default=20.0,
              help="Ground-robot slope cap (deg): rescale relief so the DEM's "
                   "mean surface slope meets it. Default 20 (UGV-drivable); "
                   "0 = off (aerial/scenery worlds).")
@click.option("--manifest", type=click.Path(exists=True), default="assets/manifest.yaml",
              help="Asset manifest holding the per-biome palettes.")
@click.option("--base-path", type=click.Path(), default=".",
              help="Project base (contains models/ and worlds/). Default: cwd.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print the resolved scenario spec (YAML) and exit without building.")
@click.pass_context
def scenario(ctx, seed, biome, preset, density_scale, size, pixel_m,
             max_slope_deg, manifest, base_path, dry_run):
    """Generate a complete randomized world from ONE master seed.

    Chains terraingen -> terrain -> ground (+ per-basin water) -> generate with
    per-stage seeds derived from the master seed (SeedSequence.spawn). The biome,
    terrain preset/knobs and densities are drawn from per-biome envelopes; every
    resolved value is written to worlds/scenario_<seed>.yaml, so the world is
    reproducible from the seed (plus any explicit overrides) alone.

    \b
    Examples:
        wildseed scenario --seed 42                      # fully random, reproducible
        wildseed scenario --seed 42 --biome alpine       # fix the biome, randomize the rest
        wildseed scenario --seed 7 --density-scale 1.5   # denser variant of seed 7
        wildseed scenario --seed 7 --dry-run             # inspect without building
    """
    console = ctx.obj["console"]

    spec = resolve_scenario(
        seed,
        biome=None if biome == "random" else biome,
        preset=None if preset == "random" else preset,
        density_scale=density_scale, size=size, pixel_m=pixel_m,
        max_slope_deg=max_slope_deg,
    )

    import yaml
    console.print(f"[bold]Scenario[/bold] seed=[cyan]{seed}[/cyan] "
                  f"biome=[cyan]{spec['biome']}[/cyan] preset=[cyan]{spec['preset']}[/cyan]")
    console.print(f"[dim]{yaml.safe_dump(spec, sort_keys=False)}[/dim]")
    if dry_run:
        return

    try:
        from wildseed.core.terraingen import GDAL_AVAILABLE
        if not GDAL_AVAILABLE:
            raise click.ClickException(
                "GDAL is required (use the wildseed Docker image, or "
                "`sudo apt install python3-gdal gdal-bin`).")
        from wildseed.core.scenario import run_scenario
        result = run_scenario(spec, base_path=Path(base_path),
                              manifest_path=Path(manifest))
    except (ImportError, FileNotFoundError, KeyError, ValueError) as e:
        raise click.ClickException(str(e))

    stats = result["stats"]
    console.print(f"[green]Success![/green] world -> [cyan]{result['world']}[/cyan]")
    console.print(f"  spec  -> [cyan]{result['spec']}[/cyan]")
    console.print(f"  models placed: {stats['total_models']} "
                  f"{ {k: v for k, v in stats['by_category'].items() if v} }"
                  + (f"  lakes: {result['lakes']}" if result["lakes"] else ""))
    console.print(f"[dim]Launch: wildseed launch --world {result['world']}[/dim]")
