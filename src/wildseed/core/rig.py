"""Sensor rig generation (docs/SENSOR_RIG.md).

Generates the ``sensor_rig`` Gazebo model — a floating multi-sensor body used to
test generated worlds and record demos — plus the world-level requirements the
rig's sensors need (system plugins, spherical coordinates).

Everything here reproduces what the Phase-0 spike (worlds/sensor_spike.world)
verified 13/13 on gz Harmonic / ogre2 / EGL, including its hard-won gotchas:
gpu_lidar reads ``laser_retro`` from visuals; segmentation labels_map carries the
class label in channel 2; the magnetometer publishes the WMM field (in Gauss)
derived from ``<spherical_coordinates>``.
"""

from pathlib import Path
from typing import Optional, Tuple
from xml.etree import ElementTree as ET

from pydantic import BaseModel, Field

# One id space shared by BOTH semantic channels: segmentation class labels and
# lidar laser_retro intensities use the same per-category value (tree=1 ... ),
# so cross-sensor ground truth needs no mapping table. Categories the lidar
# can't label (retro is baked at asset conversion; ground/water models predate
# it) still get a segmentation label here.
CLASS_LABELS = {
    "tree": 1, "bush": 2, "rock": 3, "grass": 4, "sand": 5,
    "ground": 6, "water": 7,
    # runtime-spawned kinematic movers (`wildseed record --distractors`):
    # a DEDICATED class so per-frame motion masks are a plain label==8 test
    # on the segmentation stream, no instance bookkeeping needed.
    "distractor": 8,
}


class CameraSpec(BaseModel):
    width: int = 640
    height: int = 480
    fov: float = Field(default=1.0, description="horizontal FOV, radians")
    rate: float = 10.0
    far: float = 2000.0


class LidarSpec(BaseModel):
    enabled: bool = True
    channels: int = 16
    samples: int = 360
    vertical_min: float = -0.7
    vertical_max: float = 0.26
    range_max: float = 150.0
    rate: float = 10.0


class RigConfig(BaseModel):
    """Sensor rig configuration (YAML-friendly; all defaults spike-verified)."""

    name: str = "sensor_rig"
    topic_prefix: str = "rig"
    mass: float = 2.0

    camera: CameraSpec = CameraSpec()
    stereo_baseline: float = Field(
        default=0.12, ge=0.0,
        description="stereo baseline, metres; 0 disables the right camera")
    rgbd: bool = True
    rgbd_far: float = 500.0
    wideangle: bool = True
    wideangle_fov: float = 3.0
    segmentation: bool = True
    segmentation_type: str = "instance"
    lidar: LidarSpec = LidarSpec()
    imu_rate: float = 100.0
    navsat_rate: float = 5.0
    air_pressure_rate: float = 10.0
    magnetometer_rate: float = 10.0
    odometry_rate: float = 50.0
    reference_altitude: float = Field(
        default=600.0, description="baro reference + navsat elevation, metres")


# world origin used everywhere a rig world needs georeferencing (spike-verified)
DEFAULT_LATITUDE = 57.0271155
DEFAULT_LONGITUDE = -115.426770


def rig_topics(config: RigConfig) -> dict:
    """Expected gz topics for a generated rig (single source of truth)."""
    p = config.topic_prefix
    topics = {
        "cam_left": f"{p}/cam_left",
        "imu": f"{p}/imu",
        "navsat": f"{p}/navsat",
        "air_pressure": f"{p}/air_pressure",
        "magnetometer": f"{p}/magnetometer",
        "odometry": f"/model/{config.name}/odometry",
    }
    if config.stereo_baseline > 0:
        topics["cam_right"] = f"{p}/cam_right"
    if config.rgbd:
        topics["rgbd_rgb"] = f"{p}/rgbd/image"
        topics["rgbd_depth"] = f"{p}/rgbd/depth_image"
    if config.wideangle:
        topics["wideangle"] = f"{p}/wideangle"
    if config.segmentation:
        topics["segmentation"] = f"{p}/segmentation/labels_map"
        topics["seg_colored"] = f"{p}/segmentation/colored_map"
    if config.lidar.enabled:
        topics["lidar_points"] = f"{p}/lidar/points"
    return topics


def _sensor(link: ET.Element, name: str, stype: str, topic: str, rate: float,
            pose: str = "0 0 0 0 0 0") -> ET.Element:
    s = ET.SubElement(link, "sensor", {"name": name, "type": stype})
    ET.SubElement(s, "pose").text = pose
    ET.SubElement(s, "topic").text = topic
    ET.SubElement(s, "always_on").text = "1"
    ET.SubElement(s, "update_rate").text = f"{rate:g}"
    return s


def _camera_block(sensor: ET.Element, spec: CameraSpec, far: float,
                  fov: Optional[float] = None) -> ET.Element:
    cam = ET.SubElement(sensor, "camera")
    ET.SubElement(cam, "horizontal_fov").text = f"{fov if fov else spec.fov:g}"
    image = ET.SubElement(cam, "image")
    ET.SubElement(image, "width").text = str(spec.width)
    ET.SubElement(image, "height").text = str(spec.height)
    clip = ET.SubElement(cam, "clip")
    ET.SubElement(clip, "near").text = "0.1"
    ET.SubElement(clip, "far").text = f"{far:g}"
    return cam


def _body_visuals(link: ET.Element) -> None:
    """Quad-style body from primitives: no mesh files, no Blender dependency."""
    body = ET.SubElement(link, "visual", {"name": "body"})
    geo = ET.SubElement(body, "geometry")
    box = ET.SubElement(geo, "box")
    ET.SubElement(box, "size").text = "0.30 0.30 0.10"
    mat = ET.SubElement(body, "material")
    ET.SubElement(mat, "ambient").text = "0.15 0.15 0.15 1"
    ET.SubElement(mat, "diffuse").text = "0.15 0.15 0.15 1"
    for i, (dx, dy) in enumerate([(0.2, 0.2), (0.2, -0.2), (-0.2, 0.2), (-0.2, -0.2)]):
        rotor = ET.SubElement(link, "visual", {"name": f"rotor_{i}"})
        ET.SubElement(rotor, "pose").text = f"{dx} {dy} 0.06 0 0 0"
        geo = ET.SubElement(rotor, "geometry")
        cyl = ET.SubElement(geo, "cylinder")
        ET.SubElement(cyl, "radius").text = "0.12"
        ET.SubElement(cyl, "length").text = "0.02"
        mat = ET.SubElement(rotor, "material")
        ET.SubElement(mat, "ambient").text = "0.4 0.4 0.45 1"
        ET.SubElement(mat, "diffuse").text = "0.4 0.4 0.45 1"
    # lidar mast: top at 0.42 so the sensor origin (0.45) sits clear of it —
    # a downward ray leaves the 0.012 radius within ~8 mm of the origin
    mast = ET.SubElement(link, "visual", {"name": "mast"})
    ET.SubElement(mast, "pose").text = "0 0 0.235 0 0 0"
    geo = ET.SubElement(mast, "geometry")
    cyl = ET.SubElement(geo, "cylinder")
    ET.SubElement(cyl, "radius").text = "0.012"
    ET.SubElement(cyl, "length").text = "0.37"
    mat = ET.SubElement(mast, "material")
    ET.SubElement(mat, "ambient").text = "0.15 0.15 0.15 1"
    ET.SubElement(mat, "diffuse").text = "0.15 0.15 0.15 1"


def build_rig_model(config: RigConfig) -> ET.Element:
    """Build the rig ``<model>`` element (embeddable in an <sdf> or a world)."""
    p = config.topic_prefix
    model = ET.Element("model", {"name": config.name})

    odom = ET.SubElement(model, "plugin", {
        "filename": "gz-sim-odometry-publisher-system",
        "name": "gz::sim::systems::OdometryPublisher"})
    ET.SubElement(odom, "odom_frame").text = "world"
    ET.SubElement(odom, "robot_base_frame").text = config.name
    ET.SubElement(odom, "dimensions").text = "3"
    ET.SubElement(odom, "odom_publish_frequency").text = f"{config.odometry_rate:g}"

    link = ET.SubElement(model, "link", {"name": "base"})
    # gravity off: the same body works kinematically (set_pose, Phase 2) and
    # dynamically (ApplyLinkWrench w/ explicit gravity compensation, Phase 4)
    ET.SubElement(link, "gravity").text = "false"
    inertial = ET.SubElement(link, "inertial")
    ET.SubElement(inertial, "mass").text = f"{config.mass:g}"
    inertia = ET.SubElement(inertial, "inertia")
    for k, v in [("ixx", 0.02), ("iyy", 0.02), ("izz", 0.02),
                 ("ixy", 0), ("ixz", 0), ("iyz", 0)]:
        ET.SubElement(inertia, k).text = f"{v:g}"

    _body_visuals(link)

    # Mounts (measured, not guessed): cameras on the front-bottom, clear of the
    # body box (0.30 wide) and the rotor disks (z=+0.06, radial 0.16..0.40) —
    # a first render showed a rotor filling the frame corner from a body-center
    # mount. rgbd + segcam sit exactly at cam_left's pose so RGB/depth/labels
    # are pixel-paired ground truth.
    cam_mount_x, cam_mount_z = 0.20, -0.08
    half_b = config.stereo_baseline / 2.0
    left_pose = f"{cam_mount_x:g} {half_b:g} {cam_mount_z:g} 0 0 0"
    s = _sensor(link, "cam_left", "camera", f"{p}/cam_left", config.camera.rate,
                pose=left_pose)
    _camera_block(s, config.camera, config.camera.far)
    if config.stereo_baseline > 0:
        s = _sensor(link, "cam_right", "camera", f"{p}/cam_right",
                    config.camera.rate,
                    pose=f"{cam_mount_x:g} {-half_b:g} {cam_mount_z:g} 0 0 0")
        _camera_block(s, config.camera, config.camera.far)

    if config.rgbd:
        s = _sensor(link, "rgbd", "rgbd_camera", f"{p}/rgbd", config.camera.rate,
                    pose=left_pose)
        _camera_block(s, config.camera, config.rgbd_far)

    if config.wideangle:
        # fisheye sees the rotors at the frame edge — that's what a real
        # drone's wide-angle records too; deliberate.
        s = _sensor(link, "wideangle", "wideanglecamera", f"{p}/wideangle",
                    config.camera.rate,
                    pose=f"{cam_mount_x:g} 0 {cam_mount_z:g} 0 0 0")
        cam = _camera_block(s, config.camera, config.camera.far,
                            fov=config.wideangle_fov)
        lens = ET.SubElement(cam, "lens")
        ET.SubElement(lens, "type").text = "equidistant"
        ET.SubElement(lens, "scale_to_hfov").text = "true"
        ET.SubElement(lens, "cutoff_angle").text = "1.5"

    if config.segmentation:
        s = _sensor(link, "segcam", "segmentation", f"{p}/segmentation", 5,
                    pose=left_pose)
        cam = _camera_block(s, config.camera, config.rgbd_far)
        seg_type = ET.SubElement(cam, "segmentation_type")
        seg_type.text = config.segmentation_type
        # element order: segmentation_type must come first for readability only
        cam.remove(seg_type)
        cam.insert(0, seg_type)

    if config.lidar.enabled:
        # top of the mast: from z=0.45 a ray at the default steepest depression
        # (0.7 rad) crosses the rotor plane at radial 0.45 m, beyond the disks'
        # outer edge (0.40 m) — no self-hits
        s = _sensor(link, "lidar", "gpu_lidar", f"{p}/lidar",
                    config.lidar.rate, pose="0 0 0.45 0 0 0")
        lidar = ET.SubElement(s, "lidar")
        scan = ET.SubElement(lidar, "scan")
        horizontal = ET.SubElement(scan, "horizontal")
        ET.SubElement(horizontal, "samples").text = str(config.lidar.samples)
        ET.SubElement(horizontal, "resolution").text = "1"
        ET.SubElement(horizontal, "min_angle").text = "-3.14159"
        ET.SubElement(horizontal, "max_angle").text = "3.14159"
        vertical = ET.SubElement(scan, "vertical")
        ET.SubElement(vertical, "samples").text = str(config.lidar.channels)
        ET.SubElement(vertical, "resolution").text = "1"
        ET.SubElement(vertical, "min_angle").text = f"{config.lidar.vertical_min:g}"
        ET.SubElement(vertical, "max_angle").text = f"{config.lidar.vertical_max:g}"
        rng = ET.SubElement(lidar, "range")
        ET.SubElement(rng, "min").text = "0.1"
        ET.SubElement(rng, "max").text = f"{config.lidar.range_max:g}"
        ET.SubElement(rng, "resolution").text = "0.01"

    _sensor(link, "imu", "imu", f"{p}/imu", config.imu_rate)
    _sensor(link, "navsat", "navsat", f"{p}/navsat", config.navsat_rate)
    s = _sensor(link, "air_pressure", "air_pressure", f"{p}/air_pressure",
                config.air_pressure_rate)
    ap = ET.SubElement(s, "air_pressure")
    ET.SubElement(ap, "reference_altitude").text = f"{config.reference_altitude:g}"
    _sensor(link, "magnetometer", "magnetometer", f"{p}/magnetometer",
            config.magnetometer_rate)

    return model


def write_rig_model(config: RigConfig, models_path: Path,
                    calib_dial: Optional[float] = None,
                    calib_seed: int = 0) -> Path:
    """Write models/<name>/{model.config,model.sdf}; returns the model dir.

    ``calib_dial`` (0..1) applies the seeded calibration perturbation (mount
    extrinsics, camera FOV/fx, IMU noise — see core.calib) and exports the
    TRUE drawn values to ``rig_calibration.json`` in the model dir. 0 leaves
    the SDF untouched but still exports the nominal calibration."""
    model_dir = Path(models_path) / config.name
    model_dir.mkdir(parents=True, exist_ok=True)

    model_el = build_rig_model(config)
    if calib_dial is not None:
        from wildseed.core.calib import perturb_rig_model, write_calibration
        truth = perturb_rig_model(model_el, calib_dial, calib_seed)
        write_calibration(model_dir, truth)

    sdf_root = ET.Element("sdf", version="1.8")
    sdf_root.append(model_el)
    tree = ET.ElementTree(sdf_root)
    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    tree.write(str(model_dir / "model.sdf"), encoding="utf-8",
               xml_declaration=True)

    (model_dir / "model.config").write_text(f"""<?xml version="1.0"?>
<model>
    <name>{config.name}</name>
    <version>1.0</version>
    <sdf version="1.8">model.sdf</sdf>
    <description>WildSeed sensor rig (generated by `wildseed rig`)</description>
</model>""")
    return model_dir


def add_world_sensor_requirements(
        world: ET.Element,
        latitude: float = DEFAULT_LATITUDE,
        longitude: float = DEFAULT_LONGITUDE,
        elevation: float = 600.0) -> None:
    """Add the system plugins + georeference the rig's sensors need.

    Idempotent: skips anything already present (worlds built by
    create_world_base already carry Physics/UserCommands/SceneBroadcaster).
    """
    have = {p.get("name") for p in world.findall("plugin")}
    needed = [
        ("gz-sim-physics-system", "gz::sim::systems::Physics", None),
        ("gz-sim-user-commands-system", "gz::sim::systems::UserCommands", None),
        ("gz-sim-scene-broadcaster-system", "gz::sim::systems::SceneBroadcaster", None),
        ("gz-sim-sensors-system", "gz::sim::systems::Sensors", "ogre2"),
        ("gz-sim-imu-system", "gz::sim::systems::Imu", None),
        ("gz-sim-navsat-system", "gz::sim::systems::NavSat", None),
        ("gz-sim-air-pressure-system", "gz::sim::systems::AirPressure", None),
        ("gz-sim-magnetometer-system", "gz::sim::systems::Magnetometer", None),
        ("gz-sim-apply-link-wrench-system", "gz::sim::systems::ApplyLinkWrench", None),
    ]
    for filename, name, render_engine in needed:
        if name in have:
            continue
        plugin = ET.SubElement(world, "plugin",
                               {"filename": filename, "name": name})
        if render_engine:
            ET.SubElement(plugin, "render_engine").text = render_engine

    if world.find("spherical_coordinates") is None:
        sc = ET.SubElement(world, "spherical_coordinates")
        ET.SubElement(sc, "surface_model").text = "EARTH_WGS84"
        ET.SubElement(sc, "world_frame_orientation").text = "ENU"
        ET.SubElement(sc, "latitude_deg").text = f"{latitude:.7f}"
        ET.SubElement(sc, "longitude_deg").text = f"{longitude:.6f}"
        ET.SubElement(sc, "elevation").text = f"{elevation:g}"
        ET.SubElement(sc, "heading_deg").text = "0"


def add_label_plugin(element: ET.Element, category: str) -> None:
    """Attach the gz Label system so segmentation cameras see this model.

    Works inside ``<include>`` and ``<model>`` alike (spike-verified, including
    on MASK-foliage models). Unknown categories are left unlabeled (render 0).
    """
    label = CLASS_LABELS.get(category)
    if label is None:
        return
    plugin = ET.SubElement(element, "plugin", {
        "filename": "gz-sim-label-system", "name": "gz::sim::systems::Label"})
    ET.SubElement(plugin, "label").text = str(label)


def add_rig_include(world: ET.Element, config: RigConfig,
                    pose: Tuple[float, float, float, float, float, float]) -> None:
    """Include the generated rig model in a world at the given pose."""
    include = ET.SubElement(world, "include")
    ET.SubElement(include, "uri").text = f"model://{config.name}"
    ET.SubElement(include, "name").text = config.name
    ET.SubElement(include, "pose").text = " ".join(f"{v:.4f}" for v in pose)


def inject_rig_into_world(world_path: Path, config: RigConfig,
                          models_path: Path,
                          rig_pose: Optional[Tuple[float, ...]] = None,
                          shell_only: bool = False,
                          labels: bool = True) -> Path:
    """Retrofit an EXISTING world file with the rig + everything it needs.

    Idempotent: adds the sensor system plugins, spherical coordinates,
    per-include class labels (category from the ``model://<cat>/...`` uri)
    and the rig include only where missing. The rig model itself is
    (re)generated under ``models_path``. Default pose: above the first
    include's position or the origin, 25 m up — pass ``rig_pose`` for
    anything camera-worthy.

    ``shell_only=True`` injects the world-shell (system plugins, spherical
    coordinates, labels) but neither the rig include nor the rig model —
    for worlds that host an externally spawned robot instead of the rig.

    ``labels=False`` skips adding the per-include Label plugins — for worlds
    whose consumer has no segmentation camera, where thousands of Label
    systems are pure per-entity overhead (e.g. an external UGV robot).
    Existing labels are left untouched (strip them consumer-side if needed).
    """
    world_path = Path(world_path)
    tree = ET.parse(world_path)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        raise ValueError(f"no <world> element in {world_path}")

    add_world_sensor_requirements(world)
    if not shell_only:
        write_rig_model(config, models_path)

        for inc in world.findall("include"):
            name = inc.findtext("name") or ""
            if name == config.name:
                break   # rig already present; labels below stay idempotent
        else:
            if rig_pose is None:
                rig_pose = (0.0, 0.0, 40.0, 0.0, 0.0, 0.0)
            add_rig_include(world, config, tuple(rig_pose))

    if labels:
        for inc in world.findall("include"):
            uri = inc.findtext("uri") or ""
            if not uri.startswith("model://") or uri == f"model://{config.name}":
                continue
            has_label = any(p.get("name") == "gz::sim::systems::Label"
                            for p in inc.findall("plugin"))
            if not has_label:
                category = uri[len("model://"):].split("/")[0]
                add_label_plugin(inc, category)

    try:
        ET.indent(tree, space="    ")
    except AttributeError:
        pass
    tree.write(str(world_path), encoding="utf-8", xml_declaration=True)
    return world_path
