"""Unified CLI for WildSeed."""

import click
from rich.console import Console

from wildseed import __version__
from wildseed.utils.logging import setup_logging

console = Console()


@click.group()
@click.version_option(version=__version__, prog_name="wildseed")
@click.option("-v", "--verbose", count=True, help="Increase verbosity (-v, -vv, -vvv)")
@click.option("-q", "--quiet", is_flag=True, help="Suppress all output except errors")
@click.option(
    "-c", "--config", "config_path", type=click.Path(exists=True), help="Path to configuration file"
)
@click.pass_context
def main(ctx, verbose, quiet, config_path):
    """WildSeed - Terrain and forest generation for Gazebo simulation.

    Generate realistic outdoor environments for robotics simulation from
    DEM data and Blender assets.

    \b
    Examples:
        wildseed terrain --dem terrain.tif
        wildseed convert --input ./blender-assets --output ./models
        wildseed generate --density '{"tree": 50, "rock": 10}'

    \b
    Configuration:
        WildSeed looks for config files in these locations:
        - ./wildseed.yaml
        - ~/.config/wildseed/config.yaml
        - ~/.wildseed.yaml

    \b
    Environment Variables:
        WILDSEED_BLENDER_PATH  - Path to Blender executable
        WILDSEED_BASE_PATH     - Project base directory
        WILDSEED_MODELS_PATH   - Models output directory
    """
    ctx.ensure_object(dict)

    # Setup logging based on verbosity
    if quiet:
        log_level = "ERROR"
    else:
        log_level = ["INFO", "DEBUG", "DEBUG"][min(verbose, 2)]

    ctx.obj["logger"] = setup_logging(log_level, console=console)
    ctx.obj["config_path"] = config_path
    ctx.obj["console"] = console
    ctx.obj["verbose"] = verbose


# Import and register subcommands
from wildseed.cli.terrain import terrain
from wildseed.cli.terraingen import terraingen
from wildseed.cli.convert import convert
from wildseed.cli.generate import generate
from wildseed.cli.launch import launch
from wildseed.cli.ground import ground
from wildseed.cli.scenario import scenario
from wildseed.cli.randomize import randomize
from wildseed.cli.weather import weather
from wildseed.cli.assetgen import assetgen
from wildseed.cli.rig import rig
from wildseed.cli.fly import fly
from wildseed.cli.height import height
from wildseed.cli.record import record
from wildseed.cli.corridor_map import corridor_map
from wildseed.cli.heightmap import heightmap
from wildseed.cli.benchmark import benchmark
from wildseed.cli.experiment import experiment
from wildseed.cli.sweep import sweep

main.add_command(terrain)
main.add_command(terraingen)
main.add_command(convert)
main.add_command(generate)
main.add_command(launch)
main.add_command(ground)
main.add_command(scenario)
main.add_command(randomize)
main.add_command(weather)
main.add_command(assetgen)
main.add_command(rig)
main.add_command(fly)
main.add_command(height)
main.add_command(record)
main.add_command(corridor_map)
main.add_command(heightmap)
main.add_command(benchmark)
main.add_command(experiment)
main.add_command(sweep)


if __name__ == "__main__":
    main()
