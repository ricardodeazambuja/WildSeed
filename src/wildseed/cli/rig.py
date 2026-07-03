"""Sensor rig generation CLI subcommand (docs/SENSOR_RIG_PLAN.md Phase 1)."""

from pathlib import Path

import click

from wildseed.core.rig import RigConfig, rig_topics, write_rig_model


@click.command()
@click.option("--config", "config_path", type=click.Path(exists=True),
              help="Rig YAML config (defaults are the spike-verified suite).")
@click.option("--models", "models_dir", type=click.Path(), default="./models",
              help="Models root to write into. Default: ./models")
@click.option("--name", default=None,
              help="Override the model name (default from config: sensor_rig).")
@click.pass_context
def rig(ctx, config_path, models_dir, name):
    """Generate the flying sensor-rig model (test instrument + camera dolly).

    Full suite by default: stereo cams, wide-angle, RGB-D, instance
    segmentation, 16-ch 3D lidar, IMU, GPS, barometer, magnetometer and a
    ground-truth odometry publisher — every stream verified headless on gz
    Harmonic (see docs/SENSOR_RIG_PLAN.md). Include it in worlds with
    `wildseed generate --rig` (adds the required world plugins too).

    \b
    Examples:
        wildseed rig                            # default rig -> ./models/sensor_rig
        wildseed rig --config my_rig.yaml
    """
    console = ctx.obj["console"]

    if config_path:
        import yaml
        raw = yaml.safe_load(Path(config_path).read_text()) or {}
        config = RigConfig(**raw)
    else:
        config = RigConfig()
    if name:
        config = config.model_copy(update={"name": name})

    model_dir = write_rig_model(config, Path(models_dir))
    console.print(f"[green]Sensor rig written[/green] -> [cyan]{model_dir}[/cyan]")
    console.print("Topics:")
    for stream, topic in sorted(rig_topics(config).items()):
        console.print(f"  {stream:14} [dim]{topic}[/dim]")
    console.print("[dim]Drop into a world with `wildseed generate --rig` "
                  "(injects the sensor system plugins + spherical coordinates).[/dim]")
