# QSimEx v4

DFN 입력 설계와 RQD 관측을 연결하고, 누적 원관측에 Jr/Ja 시나리오를 적용해 Q′를
분석하는 작업 영역입니다. 고정 LHS 설계, DFN 생성·측정, SQLite 저장, 수동 batch
추가·중단 재개, 누적 재분석·CSV 보고와 BH 목표별 자동 메인 탐색 기능을 제공합니다.

메인 탐색기(T011)는 별도 정책·제어 장부를 사용합니다.
시그니처는 **DFN → RQD 관계**를 표현하며 `(RQD, Jn, Jr, Ja)` 점수 조합과
구분합니다. 구현·테스트 완료는 현재 파일럿의 실제 실행 완료나 메인 실행 승인이 아닙니다.

## 기준 문서와 승인 경계

- [전략 및 요구사항 계획](Specification/RQDExplorationStrategy_20261026/plan.md):
  최신 사용자 합의, 과학적 의미와 승인 범위
- [구현 계획](Specification/ImplementationPlan_v4.md):
  작업 순서, 검증 결과, 단계별 이력과 다음 작업
- [작업 체크포인트](Specification/RQDExplorationStrategy_20261026/checkpoints/tasks-to-impl.yaml):
  인계 기록; 오래된 필드는 두 계획의 최신 기록과 대조

실제 DB 생성·manifest 저장·DFN 생성·simulation은 별도 명시 승인이 필요합니다.
메인 실행은 코드 사용 안내와 구별되는 별도 승인 경계입니다.
README는 현행 사용 안내이며 단계별 작업 이력은 위 기준 문서에서 관리합니다.

## 폴더 구조

```text
QSimEx/
├── readme.md
├── run_rqd_exploration.py       # 실제 package CLI 진입점
├── config/
│   ├── rqd_exploration_pilot.yml   # Jn 2/4, 절리군 1/2
│   ├── rqd_exploration_pilot2.yml  # Jn 9/15, 절리군 3/4; pilot CLI 기본값
│   ├── rqd_exploration_jn20.yml    # Jn20, 5군, LHS5, design seed40/realization43
│   └── rqd_exploration_main.yml    # 승인된 메인 정책과 입력 파일 연결
├── Specification/
│   ├── ImplementationPlan_v4.md
│   └── RQDExplorationStrategy_20261026/
├── src/
│   ├── rqd_exploration/        # 설계·측정·저장·실행·누적 분석/보고
│   ├── euler_campaign/         # 재사용 계산/backend 경계
│   ├── core/                  # 재사용 joint_models
│   └── test/                  # 기존 계산 및 v4 회귀·통합 테스트
├── results/
│   └── rqd_exploration/        # 기본 보고 출력 위치
└── obsolete/                  # 보관된 이전 소스·문서·설정·분석·결과
```

`.git/`, `.gitignore`, `.vscode/`는 저장소·개발 환경 설정입니다.
실제 DB·CSV는 실행/보고 시 생성하며 버전 관리하지 않습니다.

## 파일럿 입력

| 설정 | fixed_Jn | 대응 절리군 수 | LHS 표본 |
|---|---|---|---|
| [pilot](config/rqd_exploration_pilot.yml) | 2, 4 | 1, 2 | 조건당 5개, 총 10 jobs |
| [pilot2](config/rqd_exploration_pilot2.yml) | 9, 15 | 3, 4 | 조건당 5개, 총 10 jobs |

실행 허용 Jn은 `{2,4,9,15,20}`이며 절리군 수 `{1,2,3,4,5}`와 대응합니다.
Jn15/20은 승인된 대표·근사 구성이고, Jn20은 현재 두 YAML에 포함되지 않습니다.
Jn0.5/1은 과거 실험용이며 새 실행 대상이 아닙니다.

각 파일은 design seeds 39/36과 realization seed 43을 사용합니다.
job은 한 DFN 입력 시그니처와 realization seed의 생성·측정 단위이며 위치 수와 다릅니다.
각 파일은 BH 600개 + face 610개, 총 1,210개 위치를 계획합니다.
YAML 입력 schema는 1, 누적 SQLite schema는 4로 서로 다릅니다. `target_goals`는 사용하지
않으며 파일럿은 특정 bin 충족을 강제하지 않고 전체 bin을 분석합니다.
Jn은 생성 입력에 고정하고 Jr/Ja는 후처리 축으로 적용합니다.

## 환경과 CLI

프로젝트 루트에서 기존 conda `dlo-cq`만 사용합니다. `.venv`나 다른 환경을 만들거나
사용하지 않습니다. 사용자가 승인 후 실제 실행할 때는 환경을 활성화하고 `python -u`로
실시간 진행 로그를 확인합니다. MLX GPU를 사용하며 CPU로 묵시 fallback하지 않습니다.

| 명령 | 동작 및 저장 경계 |
|---|---|
| `validate` | YAML 검증. MLX preflight·DB write·simulation 없음 |
| `preview` | MLX preflight와 메모리 manifest 요약. DB/manifest 저장·simulation 없음 |
| `run` | 명시 확인 후 새 schema4 DB 생성, 새 batch 추가 또는 정확히 일치하는 미완료 batch 재개 |
| `analyze` | 단일 manifest의 저장 자료 분석·파생 분석 저장·CSV 보고. `--manifest-id` 필요 |
| `analyze-cumulative` | 누적 자료 revision·재점수 분석을 immutable 기록으로 DB에 저장 |
| `report-cumulative` | 저장된 누적 revision으로 CSV 보고. DB는 read-only지만 출력 파일은 생성 |
| `validate-main` | 메인 정책과 참조 YAML 검증. DB 접근·MLX preflight·생성 없음 |
| `preview-main` | 활성 목표/도달성·선택 초기 입력/기대 비용; 선택한 기존 DB는 read-only |
| `run-main` | 명시 확인 후 메인 제어/원자료 저장·자동 탐색·누적 보고; 중단 상태는 JSON으로 구별 |
| `measure-p32` | 명시 확인 후 저장된 seed/backend/생성 mode로 기하만 재생성해 in-domain P32 추가 저장; 완료 입력은 skip |

별도 `resume` 명령은 없습니다. `run/preview`에는 `--manifest-id`를 주지 않습니다.
실행 batch ID는 내부 생성되며 preview의 ID는 저장된 실행 ID가 아닙니다.
누적 분석/보고에는 `--manifest-id`가 필요하지 않습니다.

다음은 DB를 열거나 simulation을 수행하지 않는 검토 명령입니다.
**기본 설정은 pilot2**이므로 첫 파일 검토에는 `--config`를 명시합니다.

```sh
conda run -n dlo-cq python run_rqd_exploration.py --help
conda run -n dlo-cq python run_rqd_exploration.py run --help
conda run -n dlo-cq python run_rqd_exploration.py validate --config config/rqd_exploration_pilot.yml
conda run -n dlo-cq python run_rqd_exploration.py preview --config config/rqd_exploration_pilot.yml
```

실행 명령의 형식은 다음과 같습니다. **자리표시자는 실행용 값이 아니며, 이 안내는
실행 승인이 아닙니다.** config·DB·예정 작업·실행 순서를 확인하고 명시 승인 후 사용합니다.
고정 파일럿은 별도 상한 없이 저장된 작업 목록을 순서대로 처리합니다.
후속 설정을 자동 실행하지 않습니다.

```text
python -u run_rqd_exploration.py run --config <approved-config> --database <approved-db> --confirm-execution
python -u run_rqd_exploration.py analyze-cumulative --database <approved-db>
python -u run_rqd_exploration.py report-cumulative --database <approved-db> --output-dir <approved-output-dir>
```

누적 보고는 먼저 저장된 누적 revision이 필요합니다. `--revision-index`로 기존 revision을
선택할 수 있으며 생략하면 최신 것을 사용합니다. 누적 분석/보고의 `--jr-values`와
`--ja-values`는 후처리 시나리오 부분집합을 선택하며 원관측을 바꾸거나 DFN을 재생성하지 않습니다.

## 메인 탐색 사용

```sh
conda run -n dlo-cq python run_rqd_exploration.py validate-main
conda run -n dlo-cq python run_rqd_exploration.py preview-main --config config/rqd_exploration_main.yml
```

`preview-main --database <existing-schema4-db>`는 현재 원자료와 제어 상태를 읽기만 합니다.
DFN 생성이나 제어 DDL, CSV 출력은 하지 않으며 MLX 실행 가능성을 검증한 결과는 아닙니다.
메인 명령의 기본 config는 `rqd_exploration_main.yml`이고 기존 파일럿 명령은 pilot2를 유지합니다.
메인 정책 값은 승인값으로 검증하며 YAML을 임의 튜닝하는 인터페이스가 아닙니다.

명시적으로 승인한 실제 실행에만 다음 형식을 사용합니다. 이 예시는 실행 승인이 아닙니다.

```text
python -u run_rqd_exploration.py run-main --config <approved-main-config> --database <approved-db> --output-dir <approved-reports-root> --confirm-execution
```

이 작업공간의 DB와 메인 결과는 Documents 밖의
`/Users/myungkyusong/QSimExOutput`으로 이동했습니다. 이 환경에서 새 메인 실행/재개 시
아래 경로를 명시해야 합니다. `--output-dir`을 생략하면 CLI 기본값이 다시 저장소 내부
`results/rqd_exploration`을 사용하므로 Documents에 결과가 생길 수 있습니다.

```text
conda run -n dlo-cq python -u run_rqd_exploration.py run-main --config config/rqd_exploration_main.yml --database /Users/myungkyusong/QSimExOutput/sqlite/qsimex-rqd-v4.sqlite --output-dir /Users/myungkyusong/QSimExOutput/results/rqd_exploration --confirm-execution
```

- 현재 단일 run은 최대20,000 starts, 10,000 starts에서 수동 review checkpoint입니다.
  이번 정책 변경은 설정 fingerprint를 바꾸므로 이전 300-start run을 재개하지 않고 별도 run을
  만듭니다. 같은 DB를 사용해 기존 원자료와 누적 분석을 보존합니다. 새 run이 checkpoint에서
  멈춘 뒤에는 동일 config/database/output-dir의 명령을 다시 실행해 같은 run을 이어갑니다.
- 기본 설정은 `initial_input: null`이며 Jn20 생성/목표를 제외합니다.
  기존 Jn2/4/9/15 자료를 재사용해 추가 초기 생성 없이 bin10부터 하향합니다.
  `(bin,Jn,Jr,Ja,BH profile)` 목표의 RQD upper가 Jn별 PH floor 이상이고 lower가100 미만이어야 합니다.
  PH floor는 `max(10,100*exp(-n_sets)*(1+n_sets))`를 소수1자리로 반올림하며
  Jn2/4/9/15에서73.6/40.6/19.9/10입니다. 이는 목표 도달성만 제한하며 관측 자료를 필터하지 않습니다.
  원자료 RQD0도 보존하며 계산에만 floor10을 적용합니다.
  Jn20 파일/5군 지원은 보존합니다. 별도 승인 후 `initial_input`에 Jn20 YAML 경로를
  지정하면 LHS5/design40/realization43 초기 생성과 Jn20 목표를 함께 포함합니다.
  선택 변경은 fingerprint에 반영되며 기존 메인 run의 정책/예산을 묵시적으로 바꾸지 않습니다.
- 메인은 별도 baseline YAML에서 군별 P32 `[0.01,10]`, 반경 `[1,150]`m을 log LHS로 뽑습니다.
  Alpha `[2.5,4]`, kappa `[0,50]`, 방향 bounds는 유지하며 P32 step은0.1/1.0입니다.
  기존 파일럿 YAML/기본 생성기는 변경하지 않습니다.
- 목표마다 실제 양의 BH support를 가진 생성 입력3개가 필요합니다. Seed·Jr/Ja·
  주석·장치 runtime 변경을 다른 생성 입력으로 세지 않습니다. 생성 mode는 물리 입력 identity에 포함합니다.
  각 입력은 seed44부터 겹치지 않는
  3-seed 그룹의 CDF/support 차이 각각10%p 이하를 연속2회 통과해야 합니다.
  모두0인 목표 support는 통과가 아니며 실패한 안정성 관측도 누적 자료에 남습니다.
- 신규 후보는 회차당 최대8/2/2(한 축/복수 축/LHS)입니다. 진전 확인 입력 최대2개,
  완전 안정성 확인 입력1개를 배정하며 적격 입력3개가 있으면 검증을 우선합니다.
  신규 bounds 밖의 기존 자료도 목표 판단에는 포함하지만 mutation 참조에서는 제외하고 사유를 기록합니다.
  적격 참조가 없으면 신규 LHS를 최대12개 배정하며 참조가 생기면8/2/2로 돌아갑니다.
  같은 우선순위의 참조는 완전한 두 축의 ±작은/큰 step 묶음을 유지하며 순환합니다.
  진전 문턱은 거리1 RQD 포인트/support1%p와 다른 지표의 실제 비악화 조건입니다.
  개선 문턱보다 작은 악화도 비악화로 취급하지 않습니다. 최초2/3이며 정확히1/3일 때만
  2개를 추가해3/5로 판정합니다. 이는 안정성 확인 및 최종 통계적 충분성과 다릅니다.
- 메인 시작 예산은 논리 run당 최대20,000회입니다. 참조·실패·중단 후 재생성도 차감하고 저장된
  입력/seed 재사용은 차감하지 않습니다. 기대 절리 수1000만 초과는 생성 전에 검토 중단하며
  정확히1000만은 허용합니다. 10,000회에서 수동 검토용 review checkpoint로 중단합니다.
  검토 후 동일 `run-main` 명령을 다시 실행하면 같은 run에서 남은 예산으로 재개하며 횟수는
  초기화되지 않습니다. 목표 완료나 다른 정책/실행 중단이 먼저 발생하지 않으면 20,000회에
  멈춥니다. 기대값은 실제 개수·시간·메모리 보장이 아닙니다.
- 완료된3회차 무진전, 예산, 고비용, 오류, 비교 불가, 후보 소진, 목표 완료,
  사용자 중단을 구분합니다. 오류 자동 재시도는 없습니다. 사용자 중단만 동일 명령으로
  자동 재개하며 미완료 DFN 재생성은 추가 차감합니다. 다른 pause는 별도 검토/승인 경계입니다.
  `--recover-incomparable`은 예외적으로, saved queue의 안정성 샘플이 이미 성공했고
  현재 누적 원자료에서 해당 seed의 유효 BH support가 복구된 경우에만 명시적으로 재개합니다.
  이 경우 저장된 관측을 재사용해 새 시작 예산을 차감하지 않으며, 그 외 비교 불가 상태는 거부합니다.
  `run-main`은 목표 완료에만 종료코드0, 검토 pause에1, 확인 누락에2를 반환합니다.
- DB 옆 `.main-control.lock` 파일로
  동시 메인 제어를 차단하며 프로세스 종료 후 OS가 잠금을 해제합니다. 잠금 파일은 유지합니다.
  같은 DB에 파일럿과 메인을 동시에 실행하지 않습니다. Raw schema4는 유지하고
  별도 `main_control_*` schema1에 시작/회차/검증/RNG/상태를 저장합니다.
  완료 회차의 후보·생략 사유·참조 짝비교·진전/정체 결과는 immutable `round_complete` event에
  보존하며 회차 checkpoint와 함께 저장합니다. 완료된 세 번째 정체 회차 뒤 재개도 새 시작을 금지합니다.
- bin 전환·중단·완료마다 기존 `cumulative/revision-N/reports/` CSV와
  `<main-run-id>/event-N/summary.json`을 보존합니다. 출력 루트 기본값은
  `results/rqd_exploration`이며 재개 시 같은 `--output-dir`를 사용합니다.
  일치하는 CSV는 재개 시 다시 쓰지 않습니다. 기존 revision 보고가 다른 Jr/Ja 분석이면
  `cumulative/revision-N/analysis-<fingerprint>/reports/`에 메인 분석을 따로 보존합니다.
  보고 schema 또는 측정 P32 snapshot이 바뀌면 report identity별 디렉터리에 별도로 보존합니다.
  기존 `report-cumulative`의 명시한 출력 디렉터리 쓰기 동작은 유지합니다.
  입력 조건·seed/group·Jr/Ja 조합 수는 독립 DFN 수와 구별합니다.
  Face는 관측·분포 대비용이며 후보 선택/거부/안정성/bin 전환 gate가 아닙니다.
  자동 weight·굴착/PR/TR/POST 경계 및 미측정 profile 계산은 제공하지 않습니다.
  메인 반경 후보는 승인된 `최소<=최대`를 허용하며 같으면 그대로 상수 반경으로 실행합니다.
  파일럿 LHS/기존 adapter의 기본 strict 반경 검증은 변경하지 않습니다.

### 생성 mode와 in-domain P32 측정

메인 생성기는 절리 중심을 고정된 물리 도메인 안에만 배치합니다. 반경별 buffer 확장이나
입력 P32 보정은 하지 않습니다. 입력 P32는 설계 변수이며, 경계 절단과 표본 변동을 포함한
실제 영역 내 P32를 별도로 측정해 분석합니다. 파일럿은 기존 중심 배치 방식을 유지합니다.

완료 메인 job은 disk∩box 면적을 군별/합계로 `realization_p32` additive table에 저장합니다.
내부 disk는 정확한πr², 경계 disk는6면으로 clipped128-gon을 사용하며 raw schema4/RQD는 바꾸지 않습니다.
누적 `qprime_p32.csv`는 nominal P32와 측정 P32/합계/method/version/joint count를 함께 제공합니다.
미측정 P32는 빈칸이며 목표 판단은 계속 BH RQD만 사용합니다.

다음은 사용자가 명시 승인한 DB에서 실행하는 형식입니다. 일반 backfill은 RQD를 재측정하지 않습니다.
`--verify-job`에는 저비용 성공 job의64자리 execution fingerprint를 지정하면 저장 RQD와 정확히 대조합니다.
이 옵션은 선택한 fingerprint만 처리하며 전체 backfill을 실행하지 않습니다.
완료 P32는 재개 시 skip하지만 명시한 verification job은 다시 생성해 검증합니다.

```text
conda run -n dlo-cq python run_rqd_exploration.py measure-p32 --database <approved-db> --confirm-execution
conda run -n dlo-cq python run_rqd_exploration.py measure-p32 --database <approved-db> --confirm-execution --verify-job <execution-fingerprint>
```

## 파일럿 추가·재개·작업 완료의 의미

- 기존 DB는 schema4여야 합니다. 구형 schema2/3을 자동 migration하지 않습니다.
- 정확한 YAML bytes와 실행 runtime을 비교해 기존 미완료 batch를 재개합니다.
  주석·공백만 달라도 새 batch로 식별될 수 있습니다. 과학적 execution fingerprint의
  중복 집계 방지는 이 batch 식별과 별도입니다.
- 완료된 정확한 중복 batch와 모호한 일치는 명시 오류로 거부합니다.
  새 설정은 같은 DB에 별도 batch로 추가할 수 있지만 자동 후보 선정은 아닙니다.
- 성공 job은 건너뛰고 running attempt는 재개합니다. 실패 attempt는 자동 재시도하지
  않습니다. 완료 commit 전 중단된 현재 job의 DFN은 재생성될 수 있습니다.
- 파일럿에는 `--maximum-simulations` 옵션이 없습니다. 설정된 유한 작업 목록을 처리하며
  추가 시그니처를 자동 생성하지 않습니다. `simulation_count`는 이 호출에서 생성·측정에
  진입한 수로, running job 재개는 포함하고 성공 job skip은 포함하지 않습니다.
- 작업 목록 처리를 마친 명령의 종료 요약은 `jobs_complete`입니다.
  작업/attempt의 성공·실패·미완료 상태는 별도로 확인해야 합니다.
  실행 오류는 명시 오류로 반환하고 중단된 작업은 다음 `run`에서 안전하게 재개합니다.
  과거 `budget_exhausted`나 목표별 `unresolved_at_budget`를 현재 파일럿 출력으로 기대하지 않습니다.
- 메인 자동 탐색의 유한 시작 예산·종료 기준은 위 별도 명령에만 적용합니다.

원관측과 provenance를 보존하고 누적 분석은 immutable revision으로 기록합니다.
같은 execution fingerprint는 과학적 집계에서 중복 계산하지 않으며 모든 원자료는
보존합니다. 관측/상태 충돌은 표시하고 해당 fingerprint를 집계에서 제외합니다.
BH 길이 support와 face 면적 support는 분리합니다.

## 회귀 테스트

프로젝트 루트에서 기존 환경으로 실행합니다.

```sh
conda run -n dlo-cq python -m unittest discover -s src/test -p 'test_*.py' -v
```

기존 계산 경계와 v4 입력·설계·실행·저장·누적 분석/보고를 검증합니다.
임시 DB와 모의 backend/측정을 사용하는 통합 시험은 실제 파일럿 결과가 아닙니다.
최신 테스트 결과·실행 여부는 구현 계획의 날짜별 기록을 확인합니다.

## 과거 자료 참조

- [이전 전체 소스](obsolete/src_obs/)
- [과거 문서 및 설계 계약](obsolete/Specification/)
- [분석 자료](obsolete/Analysis/)
- [케이스](obsolete/cases/) 및 [설정](obsolete/config/)
- [기존 도구](obsolete/tools/)
- [이전 README](obsolete/readme.md)

보관된 자료는 필요한 근거를 확인할 때만 참조합니다. 보관 스크립트와 README의 명령은
과거 경로·계약을 전제로 하므로 현행 v4 실행 안내로 사용하지 않습니다.
