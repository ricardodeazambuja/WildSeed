"""VIO/LIO benchmark CLI group — accessible wrappers over the eval tools.

These are thin pass-through wrappers: the heavy render/estimation code stays in
``tools/*.py`` (still runnable directly). Each subcommand forwards any extra
flags straight to its tool, so the tool's own options work unchanged; run the
underlying ``tools/<name>.py --help`` for the full flag list.

PREREQUISITES (shared): every benchmark renders real gz sensors and MUST run
inside the GPU container ``wildseed:egl`` from the project root. rtf/lidar need a
rig world (``wildseed scenario --profile vio_lio`` / ``generate --rig``); validate
needs a recorded dataset (``wildseed record --dataset``). See docs/GROUND_CLUTTER.md
and docs/VIO_LIO_FEATURES.md.
"""

import os
import subprocess
import sys
from pathlib import Path

import click

# Pass unknown flags through to the underlying tool instead of erroring.
_PASSTHROUGH = dict(ignore_unknown_options=True, allow_extra_args=True)


def _find_tools_dir(base_path: str) -> Path:
    """Locate the repo's tools/ dir: prefer --base-path/cwd, else the src layout."""
    candidates = [Path(base_path) / "tools",
                  Path(__file__).resolve().parents[3] / "tools"]
    for c in candidates:
        if (c / "vio_bench.py").exists():
            return c
    raise click.ClickException(
        f"tools/ directory not found (looked in {', '.join(str(c) for c in candidates)}).\n"
        "Run from the WildSeed project root, or pass --base-path <repo>.")


def _run_tool(ctx, script: str, base_path: str, extra: tuple) -> None:
    """Shell out to tools/<script> with the forwarded args; propagate exit code."""
    tool = _find_tools_dir(base_path) / script
    if not tool.exists():
        raise click.ClickException(f"benchmark tool not found: {tool}")
    env = dict(os.environ)
    # tools import `wildseed`; make the src layout importable if it isn't already.
    src = Path(__file__).resolve().parents[2]
    if (src / "wildseed").is_dir():
        env["PYTHONPATH"] = os.pathsep.join(
            [str(src)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    cmd = [sys.executable, str(tool), *extra]
    ctx.obj["console"].print(f"[dim]$ {' '.join(cmd)}[/dim]")
    raise SystemExit(subprocess.call(cmd, env=env))


@click.group()
def benchmark():
    """Measure whether a generated world supports VIO/LIO (GPU container).

    \b
    Subcommands:
        vio       camera descriptor data-association quality (aliasing)
        rtf       real-time-factor under sensor load (the cost gauge)
        lidar     gpu_lidar range roughness (the LIO-registrable signal)
        validate  end-to-end trajectory drift (ATE) on a recorded dataset

    All run inside `wildseed:egl` from the project root. See the per-command
    --help for prerequisites, and docs/VIO_LIO_FEATURES.md for the tune loop.
    """


@benchmark.command(context_settings=_PASSTHROUGH)
@click.option("--base-path", type=click.Path(), default=".",
              help="Project root holding tools/ + models/. Default: cwd.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def vio(ctx, base_path, args):
    """Camera VIO data-association benchmark (wraps tools/vio_bench.py).

    Renders the sensor-rig camera along a canonical trajectory over the CURRENT
    models/ world and reports descriptor matchability, essential-matrix inlier
    ratio, and a GOOD/ALIASING-RISK verdict — the metric that predicts VIO
    failure (perceptual aliasing) which feature count misses.

    \b
    PREREQUISITE: GPU container wildseed:egl; a built world in models/.
    Extra flags forward to the tool, e.g. --world <stem> (graft placement from
    worlds/<stem>.world, e.g. a scenario world), --tag / --ground-modes / --viz.

    \b
    Examples:
        wildseed benchmark vio --world vio_lio_7 --tag recipe --agl 2 --step 2.0
        wildseed benchmark vio --ground-modes patchy,uniform_t1
    """
    _run_tool(ctx, "vio_bench.py", base_path, args)


@benchmark.command(context_settings=_PASSTHROUGH)
@click.option("--base-path", type=click.Path(), default=".",
              help="Project root holding tools/ + worlds/. Default: cwd.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def rtf(ctx, base_path, args):
    """Real-time-factor-under-load benchmark (wraps tools/rtf_bench.py).

    Launches a real `gz sim -s -r` server on a rig world, attaches cam/lidar
    consumers, and samples real_time_factor. Keep the operating point where
    rtf_min stays >= ~0.5.

    \b
    PREREQUISITE: GPU container wildseed:egl; a RIG world (build with
    `wildseed scenario --profile vio_lio` or `generate --rig`).
    Extra flags forward to the tool, e.g. --world / --tag / --secs.

    \b
    Examples:
        wildseed benchmark rtf --world vio_lio_7 --tag recipe --secs 20
    """
    _run_tool(ctx, "rtf_bench.py", base_path, args)


@benchmark.command(context_settings=_PASSTHROUGH)
@click.option("--base-path", type=click.Path(), default=".",
              help="Project root holding tools/ + worlds/. Default: cwd.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def lidar(ctx, base_path, args):
    """LIDAR range-roughness benchmark (wraps tools/lidar_spread.py).

    Grabs a few gpu_lidar scans on the current rig world and reports
    ring_roughness_m (the core LIO signal — ~0 over flat ground, rises with
    clutter/relief), range_std_m, near_frac and finite_frac.

    \b
    PREREQUISITE: GPU container wildseed:egl; a RIG world with the lidar near the
    ground (`wildseed scenario --profile vio_lio` or `generate --rig`).
    Extra flags forward to the tool, e.g. --world / --tag / --scans.

    \b
    Examples:
        wildseed benchmark lidar --world vio_lio_7 --tag recipe --scans 5
    """
    _run_tool(ctx, "lidar_spread.py", base_path, args)


@benchmark.command(context_settings=_PASSTHROUGH)
@click.option("--base-path", type=click.Path(), default=".",
              help="Project root holding tools/. Default: cwd.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def validate(ctx, base_path, args):
    """End-to-end VIO/LIO ATE validation (wraps tools/vio_validate.py).

    Turns the proxies into real trajectory drift: a self-contained reference
    estimator (monocular ORB+essential-matrix VO, GT-scaled, + point-to-point
    ICP LIO) Umeyama-aligned to the TUM ground truth, scored as ATE RMSE. Run it
    on the recipe world AND a bare baseline; recipe ATE < baseline ATE confirms
    the proxies predict real drift.

    \b
    PREREQUISITE: GPU container wildseed:egl; one or more recorded runs
    (`wildseed record --dataset --keep-frames`), passed as positional RUN dirs.

    \b
    Examples:
        wildseed benchmark validate runs/recipe runs/baseline
    """
    _run_tool(ctx, "vio_validate.py", base_path, args)
