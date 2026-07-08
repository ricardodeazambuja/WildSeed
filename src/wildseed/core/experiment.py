"""Experiment spec: hypothesis + stressor dials -> one reproducible world.

The researcher-facing layer over the master-seed scenario pipeline
(docs/EXPERIMENT_PLAN.md D2/D3). A spec YAML names the *stress condition*
(dials that map to measured VIO/LIO failure modes), records the hypothesis the
world exists to test, and resolves — via the master seed — into the exact
world that applies that stress. The resolved record written next to the world
carries the spec verbatim plus every drawn value and the provenance hashes, so
one file regenerates and pins the condition.

Dial -> lever mappings (evidence in docs/GROUND_CLUTTER.md):

    structure    0..1 -> object_density = round(250 * d); 0.7 puts the budget
                 at ~175, the measured VIO saturation point (option c).
    texture      0..1 -> ground compositor mode: <0.5 uniform (the measured
                 aliasing worst case), >=0.5 patchy (de-aliased).
    relief       0..1 -> vio_lio macro relief under the drivable slope cap.
    variety      0..1 -> vio_lio uniqueness dial (recolour variants etc.).
    photometric  0..1 -> sun stress: elevation 55->5 deg, intensity 1->5x,
                 emissive sun disk at >=0.75; azimuth seeded + recorded.

structure/texture/relief/variety act through the vio_lio profile (where they
were measured); photometric/weather apply on both the profile and biome paths.
"""

import inspect
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import (BaseModel, ConfigDict, Field, field_validator,
                      model_validator)

from wildseed.core.scenario import (BIOME_NAMES, PROFILE_NAMES,
                                    resolve_scenario)

# structure dial budget: 250 at dial 1.0 puts the measured saturation (~175)
# at dial 0.7 with headroom above it to demonstrate the RTF-only regime.
STRUCTURE_BUDGET = 250

# Benchmarks a spec may request (consumed by `wildseed sweep`; names match the
# `wildseed benchmark` subcommands).
BENCH_NAMES = ("vio", "lidar", "rtf")

_PROFILE_DIALS = ("structure", "texture", "relief", "variety")


class ExperimentDials(BaseModel):
    """Stressor dials, all 0..1, all optional (unset = pipeline default)."""
    model_config = ConfigDict(extra="forbid")

    structure: Optional[float] = Field(None, ge=0.0, le=1.0)
    texture: Optional[float] = Field(None, ge=0.0, le=1.0)
    relief: Optional[float] = Field(None, ge=0.0, le=1.0)
    variety: Optional[float] = Field(None, ge=0.0, le=1.0)
    photometric: Optional[float] = Field(None, ge=0.0, le=1.0)

    def set_items(self) -> Dict[str, float]:
        return {k: v for k, v in self.model_dump().items() if v is not None}


class ExperimentSpec(BaseModel):
    """One experiment = one hypothesis + one stress condition + one seed."""
    model_config = ConfigDict(extra="forbid")

    hypothesis: str = Field(min_length=1,
                            description="What this world exists to test.")
    seed: int
    name: Optional[str] = Field(
        None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
        description="Output stem suffix (exp_<name>); default exp_<seed>.")
    profile: Optional[str] = "vio_lio"
    biome: Optional[str] = None
    biome_file: Optional[str] = None
    preset: Optional[str] = None
    dials: ExperimentDials = Field(default_factory=ExperimentDials)
    weather: Optional[str] = None
    overrides: Dict[str, Any] = Field(default_factory=dict)
    benchmark: List[str] = Field(default_factory=list)

    @field_validator("profile")
    @classmethod
    def _profile_known(cls, v):
        if v is not None and v not in PROFILE_NAMES:
            raise ValueError(f"unknown profile {v!r}; expected one of "
                             f"{PROFILE_NAMES} or null")
        return v

    @model_validator(mode="after")
    def _biome_known(self):
        # with a biome_file the name may be custom; resolve validates it then
        if (self.biome is not None and self.biome_file is None
                and self.biome not in BIOME_NAMES):
            raise ValueError(f"unknown biome {self.biome!r}; expected one of "
                             f"{BIOME_NAMES} (or set biome_file)")
        return self

    @field_validator("benchmark")
    @classmethod
    def _bench_known(cls, v):
        bad = [b for b in v if b not in BENCH_NAMES]
        if bad:
            raise ValueError(f"unknown benchmark(s) {bad}; expected from {BENCH_NAMES}")
        return v


def experiment_stem(spec: ExperimentSpec) -> str:
    """Output stem: exp_<name|seed>. The exp_ prefix keeps generated DEM/world
    artifacts on the gitignore's radar and out of the scenario_* namespace."""
    return f"exp_{spec.name or spec.seed}"


def load_experiment(path: Path) -> ExperimentSpec:
    """Load + validate an experiment spec YAML (pydantic errors propagate).

    A relative ``biome_file`` resolves against the spec file's directory
    (specs and their biome files travel together)."""
    path = Path(path)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping, got {type(data).__name__}")
    spec = ExperimentSpec(**data)
    if spec.biome_file and not Path(spec.biome_file).is_absolute():
        sibling = path.parent / spec.biome_file
        if sibling.exists():
            spec.biome_file = str(sibling)
    return spec


def resolve_experiment(spec: ExperimentSpec) -> dict:
    """Resolve a spec into the full scenario dict (deterministic in the spec).

    Dial mapping happens here; ``overrides`` are raw resolve_scenario kwargs
    applied AFTER the dials (the recorded escape hatch — an override of a
    dial-controlled knob wins and is visible in the record).
    """
    dials = spec.dials
    profile_set = {k: v for k, v in dials.set_items().items()
                   if k in _PROFILE_DIALS}
    if spec.profile is None and profile_set:
        raise ValueError(
            f"dials {sorted(profile_set)} act through the vio_lio profile "
            f"(where they were measured); set profile: vio_lio or drop them")

    kwargs: Dict[str, Any] = dict(
        seed=spec.seed, biome=spec.biome, preset=spec.preset,
        profile=spec.profile, photometric=dials.photometric,
        weather=spec.weather)
    biome_prov = None
    if spec.biome_file:
        from wildseed.core.biomes import load_biome_file
        kwargs["extra_biomes"], biome_prov = load_biome_file(Path(spec.biome_file))
    if dials.structure is not None:
        kwargs["object_density"] = int(round(STRUCTURE_BUDGET * dials.structure))
    if dials.texture is not None:
        kwargs["texture"] = float(dials.texture)
    if dials.relief is not None:
        kwargs["relief"] = float(dials.relief)
    if dials.variety is not None:
        kwargs["variety"] = float(dials.variety)

    allowed = set(inspect.signature(resolve_scenario).parameters) - {"seed"}
    for key, value in spec.overrides.items():
        if key not in allowed:
            raise ValueError(f"override {key!r} is not a scenario knob; "
                             f"allowed: {sorted(allowed)}")
        kwargs[key] = value

    resolved = resolve_scenario(**kwargs)
    resolved["experiment"] = {
        "name": experiment_stem(spec),
        "hypothesis": spec.hypothesis,
        "dials": dials.set_items(),
        "weather": spec.weather,
        "overrides": dict(spec.overrides),
        "benchmark": list(spec.benchmark),
    }
    if biome_prov:
        resolved["biome_file"] = biome_prov
    return resolved
