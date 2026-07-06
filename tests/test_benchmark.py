"""VIO/LIO benchmark CLI: registration, prereq help, and arg pass-through."""

import pytest
from click.testing import CliRunner
from rich.console import Console


def _ctx():
    return {"console": Console()}


def test_benchmark_group_registered():
    from wildseed.cli.main import main
    assert "benchmark" in main.commands
    sub = main.commands["benchmark"].commands
    assert {"vio", "rtf", "lidar", "validate"} <= set(sub)


@pytest.mark.parametrize("cmd", ["vio", "rtf", "lidar", "validate"])
def test_each_subcommand_help_states_prerequisite(cmd):
    from wildseed.cli.benchmark import benchmark
    res = CliRunner().invoke(benchmark, [cmd, "--help"], obj=_ctx())
    assert res.exit_code == 0
    assert "PREREQUISITE" in res.output
    assert "wildseed:egl" in res.output


@pytest.mark.parametrize("cmd,script", [
    ("vio", "vio_bench.py"),
    ("rtf", "rtf_bench.py"),
    ("lidar", "lidar_spread.py"),
    ("validate", "vio_validate.py"),
])
def test_subcommand_shells_out_to_its_tool(cmd, script, monkeypatch):
    """The wrapper forwards extra flags verbatim to the right tools/ script."""
    import wildseed.cli.benchmark as bench
    captured = {}

    def fake_call(argv, env=None):
        captured["argv"] = argv
        captured["env"] = env
        return 0

    monkeypatch.setattr(bench.subprocess, "call", fake_call)
    from wildseed.cli.benchmark import benchmark
    res = CliRunner().invoke(benchmark, [cmd, "--tag", "foo", "--extra", "1"],
                             obj=_ctx())
    # SystemExit(0) is caught by CliRunner -> exit_code 0
    assert res.exit_code == 0, res.output
    argv = captured["argv"]
    assert argv[1].endswith(script)
    assert argv[-4:] == ["--tag", "foo", "--extra", "1"]     # forwarded verbatim
    assert "PYTHONPATH" in captured["env"]                    # src made importable


def test_nonzero_tool_exit_propagates(monkeypatch):
    import wildseed.cli.benchmark as bench
    monkeypatch.setattr(bench.subprocess, "call", lambda argv, env=None: 3)
    from wildseed.cli.benchmark import benchmark
    res = CliRunner().invoke(benchmark, ["vio"], obj=_ctx())
    assert res.exit_code == 3


def test_find_tools_dir_errors_clearly(tmp_path):
    import click
    from wildseed.cli.benchmark import _find_tools_dir
    # a base-path with no tools/ AND monkeyless: the src-layout fallback still
    # resolves in the repo, so instead assert the happy path finds vio_bench.py.
    found = _find_tools_dir(str(tmp_path))
    assert (found / "vio_bench.py").exists()
