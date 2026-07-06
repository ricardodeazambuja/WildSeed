"""Small helpers for locating a world and its internal gz name.

A gz world file's *internal* ``<world name="...">`` need not match its file name —
``wildseed scenario`` names every world's SDF ``forest_world`` regardless of the
output file (``scenario_7.world``, ``vio_lio_7.world``, …). Tools that subscribe to
a world-scoped topic (``/world/<name>/stats``) must use the INTERNAL name, while
the user only knows the FILE. These helpers bridge the two so a command can take a
file stem and still talk to the right topics.
"""

from pathlib import Path
from xml.etree import ElementTree as ET


def world_name_from_file(world_file) -> str:
    """Return the ``<world name>`` inside a .world file (fallback: the file stem).

    Used to derive the ``/world/<name>/…`` topic namespace from a world the user
    referenced by file. Any parse failure falls back to the file stem, so a plain
    ``forest_world.world`` keeps working unchanged.
    """
    path = Path(world_file)
    try:
        root = ET.parse(str(path)).getroot()
        world = root.find("world") if root.tag != "world" else root
        name = world.get("name") if world is not None else None
        if name:
            return name
    except (ET.ParseError, OSError, AttributeError):
        pass
    return path.stem


def resolve_world_file(world: str, world_file=None, base_path=".") -> Path:
    """Resolve a world reference to a .world path.

    ``world_file`` (explicit path) wins; otherwise ``world`` is treated as a file
    stem under ``<base_path>/worlds/``. The returned path is not guaranteed to
    exist — callers report their own missing-file error.
    """
    if world_file:
        return Path(world_file)
    return Path(base_path) / "worlds" / f"{world}.world"
