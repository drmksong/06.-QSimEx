# Q-Rock Simulator v0.2

터널 전방 시추공 Q값/Q'값과 굴진면 Q값/Q'값의 공간적 비교를 수행하는 시뮬레이터입니다.

## 개요

터널 굴착 전에 수평 시추공으로 얻은 지표(Q, Q')가 실제 굴진면 조건을 어느 정도 설명하는지,
DFN 기반 가상 암반에서 반복 실험으로 평가합니다.

핵심 목적 예시:

- Q'의 예측 가능성 평가 (borehole Q' vs tunnel Q')
- 저절리 처분장 조건에서의 적용성 확인
- 케이스/시드 반복을 통한 통계적 경향 확인

## 핵심 기능

- 물리 기반 DFN 생성
  - 절리 크기: Power Law
  - 절리 방향: Fisher
  - 절리 형상: 원판(Disk)
- RQD 계산
  - Deere 직접법
  - Priest-Hudson 근사
- Q-System 파라미터 필드 계산
- 시추공 vs 막장면 비교 분석
- 배치/멀티케이스 실행 및 CSV 산출
- ParaView/PyVista 3D 시각화

## 설치

권장: conda 환경 사용

```bash
pip install -r requirements.txt
```

## 빠른 시작

### 1) 케이스 목록 확인

```bash
python run_cli.py --list-cases
```

### 2) 단일 케이스 실행

```bash
python run_cli.py --case granite_2sets --visualize
```

### 3) 단일 케이스 + 3D 내보내기

```bash
python run_cli.py --case scenario_07_isotropic --paraview --output-dir output
```

### 4) 멀티케이스 실행

```bash
python run_multicase_test.py
```

## 주요 실행 스크립트

### run_cli.py

단일 케이스/배치 실행용 메인 CLI입니다.

주요 옵션:

- 입력
  - --case: 케이스 이름
  - --case-file: YAML 경로 직접 지정
  - --case-dir: 케이스 디렉토리 (기본: cases)
- 분석
  - --face-positions: 굴진면 x 인덱스 목록
  - --bh-window: 시추공 평균 윈도우 (기본 3)
  - --seed: 시드 오버라이드
  - --backend: auto/cuda/mps/mlx/cpu
  - --batch-size: 백엔드 배치 크기
- 출력
  - --visualize: Matplotlib 그래프
  - --verify-dfn: DFN 분포 검증 그래프
  - --paraview: VTK 파일 내보내기
  - --pyvista: VTK 내보내기 후 PyVista 즉시 표시
  - --export: 결과 JSON 저장 경로
  - --output-dir: 내보내기 디렉토리 (기본: output)
- 관리/배치
  - --list-cases
  - --init-cases
  - --batch

예시:

```bash
python run_cli.py --case sedimentary_3sets --paraview --visualize --output-dir output
```

```bash
python run_cli.py --case granite_2sets --face-positions 20 40 60 80 --backend mlx
```

### run_multicase_test.py

처분장 저절리 조건을 가정한 큐레이션 케이스 멀티런 스크립트입니다.

현재 기본 설정:

- 케이스: 5개 (scenario_03/05/06/07/10)
- seeds: 40~59
- face_positions: 10,20,30
- output_dir: outputs/disposal_lowfract_curated

실행:

```bash
python run_multicase_test.py
```

### run_multicase_plot.py

멀티케이스 통합 CSV를 읽어 Q' 관계 플롯(전체 + 케이스별)을 생성합니다.

옵션:

- --input-dir: 통합 CSV 디렉토리 (기본: outputs/disposal_lowfract_curated)
- --save-path: 이미지 저장 경로 (생략 시 화면 표시)

예시:

```bash
python run_multicase_plot.py --save-path outputs/disposal_lowfract_curated/qprime_multicase.png
```

### run_pyvista_viewer.py

내보낸 VTK 결과를 PyVista로 시각화합니다.

옵션:

- --case-dir: 내보내기 케이스 폴더 (예: output/scenario_07_isotropic)
- --scalar: 단면 컬러 스칼라 (기본: Qprime)
- --screenshot: 스크린샷 저장 경로
- --off-screen: 오프스크린 렌더링
- --no-save: 자동 스크린샷 저장 비활성화

기본 저장 정책:

- screenshot 미지정 시 output/figures/<case>\_pyvista.png 자동 저장

예시:

```bash
python run_pyvista_viewer.py --case-dir output/scenario_07_isotropic
```

```bash
python run_pyvista_viewer.py --case-dir output/scenario_07_isotropic --screenshot output/figures/custom.png --off-screen
```

## 출력 폴더 규칙 (중요)

혼동 방지를 위해 아래처럼 구분합니다.

- output/
  - 단일 케이스 run_cli 내보내기 기본 폴더
  - VTI/VTP/PVD 및 PyVista 스크린샷 기본 경로(output/figures)
- outputs/
  - 멀티케이스/분석용 집계 결과 폴더
  - 예: outputs/disposal_lowfract_curated

즉, 단일 3D 내보내기는 output, 멀티케이스 집계는 outputs를 기본으로 사용합니다.

## 대표 산출물

멀티케이스 통합 CSV 예시:

- outputs/disposal_lowfract_curated/all_cases_face_rows.csv
- outputs/disposal_lowfract_curated/all_cases_borehole_rows.csv
- outputs/disposal_lowfract_curated/all_cases_summary_rows.csv

단일 케이스 3D 내보내기 예시:

- output/scenario_07_isotropic/domain_fields.vti
- output/scenario_07_isotropic/joints_all.vtp
- output/scenario_07_isotropic/tunnel.vtp
- output/scenario_07_isotropic/boreholes.vtp
- output/scenario_07_isotropic/face_traces/\*.vtp
- output/scenario_07_isotropic/excavation_series.pvd
- output/figures/scenario_07_isotropic_pyvista.png

## 참고 스크립트

분포 검증:

```bash
python run_verify.py
```

GUI 실행:

```bash
python run_gui.py
```
