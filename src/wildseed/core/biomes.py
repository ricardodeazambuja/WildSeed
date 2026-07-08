"""User-defined biomes (YAML) under the testing contract.

Extensibility that preserves scoreability (docs/EXPERIMENT_PLAN.md D6): a
custom biome is accepted ONLY with its VIO/LIO-relevant declarations —
terrain envelope (parallax/relief), ground texture family (aliasing), and the
per-category structure densities (landmark supply). The ground-truth machinery
(instances.json, laser_retro + segmentation labels, passable understory) is
category-level and therefore automatic for any biome that passes the contract.

Two determinism rules:
- custom biomes NEVER join the seed-random biome draw pool (that would shift
  every existing seed->biome mapping); they are selected explicitly with
  ``--biome <name>``.
- the biome file's sha256 is recorded in the scenario record, so a world
  built from a custom biome pins the exact definition it used.

File shape (one or more biomes per file)::

    mangrove:
      presets: [lakeland]                  # terraingen presets to draw from
      knobs: {feature_m: [110, 150], detail: [0.1, 0.2]}
      ground: grassland                    # texture family: grassland|desert|gravel|snow
      water: true
      density: {tree: 90, rock: 20, bush: 140, grass: 200}
      palette_from: wetland                # reuse a manifest palette...
      # palette: {trees: [...], bushes: [...], grasses: [...], rocks: [...]}
      rows:                                # optional structured-row envelopes
        tree: {row_distance: [5, 8], plant_distance: [3.5, 5.5],
               field_size: [60, 95], angle: [0, 3.1416], jitter: [0.08, 0.25],
               missing: [0.03, 0.12], wave_amplitude: [0, 1.5]}
"""

import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from wildseed.config.schema import PRESET_NAMES, TerrainGenConfig

GROUND_FAMILIES = ("grassland", "desert", "gravel", "snow")
PALETTE_KEYS = ("trees", "bushes", "grasses", "rocks")

# terraingen knobs a biome envelope may draw from (numeric TerrainGenConfig
# fields; seed/preset/resolution/pixel come from the scenario, not the biome).
_KNOB_FIELDS = tuple(sorted(
    k for k in TerrainGenConfig.model_fields
    if k not in ("seed", "preset", "resolution", "pixel_m", "valley")))

_ROW_FIELDS = ("row_distance", "plant_distance", "field_size", "angle",
               "jitter", "missing", "wave_amplitude")


class _Range(BaseModel):
    """(lo, hi) envelope; drawn uniformly by the scenario resolver."""
    model_config = ConfigDict(extra="forbid")
    lo: float
    hi: float

    @model_validator(mode="after")
    def _ordered(self):
        if self.hi < self.lo:
            raise ValueError(f"range [{self.lo}, {self.hi}] has hi < lo")
        return self


def _as_range(name: str, v) -> Tuple[float, float]:
    if not (isinstance(v, (list, tuple)) and len(v) == 2):
        raise ValueError(f"{name}: expected [lo, hi], got {v!r}")
    r = _Range(lo=float(v[0]), hi=float(v[1]))
    return (r.lo, r.hi)


class BiomeDef(BaseModel):
    """One custom biome; the contract every field enforces is in the docstring
    above (no field is optional except rows/palette source selection)."""
    model_config = ConfigDict(extra="forbid")

    presets: List[str] = Field(min_length=1)
    knobs: Dict[str, object]
    ground: str
    water: bool
    density: Dict[str, int]
    palette_from: Optional[str] = None
    palette: Optional[Dict[str, List[str]]] = None
    rows: Dict[str, Dict[str, object]] = Field(default_factory=dict)

    @field_validator("presets")
    @classmethod
    def _presets_known(cls, v):
        bad = [p for p in v if p not in PRESET_NAMES]
        if bad:
            raise ValueError(f"unknown preset(s) {bad}; expected from {PRESET_NAMES}")
        return v

    @field_validator("ground")
    @classmethod
    def _ground_known(cls, v):
        if v not in GROUND_FAMILIES:
            raise ValueError(f"unknown ground family {v!r}; expected one of "
                             f"{GROUND_FAMILIES} (the aliasing lever needs a "
                             "known texture family)")
        return v

    @field_validator("density")
    @classmethod
    def _density_contract(cls, v):
        missing = [c for c in ("tree", "rock", "bush", "grass") if c not in v]
        if missing:
            raise ValueError(
                f"density must declare every category (missing {missing}) — "
                "the structure densities are the biome's landmark-supply "
                "declaration; use 0 for 'none', don't omit")
        bad = {k: n for k, n in v.items() if n < 0}
        if bad:
            raise ValueError(f"negative densities: {bad}")
        return v

    @field_validator("knobs")
    @classmethod
    def _knobs_known(cls, v):
        out = {}
        for k, rng in v.items():
            if k not in _KNOB_FIELDS:
                raise ValueError(f"unknown terrain knob {k!r}; expected from "
                                 f"{_KNOB_FIELDS}")
            out[k] = _as_range(f"knobs.{k}", rng)
        return out

    @field_validator("rows")
    @classmethod
    def _rows_known(cls, v):
        out = {}
        for cat, envelope in v.items():
            drawn = {}
            for k, rng in envelope.items():
                if k not in _ROW_FIELDS:
                    raise ValueError(f"unknown row param {k!r}; expected from "
                                     f"{_ROW_FIELDS}")
                drawn[k] = _as_range(f"rows.{cat}.{k}", rng)
            out[cat] = drawn
        return out

    @model_validator(mode="after")
    def _palette_contract(self):
        if bool(self.palette_from) == bool(self.palette):
            raise ValueError(
                "declare exactly one of palette_from (reuse a manifest biome's "
                "palette) or palette (explicit model ids) — a biome without a "
                "palette cannot place labelled instances")
        if self.palette is not None:
            bad = [k for k in self.palette if k not in PALETTE_KEYS]
            if bad:
                raise ValueError(f"unknown palette key(s) {bad}; expected {PALETTE_KEYS}")
            if not any(self.palette.get(k) for k in PALETTE_KEYS):
                raise ValueError("explicit palette lists no models at all")
        return self

    def to_space(self) -> dict:
        """The BIOME_SPACE-shaped dict the scenario resolver consumes."""
        space = {
            "presets": tuple(self.presets),
            "knobs": dict(self.knobs),
            "ground": self.ground,
            "water": self.water,
            "density": dict(self.density),
        }
        if self.rows:
            space["rows"] = {c: dict(env) for c, env in self.rows.items()}
        if self.palette is not None:
            space["palette_source"] = {"explicit": {k: list(self.palette.get(k, []))
                                                    for k in PALETTE_KEYS}}
        else:
            space["palette_source"] = {"manifest_biome": self.palette_from}
        return space


def load_biome_file(path: Path) -> Tuple[Dict[str, dict], dict]:
    """Load + validate a biome YAML. Returns (name -> space dict, provenance).

    Names must not collide with built-ins (silent redefinition of a shipped
    biome would poison seed provenance).
    """
    from wildseed.core.scenario import BIOME_NAMES
    path = Path(path)
    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected a mapping of biome name -> definition")
    spaces = {}
    for name, body in data.items():
        if name in BIOME_NAMES:
            raise ValueError(f"{path}: {name!r} collides with a built-in biome; "
                             "pick a new name (built-ins are not redefinable)")
        if not isinstance(body, dict):
            raise ValueError(f"{path}: biome {name!r} is not a mapping")
        try:
            spaces[name] = BiomeDef(**body).to_space()
        except Exception as e:
            raise ValueError(f"{path}: biome {name!r} fails the contract: {e}")
    provenance = {"path": str(path),
                  "sha256": hashlib.sha256(raw).hexdigest(),
                  "biomes": sorted(spaces)}
    return spaces, provenance
