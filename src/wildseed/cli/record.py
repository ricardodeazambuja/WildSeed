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
@click.option("--distractors", "distractor_dial",
              type=click.FloatRange(0.0, 1.0), default=None,
              help="Dynamics axis 0..1: spawn round(16*dial) seeded kinematic "
                   "movers (bush/rock models, segmentation label 8) and drive "
                   "them through the camera's view during the flight. "
                   "Commanded tracks + velocities -> distractors.json.")
@click.option("--distractor-seed", type=int, default=None,
              help="Seed for --distractors tracks/models. Default: the "
                   "trajectory's seed.")
@click.pass_context
def record(ctx, pattern, seed, speed, agl, radius, trajectory_path, base_path,
           out, world, model, dataset, keep_frames, mode, distractor_dial,
           distractor_seed):
    """Fly the rig and record a demo video (and optionally a dataset).

    Needs a RUNNING gz server hosting a world with the sensor rig
    (`wildseed generate --rig` + `gz sim -s -r ...`), and the gz python
    bindings — i.e. run inside the wildseed/wildseed:egl containers.

    \b
    Examples:
        wildseed record -p orbit --seed 7 --radius 60
        wildseed record -p flythrough --seed 3 --dataset
        wildseed record --trajectory worlds/trajectory_orbit_7.json
        wildseed record -p dolly --seed 3 --dataset --distractors 0.5
    """
    console = ctx.obj["console"]
    base = Path(base_path)

    terrain = None
    stl = base / "models" / "ground" / "mesh" / "terrain.stl"
    if trajectory_path:
        traj = json.loads(Path(trajectory_path).read_text())
    else:
        if not stl.exists():
            raise click.ClickException(f"terrain mesh not found: {stl}")
        terrain = TerrainSampler(stl)
        traj = synthesize(pattern, seed, terrain, speed=speed,
                          agl=agl, radius=radius)

    plan = None
    if distractor_dial:
        from wildseed.core.distract import (list_mover_models,
                                            synthesize_distractors)
        if terrain is None:
            if not stl.exists():
                raise click.ClickException(
                    f"--distractors needs the terrain mesh ({stl}) for "
                    "ground-following tracks")
            terrain = TerrainSampler(stl)
        movers = list_mover_models(base / "models")
        d_seed = distractor_seed if distractor_seed is not None \
            else traj["seed"]
        try:
            plan = synthesize_distractors(traj, terrain, distractor_dial,
                                          d_seed, movers)
        except ValueError as e:
            raise click.ClickException(str(e))

    run_dir = Path(out) if out else (
        base / "runs" /
        f"{world}_{traj['pattern']}_seed{traj['seed']}")
    console.print(f"[bold]record[/bold] {traj['pattern']} seed={traj['seed']} "
                  f"({traj['duration']:.0f}s) -> [cyan]{run_dir}[/cyan]")
    if plan:
        console.print(f"  distractors: {plan['count']} movers "
                      f"(dial={plan['dial']:g} seed={plan['seed']}, "
                      f"label {plan['label']})")

    try:
        from wildseed.core.record import record_run
        summary = record_run(traj, run_dir, world=world, model=model,
                             dataset=dataset, keep_frames=keep_frames,
                             mode=mode, distractors=plan)
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
    if summary.get("distractors"):
        d = summary["distractors"]
        console.print(f"  distractors  {d['count']} movers, "
                      f"{d['pose_acks']}/{d['pose_ticks']} pose batches "
                      f"acked, t0_sim={d['t0_sim']:.2f}s -> distractors.json")
    if summary["video"]:
        console.print(f"[green]video[/green] {summary['video']} "
                      f"@ {summary['video_fps']} fps")
    else:
        console.print("[yellow]no frames captured — is the rig in the "
                      "running world and the Sensors system on?[/yellow]")
    console.print(f"[green]run complete[/green] -> {run_dir}/manifest.json")
