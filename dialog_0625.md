# dialog_0625

Date: 2026-06-25

## Quick Resume

- Goal: judge whether borehole Q' can explain tunnel Q' in disposal-relevant low-fracture conditions.
- Final reading: overall positive linear relation is strong, but within-case relation is weak.
- Conclusion: Q' is conditionally useful as a support signal, not a standalone decision rule.
- Next likely step: refine the PyVista 3D inspection and keep Q' plots auto-saved with each run.

## Context Summary

오늘의 핵심 작업은 처분터널 조건에서 수평 시추공 Q'이 실제 터널 Q'를 얼마나 잘 설명하는지 평가하는 것이었다.

관점은 단순한 합격/불합격 분류보다, borehole Q'와 tunnel Q' 사이의 양의 선형관계가 존재하는지와 그 관계가 같은 조건 내부에서도 유지되는지로 정리했다.

## What Was Done

- 멀티케이스 배치 실험을 수행했다.
- 저절리 처분장 조건을 염두에 두고 케이스를 큐레이션했다.
- 완료된 5개 케이스:
  - scenario_03_sparse_large
  - scenario_05_orthogonal_two_sets
  - scenario_06_layered_density
  - scenario_07_isotropic
  - scenario_10_fieldlike
- 완료 결과를 통합 CSV로 정리했다.
  - outputs/disposal_lowfract_curated/all_cases_summary_rows.csv
  - outputs/disposal_lowfract_curated/all_cases_face_rows.csv
  - outputs/disposal_lowfract_curated/all_cases_borehole_rows.csv

## Main Findings

- 전체 통합 기준에서는 Q'\_borehole 와 Q'\_tunnel 사이에 강한 양의 선형관계가 나타났다.
  - Pearson r ~= 0.951
  - Spearman rho ~= 0.934
  - slope > 0
- 그러나 케이스 내부에서는 관계가 매우 약하거나 거의 사라졌다.
  - 케이스별 Pearson은 대체로 0에 가깝거나 약한 수준이었다.
  - within-case centered correlation도 매우 약했다.
- 해석:
  - 케이스 간 구조 차이에 의해 전체 상관이 크게 보이는 경향이 있다.
  - 같은 조건 내부에서 tunnel Q'를 정밀 예측하는 단독 지표로는 아직 약하다.
  - 보조 지표 또는 Bayesian evidence의 한 축으로는 의미가 있다.

## Interpretation for Q'

- Q'은 완전히 버릴 수준은 아니다.
- 다만 단독 판정 지표로 강하게 채택하기보다 조건부 채택이 적절하다.
- 즉, 구조 차이/케이스 수준 비교에는 쓸 수 있지만, 동일 조건 내부의 예측력은 추가 검증이 필요하다.

## Visualization Work

- Q' 관계를 볼 수 있는 멀티케이스 플롯을 추가했다.
  - run_multicase_plot.py
  - src/visualization/plots.py 에 plot_multicase_qprime 추가
- 3D 가시화를 위해 PyVista 뷰어를 추가했다.
  - run_pyvista_viewer.py
  - src/visualization/pyvista_viewer.py
- CLI에 PyVista 옵션도 연결했다.
  - --pyvista
- 의존성에 pyvista를 추가했다.

## Run Notes

- conda 환경은 dlo-cq
- PyVista는 해당 환경에 설치되어 있다.
- 플롯 저장 스모크 테스트는 성공했다.
- PyVista 뷰어 import도 성공했다.

## Useful Commands

```bash
conda run -n dlo-cq python run_multicase_plot.py --save-path outputs/disposal_lowfract_curated/qprime_multicase.png
```

```bash
conda run -n dlo-cq python run_pyvista_viewer.py --case-dir outputs/disposal_lowfract_curated/by_case_pure/scenario_07_isotropic
```

```bash
conda run -n dlo-cq python run_cli.py --case scenario_07_isotropic --pyvista
```

## Next Step Suggestion

- 남은 작업은 PyVista에서 절리/터널/시추공 토글 옵션을 더 세밀하게 만들거나,
- Q' 플롯을 결과 폴더에 자동 저장하도록 정리하는 것이다.
