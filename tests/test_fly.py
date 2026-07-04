"""Tests for seeded trajectory synthesis (docs/SENSOR_RIG.md)."""

import json
import math

import numpy as np
import pytest

from wildseed.core.fly import (PATTERNS, TerrainSampler, interpolate_pose,
                               synthesize, write_trajectory)


@pytest.fixture(scope="module")
def terrain(tmp_path_factory):
    """Synthetic 200x200 m bumpy terrain STL (z = gentle sine hills)."""
    from stl import mesh as stl_mesh

    n = 21
    xs = np.linspace(-100, 100, n)
    ys = np.linspace(-100, 100, n)
    gx, gy = np.meshgrid(xs, ys)
    gz = 5.0 * np.sin(gx / 40.0) * np.cos(gy / 50.0) + 10.0

    tris = []
    for i in range(n - 1):
        for j in range(n - 1):
            v00 = (gx[i, j], gy[i, j], gz[i, j])
            v10 = (gx[i, j + 1], gy[i, j + 1], gz[i, j + 1])
            v01 = (gx[i + 1, j], gy[i + 1, j], gz[i + 1, j])
            v11 = (gx[i + 1, j + 1], gy[i + 1, j + 1], gz[i + 1, j + 1])
            tris.append([v00, v10, v11])
            tris.append([v00, v11, v01])
    data = np.zeros(len(tris), dtype=stl_mesh.Mesh.dtype)
    data["vectors"] = np.array(tris)
    m = stl_mesh.Mesh(data)
    path = tmp_path_factory.mktemp("terrain") / "terrain.stl"
    m.save(str(path))
    return TerrainSampler(path)


def test_sampler_matches_analytic_surface(terrain):
    for x, y in [(0.0, 0.0), (25.0, -30.0), (-60.0, 45.0)]:
        expect = 5.0 * math.sin(x / 40.0) * math.cos(y / 50.0) + 10.0
        assert abs(float(terrain.height(x, y)) - expect) < 0.6


@pytest.mark.parametrize("pattern", PATTERNS)
def test_seed_determinism_byte_identical(pattern, terrain, tmp_path):
    a = synthesize(pattern, seed=7, terrain=terrain)
    b = synthesize(pattern, seed=7, terrain=terrain)
    pa = write_trajectory(a, tmp_path / "a.json")
    pb = write_trajectory(b, tmp_path / "b.json")
    assert pa.read_bytes() == pb.read_bytes()
    c = synthesize(pattern, seed=8, terrain=terrain)
    assert json.dumps(c) != json.dumps(a)


@pytest.mark.parametrize("pattern", PATTERNS)
def test_agl_stays_bounded(pattern, terrain):
    traj = synthesize(pattern, seed=3, terrain=terrain, agl=12.0)
    xs = np.array([s["x"] for s in traj["samples"]])
    ys = np.array([s["y"] for s in traj["samples"]])
    zs = np.array([s["z"] for s in traj["samples"]])
    ground = terrain.height(xs, ys)
    agl = zs - ground
    # z is low-pass filtered over smoothed ground: allow the hills' amplitude
    assert agl.min() > 4.0, f"{pattern}: min AGL {agl.min():.1f}"
    assert agl.max() < 25.0, f"{pattern}: max AGL {agl.max():.1f}"


@pytest.mark.parametrize("pattern", PATTERNS)
def test_stays_inside_margin(pattern, terrain):
    margin = 15.0
    traj = synthesize(pattern, seed=11, terrain=terrain, margin=margin)
    xs = np.array([s["x"] for s in traj["samples"]])
    ys = np.array([s["y"] for s in traj["samples"]])
    # PCHIP (open paths) is shape-preserving: no overshoot beyond waypoints
    assert xs.min() > -100 + margin - 0.5 and xs.max() < 100 - margin + 0.5
    assert ys.min() > -100 + margin - 0.5 and ys.max() < 100 - margin + 0.5


def test_orbit_looks_at_center(terrain):
    traj = synthesize("orbit", seed=5, terrain=terrain, center=(0.0, 0.0))
    for s in traj["samples"][:: len(traj["samples"]) // 10]:
        yaw = 2 * math.atan2(s["qz"], s["qw"])   # roll=0, small pitch
        bearing = math.atan2(-s["y"], -s["x"])   # toward the centre
        d = (yaw - bearing + math.pi) % (2 * math.pi) - math.pi
        assert abs(d) < 0.2


def test_dolly_yaw_follows_velocity(terrain):
    traj = synthesize("dolly", seed=2, terrain=terrain)
    s = traj["samples"]
    mid = len(s) // 2
    vx = s[mid + 1]["x"] - s[mid - 1]["x"]
    vy = s[mid + 1]["y"] - s[mid - 1]["y"]
    yaw = 2 * math.atan2(s[mid]["qz"], s[mid]["qw"])
    d = (yaw - math.atan2(vy, vx) + math.pi) % (2 * math.pi) - math.pi
    assert abs(d) < 0.15


def test_interpolate_pose_endpoints_and_midpoint(terrain):
    traj = synthesize("dolly", seed=1, terrain=terrain)
    first, last = traj["samples"][0], traj["samples"][-1]
    assert interpolate_pose(traj, -1.0) == first
    assert interpolate_pose(traj, last["t"] + 5) == last
    mid_t = (traj["samples"][10]["t"] + traj["samples"][11]["t"]) / 2
    p = interpolate_pose(traj, mid_t)
    assert min(traj["samples"][10]["x"], traj["samples"][11]["x"]) - 1e-9 \
        <= p["x"] <= max(traj["samples"][10]["x"], traj["samples"][11]["x"]) + 1e-9
    q_norm = p["qw"]**2 + p["qx"]**2 + p["qy"]**2 + p["qz"]**2
    assert abs(q_norm - 1.0) < 1e-9


def test_kinematic_mode_recorded(terrain):
    traj = synthesize("orbit", seed=0, terrain=terrain)
    assert traj["mode"] == "kinematic"   # datasets must know IMU is invalid


def test_height_cli_json(tmp_path):
    """`wildseed height --json` reports the sampled ground z + bounds."""
    from click.testing import CliRunner
    from stl import mesh as stl_mesh

    from wildseed.cli.main import main as cli_main

    mesh_dir = tmp_path / "models" / "ground" / "mesh"
    mesh_dir.mkdir(parents=True)
    # flat 20x20 m plate at z=3.25 under base/models/ground/mesh/terrain.stl
    n = 5
    xs = np.linspace(-10, 10, n)
    gx, gy = np.meshgrid(xs, xs)
    gz = np.full_like(gx, 3.25)
    tris = []
    for i in range(n - 1):
        for j in range(n - 1):
            v00 = (gx[i, j], gy[i, j], gz[i, j])
            v10 = (gx[i, j + 1], gy[i, j + 1], gz[i, j + 1])
            v01 = (gx[i + 1, j], gy[i + 1, j], gz[i + 1, j])
            v11 = (gx[i + 1, j + 1], gy[i + 1, j + 1], gz[i + 1, j + 1])
            tris.append([v00, v10, v11])
            tris.append([v00, v11, v01])
    data = np.zeros(len(tris), dtype=stl_mesh.Mesh.dtype)
    data["vectors"] = np.array(tris)
    stl_mesh.Mesh(data).save(str(mesh_dir / "terrain.stl"))

    result = CliRunner().invoke(
        cli_main, ["height", "-x", "1.5", "-y", "-2.0", "--json",
                   "--base-path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip().splitlines()[-1])
    assert abs(payload["z"] - 3.25) < 1e-3
    assert payload["bounds"]["x_max"] == 10.0
