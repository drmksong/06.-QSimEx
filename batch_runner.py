"""
Monte Carlo batch runner
- 여러 seed / 여러 case 반복 실행
- face-level / borehole-level 결과 row 수집
- CSV 저장 지원
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
import copy
import csv
import os
import time

from src.core.domain import AnalysisCase, RockDomain
from src.core.tunnel import Tunnel
from src.core.comparison import ComparisonEngine
from src.core.reporting import ResearchReporter


@dataclass
class BatchConfig:
    """배치 실행 설정"""

    seeds: List[int]
    face_positions: Optional[List[int]] = None
    borehole_window: int = 3
    backend: str = "auto"
    batch_size: int = 500
    verbose: bool = True
    output_dir: Optional[str] = None
    correction_mode: str = "pure"
    # Costs for Bayesian decision reporting (FP, FN)
    # Defaults changed to centralised defaults: cost_fp=1 (false-positive), cost_fn=5 (false-negative)
    cost_fp: float = 1.0
    cost_fn: float = 5.0


@dataclass
class BatchResult:
    """배치 실행 결과"""

    face_rows: List[Dict[str, Any]] = field(default_factory=list)
    borehole_rows: List[Dict[str, Any]] = field(default_factory=list)
    summary_rows: List[Dict[str, Any]] = field(default_factory=list)

    def save_csv(self, output_dir: str, prefix: str = "batch_result"):
        """결과를 CSV 파일로 저장"""
        os.makedirs(output_dir, exist_ok=True)

        if self.face_rows:
            self._write_csv(
                os.path.join(output_dir, f"{prefix}_face_rows.csv"), self.face_rows
            )

        if self.borehole_rows:
            self._write_csv(
                os.path.join(output_dir, f"{prefix}_borehole_rows.csv"),
                self.borehole_rows,
            )

        if self.summary_rows:
            self._write_csv(
                os.path.join(output_dir, f"{prefix}_summary_rows.csv"),
                self.summary_rows,
            )

    @staticmethod
    def _write_csv(path: str, rows: List[Dict[str, Any]]):
        """dict list → csv"""
        if not rows:
            return

        # 모든 key 합집합
        fieldnames = []
        seen = set()
        for row in rows:
            for k in row.keys():
                if k not in seen:
                    seen.add(k)
                    fieldnames.append(k)

        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)


class BatchRunner:
    """
    Monte Carlo batch runner

    역할:
      - case × seed 반복 실행
      - domain 생성
      - tunnel 생성
      - comparison 실행
      - 결과 row 수집
    """

    def __init__(self, case: AnalysisCase, config: BatchConfig):
        self.case = case
        self.config = config

    def run(self) -> BatchResult:
        """배치 실행"""
        result = BatchResult()

        n_total = len(self.config.seeds)
        t0_all = time.time()

        for i, seed in enumerate(self.config.seeds):
            t0 = time.time()

            if self.config.verbose:
                print(f"\n[Batch] {i+1}/{n_total} seed={seed} 실행 중...")

            case_seeded = self._clone_case_with_seed(self.case, seed)

            # 1) Domain 생성
            domain = RockDomain(case_seeded)
            domain.generate(
                verbose=False,
                backend=self.config.backend,
                batch_size=self.config.batch_size,
            )

            # 2) Tunnel + Comparison
            tunnel = Tunnel(domain, correction_mode=self.config.correction_mode)
            engine = ComparisonEngine(tunnel)

            comparisons = engine.progressive_comparison(
                face_positions=self.config.face_positions,
                borehole_window=self.config.borehole_window,
            )
            summary = engine.summary_statistics(comparisons)

            # 3) row 변환
            face_rows = engine.comparisons_to_face_rows(
                comparisons=comparisons, case_name=case_seeded.name, seed=seed
            )
            borehole_rows = engine.comparisons_to_borehole_rows(
                comparisons=comparisons, case_name=case_seeded.name, seed=seed
            )
            summary_row = self._summary_to_row(
                summary=summary, case_name=case_seeded.name, seed=seed
            )

            result.face_rows.extend(face_rows)
            result.borehole_rows.extend(borehole_rows)
            result.summary_rows.append(summary_row)

            elapsed = time.time() - t0
            if self.config.verbose:
                print(
                    f"[Batch] seed={seed} 완료 ({elapsed:.1f}초), "
                    f"faces={len(comparisons)}"
                )

        total_elapsed = time.time() - t0_all
        if self.config.verbose:
            print(f"\n[Batch] 전체 완료: seeds={n_total}, " f"총 {total_elapsed:.1f}초")

        # 자동 저장 옵션
        if self.config.output_dir:
            prefix = self.case.name
            result.save_csv(self.config.output_dir, prefix=prefix)
            # Generate research tables CSVs (Table1..Table5)
            try:
                ResearchReporter.save_all_tables_as_csv(
                    face_rows=result.face_rows,
                    summary_rows=result.summary_rows,
                    output_dir=self.config.output_dir,
                    prefix=prefix,
                    cost_fp=self.config.cost_fp,
                    cost_fn=self.config.cost_fn,
                )
                if self.config.verbose:
                    print(
                        f"[Batch] Research tables CSV 생성 완료: {self.config.output_dir}"
                    )
            except Exception as e:
                print(f"[Batch] Research table generation 실패: {e}")
            if self.config.verbose:
                print(f"[Batch] CSV 저장 완료: {self.config.output_dir}")

        return result

    def _clone_case_with_seed(self, case: AnalysisCase, seed: int) -> AnalysisCase:
        """seed만 바꾼 case 복제"""
        case_copy = copy.deepcopy(case)
        case_copy.seed = seed
        return case_copy

    def _summary_to_row(
        self, summary: Dict[str, Any], case_name: str, seed: int
    ) -> Dict[str, Any]:
        """summary dict → 1 row"""
        row = {
            "case_name": case_name,
            "seed": seed,
        }

        for k, v in summary.items():
            if isinstance(v, dict):
                # diagnostic 같은 nested dict는 1-depth flatten
                for kk, vv in v.items():
                    row[f"{k}_{kk}"] = vv
            else:
                row[k] = v

        return row
