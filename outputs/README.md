# QSimEx 반복 실행 산출물

여러 seed, 케이스, 굴진면 위치를 반복 실행한 데이터와 분석 결과를 보관합니다.

## 디렉터리

- `disposal_lowfract_curated/`: 처분장 저절리 대표 케이스의 주요 분석 데이터
- `test_multicase/`: 멀티케이스 테스트·디버그 결과
- `granite_rqd_p32_rot/`: 화강암 RQD/P32 회전 실험 결과
- `deleteit/`: 삭제 전 확인이 필요한 임시 보관 영역. 새 결과 저장 금지

각 실험 디렉터리에는 가능한 한 다음 구조를 유지합니다.

- `all_cases_*_rows.csv`: 전체 통합 결과
- `by_case_<correction_mode>/`: 케이스별 원자료
- `analysis/`: 임계값, 비용, 의사결정 분석 결과

## 생성 코드

- `run_multicase_test.py`
- `run_multicase_plot.py`
- `multi_case_descision.py`
- `analyze_rqd_method.py`

단일 케이스의 VTK/VTP/PyVista 파일은 상위 `../output/`에 저장합니다.
