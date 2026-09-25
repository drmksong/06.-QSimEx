"""
Multi-case batch runner

역할:
- 여러 YAML case × 여러 seed × 여러 face position 실행
- 각 case 결과에 metadata 추가
- 전체 결과를 하나로 병합 저장
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import os
import time
import yaml

from src.core.case_library import CaseLibrary
from batch_runner import BatchRunner, BatchConfig, BatchResult
from src.core.constants import standardize_metrics, STANDARD_COST_KEYS


@dataclass
class MultiCaseBatchConfig:
    case_paths: List[str]
    seeds: List[int]
    face_positions: Optional[List[int]] = None
    borehole_window: int = 3
    backend: str = "auto"
    batch_size: int = 500
    verbose: bool = True
    output_dir: str = "legacy_results/outputs/multicase"
    save_each_case: bool = True
    save_combined: bool = True
    checkpoint_on_seed: bool = True
    correction_mode: str = "pure"
    # Costs forwarded to ResearchReporter (FP,FN)
    # Central defaults: cost_fp=1.0, cost_fn=5.0
    cost_fp: float = 1.0
    cost_fn: float = 5.0


class MultiCaseBatchRunner:
    def __init__(self, config: MultiCaseBatchConfig):
        self.config = config

    def run(self) -> BatchResult:
        all_result = BatchResult()
        total_cases = len(self.config.case_paths)
        started = time.time()

        os.makedirs(self.config.output_dir, exist_ok=True)

        for i, case_path in enumerate(self.config.case_paths):
            if self.config.verbose:
                print("\n" + "=" * 100)
                print(f"[MultiCase] {i+1}/{total_cases}", flush=True)
                print(f"case: {case_path}", flush=True)
                print("=" * 100, flush=True)

            case, metadata = self._load_case_and_metadata(case_path)

            case_output_dir = None
            if self.config.save_each_case:
                case_output_dir = os.path.join(
                    self.config.output_dir,
                    "by_case" + f"_{self.config.correction_mode}",
                    case.name,
                )

            # Allow per-case YAML to override costs (look for cost_fp/cost_fn)
            case_cost_fp = metadata.get("cost_fp", self.config.cost_fp)
            case_cost_fn = metadata.get("cost_fn", self.config.cost_fn)

            batch_config = BatchConfig(
                seeds=self.config.seeds,
                face_positions=self.config.face_positions,
                borehole_window=self.config.borehole_window,
                backend=self.config.backend,
                batch_size=self.config.batch_size,
                verbose=self.config.verbose,
                output_dir=case_output_dir,
                checkpoint_on_seed=self.config.checkpoint_on_seed,
                cost_fp=case_cost_fp,
                cost_fn=case_cost_fn,
            )

            runner = BatchRunner(case, batch_config)
            result = runner.run()

            # 각 row에 case metadata 추가
            # Normalize metric keys in summary rows and attach metadata
            import logging

            normalized_summary = []
            for s in result.summary_rows:
                try:
                    # ensure metadata-level cost aliases are canonicalized too
                    row = dict(s)
                    # first normalize any legacy cost keys present in the summary row
                    row = standardize_metrics(row)
                    # also apply canonicalization to case-level metadata that may use legacy keys
                    # e.g., YAML may contain cost_safe/cost_alarm
                    # canonicalize metadata keys as well before attaching
                    normalized_summary.append(row)
                except Exception as e:
                    logging.warning("standardize_metrics failed for summary row: %s", e)
                    normalized_summary.append(dict(s))

            result.summary_rows = normalized_summary

            self._attach_metadata(result.face_rows, metadata)
            self._attach_metadata(result.borehole_rows, metadata)
            self._attach_metadata(result.summary_rows, metadata)

            all_result.face_rows.extend(result.face_rows)
            all_result.borehole_rows.extend(result.borehole_rows)
            all_result.summary_rows.extend(result.summary_rows)

            if self.config.verbose:
                elapsed = time.time() - started
                average = elapsed / (i + 1)
                remaining = average * (total_cases - i - 1)
                print(
                    f"[MultiCase] case 완료: {i + 1}/{total_cases} "
                    f"진행률={(i + 1) / total_cases * 100:.1f}% "
                    f"예상 잔여={remaining / 60:.1f}분",
                    flush=True,
                )

        if self.config.save_combined:
            all_result.save_csv(self.config.output_dir, prefix="all_cases")
            if self.config.verbose:
                print(f"\n[MultiCase] combined CSV saved to: {self.config.output_dir}", flush=True)

        return all_result

    def _load_case_and_metadata(self, case_path: str):
        """
        case load + YAML tags 읽기

        YAML에 tags가 있으면 row에 같이 붙임.
        """
        case = CaseLibrary.load_case(case_path)

        metadata = {
            "case_path": case_path,
            "case_name_meta": case.name,
        }

        # YAML 파일이면 tags 읽기 및 비용 오버라이드 탐지
        if os.path.exists(case_path):
            try:
                with open(case_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}

                tags = data.get("tags", {}) or {}

                # tags 전체 flatten
                for k, v in tags.items():
                    metadata[k] = v

                # 자주 쓸 만한 항목 기본값
                metadata.setdefault(
                    "quality_regime", tags.get("quality_regime", "unknown")
                )
                metadata.setdefault(
                    "density_regime", tags.get("density_regime", "unknown")
                )
                metadata.setdefault(
                    "orientation_regime", tags.get("orientation_regime", "unknown")
                )
                metadata.setdefault(
                    "anisotropy_regime", tags.get("anisotropy_regime", "unknown")
                )

                # case-level cost override: look in top-level YAML, a top-level
                # `cost:` mapping, and tags for supported keys: cost_fp, cost_fn
                top_cost_fp = data.get("cost_fp")
                top_cost_fn = data.get("cost_fn")

                # also support a nested `cost:` mapping
                top_cost_block = data.get("cost") or {}
                if isinstance(top_cost_block, dict):
                    top_cost_fp = top_cost_fp or top_cost_block.get("cost_fp")
                    top_cost_fn = top_cost_fn or top_cost_block.get("cost_fn")

                tag_cost_fp = tags.get("cost_fp")
                tag_cost_fn = tags.get("cost_fn")

                if top_cost_fp is not None:
                    metadata["cost_fp"] = top_cost_fp
                elif tag_cost_fp is not None:
                    metadata["cost_fp"] = tag_cost_fp

                if top_cost_fn is not None:
                    metadata["cost_fn"] = top_cost_fn
                elif tag_cost_fn is not None:
                    metadata["cost_fn"] = tag_cost_fn

            except Exception as e:
                print(f"[WARN] Failed to read YAML metadata: {case_path}, {e}")

        return case, metadata

    def _attach_metadata(self, rows: List[Dict[str, Any]], metadata: Dict[str, Any]):
        for row in rows:
            for k, v in metadata.items():
                # 기존 case_name은 유지하고, metadata는 추가
                row[k] = v
