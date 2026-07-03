"""Weather post-processing: sun/scene rewrite + particle emitters, idempotent."""

import math
from xml.etree import ElementTree as ET

import numpy as np
import pytest

from wildseed.core.weather import (
    WEATHER_PRESETS, apply_weather, lens_flare_snippet, sun_direction,
)


@pytest.fixture
def world_file(tmp_path):
    from wildseed.utils.sdf import create_world_base, write_world_file
    root, _world = create_world_base("test_world")
    path = tmp_path / "worlds" / "test.world"
    path.parent.mkdir()
    write_world_file(root, path)
    (tmp_path / "models").mkdir()
    return path


def _world(path):
    return ET.parse(path).getroot().find("world")


def test_sun_direction_low_sun_is_nearly_horizontal():
    d = sun_direction(10.0, 0.0)
    assert abs(np.linalg.norm(d) - 1.0) < 1e-6
    assert d[2] == pytest.approx(-math.sin(math.radians(10)))
    assert d[0] < -0.9  # travelling west->... towards -x (sun in +x/east)


def test_sunglare_sets_bright_low_sun_and_disk(world_file, tmp_path):
    info = apply_weather(world_file, "sunglare", tmp_path / "models")
    w = _world(world_file)
    sun = [l for l in w.findall("light") if l.get("name") == "sun"][0]
    assert float(sun.findtext("intensity")) == 5.0
    dz = float(sun.findtext("direction").split()[2])
    assert -0.25 < dz < 0  # ~10 deg above horizon
    disks = [m for m in w.findall("model") if m.get("name") == "weather_sun_disk"]
    assert len(disks) == 1
    assert info["sun_elevation_deg"] == 10.0


def test_rain_writes_emitter_model_and_plugin(world_file, tmp_path):
    apply_weather(world_file, "rain", tmp_path / "models", particle_rate=123.0)
    w = _world(world_file)
    plugins = [p.get("filename") for p in w.findall("plugin")]
    assert "gz-sim-particle-emitter-system" in plugins
    incs = [i.findtext("uri") for i in w.findall("include")]
    assert "model://weather_rain" in incs
    sdf = (tmp_path / "models" / "weather_rain" / "model.sdf").read_text()
    assert "<particle_emitter" in sdf and "<rate>123</rate>" in sdf
    # emits downward: pitch +90deg pose on the emitter
    assert f"{math.pi / 2:.5f}" in sdf
    assert (tmp_path / "models" / "weather_rain" / "materials" / "textures"
            / "particle.png").exists()


def test_fog_emits_upward_from_ground(world_file, tmp_path):
    apply_weather(world_file, "fog", tmp_path / "models")
    sdf = (tmp_path / "models" / "weather_fog" / "model.sdf").read_text()
    assert f"{-math.pi / 2:.5f}" in sdf


def test_reapply_replaces_previous_weather(world_file, tmp_path):
    apply_weather(world_file, "rain", tmp_path / "models")
    apply_weather(world_file, "snow", tmp_path / "models")
    apply_weather(world_file, "sunglare", tmp_path / "models")
    apply_weather(world_file, "clear", tmp_path / "models")
    w = _world(world_file)
    incs = [i.findtext("uri", "") for i in w.findall("include")]
    assert not any(u.startswith("model://weather_") for u in incs)
    assert not any((m.get("name") or "").startswith("weather_")
                   for m in w.findall("model"))
    # exactly one sun with clear's settings
    suns = [l for l in w.findall("light") if l.get("name") == "sun"]
    assert len(suns) == 1
    assert float(suns[0].findtext("intensity")) == 1.0


def test_all_presets_apply_cleanly(world_file, tmp_path):
    for preset in WEATHER_PRESETS:
        info = apply_weather(world_file, preset, tmp_path / "models")
        assert info["preset"] == preset
        assert _world(world_file) is not None  # still valid XML


def test_overrides_beat_preset(world_file, tmp_path):
    info = apply_weather(world_file, "overcast", tmp_path / "models",
                         sun_elevation_deg=30.0, sun_intensity=0.9)
    assert info["sun_elevation_deg"] == 30.0
    sun = [l for l in _world(world_file).findall("light")
           if l.get("name") == "sun"][0]
    assert float(sun.findtext("intensity")) == 0.9


def test_unknown_preset_rejected(world_file, tmp_path):
    with pytest.raises(ValueError, match="unknown weather preset"):
        apply_weather(world_file, "hurricane", tmp_path / "models")


def test_terrain_extent_sizes_emitter(tmp_path):
    """Emitter box spans the terrain read from models/ground/mesh/terrain.stl."""
    from stl import mesh as stl_mesh
    from wildseed.utils.sdf import create_world_base, write_world_file
    models = tmp_path / "models"
    gm = models / "ground" / "mesh"
    gm.mkdir(parents=True)
    data = np.zeros(2, dtype=stl_mesh.Mesh.dtype)
    data["vectors"][0] = [[-50, -30, 0], [50, -30, 0], [50, 30, 0]]
    data["vectors"][1] = [[-50, -30, 0], [50, 30, 0], [-50, 30, 0]]
    stl_mesh.Mesh(data).save(str(gm / "terrain.stl"))
    root, _ = create_world_base("w")
    wpath = tmp_path / "t.world"
    write_world_file(root, wpath)

    apply_weather(wpath, "snow", models)
    sdf = (models / "weather_snow" / "model.sdf").read_text()
    assert "<size>1 60 100</size>" in sdf


def test_lens_flare_snippet_targets_camera_plugin():
    xml = lens_flare_snippet(scale=2.0)
    assert "gz-sim-lens-flare-system" in xml and "<scale>2</scale>" in xml


def test_cli_registers_weather():
    from wildseed.cli.main import main as cli_main
    assert "weather" in cli_main.commands
