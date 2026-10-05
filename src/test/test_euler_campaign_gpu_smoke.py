from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import yaml

from src.euler_campaign.campaign import CampaignPlan
from src.euler_campaign.config import (
    CampaignProject,
    save_campaign_project,
    save_case,
)
from src.euler_campaign.coverage import CoverageGrid
from src.euler_campaign.euler import FeatureBound
from src.euler_campaign.models import (
    BartonCategory,
    CaseSpec,
    DomainSpec,
    JointCondition,
    JointSetSpec,
    TunnelSpec,
    identify_signature,
)


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_GPU_SMOKE_ENABLED = os.environ.get("QSIMEX_RUN_GPU_CAMPAIGN_SMOKE") == "1"


def _write_smoke_project(project_root: Path) -> Path:
    categories = (
        BartonCategory("jr-smoke", "Jr", "Rough", 3.0, 4.0),
        BartonCategory("ja-smoke", "Ja", "Slight", 1.0, 2.0),
    )
    category_catalog = {
        "categories": [
            {
                "category_id": category.category_id,
                "parameter": category.parameter,
                "description": category.description,
                "lower_value": category.lower_value,
                "upper_value": category.upper_value,
            }
            for category in categories
        ],
    }
    (project_root / "categories.yaml").write_text(
        yaml.safe_dump(category_catalog, sort_keys=False),
        encoding="utf-8",
    )

    case = CaseSpec(
        "campaign-gpu-smoke",
        DomainSpec((6, 6, 6), (1.0, 1.0, 1.0), 1.0),
        (
            JointSetSpec(
                1,
                "set-1",
                "P32",
                0.2,
                3.0,
                0.3,
                0.8,
                90.0,
                270.0,
                10.0,
                JointCondition(*categories),
            ),
        ),
        (),
        TunnelSpec(((0.0, 3.0, 3.0), (6.0, 3.0, 3.0)), 0.5),
    )
    save_case(project_root / "base_case.yaml", case)

    plan = CampaignPlan(
        "campaign-gpu-smoke",
        (identify_signature(case),),
        CoverageGrid("smoke-grid", (0.0, 400.0)),
        (
            FeatureBound("joint_sets.1.density_value", 0.05, 0.35),
        ),
        701,
        (702, 703, 704),
    )
    project = CampaignProject(
        plan,
        "base_case.yaml",
        "categories.yaml",
        1,
        None,
        None,
        1,
        "results/euler_campaigns/{campaign_id}/runs/{run_generation_id}",
    )
    project_path = project_root / "campaign.yaml"
    save_campaign_project(project_path, project)
    return project_path


@unittest.skipUnless(
    _GPU_SMOKE_ENABLED,
    "set QSIMEX_RUN_GPU_CAMPAIGN_SMOKE=1 to run the opt-in MLX GPU smoke test",
)
class TestEulerCampaignGpuSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from src.euler_campaign.mlx_backend import require_mlx_gpu

            require_mlx_gpu()
        except (ImportError, RuntimeError) as error:
            raise unittest.SkipTest(f"MLX GPU is unavailable: {error}") from error

    def test_launcher_executes_and_resumes_a_bounded_campaign(self) -> None:
        with TemporaryDirectory(prefix="qsimex-campaign-gpu-smoke-") as directory:
            project_path = _write_smoke_project(Path(directory))
            command = [
                sys.executable,
                str(_PROJECT_ROOT / "run_euler_campaign.py"),
                "--project",
                str(project_path),
                "--run-generation-id",
                "smoke-run",
            ]

            first = subprocess.run(
                command,
                cwd=_PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            first_output = first.stdout + first.stderr
            self.assertIn(first.returncode, (0, 2), first_output)
            self.assertIn("coverage state at invocation start", first_output)
            self.assertIn("empty_bins_1based=", first_output)
            self.assertIn("coverage state after signature_id=", first_output)

            summary_path = (
                Path(directory)
                / "results"
                / "euler_campaigns"
                / "campaign-gpu-smoke"
                / "runs"
                / "smoke-run"
                / "run_summary.json"
            )
            self.assertTrue(summary_path.is_file(), first.stdout + first.stderr)
            first_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(first_summary["run_generation_id"], "smoke-run")
            self.assertEqual(first_summary["execution"]["backend"], "mlx")
            self.assertTrue(first_summary["execution"]["device_runtime"])
            self.assertEqual(first_summary["rounds_completed_in_generation"], 1)
            self.assertNotEqual(first_summary["status"], "failed")

            resumed = subprocess.run(
                command,
                cwd=_PROJECT_ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            resumed_output = resumed.stdout + resumed.stderr
            self.assertIn(resumed.returncode, (0, 2), resumed_output)
            self.assertIn("coverage state at invocation start", resumed_output)
            self.assertIn("empty_bins_1based=", resumed_output)
            resumed_summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(
                resumed_summary["rounds_executed_this_invocation"], 0,
            )
            self.assertEqual(
                resumed_summary["rounds_completed_in_generation"], 1,
            )
            self.assertEqual(
                resumed_summary["run_generation_id"], "smoke-run",
            )


if __name__ == "__main__":
    unittest.main()
