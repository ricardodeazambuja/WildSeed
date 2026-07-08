"""Experiment-spec CLI subcommand (hypothesis + stressor dials -> world)."""

from pathlib import Path

import click
from pydantic import ValidationError

from wildseed.core.experiment import (experiment_stem, load_experiment,
                                      resolve_experiment)


@click.command()
@click.option("--spec", "spec_path", type=click.Path(exists=True), required=True,
              help="Experiment spec YAML (hypothesis, seed, dials, weather, "
                   "overrides). See docs/EXPERIMENTS.md.")
@click.option("--manifest", type=click.Path(exists=True),
              default="assets/manifest.yaml",
              help="Asset manifest holding the per-biome palettes.")
@click.option("--base-path", type=click.Path(), default=".",
              help="Project base (contains models/ and worlds/). Default: cwd.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print the resolved condition (YAML) and exit without building.")
@click.pass_context
def experiment(ctx, spec_path, manifest, base_path, dry_run):
    """Build the world an experiment spec describes.

    A spec is one hypothesis + one stress condition + one seed: stressor dials
    (structure, texture, relief, variety, photometric — each mapped to a
    measured VIO/LIO failure mode) resolve deterministically into a world, and
    worlds/<stem>.yaml records the spec verbatim, every drawn value, and the
    provenance hashes — one file = the exact regenerable stress condition.

    \b
    Example spec:
        hypothesis: "Grazing sun halves confident inliers on the recipe world"
        seed: 42
        dials: {structure: 0.7, texture: 1.0, photometric: 0.9}
        benchmark: [vio]

    \b
    Examples:
        wildseed experiment --spec exp.yaml --dry-run   # inspect the condition
        wildseed experiment --spec exp.yaml             # build it
    """
    console = ctx.obj["console"]

    try:
        spec = load_experiment(Path(spec_path))
        resolved = resolve_experiment(spec)
    except (ValidationError, ValueError) as e:
        raise click.ClickException(f"invalid experiment spec: {e}")

    stem = experiment_stem(spec)
    import yaml
    console.print(f"[bold]Experiment[/bold] [cyan]{stem}[/cyan] "
                  f"seed=[cyan]{spec.seed}[/cyan]")
    console.print(f"[bold]Hypothesis:[/bold] {spec.hypothesis}")
    console.print(f"[dim]{yaml.safe_dump(resolved, sort_keys=False)}[/dim]")
    if dry_run:
        return

    try:
        from wildseed.core.terraingen import GDAL_AVAILABLE
        if not GDAL_AVAILABLE:
            raise click.ClickException(
                "GDAL is required (use the wildseed Docker image, or "
                "`sudo apt install python3-gdal gdal-bin`).")
        from wildseed.core.scenario import run_scenario
        result = run_scenario(resolved, base_path=Path(base_path),
                              manifest_path=Path(manifest), out_stem=stem)
    except (ImportError, FileNotFoundError, KeyError, ValueError) as e:
        raise click.ClickException(str(e))

    prov = result["provenance"]
    console.print(f"[green]Success![/green] world -> [cyan]{result['world']}[/cyan]")
    console.print(f"  record -> [cyan]{result['spec']}[/cyan]")
    console.print(f"  world sha256 [dim]{prov['sha256']['world']}[/dim]")
    if spec.benchmark:
        console.print("  requested benchmarks (run in wildseed:egl, or use "
                      "`wildseed sweep` for a report card):")
        for b in spec.benchmark:
            console.print(f"    wildseed benchmark {b} --world {stem} --tag {stem}")
