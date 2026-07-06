"""Corridor density-map CLI subcommand (steered-scatter plumbing).

Paints a driving-corridor density map to feed ``generate --density-maps``, so a
small RTF-bounded object budget lands where the vehicle actually drives (high
local density in view, low total count). See ``docs/GROUND_CLUTTER.md`` (option
(c), steered scatter) and ``docs/VIO_LIO_FEATURES.md``.
"""

from pathlib import Path

import click

from wildseed.core.density_maps import (
    build_corridor_map, save_png, terrain_extent_y, white_fraction,
)


@click.command("corridor-map")
@click.option("--out", required=True, type=click.Path(),
              help="Output PNG path.")
@click.option("--half-width", type=float, default=6.0, show_default=True,
              help="Corridor half-width, metres (full width = 2x).")
@click.option("--y0", type=float, default=0.0, show_default=True,
              help="Corridor centre-line world Y (m). 0 = the vio_bench drive line.")
@click.option("--extent", default="auto", show_default=True,
              help="Terrain side length (m), or 'auto' to read "
                   "models/ground/mesh/terrain.obj under --base-path.")
@click.option("--res", type=int, default=512, show_default=True,
              help="Output image side, px.")
@click.option("--soft", is_flag=True, default=False,
              help="Gaussian taper to the corridor edges (else a hard white band).")
@click.option("--base-path", type=click.Path(), default=".",
              help="Project base (holds models/) for --extent auto. Default: cwd.")
@click.pass_context
def corridor_map(ctx, out, half_width, y0, extent, res, soft, base_path):
    """Paint a driving-corridor density map for steered object placement.

    The corridor is a white band along the +X drive line at world Y=--y0. Feed
    the PNG to `generate --density-maps` with a modest object budget; placement
    is intensity-proportional, so every requested instance lands in the band —
    high LOCAL density where the robot drives, low TOTAL count (RTF-friendly).

    The map's SHAPE is deterministic (no seed); the OBJECTS scattered into it are
    seeded by `generate --seed`.

    \b
    Examples:
        wildseed corridor-map --out corridor.png --half-width 8 --soft
        wildseed generate --density-maps '{"rock":"corridor.png","bush":"corridor.png"}' \\
            --density '{"rock":200,"bush":300,"tree":0,"grass":0}' --rig
    """
    console = ctx.obj["console"]

    if str(extent).lower() == "auto":
        obj = Path(base_path) / "models" / "ground" / "mesh" / "terrain.obj"
        if not obj.exists():
            raise click.ClickException(
                f"terrain OBJ not found: {obj}\nGenerate terrain first "
                "(wildseed terrain/terraingen/scenario), or pass --extent <metres>.")
        min_y, max_y = terrain_extent_y(obj)
        extent_m = max_y - min_y
    else:
        try:
            extent_m = float(extent)
        except ValueError:
            raise click.ClickException(f"--extent must be a number or 'auto', got {extent!r}")

    img = build_corridor_map(extent_m, half_width, y0=y0, res=res, soft=soft)
    save_png(img, out)
    frac = white_fraction(img)
    console.print(
        f"[green]wrote[/green] [cyan]{out}[/cyan] ({res}x{res}); corridor y0={y0:g} "
        f"half-width={half_width:g} m over extent {extent_m:.1f} m; "
        f"placeable area frac ~{frac:.3f}")
