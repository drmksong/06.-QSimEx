"""Adapt normalized geometry and sampled inputs to the existing DFN factory model."""

from src.euler_campaign.models import (
    BartonCategory,
    BoreholeSpec,
    CaseSpec,
    DomainSpec,
    JointCondition,
    JointSetSpec,
    TunnelSpec,
    validate_case,
)

from .config import GeometryInput, MeasurementInput
from .fingerprint import ExecutionJointSet

_GENERATION_ONLY_CONDITION = JointCondition(
    BartonCategory(
        "generation-only-jr", "Jr", "Generation compatibility only; not analysis", 1.0, 1.0,
    ),
    BartonCategory(
        "generation-only-ja", "Ja", "Generation compatibility only; not analysis", 1.0, 1.0,
    ),
)


def build_generation_case(
    geometry: GeometryInput,
    measurements: MeasurementInput,
    fixed_jn: float,
    joint_sets: tuple[ExecutionJointSet, ...],
    *,
    case_id: str,
) -> CaseSpec:
    """Build a generation-only case; its placeholder Jr/Ja must never score observations."""
    if not 1 <= len(joint_sets) <= 5:
        raise ValueError("joint_sets must contain between 1 and 5 sampled sets")
    if any(not item.joint_set_id.strip() for item in joint_sets):
        raise ValueError("joint_set_id must not be empty")
    if len({item.joint_set_id for item in joint_sets}) != len(joint_sets):
        raise ValueError("joint_set_id values must be unique")
    if geometry.coordinate_frame != "ENU":
        raise ValueError("geometry.coordinate_frame must be 'ENU'")
    if any(
        count * spacing != size
        for count, spacing, size in zip(
            geometry.cell_counts, geometry.grid_spacing_m, geometry.domain_size_m,
        )
    ):
        raise ValueError("geometry cell counts/grid spacing must match domain size")
    for item in joint_sets:
        if not item.size_r_min_m < item.size_r_max_m:
            raise ValueError("sampled radii must satisfy size_r_min_m < size_r_max_m")

    case = CaseSpec(
        case_id=case_id,
        domain=DomainSpec(geometry.cell_counts, geometry.grid_spacing_m, fixed_jn),
        joint_sets=tuple(
            JointSetSpec(
                set_id=index,
                name=item.joint_set_id,
                density_type="P32",
                density_value=item.p32_m2_per_m3,
                size_alpha=item.size_alpha,
                size_r_min=item.size_r_min_m,
                size_r_max=item.size_r_max_m,
                mean_dip=item.mean_dip_deg,
                mean_dip_dir=item.mean_dip_dir_deg,
                fisher_kappa=item.fisher_kappa,
                condition=_GENERATION_ONLY_CONDITION,
            )
            for index, item in enumerate(joint_sets, start=1)
        ),
        boreholes=(
            BoreholeSpec(
                borehole_id="pilot-bh",
                start=geometry.borehole_start_m,
                direction=geometry.borehole_direction_enu,
                requested_length=geometry.borehole_length_m,
                interval_length=measurements.bh_interval_m,
                purpose="face_comparison",
            ),
        ),
        tunnel=TunnelSpec(geometry.tunnel_vertices_m, geometry.tunnel_radius_m),
    )
    validate_case(case)
    return case
