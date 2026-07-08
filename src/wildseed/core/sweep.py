"""Stressor-axis sweep -> graded benchmark report card.

Sweeps ONE stressor dial of an experiment spec across values (seeds held or
replicated), builds each condition, runs the requested benchmarks on it, and
emits a difficulty-ladder report (markdown + JSON): the regenerable analogue
of a graded benchmark suite (docs/EXPERIMENT_PLAN.md D4).

Constraints honoured:
- ``models/ground`` is shared mutable state, so the loop is strictly
  sequential and each condition is benchmarked immediately after its build
  (a world file is only valid while its ground/models are the current ones).
- benchmarks need the GPU container (wildseed:egl) exactly like the
  ``wildseed benchmark`` group; the build-only path (no benches) needs GDAL.
- vio runs at the study's canonical ground-robot pose (AGL 2 m, 2 m/frame —
  the P1 failure pose) so ladder numbers are comparable with the measured
  tables in docs/GROUND_CLUTTER.md.
- when a condition carries a photometric/weather stage, vio_bench gets
  ``--world-sun`` so the stress is actually rendered (purpose test).
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from wildseed.core.experiment import (BENCH_NAMES, ExperimentSpec,
                                      experiment_stem, resolve_experiment)

logger = logging.getLogger("wildseed.sweep")

SWEEP_AXES = ("structure", "texture", "relief", "variety", "photometric")

# study pose: 2 m AGL, fast forward motion — the P1 ground-robot failure pose.
VIO_DEFAULT_ARGS = ("--agl", "2", "--step", "2.0")

_TOOL = {"vio": "vio_bench.py", "lidar": "lidar_spread.py", "rtf": "rtf_bench.py"}
_TOOL_JSON = {"vio": "vio_bench_{tag}.json", "lidar": "lidar_spread_{tag}.json",
              "rtf": "rtf_bench_{tag}.json"}
# report-card columns pulled from each tool's JSON
_VIO_KEYS = ("inliers_per_pair", "ratio_reject", "inlier_ratio",
             "orb_per_frame", "self_ambiguity", "verdict")
_LIDAR_KEYS = ("ring_roughness_m", "range_std_m", "near_frac", "finite_frac")
_RTF_KEYS = ("rtf_min", "rtf_mean", "window_rtf", "load_wait_s", "stalled")

BENCH_TIMEOUT_S = 1200  # per tool call; rtf/vio load+render are minutes each


def condition_stem(spec: ExperimentSpec, axis: str, value: float, seed: int) -> str:
    """Deterministic, filesystem-safe stem: exp_<name>_<axis><val*100>_s<seed>."""
    return f"{experiment_stem(spec)}_{axis}{int(round(value * 100)):03d}_s{seed}"


def sweep_conditions(spec: ExperimentSpec, axis: str, values: List[float],
                     seeds: List[int]) -> List[dict]:
    """Resolve every (value x seed) condition (no building). Deterministic."""
    if axis not in SWEEP_AXES:
        raise ValueError(f"unknown sweep axis {axis!r}; expected one of {SWEEP_AXES}")
    conditions = []
    for value in values:
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"axis value {value} outside [0, 1]")
        for seed in seeds:
            cond = spec.model_copy(deep=True)
            cond.seed = int(seed)
            setattr(cond.dials, axis, float(value))
            resolved = resolve_experiment(cond)
            conditions.append({
                "axis": axis, "value": float(value), "seed": int(seed),
                "stem": condition_stem(spec, axis, value, seed),
                "resolved": resolved,
            })
    return conditions


def _tool_env(base_path: Path) -> Dict[str, str]:
    """tools/*.py import wildseed; make the src layout importable (live source
    wins over any pip-installed copy — the container gotcha)."""
    env = dict(os.environ)
    src = Path(__file__).resolve().parents[2]
    if (src / "wildseed").is_dir():
        env["PYTHONPATH"] = os.pathsep.join(
            [str(src)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    return env


def _run_bench(bench: str, stem: str, base_path: Path,
               world_sun: bool) -> dict:
    """Run one benchmark tool on the just-built world; return its metrics row
    (never raises — a failed bench records its error and the sweep goes on)."""
    tool = base_path / "tools" / _TOOL[bench]
    cmd = [sys.executable, str(tool), "--tag", stem, "--world", stem]
    if bench == "vio":
        cmd += list(VIO_DEFAULT_ARGS)
        if world_sun:
            cmd.append("--world-sun")
    t0 = time.time()
    try:
        r = subprocess.run(cmd, cwd=base_path, env=_tool_env(base_path),
                           capture_output=True, text=True,
                           timeout=BENCH_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"error": f"timeout after {BENCH_TIMEOUT_S}s"}
    row = {"bench_wall_s": round(time.time() - t0, 1)}
    out_json = base_path / "frames" / _TOOL_JSON[bench].format(tag=stem)
    if r.returncode != 0 or not out_json.exists():
        row["error"] = (r.stderr or r.stdout or "no output")[-400:]
        return row
    data = json.loads(out_json.read_text())
    if bench == "vio":
        results = data.get("results") or [{}]
        src = results[0]
        keys = _VIO_KEYS
    elif bench == "lidar":
        src, keys = data, _LIDAR_KEYS
    else:
        src, keys = data, _RTF_KEYS
    row.update({k: src.get(k) for k in keys})
    return row


def run_sweep(spec: ExperimentSpec, axis: str, values: List[float],
              seeds: List[int], base_path: Path, manifest_path: Path,
              benches: List[str], out_dir: Optional[Path] = None,
              progress=print) -> dict:
    """Build + benchmark every condition sequentially; write the report card.

    Returns the report dict; writes report.json + report.md (+ the spec) under
    ``out_dir`` (default runs/sweep_<name>).
    """
    from wildseed.core.scenario import run_scenario

    bad = [b for b in benches if b not in BENCH_NAMES]
    if bad:
        raise ValueError(f"unknown benchmark(s) {bad}; expected from {BENCH_NAMES}")
    base_path = Path(base_path)
    # axis in the default dir name: sweeps of different axes from one spec
    # must not overwrite each other's reports
    out_dir = (Path(out_dir) if out_dir
               else base_path / "runs" / f"sweep_{experiment_stem(spec)}_{axis}")
    out_dir.mkdir(parents=True, exist_ok=True)

    conditions = sweep_conditions(spec, axis, values, seeds)
    if benches and not conditions[0]["resolved"].get("rig") and \
            {"lidar", "rtf"} & set(benches):
        progress("WARNING: lidar/rtf need a rig world; the biome path builds "
                 "none — expect those benches to fail (use profile: vio_lio).")

    rows = []
    for i, cond in enumerate(conditions):
        stem, resolved = cond["stem"], cond["resolved"]
        progress(f"[{i + 1}/{len(conditions)}] {stem}: building ...")
        t0 = time.time()
        result = run_scenario(resolved, base_path=base_path,
                              manifest_path=manifest_path, out_stem=stem)
        row = {
            "value": cond["value"], "seed": cond["seed"], "stem": stem,
            "build_s": round(time.time() - t0, 1),
            "world_sha256": result["provenance"]["sha256"]["world"],
        }
        world_sun = bool(resolved.get("photometric") or resolved.get("weather"))
        for bench in benches:
            progress(f"[{i + 1}/{len(conditions)}] {stem}: benchmark {bench} ...")
            row[bench] = _run_bench(bench, stem, base_path, world_sun)
        rows.append(row)

    report = {
        "experiment": experiment_stem(spec),
        "hypothesis": spec.hypothesis,
        "axis": axis, "values": [float(v) for v in values],
        "seeds": [int(s) for s in seeds],
        "benches": list(benches),
        "spec": spec.model_dump(),
        "rows": rows,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "spec.yaml").write_text(yaml.safe_dump(spec.model_dump(),
                                                      sort_keys=False))
    (out_dir / "report.md").write_text(render_report_md(report))
    return {"report": report, "out_dir": out_dir}


def _fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def render_report_md(report: dict) -> str:
    """The difficulty ladder: one row per condition, worst axis value last."""
    axis = report["axis"]
    benches = report["benches"]
    lines = [
        f"# Sweep report — {report['experiment']} / axis `{axis}`",
        "",
        f"**Hypothesis:** {report['hypothesis']}",
        "",
        f"Axis `{axis}` swept over {report['values']} at seed(s) "
        f"{report['seeds']}; all other dials held at the spec values below. "
        f"Benchmarks: {', '.join(benches) if benches else 'none (build-only)'}. "
        "vio runs the study's ground-robot pose (AGL 2 m, 2 m/frame — the P1 "
        "failure pose in docs/GROUND_CLUTTER.md), so inliers/verdicts are "
        "comparable with the measured study tables.",
        "",
    ]
    cols = [axis, "seed"]
    if "vio" in benches:
        cols += ["inliers/pair", "ratio_reject", "inlier_ratio", "verdict"]
    if "lidar" in benches:
        cols += ["ring_rough_m", "finite_frac"]
    if "rtf" in benches:
        cols += ["rtf_min", "load_s"]
    cols += ["build_s", "world sha256[:12]"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "---|" * len(cols))
    for r in sorted(report["rows"], key=lambda x: (x["value"], x["seed"])):
        cells = [_fmt(r["value"]), str(r["seed"])]
        if "vio" in benches:
            v = r.get("vio", {})
            cells += [_fmt(v.get("inliers_per_pair"), 0), _fmt(v.get("ratio_reject")),
                      _fmt(v.get("inlier_ratio")),
                      v.get("verdict") or v.get("error", "—")[:24]]
        if "lidar" in benches:
            l = r.get("lidar", {})
            cells += [_fmt(l.get("ring_roughness_m"), 3),
                      _fmt(l.get("finite_frac"))]
        if "rtf" in benches:
            t = r.get("rtf", {})
            cells += [_fmt(t.get("rtf_min")), _fmt(t.get("load_wait_s"), 0)]
        cells += [_fmt(r["build_s"], 0), (r["world_sha256"] or "")[:12]]
        lines.append("| " + " | ".join(cells) + " |")
    lines += [
        "",
        "Reproduce any row: `wildseed experiment --spec spec.yaml` with the "
        f"spec in this directory, `{axis}` set to the row's value and `seed` "
        "to the row's seed — the world sha256 must match.",
        "",
    ]
    return "\n".join(lines)
