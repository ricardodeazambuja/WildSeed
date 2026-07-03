"""Tests for the sensor rig generator (docs/SENSOR_RIG_PLAN.md Phase 1)."""

from xml.etree import ElementTree as ET

import pytest

from wildseed.core.rig import (CLASS_LABELS, RigConfig, add_label_plugin,
                               add_rig_include, add_world_sensor_requirements,
                               build_rig_model, rig_topics, write_rig_model)


def sensor_names(model):
    return {s.get("name") for s in model.iter("sensor")}


def test_default_rig_has_full_suite():
    model = build_rig_model(RigConfig())
    assert sensor_names(model) == {
        "cam_left", "cam_right", "rgbd", "wideangle", "segcam", "lidar",
        "imu", "navsat", "air_pressure", "magnetometer"}
    # GT odometry publisher present
    plugins = {p.get("name") for p in model.findall("plugin")}
    assert "gz::sim::systems::OdometryPublisher" in plugins
    # floating body: gravity off so kinematic + wrench modes share the model
    assert model.find("link/gravity").text == "false"


def test_sensors_toggle_off():
    cfg = RigConfig(stereo_baseline=0.0, rgbd=False, wideangle=False,
                    segmentation=False, lidar={"enabled": False})
    names = sensor_names(build_rig_model(cfg))
    assert names == {"cam_left", "imu", "navsat", "air_pressure", "magnetometer"}
    topics = rig_topics(cfg)
    assert "cam_right" not in topics and "lidar_points" not in topics


def test_lidar_channels_configurable():
    cfg = RigConfig(lidar={"channels": 32, "samples": 1024})
    model = build_rig_model(cfg)
    lidar = next(s for s in model.iter("sensor") if s.get("name") == "lidar")
    assert lidar.find("lidar/scan/vertical/samples").text == "32"
    assert lidar.find("lidar/scan/horizontal/samples").text == "1024"


def test_stereo_baseline_split_across_cameras():
    model = build_rig_model(RigConfig(stereo_baseline=0.2))
    poses = {s.get("name"): s.find("pose").text for s in model.iter("sensor")}
    assert poses["cam_left"].split()[1] == "0.1"
    assert poses["cam_right"].split()[1] == "-0.1"


def test_write_rig_model_valid_xml(tmp_path):
    model_dir = write_rig_model(RigConfig(), tmp_path)
    assert (model_dir / "model.config").exists()
    root = ET.parse(model_dir / "model.sdf").getroot()
    assert root.tag == "sdf" and root.get("version") == "1.8"
    assert root.find("model").get("name") == "sensor_rig"


def test_world_requirements_idempotent():
    world = ET.Element("world", name="w")
    # simulate create_world_base's pre-existing plugins
    ET.SubElement(world, "plugin", {"filename": "gz-sim-physics-system",
                                    "name": "gz::sim::systems::Physics"})
    add_world_sensor_requirements(world)
    add_world_sensor_requirements(world)
    plugins = [p.get("name") for p in world.findall("plugin")]
    assert len(plugins) == len(set(plugins)), "duplicated system plugins"
    assert "gz::sim::systems::Sensors" in plugins
    assert len(world.findall("spherical_coordinates")) == 1
    sensors = next(p for p in world.findall("plugin")
                   if p.get("name") == "gz::sim::systems::Sensors")
    assert sensors.find("render_engine").text == "ogre2"


def test_label_plugin_matches_laser_retro_ids():
    # one id space across lidar intensity and segmentation (see core/rig.py)
    from wildseed.config.schema import LASER_RETRO_DEFAULTS
    for cat, retro in LASER_RETRO_DEFAULTS.items():
        assert CLASS_LABELS[cat] == retro


def test_label_plugin_on_include():
    inc = ET.Element("include")
    add_label_plugin(inc, "tree")
    plugin = inc.find("plugin")
    assert plugin.get("name") == "gz::sim::systems::Label"
    assert plugin.find("label").text == "1"
    # unknown categories stay unlabeled rather than crashing
    inc2 = ET.Element("include")
    add_label_plugin(inc2, "spaceship")
    assert inc2.find("plugin") is None


def test_add_rig_include_pose_format():
    world = ET.Element("world")
    add_rig_include(world, RigConfig(), (1, 2, 3, 0, 0, 1.5708))
    inc = world.find("include")
    assert inc.find("uri").text == "model://sensor_rig"
    assert inc.find("pose").text.split()[:3] == ["1.0000", "2.0000", "3.0000"]
