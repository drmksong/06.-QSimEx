"""YAML loading and validation for the RQD exploration pilot."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from math import hypot, isfinite
from pathlib import Path
from typing import Any

import yaml

_SAFE_INTEGER_MAX = (2**53) - 1
_SAFE_INTEGER_MIN = -_SAFE_INTEGER_MAX
_SCHEMA_VERSION = 1
JN_VALUES = (0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 9.0, 12.0, 15.0, 20.0)
EXECUTABLE_JN_SET_COUNTS = {
    2.0: 1,
    4.0: 2,
    9.0: 3,
    15.0: 4,
    20.0: 5,
}
JR_VALUES = (0.5, 1.0, 1.5, 2.0, 3.0, 4.0)
JA_VALUES = (0.75, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0, 13.0, 20.0)


@dataclass(frozen=True)
class Bounds:
    lower: float
    upper: float
    unit: str
    coordinate: str
    upper_inclusive: bool


@dataclass(frozen=True)
class GeometryInput:
    coordinate_frame: str
    domain_size_m: tuple[float, float, float]
    grid_spacing_m: tuple[float, float, float]
    cell_counts: tuple[int, int, int]
    tunnel_vertices_m: tuple[tuple[float, float, float], ...]
    tunnel_radius_m: float
    borehole_start_m: tuple[float, float, float]
    borehole_direction_enu: tuple[float, float, float]
    borehole_length_m: float


@dataclass(frozen=True)
class MeasurementInput:
    bh_interval_m: float
    face_advance_m: float


@dataclass(frozen=True)
class JointSetInput:
    joint_set_id: str
    p32: Bounds
    size_r_min_m: Bounds
    size_r_max_m: Bounds
    size_radius_transform: str


@dataclass(frozen=True)
class ShapeRandomization:
    bounds: Bounds
    distribution: str
    rng_stream: str


@dataclass(frozen=True)
class DesignInput:
    design_id: str
    block_id: str
    fixed_jn: float
    sample_count: int
    design_seed: int
    realization_seed: int
    mean_dip_deg: Bounds
    mean_dip_dir_deg: Bounds
    size_alpha: ShapeRandomization
    fisher_kappa: ShapeRandomization
    joint_sets: tuple[JointSetInput, ...]


@dataclass(frozen=True)
class NormalizedPilotInput:
    schema_version: int
    geometry: GeometryInput
    measurements: MeasurementInput
    designs: tuple[DesignInput, ...]
    source_yaml_bytes: bytes
    source_yaml_sha256: str
    source_reference: str | None


class _UniqueKeySafeLoader(yaml.SafeLoader):
    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False,
    ) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "mapping keys must be hashable",
                    key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise TypeError(f"{name} must be a mapping with string keys")
    return value


def _fields(value: Any, name: str, required: set[str]) -> dict[str, Any]:
    mapping = _mapping(value, name)
    missing = required - mapping.keys()
    unknown = mapping.keys() - required
    if missing:
        raise ValueError(f"{name} is missing required fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"{name} has unknown fields: {sorted(unknown)}")
    return mapping


def _sequence(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be a list")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if not _SAFE_INTEGER_MIN <= value <= _SAFE_INTEGER_MAX:
        raise ValueError(f"{name} must be within the safe integer range")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number")
    try:
        normalized = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite") from error
    if not isfinite(normalized):
        raise ValueError(f"{name} must be finite")
    return normalized


def _vector3(value: Any, name: str) -> tuple[float, float, float]:
    vector = _sequence(value, name)
    if len(vector) != 3:
        raise ValueError(f"{name} must contain exactly three values")
    return (
        _number(vector[0], f"{name}[0]"),
        _number(vector[1], f"{name}[1]"),
        _number(vector[2], f"{name}[2]"),
    )


def _bounds(
    value: Any,
    name: str,
    unit: str,
    coordinate: str,
    allowed_lower: float,
    allowed_upper: float,
    upper_inclusive: bool = True,
) -> Bounds:
    item = _fields(
        value,
        name,
        {"lower", "upper", "unit", "coordinate", "upper_inclusive"},
    )
    supplied_unit = _string(item["unit"], f"{name}.unit")
    if supplied_unit != unit:
        raise ValueError(f"{name}.unit must be {unit!r}")
    supplied_coordinate = _string(item["coordinate"], f"{name}.coordinate")
    if supplied_coordinate != coordinate:
        raise ValueError(f"{name}.coordinate must be {coordinate!r}")
    supplied_upper_inclusive = item["upper_inclusive"]
    if not isinstance(supplied_upper_inclusive, bool):
        raise TypeError(f"{name}.upper_inclusive must be a boolean")
    if supplied_upper_inclusive is not upper_inclusive:
        raise ValueError(f"{name}.upper_inclusive must be {upper_inclusive}")
    lower = _number(item["lower"], f"{name}.lower")
    upper = _number(item["upper"], f"{name}.upper")
    if not allowed_lower <= lower < upper <= allowed_upper:
        raise ValueError(
            f"{name} must satisfy {allowed_lower} <= lower < upper <= {allowed_upper}"
        )
    return Bounds(lower, upper, unit, coordinate, upper_inclusive)


def _geometry(value: Any) -> GeometryInput:
    root = _fields(
        value,
        "geometry",
        {
            "domain_size_m",
            "grid_spacing_m",
            "coordinate_frame",
            "tunnel_vertices_m",
            "tunnel_radius_m",
            "borehole",
        },
    )
    coordinate_frame = _string(root["coordinate_frame"], "geometry.coordinate_frame")
    if coordinate_frame != "ENU":
        raise ValueError("geometry.coordinate_frame must be 'ENU'")
    domain_size = _vector3(root["domain_size_m"], "geometry.domain_size_m")
    grid_spacing = _vector3(root["grid_spacing_m"], "geometry.grid_spacing_m")
    if any(size <= 0.0 for size in domain_size):
        raise ValueError("geometry.domain_size_m values must be positive")
    if any(spacing <= 0.0 for spacing in grid_spacing):
        raise ValueError("geometry.grid_spacing_m values must be positive")

    counts: list[int] = []
    for axis, (size, spacing) in enumerate(zip(domain_size, grid_spacing)):
        count = size / spacing
        rounded_count = round(count)
        if not isfinite(count) or rounded_count <= 0 or count != rounded_count:
            raise ValueError(
                f"geometry domain size on axis {axis} must be an integer "
                "multiple of its grid spacing"
            )
        counts.append(rounded_count)

    tunnel_vertices = tuple(
        _vector3(vertex, f"geometry.tunnel_vertices_m[{index}]")
        for index, vertex in enumerate(
            _sequence(root["tunnel_vertices_m"], "geometry.tunnel_vertices_m")
        )
    )
    if len(tunnel_vertices) < 2:
        raise ValueError("geometry.tunnel_vertices_m must contain at least two points")
    for index, vertex in enumerate(tunnel_vertices):
        if any(value < 0.0 or value > domain_size[axis]
               for axis, value in enumerate(vertex)):
            raise ValueError(
                f"geometry.tunnel_vertices_m[{index}] must lie within the domain"
            )
    for index, (first, second) in enumerate(
        zip(tunnel_vertices, tunnel_vertices[1:])
    ):
        if first == second:
            raise ValueError(
                f"geometry.tunnel_vertices_m[{index}:{index + 2}] "
                "must not define a zero-length segment"
            )

    radius = _number(root["tunnel_radius_m"], "geometry.tunnel_radius_m")
    if radius <= 0.0:
        raise ValueError("geometry.tunnel_radius_m must be positive")

    borehole = _fields(
        root["borehole"],
        "geometry.borehole",
        {"start_m", "direction_enu", "length_m"},
    )
    start = _vector3(borehole["start_m"], "geometry.borehole.start_m")
    raw_direction = _vector3(
        borehole["direction_enu"], "geometry.borehole.direction_enu",
    )
    direction_length = hypot(*raw_direction)
    if not isfinite(direction_length):
        raise ValueError("geometry.borehole.direction_enu length must be finite")
    if direction_length == 0.0:
        raise ValueError("geometry.borehole.direction_enu must be non-zero")
    direction = (
        raw_direction[0] / direction_length,
        raw_direction[1] / direction_length,
        raw_direction[2] / direction_length,
    )
    borehole_length = _number(borehole["length_m"], "geometry.borehole.length_m")
    if borehole_length <= 0.0:
        raise ValueError("geometry.borehole.length_m must be positive")
    endpoint = tuple(
        start[axis] + direction[axis] * borehole_length for axis in range(3)
    )
    if any(
        coordinate < 0.0 or coordinate > domain_size[axis]
        for point in (start, endpoint)
        for axis, coordinate in enumerate(point)
    ):
        raise ValueError("geometry.borehole start and endpoint must lie within the domain")

    return GeometryInput(
        coordinate_frame,
        domain_size,
        grid_spacing,
        (counts[0], counts[1], counts[2]),
        tunnel_vertices,
        radius,
        start,
        direction,
        borehole_length,
    )


def _measurements(value: Any) -> MeasurementInput:
    root = _fields(value, "measurements", {"bh_interval_m", "face_advance_m"})
    bh_interval = _number(root["bh_interval_m"], "measurements.bh_interval_m")
    face_advance = _number(root["face_advance_m"], "measurements.face_advance_m")
    if bh_interval != 1.0:
        raise ValueError("measurements.bh_interval_m must be 1 m for the pilot")
    if face_advance != 1.0:
        raise ValueError("measurements.face_advance_m must be 1 m for the pilot")
    return MeasurementInput(bh_interval, face_advance)


def _designs(value: Any) -> tuple[DesignInput, ...]:
    designs: list[DesignInput] = []
    design_ids: set[str] = set()
    for index, raw_design in enumerate(_sequence(value, "designs")):
        name = f"designs[{index}]"
        item = _fields(
            raw_design,
            name,
            {
                "design_id",
                "block_id",
                "fixed_jn",
                "sample_count",
                "design_seed",
                "realization_seed",
                "orientation_bounds",
                "shape_randomization",
                "joint_sets",
            },
        )
        design_id = _string(item["design_id"], f"{name}.design_id")
        block_id = _string(item["block_id"], f"{name}.block_id")
        if design_id in design_ids:
            raise ValueError(f"duplicate design_id: {design_id}")
        design_ids.add(design_id)

        fixed_jn = _number(item["fixed_jn"], f"{name}.fixed_jn")
        if fixed_jn not in EXECUTABLE_JN_SET_COUNTS:
            raise ValueError(
                f"{name}.fixed_jn must be one of the executable Barton values "
                f"{tuple(EXECUTABLE_JN_SET_COUNTS)}"
            )
        sample_count = _integer(item["sample_count"], f"{name}.sample_count")
        if sample_count <= 0:
            raise ValueError(f"{name}.sample_count must be positive")
        design_seed = _integer(item["design_seed"], f"{name}.design_seed")
        realization_seed = _integer(
            item["realization_seed"], f"{name}.realization_seed",
        )

        orientation = _fields(
            item["orientation_bounds"],
            f"{name}.orientation_bounds",
            {"mean_dip_deg", "mean_dip_dir_deg"},
        )
        mean_dip = _bounds(
            orientation["mean_dip_deg"],
            f"{name}.orientation_bounds.mean_dip_deg",
            "degree",
            "linear",
            0.0,
            90.0,
        )
        mean_dip_dir = _bounds(
            orientation["mean_dip_dir_deg"],
            f"{name}.orientation_bounds.mean_dip_dir_deg",
            "degree",
            "linear",
            0.0,
            360.0,
            upper_inclusive=False,
        )

        shape = _fields(
            item["shape_randomization"],
            f"{name}.shape_randomization",
            {"size_alpha", "fisher_kappa"},
        )
        size_alpha = _shape_randomization(
            shape["size_alpha"], f"{name}.shape_randomization.size_alpha", 2.5, 4.0,
        )
        fisher_kappa = _shape_randomization(
            shape["fisher_kappa"],
            f"{name}.shape_randomization.fisher_kappa",
            0.0,
            50.0,
        )

        joint_sets: list[JointSetInput] = []
        joint_set_ids: set[str] = set()
        for set_index, raw_joint_set in enumerate(
            _sequence(item["joint_sets"], f"{name}.joint_sets")
        ):
            set_name = f"{name}.joint_sets[{set_index}]"
            joint_set = _fields(
                raw_joint_set,
                set_name,
                {
                    "joint_set_id",
                    "p32",
                    "size_r_min_m",
                    "size_r_max_m",
                    "size_radius_transform",
                },
            )
            joint_set_id = _string(
                joint_set["joint_set_id"], f"{set_name}.joint_set_id",
            )
            if joint_set_id in joint_set_ids:
                raise ValueError(f"duplicate joint_set_id in {name}: {joint_set_id}")
            joint_set_ids.add(joint_set_id)
            p32 = _bounds(
                joint_set["p32"],
                f"{set_name}.p32",
                "m^2/m^3",
                "log",
                0.01,
                100.0,
            )
            size_r_min = _bounds(
                joint_set["size_r_min_m"],
                f"{set_name}.size_r_min_m",
                "m",
                "log",
                0.05,
                150.0,
            )
            size_r_max = _bounds(
                joint_set["size_r_max_m"],
                f"{set_name}.size_r_max_m",
                "m",
                "log",
                0.05,
                150.0,
            )
            size_radius_transform = _string(
                joint_set["size_radius_transform"],
                f"{set_name}.size_radius_transform",
            )
            if size_radius_transform != "ordered_log_pair":
                raise ValueError(
                    f"{set_name}.size_radius_transform must be 'ordered_log_pair'"
                )
            if size_r_min.lower >= size_r_max.upper:
                raise ValueError(
                    f"{set_name} radius bounds do not permit size_r_min < size_r_max"
                )
            if (
                size_r_min.lower != size_r_max.lower
                or size_r_min.upper != size_r_max.upper
            ):
                raise ValueError(
                    f"{set_name} radius bounds must match for ordered_log_pair"
                )
            joint_sets.append(
                JointSetInput(
                    joint_set_id,
                    p32,
                    size_r_min,
                    size_r_max,
                    size_radius_transform,
                )
            )
        expected_set_count = EXECUTABLE_JN_SET_COUNTS[fixed_jn]
        if len(joint_sets) != expected_set_count:
            raise ValueError(
                f"{name}.fixed_jn={fixed_jn:g} requires exactly "
                f"{expected_set_count} joint_sets; got {len(joint_sets)}"
            )

        designs.append(
            DesignInput(
                design_id,
                block_id,
                fixed_jn,
                sample_count,
                design_seed,
                realization_seed,
                mean_dip,
                mean_dip_dir,
                size_alpha,
                fisher_kappa,
                tuple(joint_sets),
            )
        )
    if not designs:
        raise ValueError("designs must contain at least one design")
    return tuple(designs)


def _shape_randomization(
    value: Any, name: str, lower: float, upper: float,
) -> ShapeRandomization:
    item = _fields(
        value, name, {"bounds", "unit", "distribution", "rng_stream"},
    )
    unit = _string(item["unit"], f"{name}.unit")
    if unit != "1":
        raise ValueError(f"{name}.unit must be '1'")
    distribution = _string(item["distribution"], f"{name}.distribution")
    if distribution != "uniform":
        raise ValueError(f"{name}.distribution must be 'uniform'")
    rng_stream = _string(item["rng_stream"], f"{name}.rng_stream")
    if rng_stream != "separate_from_lhs":
        raise ValueError(f"{name}.rng_stream must be 'separate_from_lhs'")
    bound_values = _sequence(item["bounds"], f"{name}.bounds")
    if len(bound_values) != 2:
        raise ValueError(f"{name}.bounds must contain lower and upper values")
    normalized_lower = _number(bound_values[0], f"{name}.bounds[0]")
    normalized_upper = _number(bound_values[1], f"{name}.bounds[1]")
    if not lower <= normalized_lower < normalized_upper <= upper:
        raise ValueError(
            f"{name}.bounds must satisfy "
            f"{lower} <= lower < upper <= {upper}"
        )
    return ShapeRandomization(
        Bounds(normalized_lower, normalized_upper, unit, "linear", True),
        distribution,
        rng_stream,
    )


def parse_config_bytes(
    source_yaml_bytes: bytes,
    source_reference: str | None = None,
) -> NormalizedPilotInput:
    """Parse, validate, and normalize YAML while retaining its exact source bytes."""
    if not isinstance(source_yaml_bytes, bytes):
        raise TypeError("source_yaml_bytes must be bytes")
    if source_reference is not None and not isinstance(source_reference, str):
        raise TypeError("source_reference must be a string or None")
    if source_reference is not None and not source_reference.strip():
        raise ValueError("source_reference must not be empty")
    try:
        source_text = source_yaml_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("configuration must be UTF-8 YAML") from error
    try:
        raw = yaml.load(source_text, Loader=_UniqueKeySafeLoader)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML: {error}") from error

    root = _fields(
        raw,
        "configuration",
        {"schema_version", "geometry", "measurements", "designs"},
    )
    schema_version = _integer(root["schema_version"], "schema_version")
    if schema_version != _SCHEMA_VERSION:
        raise ValueError(f"schema_version must be {_SCHEMA_VERSION}")
    geometry = _geometry(root["geometry"])
    measurements = _measurements(root["measurements"])
    designs = _designs(root["designs"])
    return NormalizedPilotInput(
        schema_version,
        geometry,
        measurements,
        designs,
        source_yaml_bytes,
        sha256(source_yaml_bytes).hexdigest(),
        source_reference.strip() if source_reference is not None else None,
    )


def load_config(path: str | Path) -> NormalizedPilotInput:
    """Read YAML bytes from disk and validate them without re-serializing provenance."""
    config_path = Path(path)
    source_bytes = config_path.read_bytes()
    return parse_config_bytes(source_bytes, str(config_path))
