"""Typed configuration boundary; no conversion from legacy normal distributions."""

from pathlib import Path
from .campaign import CampaignPlan, CampaignState
from .models import BartonCategory, CaseSpec, Signature

class CampaignProject:
    plan: CampaignPlan
    base_case: str
    category_catalog: str
    plan_revision: int
    parent_revision: int | None
    parent_plan_fingerprint: str | None
    round_budget: int | None
    output_path_template: str

def load_barton_categories(path: Path) -> tuple[BartonCategory, ...]: ...
def load_case(path: Path, categories: tuple[BartonCategory, ...]) -> CaseSpec: ...
def save_case(path: Path, case: CaseSpec) -> None: ...
def load_campaign_project(path: Path) -> CampaignProject: ...
def save_campaign_project(path: Path, project: CampaignProject) -> None: ...
def extend_campaign_project(project: CampaignProject, state: CampaignState, *, new_start_signatures: tuple[Signature, ...] = ..., additional_rounds: int | None = ...) -> CampaignProject: ...
