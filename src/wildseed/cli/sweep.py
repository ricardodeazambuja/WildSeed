"""Stressor-axis sweep CLI subcommand (difficulty-ladder report cards)."""

from pathlib import Path

import click
from pydantic import ValidationError

from wildseed.core.experiment import load_experiment
from wildseed.core.sweep import SWEEP_AXES, run_sweep, sweep_conditions


def _floats(_ctx, _param, value):
    try:
        return [float(v) for v in value.split(",") if v.strip() != ""]
    except ValueError:
        raise click.BadParameter(f"expected comma-separated floats, got {value!r}")


def _ints(_ctx, _param, value):
    if value is None:
        return None
    try:
        return [int(v) for v in value.split(",") if v.strip() != ""]
    except ValueError:
        raise click.BadParameter(f"expected comma-separated ints, got {value!r}")


@click.command()
@click.option("--spec", "spec_path", type=click.Path(exists=True), required=True,
              help="Experiment spec YAML (the sweep varies ONE of its dials).")
@click.option("--axis", type=click.Choice(SWEEP_AXES), required=True,
              help="Stressor dial to sweep; all other dials are held.")
@click.option("--values", callback=_floats, required=True,
              help="Comma-separated dial values in [0,1], e.g. 0,0.5,1")
@click.option("--seeds", callback=_ints, default=None,
              help="Comma-separated seeds (replicates). Default: the spec's seed.")
@click.option("--bench", "bench_csv", default=None,
              help="Benchmarks per condition: comma list from vio,lidar,rtf. "
                   "Default: the spec's `benchmark` list. Use '' for build-only.")
@click.option("--out", "out_dir", type=click.Path(), default=None,
              help="Report directory. Default: runs/sweep_<name>.")
@click.option("--manifest", type=click.Path(exists=True),
              default="assets/manifest.yaml",
              help="Asset manifest holding the per-biome palettes.")
@click.option("--base-path", type=click.Path(), default=".",
              help="Project base (contains models/ and worlds/). Default: cwd.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print the resolved conditions and exit without building.")
@click.pass_context
def sweep(ctx, spec_path, axis, values, seeds, bench_csv, out_dir, manifest,
          base_path, dry_run):
    """Sweep one stressor dial and emit a graded benchmark report card.

    For each (value x seed): build the condition's world, run the requested
    benchmarks on it immediately (models/ is shared state, so the loop is
    strictly sequential), and append a ladder row. Output: report.md +
    report.json + the spec, under runs/sweep_<name>/ — an easy->failure
    difficulty ladder per stressor, regenerable from the spec alone.

    \b
    PREREQUISITE for --bench: the GPU container (wildseed:egl, --gpus all),
    like the `wildseed benchmark` group. Build-only sweeps need GDAL only.

    \b
    Examples:
        wildseed sweep --spec exp.yaml --axis photometric --values 0,0.5,1
        wildseed sweep --spec exp.yaml --axis structure --values 0,0.35,0.7 \\
            --seeds 42,43 --bench vio,rtf
        wildseed sweep --spec exp.yaml --axis texture --values 0,1 --dry-run
    """
    console = ctx.obj["console"]

    try:
        spec = load_experiment(Path(spec_path))
        use_seeds = seeds or [spec.seed]
        conditions = sweep_conditions(spec, axis, values, use_seeds)
    except (ValidationError, ValueError) as e:
        raise click.ClickException(f"invalid sweep: {e}")

    benches = (spec.benchmark if bench_csv is None
               else [b for b in bench_csv.split(",") if b.strip()])

    console.print(f"[bold]Sweep[/bold] [cyan]{axis}[/cyan] x {values} "
                  f"seeds={use_seeds} benches={benches or 'build-only'} "
                  f"({len(conditions)} conditions)")
    console.print(f"[bold]Hypothesis:[/bold] {spec.hypothesis}")
    for c in conditions:
        photo = c["resolved"].get("photometric")
        sun = (f" sun_elev={photo['sun_elevation_deg']}" if photo else "")
        console.print(f"  {c['stem']}: {axis}={c['value']}{sun}")
    if dry_run:
        return

    try:
        from wildseed.core.terraingen import GDAL_AVAILABLE
        if not GDAL_AVAILABLE:
            raise click.ClickException(
                "GDAL is required (use the wildseed Docker image).")
        result = run_sweep(spec, axis, values, use_seeds,
                           base_path=Path(base_path),
                           manifest_path=Path(manifest), benches=benches,
                           out_dir=Path(out_dir) if out_dir else None,
                           progress=lambda m: console.print(f"[dim]{m}[/dim]"))
    except (ImportError, FileNotFoundError, KeyError, ValueError) as e:
        raise click.ClickException(str(e))

    out = result["out_dir"]
    console.print(f"[green]Sweep complete.[/green] report -> [cyan]{out}/report.md[/cyan]")
    for row in result["report"]["rows"]:
        v = row.get("vio") or {}
        verdict = v.get("verdict") or v.get("error", "")[:30] or "-"
        console.print(f"  {axis}={row['value']:g} seed={row['seed']}: "
                      f"inliers={v.get('inliers_per_pair', '-')} {verdict}")
