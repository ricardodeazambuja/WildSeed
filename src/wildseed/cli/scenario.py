"""Master-seed randomized scenario CLI subcommand."""

import click
from pathlib import Path

from wildseed.config.schema import PRESET_NAMES
from wildseed.core.scenario import BIOME_NAMES, PROFILE_NAMES, resolve_scenario


@click.command()
@click.option("--seed", type=int, required=True,
              help="Master seed. Drives EVERY stage (landform, ground, placement) "
                   "and the randomized parameters; same seed -> identical world.")
@click.option("--profile", type=click.Choice(PROFILE_NAMES), default=None,
              help="Recipe profile. 'vio_lio' builds the measured VIO/LIO-friendly "
                   "world (patchy ground + steered corridor scatter + drivable relief "
                   "+ sensor rig) instead of the biome-envelope scenario. See "
                   "docs/VIO_LIO_FEATURES.md.")
@click.option("--object-density", "object_density", type=int, default=175,
              show_default=True,
              help="[vio_lio] Total steered objects (study saturates VIO ~175).")
@click.option("--corridor-width", "corridor_width", type=float, default=8.0,
              show_default=True,
              help="[vio_lio] Driving-corridor HALF-width, m (steered placement band).")
@click.option("--relief", type=click.FloatRange(0.0, 1.0), default=0.5,
              show_default=True,
              help="[vio_lio] Macro relief amplitude 0..1, kept under the slope cap.")
@click.option("--variety", type=click.FloatRange(0.0, 1.0), default=0.5,
              show_default=True,
              help="[vio_lio] Uniqueness dial 0..1: co-scales recolour-variant count, "
                   "terrain roughness and corridor softness. Higher = less repetition.")
@click.option("--texture", type=click.FloatRange(0.0, 1.0), default=1.0,
              show_default=True,
              help="[vio_lio] Ground-aliasing dial 0..1: <0.5 uniform ground (the "
                   "measured aliasing worst case), >=0.5 patchy (de-aliased).")
@click.option("--photometric", type=click.FloatRange(0.0, 1.0), default=None,
              help="Sun-stress dial 0..1: elevation 55->5 deg, intensity 1->5x, "
                   "emissive sun disk at >=0.75; azimuth seeded + recorded. "
                   "Unset = leave the world's default sun.")
@click.option("--weather", type=str, default=None,
              help="Weather preset applied under the master seed (clear, overcast, "
                   "fog, rain, snow, sunglare, or 'random' = seeded draw). "
                   "Unset = no weather stage.")
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
def scenario(ctx, seed, profile, object_density, corridor_width, relief, variety,
             texture, photometric, weather,
             biome, preset, density_scale, size, pixel_m,
             max_slope_deg, manifest, base_path, dry_run):
    """Generate a complete randomized world from ONE master seed.

    Chains terraingen -> terrain -> ground (+ per-basin water) -> generate with
    per-stage seeds derived from the master seed (SeedSequence.spawn). The biome,
    terrain preset/knobs and densities are drawn from per-biome envelopes; every
    resolved value is written to worlds/scenario_<seed>.yaml, so the world is
    reproducible from the seed (plus any explicit overrides) alone.

    With --profile vio_lio the biome envelopes are replaced by the measured
    VIO/LIO recipe (patchy ground + steered corridor scatter + drivable relief +
    sensor rig); tune it with --object-density / --corridor-width / --relief /
    --variety. See docs/VIO_LIO_FEATURES.md.

    \b
    Examples:
        wildseed scenario --seed 42                      # fully random, reproducible
        wildseed scenario --seed 42 --biome alpine       # fix the biome, randomize the rest
        wildseed scenario --seed 7 --density-scale 1.5   # denser variant of seed 7
        wildseed scenario --seed 7 --profile vio_lio     # the VIO/LIO-friendly recipe
        wildseed scenario --seed 7 --profile vio_lio --variety 0.8 --object-density 200
        wildseed scenario --seed 7 --dry-run             # inspect without building
    """
    console = ctx.obj["console"]

    try:
        spec = resolve_scenario(
            seed,
            biome=None if biome == "random" else biome,
            preset=None if preset == "random" else preset,
            density_scale=density_scale, size=size, pixel_m=pixel_m,
            max_slope_deg=max_slope_deg,
            profile=profile, object_density=object_density,
            corridor_width=corridor_width, relief=relief, variety=variety,
            texture=texture, photometric=photometric, weather=weather,
        )
    except ValueError as e:
        raise click.ClickException(str(e))

    import yaml
    plabel = f" profile=[cyan]{profile}[/cyan]" if profile else ""
    console.print(f"[bold]Scenario[/bold] seed=[cyan]{seed}[/cyan]{plabel} "
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
    if result.get("corridor_map"):
        console.print(f"  corridor map -> [cyan]{result['corridor_map']}[/cyan]  "
                      "(steered placement; rig injected)")
    console.print(f"[dim]Launch: wildseed launch --world {result['world']}[/dim]")
