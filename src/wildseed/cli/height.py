"""Terrain height query CLI subcommand.

Answers "what is the ground z at (x, y)?" from the generated terrain mesh —
the number an external spawner (e.g. a ROS 2 launch dropping a ground robot
into a WildSeed world) needs so the robot starts ON the terrain instead of
inside or above it.
"""

import json as _json
from pathlib import Path

import click

from wildseed.core.fly import TerrainSampler


@click.command()
@click.option("-x", "x", type=float, default=0.0, show_default=True,
              help="World x coordinate, metres.")
@click.option("-y", "y", type=float, default=0.0, show_default=True,
              help="World y coordinate, metres.")
@click.option("--base-path", "-b", type=click.Path(exists=True), default=".",
              help="Project base (models/ + worlds/). Default: cwd")
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit machine-readable JSON {x, y, z, bounds} instead of "
                   "plain text.")
@click.pass_context
def height(ctx, x, y, base_path, as_json):
    """Print the terrain ground z at (x, y).

    Samples the same terrain mesh the flight patterns follow
    (models/ground/mesh/terrain.stl). Outside the mesh hull the nearest
    vertex height is returned.

    \b
    Examples:
        wildseed height                      # ground z at the origin
        wildseed height -x 12.5 -y -3 --json
    """
    console = ctx.obj["console"]
    base = Path(base_path)

    stl = base / "models" / "ground" / "mesh" / "terrain.stl"
    if not stl.exists():
        raise click.ClickException(
            f"terrain mesh not found: {stl}\nGenerate terrain first "
            "(wildseed terrain/terraingen).")

    terrain = TerrainSampler(stl)
    z = float(terrain.height(x, y))
    if as_json:
        click.echo(_json.dumps({
            "x": x, "y": y, "z": round(z, 4),
            "bounds": {"x_min": round(float(terrain.x_min), 4),
                       "y_min": round(float(terrain.y_min), 4),
                       "x_max": round(float(terrain.x_max), 4),
                       "y_max": round(float(terrain.y_max), 4)}}))
    else:
        console.print(f"ground z at ({x:g}, {y:g}) = [cyan]{z:.4f}[/cyan] m")
