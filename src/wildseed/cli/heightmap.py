"""Heightmap relief-ground CLI subcommand (option d2, standalone knob).

Builds a gz ``<heightmap>`` world carrying cm–dm surface roughness on a flat,
drivable macro — VIO/LIO texture without slope. This is a STANDALONE knob (no
object placement / ground-truth on the heightmap yet — deferred in the study);
for the full recipe use ``wildseed scenario --profile vio_lio``.

PREREQUISITES: needs the ground texture in ``models/ground/texture/`` (build any
world first, e.g. `wildseed scenario`/`ground`); the rendered world runs in the
GPU container (`wildseed:egl`). Measure it with `wildseed benchmark rtf/lidar`.
"""

from pathlib import Path

import click

from wildseed.core.heightmap import generate_heightmap_world, is_pow2_plus_1


@click.command()
@click.option("--out-world", type=click.Path(), default="worlds/heightmap_d2.world",
              show_default=True, help="Output gz .world path.")
@click.option("--out-png", type=click.Path(), default="dem/hm_d2.png",
              show_default=True, help="Output heightmap PNG path.")
@click.option("--res", type=int, default=1025, show_default=True,
              help="Heightmap side, px (must be 2^n+1, e.g. 513, 1025).")
@click.option("--extent", type=float, default=60.0, show_default=True,
              help="Patch side length, m.")
@click.option("--relief", type=float, default=0.35, show_default=True,
              help="Max relief height, m (cm–dm roughness on a flat macro).")
@click.option("--seed", type=int, default=7, show_default=True,
              help="Relief seed; same seed+res -> identical heightmap.")
@click.option("--rig/--no-rig", default=True, show_default=True,
              help="Inject the sensor rig at (0,0,--rig-z).")
@click.option("--rig-z", type=float, default=2.0, show_default=True,
              help="Rig height AGL, m.")
@click.option("--base-path", type=click.Path(), default=".",
              help="Project base (holds models/) for the ground texture. Default: cwd.")
@click.pass_context
def heightmap(ctx, out_world, out_png, res, extent, relief, seed, rig, rig_z, base_path):
    """Build a heightmap relief ground: cm–dm roughness on a flat drivable macro.

    Writes a multi-octave (macro-flat) heightmap PNG + a gz world skinned with the
    ground texture, optionally injecting the sensor rig. Carries VIO/LIO surface
    texture the Nyquist-limited WildSeed mesh (d1) can't, at RTF ~1.0.

    \b
    Examples:
        wildseed heightmap --out-world worlds/hm.world --relief 0.35 --seed 7
        wildseed benchmark rtf   --world hm     # RTF cost
        wildseed benchmark lidar --world hm     # LIO roughness gain
    """
    console = ctx.obj["console"]
    base = Path(base_path)

    if not is_pow2_plus_1(res):
        console.print(f"[yellow]warning:[/yellow] --res {res} is not 2^n+1; "
                      "gz heightmaps require 2^n+1 (e.g. 513, 1025).")

    tex = base / "models" / "ground" / "texture" / "ground_Color.png"
    if not tex.exists():
        raise click.ClickException(
            f"ground texture not found: {tex}\nBuild a ground first "
            "(wildseed scenario / ground / generate) so the heightmap has a skin.")

    world_path = base / out_world if not Path(out_world).is_absolute() else Path(out_world)
    png_path = base / out_png if not Path(out_png).is_absolute() else Path(out_png)

    info = generate_heightmap_world(
        world_path, png_path, extent=extent, relief=relief, res=res, seed=seed,
        models_dir=base / "models", rig=rig, rig_z=rig_z)

    console.print(
        f"heightmap {res}x{res} over {extent:g} m ({info['cm_per_px']:.1f} cm/px), "
        f"relief {info['relief_m']:.3f} m, mean_slope {info['mean_slope_deg']:.1f} deg, "
        f"p95 {info['p95_slope_deg']:.1f} deg")
    console.print(f"[green]wrote[/green] [cyan]{info['world']}[/cyan]"
                  + ("  (rig at 0,0,%g)" % rig_z if rig else ""))
