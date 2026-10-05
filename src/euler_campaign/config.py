"""YAML configuration I/O for Barton categories and Euler campaign cases.

The catalog root contains ``categories`` with category_id, parameter,
description, lower_value, and upper_value fields. A case contains case_id,
domain, joint_sets, boreholes, and tunnel. Joint-set orientation is input as
mean_dip and mean_dip_dir; the internal normal vector is derived. Each condition stores
``jr_category`` and ``ja_category`` IDs from that separately supplied catalog.
Legacy Jr/Ja normal-distribution fields are rejected rather than converted.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from math import isfinite
from pathlib import Path, PurePosixPath
import re
from string import Formatter
from typing import Any, Literal

import numpy as np
import yaml

from .campaign import (
    CampaignPlan,
    CampaignState,
    _plan_fingerprint,
    _validate_state,
    validate_plan,
)
from .coverage import CoverageGrid, validate_grid
from .euler import FeatureBound
from .models import (
    BartonCategory,
    BoreholeSpec,
    CaseSpec,
    DomainSpec,
    JointCondition,
    JointSetSpec,
    Signature,
    TunnelSpec,
    identify_signature,
    validate_case,
)

_LEGACY_CATEGORY_FIELDS = frozenset({"Jr_mean", "Jr_std", "Ja_mean", "Ja_std"})
_CAMPAIGN_SCHEMA_VERSION = 1
_PRIMARY_GRID_ID = "primary_profile_10bin_v1"
_PRIMARY_GRID_DEFINITION = (
    "geomspace(0.1, 400.0, 11), replacing the first edge with 0.0"
)
_STOP_POLICY = {
    "coverage": "all_primary_bins_observed",
    "when_lineage_saturates": "try_next_start",
    "when_all_lineages_saturate": (
        "await_explicit_start_extension_with_remaining_gaps"
    ),
}
_FIXED_EXECUTION_SETTINGS = {
    "backend": "mlx",
    "gpu_required": True,
    "cpu_fallback": False,
    "device_policy": "apple_silicon_mlx_gpu",
    "record_actual_device_and_runtime_fingerprint": True,
    "result_role": "coverage_exploration_only",
    "include_in_calibration": False,
    "include_in_validation": False,
}


@dataclass(frozen=True)
class CampaignProject:
    """Validated, portable campaign YAML inputs and their execution plan."""

    plan: CampaignPlan
    base_case: str
    category_catalog: str
    plan_revision: int
    parent_revision: int | None
    parent_plan_fingerprint: str | None
    round_budget: int | None
    output_path_template: str


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be a mapping with string keys")
    return value


def _fields(
    value: Any, name: str, required: set[str], optional: set[str] | None = None,
) -> dict[str, Any]:
    mapping = _mapping(value, name)
    optional_fields = optional or set()
    missing = required - mapping.keys()
    unknown = mapping.keys() - required - optional_fields
    if missing:
        raise ValueError(f"{name} is missing required fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{name} has unknown fields: {sorted(unknown)}")
    return mapping


def _sequence(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    number = float(value)
    if not isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    return value


def _category_parameter(value: Any, name: str) -> Literal["Jr", "Ja"]:
    parameter = _string(value, name)
    if parameter not in ("Jr", "Ja"):
        raise ValueError(f"{name} must be Jr or Ja")
    return parameter


def _density_type(value: Any, name: str) -> Literal["P32", "spacing"]:
    density_type = _string(value, name)
    if density_type not in ("P32", "spacing"):
        raise ValueError(f"{name} must be P32 or spacing")
    return density_type


def _borehole_purpose(value: Any, name: str) -> Literal["face_comparison", "independent"]:
    purpose = _string(value, name)
    if purpose not in ("face_comparison", "independent"):
        raise ValueError(f"{name} must be face_comparison or independent")
    return purpose


def _vector3(value: Any, name: str) -> tuple[float, float, float]:
    vector = _sequence(value, name)
    if len(vector) != 3:
        raise ValueError(f"{name} must contain exactly three values")
    return (
        _number(vector[0], f"{name}[0]"),
        _number(vector[1], f"{name}[1]"),
        _number(vector[2], f"{name}[2]"),
    )


def _read_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def _reject_legacy_category_fields(value: Any, location: str = "case") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _LEGACY_CATEGORY_FIELDS:
                raise ValueError(
                    f"legacy field {location}.{key} is not supported; "
                    "select explicit Jr/Ja category IDs instead"
                )
            _reject_legacy_category_fields(nested, f"{location}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_legacy_category_fields(nested, f"{location}[{index}]")


def load_barton_categories(path: Path) -> tuple[BartonCategory, ...]:
    """Load a YAML catalog with a top-level ``categories`` sequence."""
    root = _fields(_read_yaml(path), "category catalog", {"categories"})
    categories: list[BartonCategory] = []
    identifiers: set[str] = set()
    for index, raw_category in enumerate(_sequence(root["categories"], "categories")):
        name = f"categories[{index}]"
        item = _fields(
            raw_category,
            name,
            {"category_id", "parameter", "description", "lower_value", "upper_value"},
        )
        category = BartonCategory(
            category_id=_string(item["category_id"], f"{name}.category_id"),
            parameter=_category_parameter(item["parameter"], f"{name}.parameter"),
            description=_string(item["description"], f"{name}.description"),
            lower_value=_number(item["lower_value"], f"{name}.lower_value"),
            upper_value=_number(item["upper_value"], f"{name}.upper_value"),
        )
        if category.category_id in identifiers:
            raise ValueError(f"duplicate Barton category_id: {category.category_id}")
        identifiers.add(category.category_id)
        categories.append(category)
    if not categories:
        raise ValueError("category catalog must contain at least one category")
    return tuple(categories)


def load_case(path: Path, categories: tuple[BartonCategory, ...]) -> CaseSpec:
    """Load the explicit Euler case schema and resolve category IDs."""
    raw = _read_yaml(path)
    _reject_legacy_category_fields(raw)
    root = _fields(
        raw,
        "case",
        {"case_id", "domain", "joint_sets", "boreholes", "tunnel"},
    )
    category_by_id: dict[str, BartonCategory] = {}
    for category in categories:
        if not isinstance(category, BartonCategory):
            raise TypeError("categories must contain BartonCategory values")
        if category.category_id in category_by_id:
            raise ValueError(f"duplicate supplied Barton category_id: {category.category_id}")
        category_by_id[category.category_id] = category

    domain_data = _fields(
        root["domain"], "domain", {"cell_counts", "grid_spacing", "jn"},
    )
    cell_counts_raw = _sequence(domain_data["cell_counts"], "domain.cell_counts")
    if len(cell_counts_raw) != 3:
        raise ValueError("domain.cell_counts must contain exactly three values")
    domain = DomainSpec(
        (
            _integer(cell_counts_raw[0], "domain.cell_counts[0]"),
            _integer(cell_counts_raw[1], "domain.cell_counts[1]"),
            _integer(cell_counts_raw[2], "domain.cell_counts[2]"),
        ),
        _vector3(domain_data["grid_spacing"], "domain.grid_spacing"),
        _number(domain_data["jn"], "domain.jn"),
    )

    joint_sets: list[JointSetSpec] = []
    for index, raw_joint_set in enumerate(_sequence(root["joint_sets"], "joint_sets")):
        name = f"joint_sets[{index}]"
        item = _fields(
            raw_joint_set,
            name,
            {
                "set_id", "name", "density_type", "density_value", "size_alpha",
                "size_r_min", "size_r_max", "mean_dip", "mean_dip_dir",
                "fisher_kappa", "condition",
            },
        )
        condition_data = _fields(
            item["condition"], f"{name}.condition", {"jr_category", "ja_category"},
        )
        jr_id = condition_data["jr_category"]
        ja_id = condition_data["ja_category"]
        if not isinstance(jr_id, str) or not isinstance(ja_id, str):
            raise TypeError(f"{name}.condition category references must be strings")
        try:
            jr_category = category_by_id[jr_id]
        except KeyError as error:
            raise ValueError(f"unknown Jr category_id {jr_id!r} in {name}") from error
        try:
            ja_category = category_by_id[ja_id]
        except KeyError as error:
            raise ValueError(f"unknown Ja category_id {ja_id!r} in {name}") from error
        if jr_category.parameter != "Jr":
            raise ValueError(f"{name}.condition.jr_category must reference a Jr category")
        if ja_category.parameter != "Ja":
            raise ValueError(f"{name}.condition.ja_category must reference a Ja category")
        joint_sets.append(
            JointSetSpec(
                set_id=_integer(item["set_id"], f"{name}.set_id"),
                name=_string(item["name"], f"{name}.name"),
                density_type=_density_type(item["density_type"], f"{name}.density_type"),
                density_value=_number(item["density_value"], f"{name}.density_value"),
                size_alpha=_number(item["size_alpha"], f"{name}.size_alpha"),
                size_r_min=_number(item["size_r_min"], f"{name}.size_r_min"),
                size_r_max=_number(item["size_r_max"], f"{name}.size_r_max"),
                mean_dip=_number(item["mean_dip"], f"{name}.mean_dip"),
                mean_dip_dir=_number(item["mean_dip_dir"], f"{name}.mean_dip_dir"),
                fisher_kappa=_number(item["fisher_kappa"], f"{name}.fisher_kappa"),
                condition=JointCondition(jr_category, ja_category),
            )
        )

    boreholes: list[BoreholeSpec] = []
    for index, raw_borehole in enumerate(_sequence(root["boreholes"], "boreholes")):
        name = f"boreholes[{index}]"
        item = _fields(
            raw_borehole,
            name,
            {"borehole_id", "start", "direction", "requested_length", "interval_length", "purpose"},
        )
        boreholes.append(
            BoreholeSpec(
                borehole_id=_string(item["borehole_id"], f"{name}.borehole_id"),
                start=_vector3(item["start"], f"{name}.start"),
                direction=_vector3(item["direction"], f"{name}.direction"),
                requested_length=_number(item["requested_length"], f"{name}.requested_length"),
                interval_length=_number(item["interval_length"], f"{name}.interval_length"),
                purpose=_borehole_purpose(item["purpose"], f"{name}.purpose"),
            )
        )

    tunnel_data = _fields(root["tunnel"], "tunnel", {"vertices", "radius"})
    tunnel = TunnelSpec(
        tuple(
            _vector3(vertex, f"tunnel.vertices[{index}]")
            for index, vertex in enumerate(_sequence(tunnel_data["vertices"], "tunnel.vertices"))
        ),
        _number(tunnel_data["radius"], "tunnel.radius"),
    )
    case = CaseSpec(
        case_id=_string(root["case_id"], "case.case_id"),
        domain=domain,
        joint_sets=tuple(joint_sets),
        boreholes=tuple(boreholes),
        tunnel=tunnel,
    )
    validate_case(case)
    return case


def _case_mapping(case: CaseSpec) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "domain": {
            "cell_counts": list(case.domain.cell_counts),
            "grid_spacing": list(case.domain.grid_spacing),
            "jn": case.domain.jn,
        },
        "joint_sets": [
            {
                "set_id": joint_set.set_id,
                "name": joint_set.name,
                "density_type": joint_set.density_type,
                "density_value": joint_set.density_value,
                "size_alpha": joint_set.size_alpha,
                "size_r_min": joint_set.size_r_min,
                "size_r_max": joint_set.size_r_max,
                "mean_dip": joint_set.mean_dip,
                "mean_dip_dir": joint_set.mean_dip_dir,
                "fisher_kappa": joint_set.fisher_kappa,
                "condition": {
                    "jr_category": joint_set.condition.jr_category.category_id,
                    "ja_category": joint_set.condition.ja_category.category_id,
                },
            }
            for joint_set in case.joint_sets
        ],
        "boreholes": [
            {
                "borehole_id": borehole.borehole_id,
                "start": list(borehole.start),
                "direction": list(borehole.direction),
                "requested_length": borehole.requested_length,
                "interval_length": borehole.interval_length,
                "purpose": borehole.purpose,
            }
            for borehole in case.boreholes
        ],
        "tunnel": {
            "vertices": [list(vertex) for vertex in case.tunnel.vertices],
            "radius": case.tunnel.radius,
        },
    }


def save_case(path: Path, case: CaseSpec) -> None:
    """Save a validated case using category-ID references, not category copies."""
    validate_case(case)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(
            _case_mapping(case),
            stream,
            allow_unicode=True,
            sort_keys=False,
        )


def _campaign_id(value: Any) -> str:
    campaign_id = _string(value, "campaign_id")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", campaign_id):
        raise ValueError("campaign_id must be a safe path component")
    return campaign_id


def _project_reference(value: Any, name: str) -> str:
    reference = _string(value, name)
    path = PurePosixPath(reference)
    if (
        not reference
        or "\\" in reference
        or path.is_absolute()
        or any(part in (".", "..") for part in reference.split("/"))
        or path.as_posix() != reference
    ):
        raise ValueError(f"{name} must be a normalized relative project path")
    return reference


def _project_file(project_dir: Path, reference: str) -> Path:
    return project_dir.joinpath(*PurePosixPath(reference).parts)


def _primary_grid_edges() -> tuple[float, ...]:
    edges = np.geomspace(0.1, 400.0, num=11)
    edges[0] = 0.0
    return tuple(float(edge) for edge in edges)


def _load_campaign_grid(value: Any) -> CoverageGrid:
    mapping = _mapping(value, "coverage_grid")
    grid_id = _string(mapping.get("id"), "coverage_grid.id")
    if set(mapping) == {"id", "bins", "edge_definition"}:
        bins = _integer(mapping["bins"], "coverage_grid.bins")
        edge_definition = _string(
            mapping["edge_definition"], "coverage_grid.edge_definition",
        )
        if (
            grid_id != _PRIMARY_GRID_ID
            or bins != 10
            or edge_definition != _PRIMARY_GRID_DEFINITION
        ):
            raise ValueError("unsupported coverage_grid edge definition")
        grid = CoverageGrid(grid_id, _primary_grid_edges())
    elif set(mapping) == {"id", "edges"}:
        raw_edges = _sequence(mapping["edges"], "coverage_grid.edges")
        grid = CoverageGrid(
            grid_id,
            tuple(
                _number(edge, f"coverage_grid.edges[{index}]")
                for index, edge in enumerate(raw_edges)
            ),
        )
    else:
        raise ValueError(
            "coverage_grid must contain either id/bins/edge_definition "
            "or id/edges"
        )
    validate_grid(grid)
    return grid


def _load_campaign_start(
    value: Any, index: int, base_case: CaseSpec,
) -> Signature:
    name = f"starts[{index}]"
    entry = _fields(value, name, {"joint_sets"})
    base_sets = {joint_set.set_id: joint_set for joint_set in base_case.joint_sets}
    requested_sets: dict[int, dict[str, Any]] = {}
    start_fields = {
        "set_id",
        "density_value",
        "size_alpha",
        "size_r_min",
        "size_r_max",
        "mean_dip",
        "mean_dip_dir",
        "fisher_kappa",
    }
    for set_index, raw_set in enumerate(_sequence(entry["joint_sets"], f"{name}.joint_sets")):
        set_name = f"{name}.joint_sets[{set_index}]"
        joint_set = _fields(raw_set, set_name, start_fields)
        set_id = _integer(joint_set["set_id"], f"{set_name}.set_id")
        if set_id not in base_sets:
            raise ValueError(f"{set_name} references unknown set_id {set_id}")
        if set_id in requested_sets:
            raise ValueError(f"{name} contains duplicate set_id {set_id}")
        requested_sets[set_id] = joint_set

    if requested_sets.keys() != base_sets.keys():
        raise ValueError(f"{name} must define every base Case joint set exactly once")

    joint_sets = tuple(
        replace(
            base_set,
            density_value=_number(
                requested_sets[base_set.set_id]["density_value"],
                f"{name}.joint_sets.{base_set.set_id}.density_value",
            ),
            size_alpha=_number(
                requested_sets[base_set.set_id]["size_alpha"],
                f"{name}.joint_sets.{base_set.set_id}.size_alpha",
            ),
            size_r_min=_number(
                requested_sets[base_set.set_id]["size_r_min"],
                f"{name}.joint_sets.{base_set.set_id}.size_r_min",
            ),
            size_r_max=_number(
                requested_sets[base_set.set_id]["size_r_max"],
                f"{name}.joint_sets.{base_set.set_id}.size_r_max",
            ),
            mean_dip=_number(
                requested_sets[base_set.set_id]["mean_dip"],
                f"{name}.joint_sets.{base_set.set_id}.mean_dip",
            ),
            mean_dip_dir=_number(
                requested_sets[base_set.set_id]["mean_dip_dir"],
                f"{name}.joint_sets.{base_set.set_id}.mean_dip_dir",
            ),
            fisher_kappa=_number(
                requested_sets[base_set.set_id]["fisher_kappa"],
                f"{name}.joint_sets.{base_set.set_id}.fisher_kappa",
            ),
        )
        for base_set in base_case.joint_sets
    )
    return identify_signature(replace(base_case, joint_sets=joint_sets))


def _load_campaign_bounds(value: Any) -> tuple[FeatureBound, ...]:
    bounds: list[FeatureBound] = []
    for index, raw_bound in enumerate(_sequence(value, "bounds")):
        name = f"bounds[{index}]"
        item = _fields(raw_bound, name, {"feature_id", "lower", "upper"})
        bounds.append(
            FeatureBound(
                _string(item["feature_id"], f"{name}.feature_id"),
                _number(item["lower"], f"{name}.lower"),
                _number(item["upper"], f"{name}.upper"),
            )
        )
    return tuple(bounds)


def _validate_campaign_revision(project: CampaignProject) -> None:
    if (
        isinstance(project.plan_revision, bool)
        or not isinstance(project.plan_revision, int)
        or project.plan_revision < 1
    ):
        raise ValueError("plan_revision must be a positive integer")
    if project.parent_revision is not None and (
        isinstance(project.parent_revision, bool)
        or not isinstance(project.parent_revision, int)
    ):
        raise ValueError("parent_revision must be an integer or null")
    if project.plan_revision == 1:
        if project.parent_revision is not None or project.parent_plan_fingerprint is not None:
            raise ValueError("initial plan revision cannot have a predecessor")
    else:
        if project.parent_revision != project.plan_revision - 1:
            raise ValueError("parent_revision must be the immediately preceding revision")
        fingerprint = project.parent_plan_fingerprint
        if not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("parent_plan_fingerprint must be a lowercase SHA-256 fingerprint")


def _validate_round_budget(value: Any) -> int | None:
    if value is None:
        return None
    budget = _integer(value, "round_budget")
    if budget < 1:
        raise ValueError("round_budget must be null or a positive integer")
    return budget


def _validate_output_path_template(value: Any) -> str:
    template = _string(value, "execution.output_path_template")
    required_fields = {"campaign_id", "run_generation_id"}
    try:
        parsed_fields = [
            (field_name, format_spec, conversion)
            for _, field_name, format_spec, conversion in Formatter().parse(template)
            if field_name is not None
        ]
    except ValueError as error:
        raise ValueError("invalid execution.output_path_template") from error
    fields = [field_name for field_name, _, _ in parsed_fields]
    if (
        set(fields) != required_fields
        or len(fields) != len(required_fields)
        or any(format_spec or conversion for _, format_spec, conversion in parsed_fields)
    ):
        raise ValueError(
            "execution.output_path_template must contain exactly campaign_id "
            "and run_generation_id"
        )
    try:
        rendered = template.format(
            campaign_id="campaign", run_generation_id="run",
        )
    except (KeyError, ValueError) as error:
        raise ValueError("invalid execution.output_path_template") from error
    path = PurePosixPath(rendered)
    if path.is_absolute() or ".." in path.parts or "\\" in rendered:
        raise ValueError("execution.output_path_template must stay within the project")
    return template


def _validate_fixed_policy(root: dict[str, Any]) -> str:
    stop_policy = _fields(root["stop_policy"], "stop_policy", set(_STOP_POLICY))
    if stop_policy != _STOP_POLICY:
        raise ValueError("stop_policy does not match the approved campaign policy")

    execution = _fields(
        root["execution"],
        "execution",
        set(_FIXED_EXECUTION_SETTINGS) | {"output_path_template"},
    )
    for key, expected in _FIXED_EXECUTION_SETTINGS.items():
        actual = execution[key]
        if isinstance(expected, bool):
            valid = type(actual) is bool and actual is expected
        else:
            valid = actual == expected
        if not valid:
            raise ValueError(f"execution.{key} does not match the approved campaign policy")
    output_path_template = _validate_output_path_template(
        execution["output_path_template"],
    )
    return output_path_template


def _validate_project_sources(
    project: CampaignProject, project_dir: Path,
) -> None:
    if not isinstance(project, CampaignProject):
        raise TypeError("project must be a CampaignProject")
    validate_plan(project.plan)
    _campaign_id(project.plan.campaign_id)
    _validate_campaign_revision(project)
    _validate_round_budget(project.round_budget)
    _validate_output_path_template(project.output_path_template)

    base_case_ref = _project_reference(project.base_case, "base_case")
    catalog_ref = _project_reference(project.category_catalog, "category_catalog")
    categories = load_barton_categories(_project_file(project_dir, catalog_ref))
    base_case = load_case(_project_file(project_dir, base_case_ref), categories)
    category_by_id = {category.category_id: category for category in categories}
    first_case = project.plan.initial_parent.case
    if (
        first_case.case_id != base_case.case_id
        or first_case.domain != base_case.domain
        or first_case.boreholes != base_case.boreholes
        or first_case.tunnel != base_case.tunnel
        or tuple(item.set_id for item in first_case.joint_sets)
        != tuple(item.set_id for item in base_case.joint_sets)
    ):
        raise ValueError("base_case geometry and joint-set IDs must match the plan")

    base_sets = {item.set_id: item for item in base_case.joint_sets}
    for signature in project.plan.start_signatures:
        case = signature.case
        if (
            case.case_id != base_case.case_id
            or case.domain != base_case.domain
            or case.boreholes != base_case.boreholes
            or case.tunnel != base_case.tunnel
        ):
            raise ValueError("all start signatures must use the referenced base_case geometry")
        for joint_set in case.joint_sets:
            base_set = base_sets[joint_set.set_id]
            if (
                joint_set.name != base_set.name
                or joint_set.density_type != base_set.density_type
                or joint_set.condition != base_set.condition
            ):
                raise ValueError("start signatures must preserve base_case joint-set conditions")
            if (
                joint_set.condition.jr_category
                != category_by_id.get(joint_set.condition.jr_category.category_id)
                or joint_set.condition.ja_category
                != category_by_id.get(joint_set.condition.ja_category.category_id)
            ):
                raise ValueError("plan categories do not match the referenced catalog")

def load_campaign_project(path: Path) -> CampaignProject:
    """Load and validate a versioned multi-start campaign project YAML."""
    project_path = Path(path)
    root = _fields(
        _read_yaml(project_path),
        "campaign project",
        {
            "schema_version",
            "campaign_id",
            "plan_revision",
            "parent_revision",
            "parent_plan_fingerprint",
            "base_case",
            "category_catalog",
            "starts",
            "bounds",
            "coverage_grid",
            "seed_schedule",
            "update_rule_id",
            "round_budget",
            "stop_policy",
            "execution",
        },
    )
    schema_version = _integer(root["schema_version"], "schema_version")
    if schema_version != _CAMPAIGN_SCHEMA_VERSION:
        raise ValueError(f"unsupported campaign schema_version: {schema_version}")

    campaign_id = _campaign_id(root["campaign_id"])
    plan_revision = _integer(root["plan_revision"], "plan_revision")
    parent_revision_raw = root["parent_revision"]
    parent_revision = (
        None
        if parent_revision_raw is None
        else _integer(parent_revision_raw, "parent_revision")
    )
    parent_fingerprint_raw = root["parent_plan_fingerprint"]
    parent_fingerprint = (
        None
        if parent_fingerprint_raw is None
        else _string(parent_fingerprint_raw, "parent_plan_fingerprint")
    )
    base_case_ref = _project_reference(root["base_case"], "base_case")
    category_catalog_ref = _project_reference(
        root["category_catalog"], "category_catalog",
    )
    categories = load_barton_categories(
        _project_file(project_path.parent, category_catalog_ref),
    )
    base_case = load_case(
        _project_file(project_path.parent, base_case_ref),
        categories,
    )
    starts = tuple(
        _load_campaign_start(value, index, base_case)
        for index, value in enumerate(_sequence(root["starts"], "starts"))
    )
    grid = _load_campaign_grid(root["coverage_grid"])
    bounds = _load_campaign_bounds(root["bounds"])
    seed_schedule = _fields(
        root["seed_schedule"],
        "seed_schedule",
        {"exploration", "verification"},
    )
    exploration_seeds = _sequence(
        seed_schedule["exploration"], "seed_schedule.exploration",
    )
    verification_seeds = _sequence(
        seed_schedule["verification"], "seed_schedule.verification",
    )
    if len(exploration_seeds) != 1:
        raise ValueError("seed_schedule.exploration must contain exactly one seed")
    if len(verification_seeds) != 3:
        raise ValueError("seed_schedule.verification must contain exactly three seeds")
    exploration_seed = _integer(exploration_seeds[0], "seed_schedule.exploration[0]")
    verification_seed_values = (
        _integer(verification_seeds[0], "seed_schedule.verification[0]"),
        _integer(verification_seeds[1], "seed_schedule.verification[1]"),
        _integer(verification_seeds[2], "seed_schedule.verification[2]"),
    )
    update_rule_id = _string(root["update_rule_id"], "update_rule_id")
    plan = CampaignPlan(
        campaign_id=campaign_id,
        start_signatures=starts,
        grid=grid,
        bounds=bounds,
        exploration_seed=exploration_seed,
        verification_seeds=verification_seed_values,
        update_rule_id=update_rule_id,
    )
    validate_plan(plan)
    output_path_template = _validate_fixed_policy(root)
    project = CampaignProject(
        plan=plan,
        base_case=base_case_ref,
        category_catalog=category_catalog_ref,
        plan_revision=plan_revision,
        parent_revision=parent_revision,
        parent_plan_fingerprint=parent_fingerprint,
        round_budget=_validate_round_budget(root["round_budget"]),
        output_path_template=output_path_template,
    )
    _validate_project_sources(project, project_path.parent)
    return project


def _campaign_project_mapping(project: CampaignProject) -> dict[str, Any]:
    plan = project.plan
    if plan.grid.grid_id == _PRIMARY_GRID_ID and plan.grid.edges == _primary_grid_edges():
        coverage_grid: dict[str, Any] = {
            "id": _PRIMARY_GRID_ID,
            "bins": 10,
            "edge_definition": _PRIMARY_GRID_DEFINITION,
        }
    else:
        coverage_grid = {
            "id": plan.grid.grid_id,
            "edges": list(plan.grid.edges),
        }
    starts = [
        {
            "joint_sets": [
                {
                    "set_id": joint_set.set_id,
                    "density_value": joint_set.density_value,
                    "size_alpha": joint_set.size_alpha,
                    "size_r_min": joint_set.size_r_min,
                    "size_r_max": joint_set.size_r_max,
                    "mean_dip": joint_set.mean_dip,
                    "mean_dip_dir": joint_set.mean_dip_dir,
                    "fisher_kappa": joint_set.fisher_kappa,
                }
                for joint_set in signature.case.joint_sets
            ],
        }
        for signature in plan.start_signatures
    ]
    return {
        "schema_version": _CAMPAIGN_SCHEMA_VERSION,
        "campaign_id": plan.campaign_id,
        "plan_revision": project.plan_revision,
        "parent_revision": project.parent_revision,
        "parent_plan_fingerprint": project.parent_plan_fingerprint,
        "base_case": project.base_case,
        "category_catalog": project.category_catalog,
        "starts": starts,
        "bounds": [
            {
                "feature_id": bound.feature_id,
                "lower": bound.lower,
                "upper": bound.upper,
            }
            for bound in plan.bounds
        ],
        "coverage_grid": coverage_grid,
        "seed_schedule": {
            "exploration": [plan.exploration_seed],
            "verification": list(plan.verification_seeds),
        },
        "update_rule_id": plan.update_rule_id,
        "round_budget": project.round_budget,
        "stop_policy": dict(_STOP_POLICY),
        "execution": {
            **_FIXED_EXECUTION_SETTINGS,
            "output_path_template": project.output_path_template,
        },
    }


def save_campaign_project(path: Path, project: CampaignProject) -> None:
    """Serialize a validated project, preserving references to its Case/catalog."""
    project_path = Path(path)
    _validate_project_sources(project, project_path.parent)
    with project_path.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(
            _campaign_project_mapping(project),
            stream,
            allow_unicode=True,
            sort_keys=False,
        )


def extend_campaign_project(
    project: CampaignProject,
    state: CampaignState,
    *,
    new_start_signatures: tuple[Signature, ...] = (),
    additional_rounds: int | None = None,
) -> CampaignProject:
    """Create an append-only revision for saturation or exhausted-budget extension."""
    if not isinstance(project, CampaignProject):
        raise TypeError("project must be a CampaignProject")
    if not isinstance(new_start_signatures, tuple):
        raise TypeError("new_start_signatures must be a tuple")
    _validate_campaign_revision(project)
    _validate_state(project.plan, state)

    adds_starts = bool(new_start_signatures)
    adds_rounds = additional_rounds is not None
    if adds_starts == adds_rounds:
        raise ValueError("choose exactly one of new starts or additional rounds")

    if adds_starts:
        if state.status != "all_lineages_saturated":
            raise ValueError("new starts can only extend a saturated campaign")
        plan = replace(
            project.plan,
            start_signatures=project.plan.start_signatures + new_start_signatures,
        )
        round_budget = project.round_budget
    else:
        if state.status != "round_budget_exhausted":
            raise ValueError("rounds can only extend an exhausted campaign budget")
        if project.round_budget is None:
            raise ValueError("an unlimited campaign budget cannot be extended")
        if (
            isinstance(additional_rounds, bool)
            or not isinstance(additional_rounds, int)
            or additional_rounds < 1
        ):
            raise ValueError("additional_rounds must be a positive integer")
        plan = project.plan
        round_budget = project.round_budget + additional_rounds

    validate_plan(plan)
    return replace(
        project,
        plan=plan,
        plan_revision=project.plan_revision + 1,
        parent_revision=project.plan_revision,
        parent_plan_fingerprint=_plan_fingerprint(project.plan),
        round_budget=round_budget,
    )
