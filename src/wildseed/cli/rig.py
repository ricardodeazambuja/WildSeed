"""Sensor rig generation CLI subcommand (docs/SENSOR_RIG.md)."""

from pathlib import Path

import click

from wildseed.core.rig import (RigConfig, inject_rig_into_world, rig_topics,
                               write_rig_model)


@click.command()
@click.option("--config", "config_path", type=click.Path(exists=True),
              help="Rig YAML config (defaults are the spike-verified suite).")
@click.option("--models", "models_dir", type=click.Path(), default="./models",
              help="Models root to write into. Default: ./models")
@click.option("--name", default=None,
              help="Override the model name (default from config: sensor_rig).")
@click.option("--inject", "inject_world", type=click.Path(exists=True),
              default=None,
              help="Retrofit an EXISTING world file: adds the rig include, "
                   "sensor system plugins, GPS georeference and semantic "
                   "labels on all includes (idempotent).")
@click.option("--pose", "pose_str", default=None,
              help="Rig pose for --inject: 'x,y,z[,roll,pitch,yaw]'. "
                   "Default: 0,0,40.")
@click.option("--shell-only", is_flag=True, default=False,
              help="With --inject: add the world-shell (sensor system "
                   "plugins, GPS georeference, semantic labels) but NOT the "
                   "rig include/model — for worlds that host an externally "
                   "spawned robot.")
@click.option("--no-labels", is_flag=True, default=False,
              help="With --inject: skip the per-include semantic Label "
                   "plugins. Use when nothing consumes segmentation (e.g. an "
                   "external robot without a segmentation camera) — on dense "
                   "worlds thousands of Label systems are pure overhead.")
@click.option("--calib", "calib_dial", type=click.FloatRange(0.0, 1.0),
              default=None,
              help="Calibration-randomization dial 0..1: perturb mount "
                   "extrinsics (5 mm/0.3 deg at 1.0), camera FOV/fx (1%), and "
                   "inject IMU noise (MEMS baseline x 4*dial^2). TRUE values "
                   "land in rig_calibration.json next to the model — clean "
                   "test = feed the estimator truth; robustness test = feed "
                   "it the nominals. 0 = unperturbed calibration export.")
@click.option("--calib-seed", type=int, default=0, show_default=True,
              help="Seed for --calib; same (dial, seed) -> same perturbation.")
@click.pass_context
def rig(ctx, config_path, models_dir, name, inject_world, pose_str,
        shell_only, no_labels, calib_dial, calib_seed):
    """Generate the flying sensor-rig model (test instrument + camera dolly).

    Full suite by default: stereo cams, wide-angle, RGB-D, instance
    segmentation, 16-ch 3D lidar, IMU, GPS, barometer, magnetometer and a
    ground-truth odometry publisher — every stream verified headless on gz
    Harmonic (see docs/SENSOR_RIG.md). Include it in worlds with
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

    if shell_only and not inject_world:
        raise click.ClickException("--shell-only requires --inject <world>")
    if no_labels and not inject_world:
        raise click.ClickException("--no-labels requires --inject <world>")

    if inject_world:
        rig_pose = None
        if pose_str:
            if shell_only:
                raise click.ClickException("--pose is meaningless with "
                                           "--shell-only (no rig include)")
            try:
                parts = [float(v) for v in pose_str.split(",")]
            except ValueError:
                raise click.ClickException("--pose must be numbers "
                                           "'x,y,z[,roll,pitch,yaw]'")
            if len(parts) == 3:
                parts += [0.0, 0.0, 0.0]
            if len(parts) != 6:
                raise click.ClickException("--pose needs 3 or 6 numbers")
            rig_pose = tuple(parts)
        inject_rig_into_world(Path(inject_world), config, Path(models_dir),
                              rig_pose=rig_pose, shell_only=shell_only,
                              labels=not no_labels)
        what = "world-shell injected" if shell_only else "rig injected"
        labels_note = ("labels skipped (--no-labels)" if no_labels
                       else "labels added to unlabeled includes")
        console.print(f"[green]{what}[/green] into "
                      f"[cyan]{inject_world}[/cyan] (idempotent; {labels_note})")
        return

    model_dir = write_rig_model(config, Path(models_dir),
                                calib_dial=calib_dial, calib_seed=calib_seed)
    console.print(f"[green]Sensor rig written[/green] -> [cyan]{model_dir}[/cyan]")
    if calib_dial is not None:
        console.print(f"  calibration: dial=[cyan]{calib_dial}[/cyan] "
                      f"seed=[cyan]{calib_seed}[/cyan] -> "
                      f"[cyan]{model_dir}/rig_calibration.json[/cyan] "
                      "(true values; SDF carries the perturbed instrument)")
    console.print("Topics:")
    for stream, topic in sorted(rig_topics(config).items()):
        console.print(f"  {stream:14} [dim]{topic}[/dim]")
    console.print("[dim]Drop into a world with `wildseed generate --rig` "
                  "(injects the sensor system plugins + spherical coordinates).[/dim]")
