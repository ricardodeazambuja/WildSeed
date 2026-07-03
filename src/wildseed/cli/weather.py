"""Weather CLI subcommand."""

import click
from pathlib import Path

from wildseed.core.weather import WEATHER_PRESETS, apply_weather, lens_flare_snippet


@click.command()
@click.option("--world", "-w", "world_path", type=click.Path(exists=True), required=True,
              help="Generated .world file to apply weather to (modified in place unless --out).")
@click.option("--preset", "-p", type=click.Choice(list(WEATHER_PRESETS)), default="clear",
              help="Weather preset. Default: clear")
@click.option("--models-dir", type=click.Path(), default="./models",
              help="Models root (emitter models are written here). Default: ./models")
@click.option("--sun-elevation", type=click.FloatRange(1.0, 90.0), default=None,
              help="Sun elevation above horizon, degrees (overrides preset).")
@click.option("--sun-azimuth", type=float, default=None,
              help="Sun azimuth, degrees CCW from +X/east (overrides preset).")
@click.option("--sun-intensity", type=click.FloatRange(0.0, 20.0), default=None,
              help="Sun light intensity (overrides preset; sunglare default is 5).")
@click.option("--rate", "particle_rate", type=click.FloatRange(0.0, 20000.0), default=None,
              help="Particles/second for rain/snow/fog (overrides preset).")
@click.option("--fall-height", type=click.FloatRange(2.0, 200.0), default=20.0,
              help="Rain/snow emitter altitude above z=0, metres. Default: 20")
@click.option("--out", "out_path", type=click.Path(), default=None,
              help="Write to this path instead of modifying --world in place.")
@click.option("--show-lens-flare-snippet", is_flag=True, default=False,
              help="Print the camera-sensor lens-flare plugin XML (lives in the robot repo) and exit.")
@click.pass_context
def weather(ctx, world_path, preset, models_dir, sun_elevation, sun_azimuth,
            sun_intensity, particle_rate, fall_height, out_path,
            show_lens_flare_snippet):
    """Apply a weather preset to a generated world.

    Rewrites the sun light and scene tint, and adds a terrain-sized particle
    emitter for rain/snow/fog (gz-sim ParticleEmitter system). ``sunglare``
    puts a very bright sun near the horizon plus an emissive sun disk; pair it
    with the lens-flare camera plugin on the robot side
    (--show-lens-flare-snippet prints the XML).

    Idempotent: re-running with another preset replaces the previous weather.

    \b
    Examples:
        wildseed weather -w worlds/scenario_42.world -p rain
        wildseed weather -w worlds/scenario_42.world -p sunglare --sun-azimuth 0
        wildseed weather -w worlds/scenario_42.world -p clear   # remove weather
    """
    console = ctx.obj["console"]
    if show_lens_flare_snippet:
        console.print(lens_flare_snippet())
        return

    info = apply_weather(
        Path(world_path), preset, Path(models_dir),
        sun_elevation_deg=sun_elevation, sun_azimuth_deg=sun_azimuth,
        sun_intensity=sun_intensity, particle_rate=particle_rate,
        fall_height_m=fall_height, out_path=Path(out_path) if out_path else None,
    )
    console.print(f"[green]Success![/green] {info['preset']} applied -> [cyan]{info['world']}[/cyan]")
    console.print(f"  sun: elevation={info['sun_elevation_deg']}° azimuth={info['sun_azimuth_deg']}° "
                  f"intensity={info['sun_intensity']}")
    if info["emitter"]:
        console.print(f"  emitter model -> [cyan]{info['emitter']}[/cyan]")
    if preset == "sunglare":
        console.print("  [dim]camera lens flare is a robot-repo plugin: "
                      "wildseed weather --show-lens-flare-snippet -w <world>[/dim]")
