# QSimEx 단일 실행 산출물

단일 케이스의 3D 시각화 및 공간 출력 전용 폴더입니다.

## 포함 내용

- `scenario_<name>/`: `domain_fields.vti`, 절리·터널·시추공 VTP, PVD 시계열, `summary.json`
- `figures/`: PyVista 또는 단일 실행 시각화 이미지

## 생성 경로

- `run_cli.py --paraview --output-dir output`
- `run_cli.py --pyvista --output-dir output`
- `run_pyvista_viewer.py`

CSV 배치 결과나 통계 분석 결과는 이 폴더가 아니라 `../outputs/`에 저장합니다.
