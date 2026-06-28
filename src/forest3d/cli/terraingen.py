"""Procedural terrain (DEM) synthesis CLI subcommand."""

import click
from pathlib import Path

from forest3d.config.schema import TerrainGenConfig, PRESET_NAMES

DEFAULT_OUT = "./dem/synth.tif"


@click.command()
@click.option("--preset", type=click.Choice(PRESET_NAMES), default="hilly",
              help="Landform preset (feature defaults; flags override).")
@click.option("--seed", type=int, default=0, help="RNG seed (same seed -> same landform).")
@click.option("--size", "resolution", type=int, default=192,
              help="DEM pixels per side (== mesh density). Default 192.")
@click.option("--pixel", "pixel_m", type=float, default=2.5, help="Metres per pixel (default 2.5).")
@click.option("--out", "-o", "out_path", type=click.Path(), default=DEFAULT_OUT,
              help=f"Output GeoTIFF DEM (default: {DEFAULT_OUT}).")
@click.option("--amplitude", "amplitude_m", type=float, default=None, help="Override fBm base relief (m).")
@click.option("--roughness", type=float, default=None, help="Override per-octave amplitude falloff (0-1).")
@click.option("--octaves", type=int, default=None, help="Override fBm octave count.")
@click.option("--feature", "feature_m", type=float, default=None, help="Override largest hill feature size (m).")
@click.option("--ridged", type=float, default=None, help="Override ridged-noise blend (0-1).")
@click.option("--detail", type=float, default=None, help="Fine-surface detail 0-1 (1=full/spongy, 0=smooth slopes; keeps macro hills).")
@click.option("--slope", "slope_m", type=float, default=None, help="Override planar tilt across map (m).")
@click.option("--peaks", "n_peaks", type=int, default=None, help="Override number of peaks/mounts.")
@click.option("--basins", "n_basins", type=int, default=None, help="Override number of basins (lakes).")
@click.option("--creeks", "n_creeks", type=int, default=None, help="Override number of creeks.")
@click.option("--creek-depth", "creek_depth_m", type=float, default=None, help="Creek channel depth (m).")
@click.option("--creek-width", "creek_width_m", type=float, default=None, help="Creek flat-bed width (m).")
@click.option("--edge-taper", type=float, default=None, help="Border relief taper fraction (default 0.12).")
@click.option("--smooth", "smooth_sigma", type=float, default=None, help="Final anti-facet smooth sigma px (default 0.8).")
@click.pass_context
def terraingen(ctx, preset, seed, resolution, pixel_m, out_path, amplitude_m, roughness,
               octaves, feature_m, ridged, detail, slope_m, n_peaks, n_basins, n_creeks,
               creek_depth_m, creek_width_m, edge_taper, smooth_sigma):
    """Synthesize a seeded procedural terrain as a GeoTIFF DEM.

    The output feeds the existing pipeline unchanged:
    ``forest3d terrain --dem <out>`` then ``ground`` / ``generate``.

    \b
    Examples:
        forest3d terraingen --preset hilly --seed 7 --size 192 -o dem/synth.tif
        forest3d terraingen --preset lakeland --seed 7 -o dem/lake.tif
        forest3d terraingen --preset mountainous --seed 3 --amplitude 100
        # smooth surface, SAME hill pattern (tame the "spongy" look):
        forest3d terraingen --preset hilly --seed 7 --detail 0.2
    """
    console = ctx.obj["console"]

    kwargs = dict(preset=preset, seed=seed, resolution=resolution, pixel_m=pixel_m)
    for name, val in dict(
        amplitude_m=amplitude_m, roughness=roughness, octaves=octaves, feature_m=feature_m,
        ridged=ridged, detail=detail, slope_m=slope_m, n_peaks=n_peaks, n_basins=n_basins,
        n_creeks=n_creeks, creek_depth_m=creek_depth_m, creek_width_m=creek_width_m,
        edge_taper=edge_taper, smooth_sigma=smooth_sigma,
    ).items():
        if val is not None:
            kwargs[name] = val
    cfg = TerrainGenConfig(**kwargs)

    console.print(f"[bold]Terrain synthesis[/bold]  preset=[cyan]{cfg.preset}[/cyan] "
                  f"seed=[cyan]{cfg.seed}[/cyan] size=[cyan]{cfg.resolution}[/cyan]")

    try:
        from forest3d.core.terraingen import synthesize_dem, GDAL_AVAILABLE
        if not GDAL_AVAILABLE:
            raise click.ClickException(
                "GDAL is required for terrain synthesis.\n"
                "  Use Docker (forest3d:egl) or: sudo apt install python3-gdal gdal-bin"
            )
        info = synthesize_dem(cfg, Path(out_path))
    except ImportError as e:
        raise click.ClickException(str(e))

    console.print(f"[green]Success![/green] DEM -> [cyan]{info['out']}[/cyan]")
    console.print(f"  extent=[cyan]{info['extent_m']} m[/cyan]  relief z=[cyan]"
                  f"{info['z_min']}..{info['z_max']} m[/cyan] ({info['z_extent']} m)")
    if info["lakes"]:
        console.print(f"  [blue]{len(info['lakes'])} lake(s):[/blue]")
        for i, lk in enumerate(info["lakes"]):
            console.print(f"    #{i} floor_z={lk['floor_z']} m  "
                          f"suggested --water-level [bold]{lk['suggested_water_level']}[/bold]  "
                          f"center_xy={lk['center_xy_m']} r={lk['radius_m']} m")
        rec = min(lk["suggested_water_level"] for lk in info["lakes"])
        console.print(f"  [dim]single global plane: forest3d ground ... --water-level {rec}[/dim]")
    console.print(f"[dim]Next: forest3d terrain --dem {info['out']}[/dim]")
