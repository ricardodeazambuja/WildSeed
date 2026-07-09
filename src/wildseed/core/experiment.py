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
from typing import Any, Dict, List, Literal, Optional, Union

import numpy as np
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

# sampler stream tag (curricula): keeps dial sampling on its own SeedSequence
# family, disjoint from every world stage stream by construction.
_SAMPLE_TAG = 0xD1A1_5EED


class DialDist(BaseModel):
    """A distribution over a dial — sampled per world through the master seed.

    Written in a spec as ``structure: {dist: beta, params: [2, 5]}``. Params:
    uniform [lo, hi] (both in [0,1]), normal [mean, sigma] (draw clipped to
    [0,1]; the clip is part of the definition), beta [a, b] (a,b > 0).
    """
    model_config = ConfigDict(extra="forbid")

    dist: Literal["uniform", "normal", "beta"]
    params: List[float]

    @model_validator(mode="after")
    def _params_valid(self):
        p = self.params
        if len(p) != 2:
            raise ValueError(f"{self.dist} needs exactly 2 params, got {p}")
        if self.dist == "uniform":
            lo, hi = p
            if not (0.0 <= lo <= hi <= 1.0):
                raise ValueError(f"uniform params must satisfy 0 <= lo <= hi <= 1, got {p}")
        elif self.dist == "normal":
            mean, sigma = p
            if not 0.0 <= mean <= 1.0:
                raise ValueError(f"normal mean must be in [0,1], got {mean}")
            if sigma <= 0.0:
                raise ValueError(f"normal sigma must be > 0, got {sigma}")
        else:  # beta
            a, b = p
            if a <= 0.0 or b <= 0.0:
                raise ValueError(f"beta params must be > 0, got {p}")
        return self

    def sample(self, rng: np.random.Generator) -> float:
        if self.dist == "uniform":
            return float(rng.uniform(self.params[0], self.params[1]))
        if self.dist == "normal":
            return float(np.clip(rng.normal(self.params[0], self.params[1]),
                                 0.0, 1.0))
        return float(rng.beta(self.params[0], self.params[1]))


DialValue = Union[float, DialDist]


class ExperimentDials(BaseModel):
    """Stressor dials, all optional: a literal 0..1 float, or a DialDist to be
    sampled per world (``wildseed experiment --count N``)."""
    model_config = ConfigDict(extra="forbid")

    structure: Optional[DialValue] = None
    texture: Optional[DialValue] = None
    relief: Optional[DialValue] = None
    variety: Optional[DialValue] = None
    photometric: Optional[DialValue] = None

    @field_validator("*")
    @classmethod
    def _float_in_range(cls, v, info):
        if isinstance(v, (int, float)) and not 0.0 <= float(v) <= 1.0:
            raise ValueError(f"{info.field_name} must be in [0,1], got {v}")
        return v

    def set_items(self) -> Dict[str, float]:
        """Concrete (literal float) dials only."""
        return {k: float(getattr(self, k)) for k in type(self).model_fields
                if isinstance(getattr(self, k), (int, float))}

    def dist_items(self) -> Dict[str, DialDist]:
        """Distribution-valued dials (must be sampled before resolving)."""
        return {k: getattr(self, k) for k in type(self).model_fields
                if isinstance(getattr(self, k), DialDist)}


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
    unsampled = dials.dist_items()
    if unsampled:
        raise ValueError(
            f"dials {sorted(unsampled)} are distributions, not values; sample "
            f"them first: `wildseed experiment --spec <spec> --count N`")
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


def sample_experiments(spec: ExperimentSpec, count: int) -> List[dict]:
    """Draw ``count`` concrete specs from a spec with distribution dials.

    Deterministic in (spec, count) and APPEND-SAFE in count (D1 principle at
    the sampling level): sample i comes from child i of
    ``SeedSequence((_SAMPLE_TAG, spec.seed))``, so growing a curriculum from
    N to M worlds leaves the first N samples byte-identical.

    Each sample draws (in fixed order) its own world seed, then one value per
    distribution dial in field order; literal dials pass through unchanged.
    Works with zero distribution dials too — then it's a seeded replicate
    batch (same dials, fresh world seeds).
    """
    if count < 1:
        raise ValueError(f"count must be >= 1, got {count}")
    dist_dials = spec.dials.dist_items()
    children = np.random.SeedSequence((_SAMPLE_TAG, spec.seed)).spawn(count)
    samples = []
    for i, child in enumerate(children):
        rng = np.random.default_rng(child)
        world_seed = int(rng.integers(0, 2 ** 31 - 1))
        drawn = {}
        for field in ExperimentDials.model_fields:      # fixed draw order
            dist = dist_dials.get(field)
            if dist is not None:
                drawn[field] = round(dist.sample(rng), 4)
        s = spec.model_copy(deep=True)
        s.seed = world_seed
        s.name = f"{spec.name or spec.seed}-k{i:03d}"
        for k, v in drawn.items():
            setattr(s.dials, k, v)
        samples.append({
            "index": i, "name": s.name, "stem": experiment_stem(s),
            "seed": world_seed, "drawn_dials": drawn,
            "dials": s.dials.set_items(), "spec": s,
        })
    return samples


def write_samples(spec: ExperimentSpec, count: int, out_dir: Path,
                  source: Optional[str] = None) -> dict:
    """Write ``count`` sampled spec YAMLs + ``samples.yaml`` manifest.

    Returns the manifest dict (with a ``files`` list of written spec paths).
    Each sampled spec is a plain, self-sufficient experiment spec —
    buildable with ``wildseed experiment --spec`` — and the manifest records
    the distribution definitions plus every drawn value, so the whole batch
    regenerates from the source spec alone.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = sample_experiments(spec, count)
    files = []
    for s in samples:
        data = s["spec"].model_dump(exclude_none=True)
        data["dials"] = s["spec"].dials.set_items()   # drop the None dials
        header = (f"# sampled {s['index'] + 1}/{count} from "
                  f"{source or 'spec'} (master seed {spec.seed}) — "
                  "regenerate with `wildseed experiment --count`\n")
        path = out_dir / f"{s['stem']}.yaml"
        path.write_text(header + yaml.safe_dump(data, sort_keys=False))
        files.append(str(path))
    manifest = {
        "format": 1,
        "experiment": experiment_stem(spec),
        "hypothesis": spec.hypothesis,
        "master_seed": spec.seed,
        "count": count,
        "source_spec": source,
        "dist_dials": {k: v.model_dump()
                       for k, v in spec.dials.dist_items().items()},
        "samples": [{k: s[k] for k in
                     ("index", "name", "stem", "seed", "drawn_dials", "dials")}
                    for s in samples],
        "files": files,
    }
    (out_dir / "samples.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False))
    return manifest
