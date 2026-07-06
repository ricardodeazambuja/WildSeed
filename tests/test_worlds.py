"""world_name_from_file / resolve_world_file: decouple file stem from gz name."""

from pathlib import Path

from wildseed.core.worlds import resolve_world_file, world_name_from_file


def test_reads_internal_world_name(tmp_path):
    """The gz <world name> is read regardless of the file's stem."""
    f = tmp_path / "vio_lio_7.world"
    f.write_text('<?xml version="1.0"?><sdf version="1.9">'
                 '<world name="forest_world"><model name="m"/></world></sdf>')
    assert world_name_from_file(f) == "forest_world"   # NOT "vio_lio_7"


def test_falls_back_to_stem_on_no_name(tmp_path):
    f = tmp_path / "plain.world"
    f.write_text('<?xml version="1.0"?><sdf version="1.9"><world/></sdf>')
    assert world_name_from_file(f) == "plain"


def test_falls_back_to_stem_on_bad_xml(tmp_path):
    f = tmp_path / "broken.world"
    f.write_text("not xml at all <<<")
    assert world_name_from_file(f) == "broken"


def test_falls_back_to_stem_on_missing_file(tmp_path):
    assert world_name_from_file(tmp_path / "nope.world") == "nope"


def test_resolve_world_file_prefers_explicit_path():
    p = resolve_world_file("forest_world", world_file="/x/y/custom.world")
    assert p == Path("/x/y/custom.world")


def test_resolve_world_file_from_stem():
    p = resolve_world_file("vio_lio_7", base_path="/proj")
    assert p == Path("/proj/worlds/vio_lio_7.world")


def test_rtf_bench_uses_world_name_helper():
    """Regression guard: rtf_bench must derive the /stats namespace from the file,
    not assume the file stem == internal world name."""
    src = (Path(__file__).parent.parent / "tools" / "rtf_bench.py").read_text()
    assert "world_name_from_file" in src
    assert "/world/{world_name}/stats" in src
