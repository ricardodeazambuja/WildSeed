"""Backward-compat + resolution tests for per-category conversion config (P0 fork).

Run inside the container:
  docker run --rm -v "$PWD:/workspace" --entrypoint python3 forest3d:egl \
    -m pytest /workspace/tests/test_category_config.py -q
"""

from forest3d.config.schema import BlenderConfig, CategoryConfig


def test_empty_categories_reproduces_legacy_defaults():
    """No per-category entries -> legacy blanket behaviour, unchanged."""
    cfg = BlenderConfig()
    r = cfg.resolve_category("tree")
    assert r.visual_decimation == 0.1          # global default
    assert r.collision_decimation == 0.01      # global default
    assert r.collision_strategy == "mesh"      # legacy decimated-mesh collision
    assert r.skip_foliage_decimation is False


def test_unset_category_fields_fall_back_to_global():
    cfg = BlenderConfig(
        visual_decimation=0.2,
        collision_decimation=0.05,
        categories={"rock": CategoryConfig(collision_strategy="convex_hull")},
    )
    r = cfg.resolve_category("rock")
    # only strategy overridden; ratios fall back to the (custom) globals
    assert r.visual_decimation == 0.2
    assert r.collision_decimation == 0.05
    assert r.collision_strategy == "convex_hull"


def test_category_overrides_apply():
    cfg = BlenderConfig(
        categories={
            "tree": CategoryConfig(
                visual_decimation=1.0,
                skip_foliage_decimation=True,
                collision_strategy="trunk_cylinder",
            )
        }
    )
    r = cfg.resolve_category("tree")
    assert r.visual_decimation == 1.0
    assert r.skip_foliage_decimation is True
    assert r.collision_strategy == "trunk_cylinder"
    # an unconfigured category still gets legacy defaults
    assert cfg.resolve_category("bush").collision_strategy == "mesh"


def test_invalid_strategy_rejected():
    import pytest
    with pytest.raises(ValueError):
        CategoryConfig(collision_strategy="banana")
