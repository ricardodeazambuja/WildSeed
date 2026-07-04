"""Flight recording CLI subcommand (docs/SENSOR_RIG.md)."""

import json
from pathlib import Path

import click

from wildseed.core.fly import PATTERNS, TerrainSampler, synthesize


@click.command()
@click.option("--pattern", "-p", type=click.Choice(PATTERNS), default="orbit",
              help="Flight pattern (ignored with --trajectory). Default: orbit")
@click.option("--seed", type=int, default=0, help="Trajectory seed.")
@click.option("--speed", type=float, default=5.0, help="Target speed, m/s.")
@click.option("--agl", type=float, default=12.0, help="Height above ground, m.")
@click.option("--radius", type=float, default=None, help="Orbit radius, m.")
@click.option("--trajectory", "trajectory_path", type=click.Path(exists=True),
              default=None, help="Fly an existing trajectory JSON instead.")
@click.option("--base-path", "-b", type=click.Path(exists=True), default=".",
              help="Project base (models/, worlds/, runs/). Default: cwd")
@click.option("--out", "-o", type=click.Path(), default=None,
              help="Run directory. Default: runs/<world>_<pattern>_seed<seed>")
@click.option("--world", default="forest_world",
              help="Running world's name. Default: forest_world")
@click.option("--model", default="sensor_rig",
              help="Rig model name. Default: sensor_rig")
@click.option("--dataset", is_flag=True,
              help="Also dump lidar npz + imu/navsat csv + TUM ground truth.")
@click.option("--keep-frames", is_flag=True,
              help="Keep the PNG frames next to video.mp4.")
@click.option("--mode", type=click.Choice(["kinematic", "dynamic"]),
              default="kinematic",
              help="Flight mode: kinematic set_pose (smoothest camera; IMU "
                   "invalid) or dynamic PD-wrench (honest IMU for datasets).")
@click.pass_context
def record(ctx, pattern, seed, speed, agl, radius, trajectory_path, base_path,
           out, world, model, dataset, keep_frames, mode):
    """Fly the rig and record a demo video (and optionally a dataset).

    Needs a RUNNING gz server hosting a world with the sensor rig
    (`wildseed generate --rig` + `gz sim -s -r ...`), and the gz python
    bindings — i.e. run inside the wildseed/wildseed:egl containers.

    \b
    Examples:
        wildseed record -p orbit --seed 7 --radius 60
        wildseed record -p flythrough --seed 3 --dataset
        wildseed record --trajectory worlds/trajectory_orbit_7.json
    """
    console = ctx.obj["console"]
    base = Path(base_path)

    if trajectory_path:
        traj = json.loads(Path(trajectory_path).read_text())
    else:
        stl = base / "models" / "ground" / "mesh" / "terrain.stl"
        if not stl.exists():
            raise click.ClickException(f"terrain mesh not found: {stl}")
        traj = synthesize(pattern, seed, TerrainSampler(stl), speed=speed,
                          agl=agl, radius=radius)

    run_dir = Path(out) if out else (
        base / "runs" /
        f"{world}_{traj['pattern']}_seed{traj['seed']}")
    console.print(f"[bold]record[/bold] {traj['pattern']} seed={traj['seed']} "
                  f"({traj['duration']:.0f}s) -> [cyan]{run_dir}[/cyan]")

    try:
        from wildseed.core.record import record_run
        summary = record_run(traj, run_dir, world=world, model=model,
                             dataset=dataset, keep_frames=keep_frames,
                             mode=mode)
    except ImportError as e:
        raise click.ClickException(
            f"gz python bindings unavailable ({e}); run inside the "
            "wildseed/wildseed:egl containers next to a running server.")
    except RuntimeError as e:
        raise click.ClickException(str(e))

    for k, v in summary["streams"].items():
        console.print(f"  {k:12} {v} msgs")
    if summary.get("tracking"):
        t = summary["tracking"]
        console.print(f"  tracking err mean {t['err_mean_m']} m / "
                      f"p95 {t['err_p95_m']} m / max {t['err_max_m']} m")
    if summary["video"]:
        console.print(f"[green]video[/green] {summary['video']} "
                      f"@ {summary['video_fps']} fps")
    else:
        console.print("[yellow]no frames captured — is the rig in the "
                      "running world and the Sensors system on?[/yellow]")
    console.print(f"[green]run complete[/green] -> {run_dir}/manifest.json")
