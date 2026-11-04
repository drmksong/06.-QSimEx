# T011 Main Simulation Implementation Plan

**Latest low-RQD signature diagnosis (2026-11-03 18:28:05 KST +0900; read-only):**
The paused run was not targeting raw RQD <= 10; it evaluated fixed Q-prime bin/Jn/Jr/Ja
targets. Its last target `6/15/4/0.75` required calculation RQD `(17.7878,40.7689]`.
Seed-43 supported BH values for that target were 45.2803–100, with zero in-range; seed 46
had one 1 m supported observation at 32.2792. Across 64,680 supported BH observations,
none had raw RQD <= 10; minima by Jn were 60.2874, 28.5267, 28.6133, and 32.2792 for
Jn2/4/9/15 respectively.

Theoretical bin-6 tuple Jn4/Jr4/Ja0.75 admits calculation RQD `[10,10.8717]`, but
`Target.reachable` excludes it because its `physical_rqd_floor` is 40.6; this target is
absent from saved evidence. Actual Jn4 support below 40.6 and Jn2 support below 73.6
contradict treating these computed values as hard observed-RQD lower bounds. Q-prime
scoring also clamps raw RQD below 10 to calculation RQD 10. T011 proposes LHS/bounded
parameter perturbations and scores measured target distance/support; it does not invert a
raw-RQD<=10 objective into a signature. State had 4,109 input signatures but starts
covered 546 distinct inputs, and Jn20 is not in this run's templates. The separate
raw-RQD-only validation needs an approved target/success/seed/storage contract. No code,
DB, or policy was changed and no simulation was run.

**Latest root-cause diagnosis (2026-11-03 17:35:02 KST +0900; read-only):**
None of the recorded candidates for the five unfinished bin-6 targets has positive target
support at initial seed 43. Recorded candidate counts and counts with 0/1/2 positive
verification seeds among seeds 44–46 are: `6/15/4/0.75`: 102 (`101/1/0`);
`6/9/3/0.75`: 270 (`269/1/0`); `6/9/3/1`: 270 (`268/1/1`);
`6/9/4/0.75`: 270 (`270/0/0`); `6/9/4/1`: 270 (`269/1/0`). One candidate for
`6/9/3/1` had 2/3 positive verification seeds but still failed because seed 43 was negative.
Target passage requires positive initial support plus 2/3 positive verification seeds, not
similar RQD values.

The pause was caused separately by the exploration-progress/stagnation gate: same-seed
candidate/reference comparisons did not meet the progress decision in rounds 53–55, there
were no new suitable inputs, and the three-round limit was reached. The relaxed seed rule
therefore was not the direct cause, but it could not help without any seed-43-positive
candidates. Available historical records document the 300-start run at bin 7 and an earlier
`high_cost_review` run at bin 8; they do not substantiate a previous bin-6 stop. This was
read-only diagnosis; no code, DB, policy, or simulation was changed.

**최신 정지 run 진단 (2026-11-03 17:27:32 KST +0900; 사용자 DB read-only):**
사용자 DB의 run `main-f22be9820f092b195fc1fefd5bff3464c07ef599e5715f3f87e382a1bb37635f`는
`paused/stagnation`이며, 해당 `run-main` 프로세스는 실행 중이지 않다. round 55
(`6/15/4/0.75/pilot-bh`)까지 진행했고 1,078 starts 모두 succeeded, 실패는 없다.
bin6은 79/84 통과, 5개 미통과, 전체 누적 통과는 179개다. 직전 round52는 progress였지만
round53–55 연속 3회 `no_progress`, 새 suitable input 0개라 `stagnant_rounds=3` 종료 조건에
도달했다. 따라서 seed 2/3 판정 실패나 생성 job 오류로 멈춘 것은 아니다. 현재 pause 사유는
재실행만으로 자동 해제되지 않는다. DB는 read-only로 진단했으며 run/코드는 수정하지 않았다.

**최신 메인 run 상태 (2026-11-03 06:37:19 KST +0900; DB 읽기 전용 진단):**
사용자 지정 DB는 schema4이고, run `main-f22be9820f092b195fc1fefd5bff3464c07ef599e5715f3f87e382a1bb37635f` 하나가
`running` 상태다. PID 32738이 약 7시간 실행 중이며 CPU 사용률은 99%대다. checkpoint의 현재 bin은 6,
round 52의 `progress` phase, target `6/9/3/1/pilot-bh`; queue에는 progress role seed 46 작업 1개가
남아 있다. starts 1,014개는 모두 succeeded다. bin6은 reachable/evaluated 84개 중 79개 통과, 5개
미통과(`6/15/4/0.75`, `6/9/3/0.75`, `6/9/3/1`, `6/9/4/0.75`, `6/9/4/1`, 모두 `pilot-bh`)다.
전체 누적 통과는 179개다. 마지막 start 1014는 succeeded이나 checkpoint queue에 seed46이 남아 있어,
현재는 작업 완료 후 refresh/checkpoint 중일 가능성이 있다. 내부 실행 위치는 읽기 전용 DB만으로 확정할 수 없다.
동일 run ID의 저장소 내부 사본은 별도 DB였으며, 이번 진단은 사용자 DB를 read-only로 열었고 수정·시뮬레이션은 하지 않았다.

**현행 메인 실행/인계 상태 (2026-11-02 23:28:37 KST +0900; 진행 로그 갱신):**
기존 DB 위치는 저장소 내부가 아니라 `/Users/myungkyusong/QSimExOutput/sqlite/`였다.
이전 확인은 저장소 내부 경로만 점검해 기존 DB가 없다고 잘못 판단했다. 사용자가 지정한
위치의 DB는 존재하며, 해당 DB는 열거나 수정하지 않았다. 그 경로의 실행은 사용자가 직접
수행한다.

사용자가 새 메인 실행을 요청해 명령을 전달했다. 현재 config는 `initial_input: null`로
기존 원자료를 활용하므로, 명령은 빈 DB가 아니라 사용자 DB
`/Users/myungkyusong/QSimExOutput/sqlite/qsimex-rqd-v4.sqlite`를 지정한다. `run-main`은
동일 config/runtime의 미완료 run이 있으면 자동으로 그 상태를 불러온다. DB 내용은 이번에
확인하지 않았으므로 실제 run 선택 상태는 미확정이다. assistant는 명령만 전달했고 실행하지 않았다.

별도로 저장소 내부 `sqlite/qsimex-rqd-v4.sqlite`에 만든 신규 run
`main-f22be9820f092b195fc1fefd5bff3464c07ef599e5715f3f87e382a1bb37635f`는 bin10에서
23:03:11에 시작한 뒤 `paused/user_interruption`, 112/20,000 starts, bin8, queue 8,
round `progress` 상태로 checkpoint됐다. 사용자의 삭제 요청에 따라 그 저장소 내부 DB,
lock 파일 및 이번 run이 만든 `results/rqd_exploration/`을 제거했다. 확인 결과 해당 경로들은
없고 run 프로세스도 종료 상태다. `sqlite/` 디렉터리와 기존 `results/.DS_Store`는 보존했다.
QSimExOutput의 DB/출력은 수정하지 않았으며, 이후 simulation은 사용자가 직접 수행한다.

**진행 로그 보강 (2026-11-02 23:28:37 KST +0900):** 기존 job 시작/heartbeat 로그에는 현재
bin과 `targets_passed`가 있었지만 job 도중 처음 만든 진행 문맥을 재사용해 완료 직후의 통과 수가
다음 작업까지 갱신되지 않고, bin 전환 및 pause 시점의 별도 요약도 없었다. 각 작업 완료 후 갱신된
bin/통과 수를 출력하고, bin 전환 때 완료 bin과 새 현재 bin의 통과 수를, pause 때 중단 시점의
상태를 출력하도록 했다. controller/workflow focused tests 27개 통과, `git diff --check` 통과.
실제 DB 접근이나 simulation은 수행하지 않았다.

**현재 seed 통과 기준 및 완료 상태 (2026-11-02 22:47:57 KST +0900; 작업 1–8 완료):**
목표별 고정 생성 입력 하나에서 초기 seed의 양의 목표 support가 선행되어야 한다.
이어 정책이 지정한 검증 seed 시작값부터 연속 3개 중 2개 이상이 양의 목표 support를
보이면 통과한다(최소 3/4). 43–46은 예시일 뿐이며 코드에서 seed 번호를 고정하지 않는다.
A/B/C 그룹 분포 비교는 폐기한다. 분석과 컨트롤러는 설정된 seed를 사용하고, paired
진전 비교는 같은 realization seed인지 확인할 뿐 seed 하한을 두지 않는다. 새 구현 버전과
정책 fingerprint로 이전 실행과 별도 run을 만들며 이전 상태를 보존한다. 판정 경계·target
completion·bin 전환·재개 regression을 보강했다. 초기 seed 누락과 서로 다른 입력 증거의
합산을 거부하며, 복구 시 설정된 verification seed 범위만 허용한다. bin-transition fixture는
정책 설정에서 seed 값을 파생한다. 관련 analysis/controller/policy/store/workflow suite
48개와 `git diff --check`가 통과했고, 변경 Python 4개 파일의 Pylance syntax 검사도 오류가
없었다. stderr 진행 로그와 stdout/event 결과에는 전체 예산, 현재 bin의 목표 통과 현황,
동적 seed pass evidence, 회차·phase·작업 정보를 기록한다. 실제 pilot DB 쓰기 및
시뮬레이션은 하지 않았다.

**작업 순서 상태 (2026-11-02 22:47:57 KST +0900):**
1. 완료 — seed 통과 기준을 단일 규칙으로 확정·기록.
2. 완료 — §2의 활성 정책에서 A/B/C 그룹 비교와 추가 통과 문턱 제거; 후보 진전은 통과 기준과 분리.
3. 완료 — 분석 core에 초기 seed와 검증 seed 시작값을 인자로 받아 적용; 43–46 이외 seed 회귀 포함 단위 검증.
4. 완료 — 컨트롤러의 설정 seed 예약·복구·목표 완료를 통합하고, policy 변경 시 별도 run과 이전 상태 보존을 검증.
5. 완료 — 전역 예산·현재 bin/target·동적 seed evidence를 progress 로그 및 run/event 결과에 보고.
6. 완료 — 새 판정 경계·목표 완료·bin 전환·재개 회귀 테스트.
7. 완료 — 구현 기록과 현행 상태를 관련 계획에 timezone-aware timestamp와 함께 동기화.
8. 완료 — `dlo-cq` 관련 suite 48개 및 diff 검증; 실제 DB 쓰기/시뮬레이션은 수행하지 않음.

**이전 Seed 확인 방향 (2026-11-02 06:36 +09:00; 21:54 기준으로 대체됨):** 당시에는 목표별 한 생성
입력에서 seed43 통과 후 seed 2개 중 하나 통과(총 2/3)를 제안했다. 이는 후속 seed 3개 중
2개 통과하는 현재 기준으로 대체되었다. 아래 구현 체크리스트는 이전 규칙의 이력이며 현행 정책은
§2에 반영했다. 코드・DB・시뮬레이션은 이번 문서 작업에서 변경/실행하지 않았다.

**최신 운영 예산 (2026-11-01 17:22 +09:00):** 사용자 승인에 따라 메인 run 하나의 최대 시작 수를
20,000회, 중간 수동 검토 checkpoint를 10,000회로 설정한다. checkpoint 후 같은 `run-main`
명령은 동일 run을 이어가며 예산을 초기화하거나 새 stage를 만들지 않는다. 실행이나 DB 쓰기는
별도 확인 전까지 수행하지 않는다.

**현행 정책 변경 (2026-11-01 06:19 +09:00):** 사용자06:10 요청에 따라 Jn20을 당분간
제외했다. 기본 `initial_input: null`, 활성 Jn2/4/9/15, 초기 생성0개로 bin10부터 탐색한다.
Jn20 파일/지원은 보존하며 재포함은 별도 승인 경계다. 기존 관측은 삭제하지 않으며
Jn20 관측이 있더라도 현행 메인 참조/검증 장부/목표에서 제외한다.
Primary10개 bin 모두 도달 가능하지만 Jn20 조건/최저 Q' 구간까지 동일하게 조사하는 뜻은 아니다.
이론적 최소 Q'는0.0125→1/60(약0.0167), 최대266.6667은 동일하다. Bin 도달성과
실제 관측/최종 통계적 충분성은 구분한다. 나머지 step/seed/10%p/200회/비용 정책은 유지했다.
재현 red 후 전체277개 테스트(신규/보존 메인49개) 통과. Public preview 초기0/
활성4조건/전체10 bin/쓰기0, 초기 단계 없는 실행/재개 및 저장 Jn20 장부 제외를 검증했다.
Pylance 정책/제어 diagnostics 오류 없음, 목표 함수 호출2개 signature 호환 확인.
실제 DB/results/DFN/simulation은 변경/실행하지 않았다. 아래23:45 구현 결과는 이전 이력이다.

**작성:** 2026-10-31 22:32 +09:00  
**정책 승인:** 2026-10-31 22:27 +09:00, 사용자 최종 정책안 승인  
**상위:** T011 / Plan 5.2 / Phase 7  
**현재 상태 (2026-10-31 23:45 +09:00):** P7.02.01–09 전체 구현・검증 완료.
전체274개 테스트 통과(신규 메인46개 포함), 최종 검토6건 수정/재현 검증 완료.
기존 경로 변경은 필수 연결에 한정했다. 실제 메인 실행 승인 없음.

## 1. 목적과 근거

고정 파일럿의 생성・측정・원자료 누적 기능 위에 BH 목표별 자동 후보 탐색,
seed 반복 확인, bin 전환, 예산/비용/정체 중단 및 결정적 재개를 구현한다.
BH와 face는 같은 DFN의 관측 자료지만 동반 개선이나 동일 분포를 요구하지 않는다.
Face는 후보 선택・거부・갱신・bin 전환의 판단 지표로 사용하지 않는다.

계획 근거는 [전략 요구사항・설계](../RQDExplorationStrategy_20261026/plan.md),
[기존 구현 계획](../ImplementationPlan_v4.md), 그 문서의 모듈/저장 계약,
현재 `src/rqd_exploration/`의 구현과 사용자가 승인한 최종 정책이다.
별도 constitution・topology・knowledge graph는 존재하는 것으로 가정하지 않는다.
기존 설계 문서의 역할은 위 계약이 충족하며 별도의 architecture 산출물을 만들지 않는다.
두 실제 파일럿과 revision2 누적 검토는 완료된 선행 근거다. 분석 대화의 미승인
제안이나 되돌린 상세 실행 로그를 복원하지 않고, 확정된 정책과 구현 계획만 기록한다.

## 2. 승인 정책

### 2.1 목표와 전환

- 기본 메인은 Jn20 초기 생성 없이 기존 파일럿 자료를 재사용하며 첫 목표는 primary bin10.
  이후 높은 bin에서 낮은 bin으로 진행한다. 기존 정확한 `(lower, upper]` 경계 유지.
- 활성 Jn2/4/9/15를 각각 절리군1/2/3/4개로 바인딩한다. Jn15는 승인된 대표 근사다.
  Jn20/5군 근사 지원은 보존하지만 현행 생성/참조/검증/목표에서 제외한다.
  기존 raw에 다른 Jn을 대입하지 않는다.
- 목표는 `(bin, Jn, Jr, Ja, BH profile)`이다. 계산 RQD `[10,100]`에서 실제로
  교집합이 있는 점수 조건만 대상으로 삼는다. 이론적 비도달과 미관측을 구분한다.
- 각 도달 가능한 목표는 목표별 고정 생성 입력 하나에서 판정한다. 초기 seed에 양의 목표
  support가 있어야 하며, 같은 입력에서 정책이 지정한 검증 seed 시작값부터 연속 3개 seed
  중 2개 이상에 양의 목표 support가 있으면 통과한다. 43–46은 예시다. 해당 bin의 모든
  도달 가능한 목표가 통과하면 자동 전환한다.
- A/B/C 그룹 비교, 분포/CDF 유사도, 10%p 경계, 연속 비교 횟수, 여러 독립 생성 입력,
  또는 별도 안정성 이력은 목표 통과나 bin 전환의 추가 조건이 아니다.
- 목표의 운영상 통과는 최종 통계적 충분성이나 물리적 검증의 선언이 아니다.
  최종 해석은 통과 판정과 별도로 보고한다.

### 2.2 관측과 후보 진전

- 동일 원자료와 유효 관측은 다른 Jr/Ja 및 bin 분석에서도 재사용한다. 미달 관측도
  누적 분석에 남기며 원자료0은 보존하고 계산에만 `max(rawRQD,10)`을 적용한다.
  10 아래 추가 저하만을 Q' 진전으로 세지 않는다.
- 후보 진전 규칙은 탐색 후보의 우선순위 평가에만 쓴다: 거리1 RQD 포인트,
  support1%p, 최초2/3 진전, 정확히1/3 진전일 때만2개 추가해3/5 판정.
  이는 목표 통과나 bin 전환의 추가 조건이 아니다. seed별 개선/비악화 결과를 보존하며
  진전만으로 참조를 자동 교체하거나 최종 충분성을 선언하지 않는다.

### 2.3 회차와 후보

- 신규 입력 최대12개: 한 축8개, 복수 축2개(2축/3축), 미조사 LHS2개.
  선택한 두 `(절리군, 축)`에 ±작은/큰 step으로 한 축 후보8개를 제안한다.
- 유망 후보 최대2개에 후보 진전 확인을 배정한다. 별도 완전 안정성 확인 입력이나
  입력3개 충족을 위한 우선순위는 두지 않는다.
- 기존 거리/support 최선・co-best 참조를 보존한다. 미충족 목표・미검증 입력을
  우선하고 같은 우선순위에서는 목표/참조/절리군/축을 결정적으로 순환한다.
  순환 cursor・동률 순서・후보 생성 근거・RNG 상태를 저장한다.
- 미조사 LHS는 저장된 seed를 바탕으로 전역 회차/조건/역할별 결정적 RNG stream을
  사용한다. 재개 때 새 RNG나 Python hash로 다른 후보를 만들지 않는다.
- bounds 밖・반경 순서 위반・중복 후보는 사유를 남기고 생략한다. clamp/반경 교환 금지.
  같은 입력/seed의 유효 관측은 재사용하고 생성 경로가 중복되면 근거를 합친다.
  12개를 강제로 채우는 무한 재생성 금지. 적격 후보 소진은 별도 중단 사유다.

| 축 | 작은 step | 큰 step | bounds |
|---|---:|---:|---|
| 절리군 P32 | 0.1 m2/m3 | 1 m2/m3 | [0.01,10] |
| 최소 반경 | 0.1m | 1m | [1,150], 최소<=최대 |
| 최대 반경 | 0.1m | 1m | [1,150], 최소<=최대 |
| 평균 경사 | 5deg | 15deg | [0,90] |
| 평균 경사방향 | 5deg | 15deg | [0,360) |

메인 절리 중심은 고정된 물리 도메인 안에만 배치한다. 반경 buffer 확장이나 입력 P32 보정은 하지 않는다.
비용 gate는 명목 P32의 `P32*volume/expected_area`를 사용하고, 경계 절단을 반영한 실제 영역 내 P32는
별도로 측정·기록하여 분석한다.

Alpha/κ는 새 LHS에서 기존 독립 stream・범위 `[2.5,4]`/`[0,50]`로 표본화한다.
참조 주변 변경/seed 반복에서는 해당 생성 입력의 값을 고정한다.

### 2.4 예산・중단・오류

- 메인 run 전체20,000회. 실행 시작 기록1회 기준으로 신규/참조/후보/실패 시작,
  중단 후 재생성을 포함한다. 저장 자료 재사용・분석/보고는0회. 10,000회에서 검토 checkpoint로
  중단하며 같은 run 명령으로 재개한다. 재개 시 소비량을 초기화하지 않는다.
- 실행 전 절리군별 `_expected_joint_area`와 `P32*volume/expected_area`를 합산한다.
  총 기대 절리 수 `>10,000,000`이면 생성 전 중단・규모 보고・사용자 검토.
  기대값은 실제 Poisson 개수나 보장된 시간/메모리가 아니다. 자동 입력 변경/후보 악화 판정 금지.
- 정체는 완료된 회차3회 연속 무진전. 기존 BH 진전 또는 새 적격 생성 입력이 있으면 횟수 초기화.
  오류/비교 불가는 무진전 회차로 세지 않는다.
- 다른 축・폭・참조를 활용하되 진행 중인 확인 절차를 정체 판정으로 끊지 않는다.
  전체 예산・실행 오류 중단은 우선 적용한다.
- 자동 오류 재시도0회. 실패/비교 불가 사유 보존 후 중단・검토. 불리한/실패 seed의
  묵시적 교체 금지. 수동 복구/정책 변경은 별도 명시 승인 경계다.
- 목표 충족・정체・예산 소진・고비용 검토・오류・비교 불가・후보 소진・사용자 중단을
  구분한다. 재개는 저장된 계획/예산/검증 상태를 복원하며 완료 작업을 중복 생성하지 않는다.

### 2.5 선택적 Jn20 입력과 보고

- Jn20은 기본 `initial_input: null`로 제외한다. 지원/입력 파일은 보존한다.
  별도 승인해 재포함할 때의 기존 계약은 LHS5개, design seed40, realization seed43,5절리군.
  기하60x30x30m/grid1m・기존 tunnel/BH・간격1m・bounds/분포는 기존 파일럿과 동일.
  초기5개도20,000회 예산과 기대 절리 수 검토를 적용한다.
- 기존 Jn2/4/9/15 자료를 초기 장부에 반영한다. 파일럿 YAML bytes/seed/결과는 변경하지 않는다.
- 작업마다 원자료 저장, bin 전환・중단・최종 종료 시 누적 분석/보고.
  기존 revision별 CSV 경로와 이전 분석을 보존한다. 메인 상태/이유는 run/event별 별도 요약으로 보존한다.
- 자동 weight 조정・surrogate・미결 PR/TR/POST/굴착 경계・미측정 profile 구현은 이번 범위 밖.
  기존 파일럿 CLI의 무상한・append/resume・오류 계약도 보존한다.

## 3. 기술적 맥락・원칙 점검

Python/NumPy/SciPy/YAML/SQLite・기존 MLX backend, conda `dlo-cq`만 사용한다.
새 의존성・venv・GPU/CPU fallback・Euler controller 이식은 추가하지 않는다.
새 모듈은 입력 정책, 저장, 관측 판단, 후보 생성, 제어의5개 책임으로 한정한다.
현재 코드의 `config/design/fingerprint/adapter/analysis/dataset/measurement/store/runner`
helpers를 재사용하며 raw RQD・물리 geometry・bin 경계를 변경하지 않는다.

기존 SQLite raw/누적 schema4 계약은 유지하고 `main_control_*` 제어 tables 및
별도 control schema version1을 추가한다. 제어 DDL은 명시 승인한 실제 run에서만 적용한다.
schema2/3 자동 변환은 하지 않는다. 실행 시작/예산 기록을 일관된 transaction으로
묶고 raw commit과 제어 checkpoint 사이 crash는 저장 job 상태로 조정한다.
새 프로세스에서 완료 작업 재실행・예산 초기화・동시 제어 충돌을 허용하지 않는다.

원칙 점검: 기존 경로 보존/PASS, 원자료와 파생값 분리/PASS, 실패 명시/PASS,
정책값 임의 대체 금지/PASS, 실제 실행 별도 승인/PASS, README 로그 금지/PASS.
적용 지침은 `.github/copilot-instructions.md`/`SKILL.md`와 기존 모듈 계약이다.
확인한 migration guidelines는 Spring/Struts 전환용으로 이번 Python 기능에 해당하지 않는다.

## 4. 구현 순서와 작업

기존 T001–T010과 P7.01–P7.03을 유지한다. 아래는 P7.02 상세 분해이며
`P7.02.01`–`P7.02.09`를 사용한다. 별도 T001 목록으로 기존 이력을 재번호하지 않는다.
아래9개를 하나의 승인된 구현 batch로 완료했다. Source 표기는 재사용 경계를 명시한다.
Checkbox 완료는 코드/임시 DB/모의 생성기 검증을 뜻하며 실제 메인 실행 승인이 아니다.
아래 구현 체크박스와 수용 기준은 2026-10-31에 구현한 이전 정책의 검증 이력이다.
현행 seed 통과 정책은 §2와 위 작업 상태가 우선한다. 컨트롤러·저장/재개 연결은 작업 4,
진행 및 결과 보고는 작업 5에서 완료했다.

### 5.2.1 정책 타입・입력

- [x] P7.02.01 [Plan:5.2.1] `src/rqd_exploration/main_policy.py`, `config/rqd_exploration_main.yml`, `config/rqd_exploration_jn20.yml`에 승인값/단위/명시 validation・입력 fingerprint를 구현한다. 기존 `config.py`/`records.py`의 기하·절리군 타입을 재사용하며 누락/비유효값은 오류로 표시한다.
- **의존:** P7.01 정책 승인. **REQ:** 001,002,005,007,010,011.
- **수용:** 그룹3/연속2/0.10/입력3/무진전3/후보12/예산200/기대수10000000/Jn20 seed40/43과5군을 정확히 확인. 이 작업 자체는 실행하지 않는다.

### 5.2.2 제어 저장・예산・복원

- [x] P7.02.02 [P] [Plan:5.2.2] `src/rqd_exploration/main_store.py`에 run/policy・목표・후보/실행 시작・RNG/cursor・seed 그룹・진전/정체・중단 이유를 저장한다. `store.py`의 job/attempt/provenance를 참조하고 immutable 정책 snapshot 및 crash reconciliation을 구현한다.
- **의존:** P7.02.01. **REQ:** 003,007,008,009,010,013.
- **수용:** 시작 소비량/상태 일관성, 완료 raw commit 후 제어 저장 전 crash, 재생성 차감, 재개200회 초기화 금지, 동시/불일치 실행 명시 오류. 생산 DB에 DDL 적용하지 않는다.

### 5.2.3 목표・진전・안정성 계산

- [x] P7.02.03 [P] [Plan:5.2.3] `src/rqd_exploration/main_analysis.py`에 정확한 inverse 목표/도달성, BH 공통 support・paired seed 진전・입력 다양성・그룹 CDF/bin 안정성과 목표 완료 판정을 구현한다. [Source: src/rqd_exploration/analysis.py] [Source: src/rqd_exploration/dataset.py]
- **의존:** P7.02.01. **REQ:** 002,003,004,005,006,009,011,012,013.
- **수용:** 유효 source 선택/충돌 제외, seed별 정규화 후 그룹 동일 가중치, 정확한 tie/bin 경계, 두 지표10%p 경계, 양의 support, 연속 실패 초기화, 2/3・3/5와 안정성의 구분. Face 동반 개선을 요구하지 않는다.

### 5.2.4 후보 생성・기대 비용

- [x] P7.02.04 [Plan:5.2.4] `src/rqd_exploration/main_design.py`에 순환 한 축8/복수 축2/LHS2 후보, 명시 step/bounds・중복 근거 병합・입력 identity・결정적 RNG와 순수 scalar 기대 절리 수 산출을 구현한다. [Source: src/rqd_exploration/design.py] [Source: src/rqd_exploration/fingerprint.py] [Source: src/euler_campaign/dfn.py#_expected_joint_area]
- **의존:** P7.02.01, P7.02.03. **REQ:** 001,002,006,007,009,011,012,013.
- **수용:** 생성/DB 없이 재현되는 후보; α/κ 고정/표본화 구분; seed/Jr/Ja로 다양성 증가 금지; bounds 밖 생략・반경 교환 금지; 후보 소진 유한 종료; 비용 계산에 DFN/GPU generation 호출 없음.

### 5.2.5 자동 제어・회차 스케줄

- [x] P7.02.05 [Plan:5.2.5] `src/rqd_exploration/main_controller.py`에 Jn20 기초 단계→bin10부터 순차 진행, 목표별 참조/배분, 진전 확인 최대2・완전 안정성1, 기존 자료 재사용・검증 우선,3회 정체/모든 중단 상태를 조립한다.
- **의존:** P7.02.02, P7.02.03, P7.02.04. **REQ:** 006,007,009,011,012,013.
- **수용:** 여러 목표/참조 순환, 한 후보 미달≠bin 정체, 미완료 확인 block의 정체 중단 금지, 미충족 상태 자동 다음 bin 이동 금지, 예산/오류 우선, rawRQD<10 추가 저하나 재조회로 진전 증가 금지.

### 5.2.6 실제 실행 경계 연결

- [x] P7.02.06 [Plan:5.2.6] `src/rqd_exploration/runner.py`에서 단일 job 실행 경계를 공유 helper로 추출하고 `main_controller.py`에 기존 factory/measurement/atomic attempt/heartbeat를 연결한다. 생성 전에 예산・기대 절리 수・확인 gate를 적용한다. [Source: src/rqd_exploration/runner.py#execute_frozen_jobs,generate_and_measure]
- **의존:** P7.02.02, P7.02.05. **REQ:** 003,004,007,008,009,010,012,013.
- **수용:** 기존 pilot summary/무상한/skip/error 동작 유지, 기대수 정확히10000000 허용・초과 시 생성0회,200번째 시작 허용/201번째 금지, 실패 차감/중단 재생성/완료 skip, 기존 progress phases와 MLX-only 보존. 검증은 mocked factory로 수행한다.

### 5.2.7 CLI・preview・쓰기 승인

- [x] P7.02.07 [Plan:5.2.7] `src/rqd_exploration/cli.py`와 기존 root entry에 `validate-main`, `preview-main`, `run-main`을 연결한다. Main config/DB/명시 확인, 재개・불일치・중단 이유와 stdout JSON/stderr progress를 제공한다.
- **의존:** P7.02.01, P7.02.03, P7.02.05, P7.02.06. **REQ:** 006,007,008,010,011,012.
- **수용:** validate/preview는 원자료/제어 DB 쓰기와 DFN 생성0회, 기존 DB 조회는 read-only. run 확인 누락은 쓰기/생성 전 거부. 기존6개 명령/default pilot2/실패 메시지 보존. 명령명은 구현/검증됐다.

### 5.2.8 누적 보고・상태 인계

- [x] P7.02.08 [Plan:5.2.8] `main_controller.py`, `cli.py`에서 기존 `dataset.py`/`cumulative_reporting.py` 분석・report 서비스를 공유해 bin 전환/중단/종료마다 누적 revision/CSV와 run/event별 메인 상태 요약을 보존한다. `readme.md`에는 실제 구현된 사용법/명령/제한만 갱신한다.
- **의존:** P7.02.03, P7.02.05, P7.02.06, P7.02.07. **REQ:** 003,004,005,006,007,009,010,013.
- **수용:** 이전 revision/원자료 불변, 검증 미통과 유효 자료 포함・오류/무효 상태 구분, seed/입력/조합 수 분리, 미측정 profile을0으로 대체하지 않음. 같은 raw revision에서도 다른 제어 event 요약을 덮어쓰지 않음. 로그는 README가 아닌 별도 계획/상태 요약.

### 5.2.9 통합 검증・구현 완료 인계

- [x] P7.02.09 [Plan:5.2.9] `src/test/test_rqd_main_*.py` 및 기존 runner/CLI/workflow 회귀로 정책 경계・순환・중단/재개・누적 불변성을 검증하고 `Specification/MainSimulation_T011/plan.md`와 상위 두 계획/checkpoint에 실제 결과를 기록한다.
- **의존:** P7.02.01–P7.02.08 모두. **REQ:** 001–013.
- **수용:** 아래 검증표 충족, syntax/type diagnostics 및 diff 확인. 구현 완료를 실제 메인 실행/통계적 충분성/G4 승인으로 승격하지 않는다. P7.03에서 사용자 검토/실행 인계를 별도 진행한다.

## 5. 파일 구조・검증

```text
src/rqd_exploration/
  main_policy.py       # 새 정책/input 타입
  main_store.py        # 새 제어 상태; 기존 raw store 참조
  main_analysis.py     # 새 BH 목표/진전/안정성 계산
  main_design.py       # 새 후보/기대 비용
  main_controller.py   # 새 스케줄/실행/보고 조립
  runner.py, cli.py    # 기존 실행 경계/진입점 확장
config/
  rqd_exploration_main.yml
  rqd_exploration_jn20.yml
src/test/
  test_rqd_main_*.py
```

앱 유형은 Python CLI・SQLite・MLX scientific runner다. 브라우저/서비스/컨테이너 검증은 해당 없다.
기존 conda `dlo-cq`와 unittest, 임시 schema4 DB 및 mocked physical factory를 사용한다.
실제 GPU 실행은 테스트 green 이후 별도 사용자 승인 사항이다. 새 test tooling은 설치하지 않는다.

| 검증 여정 | 정확한 통과 조건 |
|---|---|
| 기존 자료로 시작 | Jn2/4/9/15 재생성0, Jn20 계획5/군5/seed40・43, 비도달 조건 실행0 |
| 후보와 반복 | 8/2/2 상한・step/bounds・동률/순환・3→5 seed・동일 입력/seed 재사용 |
| 목표 통과와 bin 전환 | 같은 입력에서 seed43 양의 목표 support 및 seed44·45·46 중 2개 이상 양의 support; bin의 모든 도달 가능 목표 통과 |
| 중단 | 예산200/비용10000000/정체3/오류0재시도 경계 및 독립 종료 사유 |
| crash/reopen | 시작 예약/생성/부분 관측/raw 완료/제어 갱신 사이 interruption; 완료 skip・재생성 소비 유지 |
| 보고 불변성 | 이전 raw/CSV/revision 유지, 모든 적격 검증 자료 포함, 읽기 전용 CSV 보고, event 덮어쓰기 없음 |
| 기존 경로 보존 | pilot runner/CLI/workflow 및 관련 Euler 측정・store 회귀 green, 물리식/기하/bins 불변 |

작은 변경 단위의 관련 suite부터 실행했다. 공유 실행 경계와 최종 통합은 기존
runner/CLI/workflow 및 전체 unittest로 검증했다. GPU 시뮬레이션은 수행하지 않았다.

## 6. Requirement Mapping

| REQ ID | 의미 | Plan Items | 예정 구현/보존 증거 |
|---|---|---|---|
| REQ-001 | 승인 LHS・미지 DFN-RQD | 5.2.1,5.2.4,5.2.9 | main_policy/main_design, 기존 design |
| REQ-002 | Jn/군 고정・기하와 점수 분리 | 5.2.1,5.2.3,5.2.4,5.2.9 | Jn20 YAML, adapter/fingerprint |
| REQ-003 | 원시 관측/evidence 보존 | 5.2.2,5.2.3,5.2.6,5.2.8,5.2.9 | 기존 measurement/store/dataset, main_store |
| REQ-004 | Q' 독립 face 위치 | 5.2.3,5.2.6,5.2.8,5.2.9 | 기존 measurement/profiles 회귀 |
| REQ-005 | floor10・66개 후처리 | 5.2.1,5.2.3,5.2.8,5.2.9 | analysis/dataset 재사용, floor 경계 |
| REQ-006 | 도달/관측/충분성 구분 | 5.2.3,5.2.4,5.2.5,5.2.7,5.2.8,5.2.9 | 목표 장부/상태/보고 |
| REQ-007 | 예산/실패/재개 | 5.2.1,5.2.2,5.2.4,5.2.5,5.2.6,5.2.7,5.2.8,5.2.9 | main_store/controller, 실행 예약 |
| REQ-008 | 기존 Euler/파일럿 보존 | 5.2.2,5.2.6,5.2.7,5.2.9 | 별도 main 모드/공유 경계 회귀 |
| REQ-009 | 계층 provenance/독립 수 | 5.2.2,5.2.3,5.2.4,5.2.5,5.2.6,5.2.8,5.2.9 | 입력/seed/group/fingerprint/source 연결 |
| REQ-010 | 승인 경계 | 5.2.1,5.2.2,5.2.6,5.2.7,5.2.8,5.2.9 | confirmation/readonly preview/별도 G4 |
| REQ-011 | inverse 목표/배분 | 5.2.1,5.2.3,5.2.4,5.2.5,5.2.7,5.2.9 | main_analysis/main_design/controller |
| REQ-012 | BH 우선 자동 갱신 | 5.2.3,5.2.4,5.2.5,5.2.6,5.2.7,5.2.9 | BH-only 판정/face 관찰, 후보 스케줄 |
| REQ-013 | 참조/지속/종료 분리 | 5.2.2,5.2.3,5.2.4,5.2.5,5.2.6,5.2.8,5.2.9 | co-best/정체/상태/재개 |

체크포인트: [REQ→계획](checkpoints/spec-to-plan.yaml), [계획→작업](checkpoints/plan-to-tasks.yaml).
구현 진척은 위9개 checkbox와 상위 `tasks-to-impl.yaml#current_status`에서 구분한다.

## 7. 22:32 계획 단계 검증 (이력)

2026-10-31, 기존 conda `dlo-cq`에서5개 checkpoint YAML의 중복 key 거부 parsing,
실제13개 REQ와9개 계획/checkbox/task 연결의 일치, 의존성 cycle 없음,
로컬 참조/기존 통합 파일 존재, 상위 역사 mapping 집계 보존을 확인했다.
신규 파일 whitespace 및 `git diff --check`도 통과했다.
코드 테스트・새 config 생성・실제 Jn20/메인 실행・생산 DB 쓰기는 수행하지 않았다.

## 8. 구현 완료・최종 검증 (2026-10-31 23:45 +09:00)

P7.02.01–09 구현 완료. 관련190개 회귀・신규 integrity10개 및 최종 전체274개 테스트
통과(실패0/skip0). 신규 메인 검증은7개 파일46개다. 초기 red를 확인한 후 구현했고,
첫 전체264개 통과 뒤 별도 검토에서 확인한6건도 재현 테스트를 추가해 수정했다.
6건은 비악화 판정・co-best step 누락・정체 완료 crash・회차 이력 소실・기존 CSV
덮어쓰기・동일 반경 실행 경계다. 좁은 후속 검토에서 모두 해결을 확인했다.

Public `validate-main`/`preview-main` 검증, Jn20 5군/5입력/seed40・43, 예산200/
안정성0.10, 미확인 `run-main` exit2/DB 및 output 생성0을 확인했다.
Syntax/signature/diff 검사도 통과했다. 작업용 임시 자료만 사용했으며 실제
pilot DB/results 변경・새 의존성/환경・물리 simulation・commit은 하지 않았다.
코드 변경은 새5개 메인 모듈/2개 설정/7개 테스트와 필수 공유 경계에 한정했다.

메인 초기 입력 중0/2/3의 기대 총 절리 수가1000만을 초과한다(약4629만/1683만/1억1774만).
실제 실행 시 기존 승인 정책대로 생성 전에 멈추며 별도 비용 검토가 필요하다.
자동 입력 변경/비용 gate 해제나 실제 실행 승인을 이번 구현 완료에 포함하지 않는다.
P7.03의 사용자 결과 검토・실제 G4/메인 실행은 남은 별도 단계다.

상세 증거: [batch report](batch-report.yaml), [작업→구현 checkpoint](checkpoints/tasks-to-impl.yaml).

### 2026-11-01 12:09 +09:00 — 고정 상자 생성 및 실측 P32 확인

메인 절리 중심은 물리 도메인 내부에만 배치하고, 명목 P32를 실측값에 맞추기 위한
상자 확장/개수 보정은 하지 않도록 했다. 명목 P32는 입력 설계값으로 유지하고,
경계 절단된 영역 내 면적에서 계산한 실측 P32를 별도 저장·보고한다.

128각형 경계 절단의 해석 가능한 원판 사례를 확인했다: 내부 원판 오차0%,
반원/사분원 오차 약−0.0402%, 원호 segment 사례 약−0.0589%. 이는 확인한 사례의
오차이며 모든 반경·방향·경계 배치에서의 최대 오차를 보장하지 않는다.
`test_rqd_p32` 15개 통과: 고정 상자 중심, 측정값 저장/보고, 임시 DB backfill 재개·
중복 실행, 저장 RQD 재생성 일치 및 원시 관측 불변을 확인했다.

실제 운영 DB backfill・새 물리 simulation은 실행하지 않았다. 당시 오차 기준과
사선/큰 반경 검증은 사용자 확인 전이었으며, 아래 후속 기록에서 기준과 결과를 갱신했다.

### 2026-11-01 12:11:48 +09:00 — P32 측정 정확도 검증 완료

사용자가 대표 해석 사례의 오차 허용을0.1%로 승인했다. 사선 원판 원호 절단 사례는
해석값 대비−0.033843%, 반경150m 원판의 도메인 단면 교차면적 사례는0%였다.
기존 내부/반원/사분원 사례의 최대 오차는−0.0589%였다. 이 수치는 검증 사례에 한정하며
모든 기하에서의 최대 오차를 보장하지 않는다.

`test_rqd_p32` 16개 및 전체 `src/test` 296개가 모두 통과했다. 임시 DB에서
P32 저장/보고/backfill 재개·중복 실행과 `--verify-job`의 RQD 재생성 일치를 확인했다.
운영 DB・기존 실행 backfill・실제 simulation은 실행하지 않았다.

### 2026-11-01 13:08:24 +09:00 — 운영 P32 backfill 부분 진행 후 중단

운영 DB에서 기존 성공 실현 188개 중 101개를 측정해 `realization_p32`에 351행을 추가했다.
사용자 요청에 따라 backfill 프로세스를 중단했으며, 읽기 전용 확인에서 미측정 성공 실현은
87개, 현재 원시 `observations` 행은 22,748개였다. backfill은 P32 추가 테이블만 기록하며
원시 관측 데이터를 재생성하거나 변경하지 않는다. 같은 명령을 다시 실행하면 저장 완료된
실현은 건너뛰고 나머지를 이어서 처리한다.

메인 입력 범위는 이미 `config/rqd_exploration_main_baseline.yml` 및
`config/rqd_exploration_main_baseline2.yml`에 P32 `[0.01, 10]`, 반경 `[1, 150] m`로
설정되어 있다. 메인 설정은 이 파일들을 참조한다.

남은 작업:
1. 사용자가 아래 `measure-p32` 명령을 실행해 나머지 87개 실현을 측정한다.
2. 완료 후 입력/생성기 조건별 실측 P32 범위와 누락 여부를 확인하고 결과를 기록한다.
3. 새 고정 도메인 메인 simulation 전에 구형 생성 방식의 RQD 관측을 새 방식의 안정성 근거로
   재사용할지 결정한다. 두 생성 방식은 절리 중심 배치 분포가 달라 자동으로 동등하다고 볼 수 없다.
4. 새 메인 simulation은 사용자가 직접 실행한다. 이번 정확도 검증의 대표 사례 결과를
   모든 방향·반경에 대한 전역 오차 보증으로 해석하지 않는다.

### 2026-11-01 13:17:39 +09:00 — 운영 P32 backfill 완료 및 결과 확인

읽기 전용으로 운영 DB를 확인했다. 성공 attempt 188/188개에 P32가 저장되어 누락은
0개다. `realization_p32`는 613행이며, 이 중 joint-set별 425행과 실현 전체 합계 188행이다.
저장 방식은 `disk_box_polygon` / `v1-128`; 합계 면적 불일치 0개, SQLite `quick_check`는
`ok`였다. 원시 `observations`는 중단 직후 확인한 값과 같은 22,748행이다.

측정 대상 188개는 모두 구형 `qsimex-mlx-generation-v1` / `mlx` 실현이다. 따라서 이
분포는 새 고정 도메인 생성 방식의 결과가 아니다. 실현 전체의 명목 P32 합계는 중앙값
37.881911, 실측 P32 중앙값은 5.734043 m²/m³였고, 실측/명목 비율 중앙값은 20.967%였다
(범위 0.181%–97.502%). 전 실현에서 실측 합계는 명목 합계보다 작았다.

| 고정 Jn | 실현 수 | 명목 P32 합계 중앙값 | 실측 P32 중앙값 | 실측/명목 중앙값 |
|---:|---:|---:|---:|---:|
| 2 | 59 | 59.373437 | 13.232751 | 22.287% |
| 4 | 59 | 11.609466 | 1.973228 | 10.683% |
| 9 | 32 | 3.147182 | 2.153563 | 3.434% |
| 15 | 38 | 67.293460 | 8.803105 | 14.541% |

기존 입력 425개 joint-set 기록은 새 메인 범위와 일치하지 않는 항목이 많다. P32는
154/425개가 `[0.01, 10]` 밖(모두 상한 초과)이었고, 반경은 268/425개에서 최소 반경이
1m 미만이었다. 188개 실현 중 187개가 적어도 한 joint set에서 새 입력 범위를 벗어났다.
따라서 위 수치를 새 범위의 대표 분포로 간주하지 않는다. DB에는 attempt가 없는 등록 job
1개도 남아 있으나, 성공 실현이 아니므로 backfill 대상에는 포함하지 않았다.

남은 작업:
1. attempt가 없는 등록 job 1개가 의도된 미실행 상태인지 확인한다.
2. 새 고정 도메인 메인 실행에서 구형 생성기 RQD 관측을 안정성 근거로 함께 사용할지 결정한다.
   현재 importer는 생성기 버전이 달라도 형상/측정 설정/Jn이 일치하면 기존 관측을 가져온다.
3. 사용자가 새 입력 범위로 메인 simulation을 실행한 뒤, 새 생성기 실측 P32와 RQD를 별도 분석한다.
4. 대표 해석 사례의 0.1% 측정 오차 기준은 전 방향·전 반경에 대한 전역 최대 오차 보증은 아니다.

### 2026-11-01 13:21:33 +09:00 — 미시작 job 원인 확인

attempt가 없는 job은 임의의 고아 기록이 아니다. 메인 run 상태의 대기열에 `lhs`, seed 43으로
남아 있으며, 해당 run은 bin 8에서 `high_cost_review`로 일시 중지된 상태다. 시작 장부에는
168개 시작만 있고 이 input/seed 조합은 없다. 비용 gate는 시작 장부에 기록하기 전에 검사하므로,
attempt가 없는 것은 gate 동작과 일치한다.

해당 Jn4 후보의 입력은 set-1 P32 0.077784, 반경 28.814–133.713m 및 set-2 P32 24.583175,
반경 0.054–135.709m였다. 예상 joint 수는 set-1 0.66개, set-2 45,156,282.84개,
합계 45,156,283.50개로, pause event의 기록과 정확히 일치한다. 따라서 이 후보에는 측정된
geometry/RQD/P32가 없으며, 이는 성공 실현 backfill 누락이 아니다.

현재 run은 완료된 것이 아니라 비용 검토에서 멈춰 있다. 그대로 재개하면 같은 후보에서 다시
멈추므로 먼저 이 후보의 처리 정책을 정해야 한다. 새 입력 범위로 새 run을 시작하는 경우에도
기존 paused run과 구분해 사전검증해야 한다.

남은 작업:
1. 이 paused run의 고비용 후보를 유지/제외할지, 또는 새 설정으로 별도 run을 시작할지 결정한다.
2. 새 고정 도메인 run에서 구형 생성기 RQD 관측을 안정성 근거로 재사용할지 결정한다.
3. 선택한 입력/관측 정책으로 no-write preview와 비용 gate를 확인한다.
4. 위 조건을 확인한 뒤 사용자가 메인 simulation을 실행한다.

### 2026-11-01 13:24:58 +09:00 — 새 범위 run 선택 및 설정 미리보기

사용자는 기존 paused run을 보존하고 새 입력 범위로 별도 run을 준비하기로 선택했다.
현재 메인 설정 검증은 통과했으며 fingerprint는
`c474f2af527bce174dd968e44a251c5e1e31db25aaa2b7c470cf67a74632a0ab`이다. 기존 paused run의
설정 fingerprint와 달라 새 설정 run으로 구분된다. 기존 run이나 운영 DB는 변경하지 않았다.

DB 없이 수행한 `preview-main`은 `database_written=false`, `simulation_started=false`였고
`initial_jobs=[]`, `runtime_preflighted=false`를 반환했다. 이는 설정 확인용 no-write preview이며,
기존 RQD 관측 재사용이나 adaptive 후보의 실행 비용을 검증한 것은 아니다. 실제 `run-main`은
시작하지 않았다.

남은 작업:
1. 구형 생성기 RQD 관측을 새 고정 도메인 run에서 사용할지 결정한다. 현재 importer는 해당 관측을
   생성기 버전으로 필터링하지 않는다.
2. 관측 정책을 반영해 DB-aware 사전 검토와 비용 gate를 확인한다. 필요하면 구형 관측 제외 동작을
   먼저 구현/검증한다.
3. 사전 검토가 통과하면 사용자가 새 범위의 메인 simulation을 실행한다.

### 2026-11-01 13:26:21 +09:00 — 구형 RQD 안정성 근거 재사용 결정

결정: `qsimex-mlx-generation-v1`에서 생성된 기존 RQD 관측은 새
`qsimex-fixed-domain-centers-v1` run의 통계적 안정성 판정에 합산하지 않는다. 기존 관측과
P32 측정은 DB에 보존하고 과거 결과 비교에는 사용할 수 있지만, 새 생성 방식의 안정성 근거는
새 생성 방식으로 만든 관측만으로 쌓는다.

근거: 운영 DB의 성공 실현 188개는 모두 구형 생성기다. 새 메인 controller는 고정 도메인
생성기를 설정하지만 `_import_existing`은 geometry/measurements/Jn만 확인하고 생성기 버전을
거르지 않는다. 이후 `_histories`도 Jn만으로 입력별 history를 모아 안정성 판정에 포함한다.
또한 과거 실현 188개 중 187개는 새 P32/반경 입력 범위에서 적어도 한 set이 벗어났다.
따라서 현재 importer 동작 그대로 새 run을 시작하면 서로 다른 생성 분포의 결과가 같은
안정성 근거에 합쳐진다.

이 결정은 아직 코드에 적용되지 않았다. 기존 importer 동작을 고치고 테스트하기 전에는
운영 DB를 사용한 새 메인 run을 시작하지 않는다.

남은 작업:
1. 안정성 근거 입력을 fixed-domain generator 버전으로 한정하되 구형 원시 관측과 보고 데이터는 보존한다.
2. 해당 필터 적용 후 DB-aware no-write preview와 비용 gate를 확인한다.
3. 사전 검토가 통과하면 사용자가 새 범위의 메인 simulation을 실행한다.

### 2026-11-01 13:35:19 +09:00 — 생성기별 안정성 근거 분리 구현

메인 controller의 과거 관측 import에서 `qsimex-fixed-domain-centers-v1`이 아닌 snapshot을
제외하도록 했다. 이 필터는 메인 안정성 근거에만 적용하며 원시 observations와 P32 저장 행은
삭제/수정하지 않는다. 회귀 테스트는 구형 관측이 새 controller의 evidence/profile/input에
들어오지 않는 것과 원시 관측 보존을 확인한다. 현 생성기 자료를 import하는 기존 workflow
테스트도 유지했다.

검증: `python -m unittest src.test.test_rqd_main_workflow` — 9개 통과. 운영 DB-aware preview와
새 simulation은 아직 실행하지 않았다.

남은 작업:
1. 운영 DB를 읽기 전용으로 연결한 no-write preview에서 구형 관측이 안정성 근거에서 빠지고,
   새 설정의 비용 게이트가 통과하는지 확인한다.
2. 사전 검토가 통과하면 사용자가 새 범위의 메인 simulation을 실행한다.

### 2026-11-01 13:39:38 +09:00 — DB-aware 사전 검토 완료

현재 설정과 운영 DB로 `preview-main`을 실행했다. 출력은
`database_written=false`, `simulation_started=false`, 기존 원시 관측 22,748개, 독립 실현 188개,
기존 paused run 1개(`high_cost_review`, 시작 168개)였다. preview는 `initial_jobs=[]`,
`runtime_preflighted=false`를 반환했다. 즉 no-write와 데이터 상태는 확인했으나 MLX 장치 preflight는
수행하지 않았다. preview 전후 DB 확인에서 observations 22,748행, realization_p32 613행,
성공 attempt 188개, job 189개, main starts 168개로 모두 변함이 없었다.

저장된 189개 job snapshot은 전부 구형 생성기다. 새 importer 필터와 회귀 테스트에 따라 이 관측들은
새 run의 안정성 근거에 들어가지 않으며, 원시 이력은 유지된다. 입력 범위의 보수적인 expected-joint
상한은 후보당 약 687,550개다: 도메인 부피 54,000m³, 최대 4 sets, set별 P32 ≤10, 반경 ≥1m를
사용해 `4 × 10 × 54,000 / π`로 상한을 계산했다. 이는 정책 한도 10,000,000보다 낮다.

새 run 실행 명령:

```bash
cd "<QSimEx project directory>"
conda activate dlo-cq
python -u -m src.rqd_exploration.cli run-main \
  --config config/rqd_exploration_main.yml \
  --database sqlite/qsimex-rqd-v4.sqlite \
  --output-dir results/rqd_exploration \
  --confirm-execution
```

`run-main`은 MLX runtime preflight를 거친 후 실행한다. 시작/완료 진행은 터미널에서 확인하고,
이벤트별 상세 요약은 `results/rqd_exploration/<run_id>/event-<index>/summary.json`,
누적 coverage 보고서는 `results/rqd_exploration/cumulative/revision-<index>/reports/report_summary.json`
에서 확인한다. CLI 최종 JSON의 `main_summary.reason`이 `targets_complete`인지 확인한다.

남은 작업: 사용자가 위 명령으로 새 메인 simulation을 실행하고 결과를 검토한다. 이번 단계에서는
`run-main`을 실행하지 않았다.

### 2026-11-01 13:41:53 +09:00 — 메인 실행 예산 확인

현재 새 메인 설정의 `maximum_starts`는 run당 200회이며 `automatic_retries`는 0이다.
별도 보호 한도인 `maximum_expected_joints`는 시작 건당 10,000,000개다. 새 범위의
P32 ≤10, 최소 반경 ≥1m, 최대 4 sets, 도메인 부피 54,000m³를 적용하면 보수적 상한은
시작당 약 687,550개, 200회 전부 사용 시 약 137.51M expected joints다. 이 값은 입력 범위로
계산한 상한이지 실행시간/실제 생성 수 예측은 아니다. 설정에는 wall-clock 또는 GPU-hour 한도가 없다.

DB에는 기존 paused run만 있으며 168/200 starts를 사용했다(32회 잔여). 이는 새 설정 run의
예산과 별개다. 기존 run은 고비용 후보 때문에 계속 paused 상태이고, 새 설정 run은 새 200회
예산을 갖는다. 200회가 목표 완료에 충분하다고 preview만으로 보장할 수는 없다.

### 2026-11-01 13:44:54 +09:00 — 200-start 예산의 expected-joint/시간 추정

새 입력 범위에서 set별 P32 상한은 10, 중심 크기 분포의 최소 반경은 1m, 도메인 부피는
54,000m³이며 후보 하나의 최대 set 수는 4다. disk area는 항상 πR²이고 R≥1이므로
E[πR²]≥π. 이에 따라 set당 expected joint 상한은 약 171,887개, 후보당은 약 687,549개,
200회를 전부 이 상한에서 실행하는 총량은 약 137.51M expected joints다. 이는 예상 개수
파라미터의 상한이지 실제 난수 생성 개수의 절대 상한은 아니다.

시간 환산의 과거 기준은 DB의 성공 실현 188개(`qsimex-mlx-generation-v1`): expected joints
총 318.78M, runtime 총 9,161초(2.54시간), 집계 처리량 약 34,797 joints/s였다. 새 run의
137.51M 상한을 이 처리량으로 환산하면 약 1.10시간이다. 과거 건별 처리량 하위 10백분위
(약 23,735 joints/s)를 적용하면 약 1.61시간이다. 따라서 200회를 모두 상한 가까이 소비하는
경우의 계획용 추정은 대략 1–2시간이다. 한 건의 상한은 약 20–29초로 환산된다.

이 추정은 구형 생성기·다른 입력 분포의 runtime으로 환산한 값이므로 새 고정 도메인 run의
보증치는 아니다. 실제 종료는 200회보다 일찍 될 수 있고, 상한보다 입력이 낮으면 더 짧다.
반대로 장치/runtime 차이, 보고서 생성, 일시 중단은 경과시간을 늘릴 수 있다. 설정에는
별도의 wall-clock/GPU-hour 제한이 없다.

### 2026-11-01 13:49:39 +09:00 — 300회 상한과 200회 검토 체크포인트

사용자 결정에 따라 새 메인 run의 최대 시작 횟수를 300회로 준비하고, 200회 완료 시
자동으로 `review_checkpoint` 상태에 멈추도록 한다. 이 체크포인트에서 같은 실행 명령을
다시 실행하면 검토 후 재개로 간주하고 최대 100회를 추가로 사용할 수 있다. 사용자
중단(`Ctrl+C`)도 같은 run의 checkpoint에서 재개하며, 이때 이미 사용한 start 수는 유지된다.
실행 시 control journal schema v1→v2를 트랜잭션으로 확장해 300 start index를 허용하며,
기존 paused run의 정책 snapshot과 start 기록은 보존한다. 새 config fingerprint로 별도 run이
생성되고, 이번 사전 검증에서는 DB 변경이나 시뮬레이션을 수행하지 않았다.

300회 모두 입력 상한에 가까운 보수적 workload는 약 206.26M expected joints다. 과거
처리량 환산은 약 1.65–2.42시간이며, 기존 runtime 차이와 실행 오버헤드를 고려한 계획용
범위는 약 2–3시간이다. 200회 체크포인트에서 빈 coverage와 안정성 근거를 검토한 뒤
재실행 여부를 결정한다. 300회 cap이나 별도 시간 제한을 넘겨 자동 실행하지 않는다.

### 2026-11-01 14:57:23 +09:00 — 200회 검토 체크포인트 진단

새 run `main-4277c2f10e990b594fababb9b4fe3119fdc4a0091aaf50978f75d7354ece28d1`은
오류가 아니라 설정된 `review_checkpoint`로 정상 정지했다. `starts_consumed=200`이고
200개 start 모두 `succeeded`다. 현재 상태는 `bin=8`, phase `search`,
target `8/9/4/0.75/pilot-bh`, 대기 queue 6건이며 데이터 손실 징후는 없다.

기존 paused run은 별도 run으로 `high_cost_review`, 168/200 상태 그대로다. coverage와
안정성 근거를 검토한 뒤, 추가 실행을 원하면 동일 config/database/output-dir로
`run-main` 명령을 다시 실행해 새 run을 최대 300회까지 이어간다.

### 2026-11-01 16:00:33 +09:00 — 300-start 실행 결과 분석

새 run `main-4277c2f10e990b594fababb9b4fe3119fdc4a0091aaf50978f75d7354ece28d1`은
`budget_exhausted`로 정상 정지했다. run 예산 300/300을 소비했고 300개 start 모두
`succeeded`; 실패한 start는 없다. 200회 검토 체크포인트 후 같은 run을 재개해 남은 100회를
사용한 결과다. 이전 paused run(`high_cost_review`, 168/200)은 별도 보존되어 있다.

컨트롤러의 빈 전이는 bin10(42 starts), bin9(137), bin8(286)에서 확인됐다. 따라서 bin10,
bin9, bin8은 각 빈의 모든 reachable target이 안정성 완료 기준을 통과했다. 총 650개
reachable target 중 안정 완료는 96개(14.8%): bin10 3/3, bin9 10/10, bin8 33/33,
bin7 50/54다. 현재 bin7에 남은 미완료 target은 `7/4/3/1/pilot-bh`(안정 입력 1개),
`7/9/3/0.75/pilot-bh`, `7/9/4/0.75/pilot-bh`, `7/9/4/1/pilot-bh`(각 안정 입력 0개)다.
현재 round는 bin7의 첫 target 안정성 단계이며 seed67 작업이 예산 때문에 대기 중이다.
bin6–1은 아직 컨트롤러가 순회하지 않았다.

누적 DB에는 observation 59,048행, P32 1,566행이 있으며 누적 report revision10의
fingerprint conflict는 0이다. 이는 기존 데이터와 새 run을 합친 누적치다. 상세 누적 요약은
`results/rqd_exploration/cumulative/revision-10/reports/report_summary.json`에 있다.
300회 상한이 실제로 목표 완료를 보장하지 않는다는 점이 확인되었다. 동일 명령 재실행만으로는
추가 시작이 되지 않으며, 추가 예산은 별도 승인과 정책/스키마 변경 후 결정해야 한다.

### 2026-11-01 17:30 +09:00 — 20,000-start 단일 run 및 최소 반경 비교

사용자 승인에 따라 새 정책을 `maximum_starts=20,000`, `review_checkpoint_starts=10,000`으로
변경했다. 체크포인트 후 같은 config/database/output-dir로 `run-main`을 재실행하면 같은 run에서
누적 시작 횟수를 유지해 재개한다. 정책 fingerprint 변경으로 이전 300-start run을 묵시적으로
이어가지 않고 새 run을 만들며, 기존 DB의 원자료/분석과 이전 run은 보존한다. 시작 기록의
SQLite 제어 저널 한도도 schema v3로 올리고 v1/v2 저널을 기록 보존 방식으로 마이그레이션한다.

최소 반경 0.05m 그룹(188회 성공)은 총 318,930,636개, 회당 평균 약 1,696,440개였고,
최소 반경 1m 그룹(300회 성공)은 총 671,114개, 회당 평균 약 2,237개였다. 정규화한 절리 수/
1,000m² 지표는 약 4,345에서 12.46으로 감소했다. 다만 두 그룹은 최소 반경뿐 아니라 P32 상한
(100→10)과 생성기(`qsimex-mlx-generation-v1`→`qsimex-fixed-domain-centers-v1`)도 달라,
이 차이를 최소 반경 변경 하나의 인과 효과로 해석할 수는 없다.

검증: 관련 테스트 49개 통과, `validate-main` 유효. 이 변경 중 DB 변경이나 DFN simulation은
수행하지 않았다.
