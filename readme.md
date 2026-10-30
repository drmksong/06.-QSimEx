# QSimEx v4

현재 작업 영역은 v4 구현 준비를 위한 소스와 기준 문서로 구성합니다.
새 `rqd_exploration` 모듈에는 입력 검증, fingerprint serializer와 DFN 모델 adapter가
구현됐으며, 파일럿 실행 기능은 구현 전입니다.
루트 실행 진입점은 CLI에 연결되어 있지만, 현재는 미구현 오류와 종료 코드 2를 반환하며
simulation이나 DB 생성을 수행하지 않습니다.

## 기준 문서

- [전략 및 요구사항 계획](Specification/RQDExplorationStrategy_20261026/plan.md)
- [ImplementationPlan_v4](Specification/ImplementationPlan_v4.md)

두 문서를 구현의 주 기준으로 삼고, 과거 계약·분석·소스는 필요한 근거를 확인할 때만
보관 영역에서 참조합니다. 파일럿 실행과 후속 자동 탐색은 각 계획의 승인 경계를 따릅니다.

## 현재 진행 및 다음 재개 지점 (2026-10-29 22:01 +09:00)

- Phase 1–4 (T001–T007, P1.01–P4.07) 구현·검증 완료, 전체 175개 테스트 통과.
- 아직 남은 일반 파일럿 작업: Phase 5 T008 (P5.01–P5.02 점수 분석), T009
  (P5.03–P5.05 진단·CSV·analyze CLI), 그리고 Phase 6 T010 (P6.01–P6.04 인계 및
  사용자 실행 후 결과 기록).
- 다음 재개 위치는 **T008/P5.01**이며, 이 문구는 착수 승인이 아니다. P5.03–P5.04 전에
  미결 D005의 참조 profile/보고 field/support 계산 범위를 확인한다.
- 실제 pilot DB/manifest 저장, DFN 생성, simulation은 아직 수행하지 않았다. 사용자가
  config/manifest/예산을 검토하고 별도로 명시 승인하기 전에는 실행하지 않는다.
- T011 adaptive batch controller는 pilot 결과 검토와 별도 정책 승인 전까지 보류다.

이 요약이 과거 handoff 메모와 충돌하면 가장 최근 timestamped 현재 상태와 실행 기록을
기준으로 삼고, Phase 1–4를 다시 실행하지 않는다.

## 폴더 구조

```text
QSimEx/
├── readme.md
├── run_rqd_exploration.py      # CLI에 연결된 미구현 안내 진입점
├── config/
│   └── rqd_exploration_pilot.yml  # 승인값을 담은 검토용 초안; 실행 승인은 별도
├── Specification/
│   ├── ImplementationPlan_v4.md
│   └── RQDExplorationStrategy_20261026/
├── src/
│   ├── rqd_exploration/       # 입력 검증/fingerprint/adapter 및 후속 모듈 골격
│   ├── euler_campaign/        # v4가 재사용할 계산/backend 경계
│   ├── core/                 # 재사용 경계에 필요한 joint_models
│   └── test/                 # 재사용 계산 경계의 회귀 테스트
├── results/
│   └── rqd_exploration/       # 출력 위치만 준비; run 결과는 실행 시 생성
└── obsolete/                 # 이전 소스·문서·설정·분석·결과·실행 도구
```

`.git/`, `.gitignore`, `.vscode/`는 저장소·개발 환경 설정으로 루트에 유지합니다.
새 v4 설정과 결과 폴더는 보관 영역과 별개로 준비했습니다. P1.08의
[pilot YAML](config/rqd_exploration_pilot.yml)은 승인된 두 block의 입력을 담은 검토용 초안입니다.
Parser 검증은 통과하지만 실행 승인을 뜻하지 않습니다.
[설계 모듈](src/rqd_exploration/design.py)은 P2.01 목표 ledger와 P2.02 block별 randomized
LHS 생성까지 구현했습니다. 승인 pilot은 각 block 5개, 총 10개 표본이며 로그 P32·정렬
로그 반경쌍·set별 방향 및 독립 α/κ stream을 사용합니다. 원 LHS 좌표·최종 입력·생성
version을 immutable 결과에 보존합니다. P2.03b의
[`build_mlx_pilot_manifest`](src/rqd_exploration/runner.py)는 MLX GPU preflight로 확인한
backend/device와 Python·NumPy·SciPy·MLX/platform runtime 및 실제 generator/measurement/
boundary version을 snapshot에 기록합니다. 실제 runtime 결과는 Python 3.11.15, NumPy 2.4.3,
SciPy 1.17.1, MLX 0.31.1, `Device(gpu, 0)`입니다. 승인 입력과 측정 planner에서 전체 10-job
계획(각 job당 60 BH interval + 61 face station, 총 1,210 location)을 생성합니다.
P2.04b에서 전체 위치의 geometry/간격, support/scanline 및 job-key 연결을 독립 기대값으로
검증했습니다. T006의 P4.01–P4.03에서 SQLite schema v1, composite-key/FK projections,
부분 관측 보존, same-attempt resume 및 원자적 완료 경계를 구현·검증했습니다. Resume은
저장된 관측을 유지하고 미완료 위치만 식별합니다. P4.04 Runner는 전체 attempt의 활성
구간을 monotonic clock으로 누적하며, 비정상 중단 뒤에는 `runtime_is_lower_bound`로
하한값임을 표시합니다. 성공한 job은 건너뛰고 동일 running attempt를 재개하며, 실패
attempt는 자동 재시도하지 않습니다. 완료 결과 commit 전에 중단된 현재 job의 DFN은
재생성될 수 있지만 이전에 commit된 job은 재실행하지 않습니다. P4.05 maximum simulation
상한은 필수 양의 정수이며 명령 실행 1회에서 새로 시작하는 simulation 횟수에 적용됩니다.
상한에 도달하면 다음 job 전에 멈추고 반환 요약에서 모든 미완료 목표를
`unresolved_at_budget`으로 표시합니다. resume 명령마다 사용자가 새 상한을 입력합니다.
이 종료/목표 상태는 현재 반환 요약에만 담기며 DB에는 별도 실행 상태로 저장하지 않습니다.
CLI는 `validate`, `preview`, `run`, `resume` 명령을 제공합니다. `validate`는 YAML만 검사하고,
`preview`는 MLX GPU preflight와 manifest 요약을 메모리에서 수행하며 DB write나 simulation은
하지 않습니다. 실행 전에는 preview에서 검토한 동일한 config와 manifest ID를 사용하고
필수 `--maximum-simulations`와 `--confirm-execution`을 명시해야 합니다. `run`은 새 DB 경로만
허용하고, `resume`은 기존 schema-v1 DB의 저장 manifest와 현재 config/runtime manifest가
정확히 일치해야 합니다. CPU fallback은 지원하지 않습니다. 예시:

```sh
python run_rqd_exploration.py validate
python run_rqd_exploration.py preview --manifest-id <manifest-id>
# 실제 실행은 사용자가 입력·manifest·예산을 검토한 후 직접 확인해 실행:
python run_rqd_exploration.py run --manifest-id <manifest-id> \
  --database results/rqd_exploration/<run-id>/pilot.sqlite \
  --maximum-simulations <positive-integer> --confirm-execution
```

P4.07 subprocess 검증은 임시 DB와 모의 runner를 사용해 CLI 실행 경계를 검증합니다. 전체
175개 테스트가 통과했습니다. 실제 pilot DB/manifest는 만들지 않았고 simulation도
실행하지 않았습니다. Phase 4 구현 검증은 완료됐지만 실제 pilot 실행은 별도 승인 사항입니다.
Phase 2 설계/manifest 검증은 완료됐지만 pilot execution은 승인되지 않았습니다.
P3.03–P3.05의 measurement producer는 clipped BH full 1 m interval, Q′와 독립적인 fixed
1 m face station, actual support, raw hit evidence와 unavailable boundary 상태를 생성합니다.
P2.04a의 fixture 검증과 P2.04b의 실제 producer 전체 위치 검증이 모두 통과했습니다.
[DFN adapter](src/rqd_exploration/adapter.py)는 실제 표본값을 받아 기존
`CaseSpec`만 구성하며 simulation은 실행하지 않습니다. 기존 모델 호환용 Jr=1/Ja=1은
`generation-only-jr`/`generation-only-ja`로 식별하며 관측의 Q′ 계산에 사용하면 안 됩니다.
Face advance는 기존 가변 굴진 순회로 전달하지 않고 새 측정 모듈에서 적용합니다.
개발·테스트 환경은 conda `dlo-cq`를 사용합니다. 결과 폴더의 `.gitkeep`만
버전 관리하고 실제 DB·CSV·run 하위 폴더는 실행 시 생성하며 Git에서 제외합니다.
보관된 설정·결과 폴더를 새 실행 대상으로 사용하지 않습니다.

## 과거 자료 참조

- [이전 전체 소스](obsolete/src_obs/)
- [과거 문서 및 설계 계약](obsolete/Specification/)
- [분석 자료](obsolete/Analysis/)
- [케이스](obsolete/cases/) 및 [설정](obsolete/config/)
- [기존 도구](obsolete/tools/)
- [이전 README](obsolete/readme.md)

그 밖의 이전 결과·그림·검증·trial·legacy 폴더도 원래 이름과 내부 구조를 유지한 채
`obsolete/`에 보관했습니다. 보관된 스크립트와 README의 실행 명령은 과거 경로를 전제로
하므로 현재 루트에서 바로 실행 가능한 v4 명령이 아닙니다.

## 회귀 테스트

프로젝트 루트에서 기존 `dlo-cq` 환경으로 실행합니다.

```bash
conda run -n dlo-cq python -m unittest discover -s src/test -p 'test_*.py' -v
```

이 명령은 현재 `src/test/`의 재사용 경계를 검증하며, 아직 구현하지 않은 v4 파일럿의
완료나 실행 승인을 의미하지 않습니다.
