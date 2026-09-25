# QSimEx Implementation Plan

- 작성일: 2026-09-24
- 기준 문서:
  - `Task_20260922.md`
  - `DesignSpec_20260922.md`
- 비고: 이 문서는 기준 문서의 내용을 구현하기 위한 실행 계획이다. 기준 문서 자체는 그대로 유지하며, 구현 단계만 이 파일에서 관리한다.

---

## 1. 목적

이 구현 계획은 다음을 달성하기 위한 실제 작업 순서를 정의한다.

- `Task_20260922.md`에 기록된 현재 상태 점검과 재개 우선순위 반영
- `DesignSpec_20260922.md`의 규정된 정의와 검증 원칙을 구현에 연결
- Q' 기반 의사결정 구조를 코드로 구현할 때, 기준 문서와 코드가 서로 어긋나지 않게 관리

핵심 원칙:

- `Task_20260922.md`와 `DesignSpec_20260922.md`는 변경 기준 문서로 유지한다.
- 기준값 선정의 구체적인 프로파일 결합 방법은 `QPrimeCutoffSelectionMethod_20260924.md`를 참조한다.
- 구현 계획은 수행 여부와 순서를 관리하는 문서로만 사용한다.
- 구현 과정에서 기준 문서의 의미가 바뀌어야 한다면, 별도 기준 문서 업데이트를 통해 정리하고 이 계획은 그 변경을 반영하는 실행 계획으로 간다.

### Q' 의사결정과 시뮬레이션 검증의 분리

실제 굴착 여부를 결정할 때 사용할 수 있는 입력은 굴착 전에 시추로 얻는
`Q'_BH`뿐이다. `Q'_face`는 실제 또는 가상 굴착 이후에 얻는 결과이므로,
운영 판정 함수의 입력이나 판정 기준값의 직접 입력으로 사용하지 않는다.

여기서 실제굴착은 현장에서 암반을 실제로 굴착하고 관측·조사·계측하는 것을
뜻한다. 가상굴착은 동일한 DFN domain에 터널·굴진면 조건을 적용하여 시뮬레이션
참조지표를 계산하는 것을 뜻한다. 현재 Phase 3에서 사용하는 `Q'_face`는 실제굴착
관측값이 아니라 가상굴착 참조 결과이다.

시뮬레이션에서는 동일한 DFN domain에 대해 `Q'_BH`와 가상 굴착 결과인
`Q'_face`를 모두 생성할 수 있다. 이때 시뮬레이션의 역할은 다음과 같이
분리한다.

1. `Q'_BH`에 하한·상한 기준값을 적용하여 굴착 보류·불확실·굴착 결정을 모의한다.
2. 가상 굴착 후의 `Q'_face`를 이용해 그 사전 결정이 적절했는지 사후 평가한다.
3. 여러 독립 domain의 반복 결과를 이용해 기준값의 안정성과 적용 가능성을 검토한다.

따라서 `Q'_face`는 실제 운영 판정의 사전 입력은 아니지만, 시뮬레이션에서
기준값 후보를 산출·평가하는 핵심 참조 결과이다. 기준값 탐색은 `Q'_BH`에
적용하고, `Q'_face`와 절리 교차·밀도·방향성·처분 적합성 관련 지표의
공통 변화점과 안정 구간을 이용해 하한·상한을 제안한다. 기존의 단일
`threshold`로 `Q'_face`를 처분 적합·부적합으로 나누는 접근은 사용하지 않는다.
`PR/TR/POST`는 프로파일 변화 상태이며 처분 적합·부적합 라벨이 아니다. 처분
적합·부적합은 EFPC 또는 향후 연결되는 독립 평가 adapter가 제공할 공학적 결과로
정의하고, 해당 adapter가 연결되기 전에는 안전성 성능을 계산하거나 주장하지 않는다.

정책 허용치나 새로운 종합지수를 먼저 도입하지 않는다. 각 참조지표를
개별적으로 관찰하여 여러 독립 domain과 조건군에서 반복되는 공통 경향을
확인한다. 공통 변화점·안정 구간이 없으면 기준값을 제시하지 않고
`Q' 단독 기준값 산출 불가`로 기록한다. EFPC가 완성되면 adapter로
처분 적합성 참조지표를 추가하여 잠정 기준값을 재검증한다.

---

## 2. 기준 문서와 구현 계획의 관계

### 기준 문서

- `Task_20260922.md`
  - 현재 상태, 재개 포인트, 작업 우선순위, 정리 대상, 검증 결과를 기록하는 문서
- `DesignSpec_20260922.md`
  - 최종 목적, 오류 정의, 경계값 원칙, Train/Validation 검증 흐름, 적용성 범위를 기술하는 문서

### 구현 계획 문서

- 이 문서 `ImplementationPlan_20260924.md`
  - 기준 문서를 실제 코드와 산출물로 연결하는 실행 계획서
  - 어떤 작업을 언제, 어떤 순서로, 어떤 산출물을 만들지 결정
  - 기준 문서 자체의 내용을 덮어쓰지 않음

---

## 3. 현재 구현 상태 요약

기준 문서 기반으로 보면 현재 QSimEx는 다음 수준에 있다.

- DFN 생성, Q/Q' 계산, 시추공-굴진면 비교 파이프라인은 실험적으로 동작함
- 대표 CLI 케이스 실행이 가능함 (`conda run -n dlo-cq python run_cli.py ...`)
- 문서와 코드 구조 간 정리 필요 항목이 존재함
  - `setup.txt`와 현재 `src/` 구조 불일치
  - `README`와 실제 테스트 경로 불일치
  - `src/core/__init__.py`의 공개 API 경로 정리 필요
  - 테스트 파일 존재하나 실제 검증이 부족
- 하지만 구현이 완전히 끝난 상태는 아니며, 보편 경계값 산정을 위한 기준 문서의 정량 규칙을 코드로 연결하는 단계가 남아 있음

---

## 4. 구현 우선순위

### Phase 1. 기준 문서의 정의를 코드 명명으로 정리

목표

- 실제 코드에서 혼재되는 FP/FN, 비용, 경계값 용어를 표준화한다.
- 기준 문서의 의미와 코드 로직이 일치하도록 정리한다.

작업 항목

- `false_safe` / `false_reject` 표준화
- `cost_false_safe` / `cost_false_reject` 표준화
- `R_FS_pass`, `R_FN_reject`의 계산 위치와 의미 정의
- 레거시 명칭 목록 정리 및 내부 변환 함수 추가

산출물

- `src/core/constants.py` 또는 유사 표준 명명 모듈
- metric normalize helper
- 문서 내 legacy mapping 기록

완료 기준

- 코드 전반에서 동일 의미의 항목이 같은 이름으로 사용됨
- 테스트가 명명 변환 및 표준화 동작을 검증함

---

### Phase 2. 데이터 분할 및 재현성 확보

목표

- Train/Validation 분할이 seed/domain 단위로 reproducible 하게 동작한다.
- 기준 문서의 “동일 DFN domain이 Train과 Validation에 섞이지 않음” 조건을 구현한다.

작업 항목

- `manifest` 생성 로직 구현
- seed/domain ID를 보존한 split 기능 추가
- 동일 domain 혼합 방지 체크
- split 결과 저장 파일 생성

산출물

- `manifests/` 또는 `results/`에 split manifest 저장
- `src/core/split_manifest.py` 또는 유사 모듈
- `src/test/test_split_manifest.py`

완료 기준

- 같은 seed/domain이 Train과 Validation에 동시에 나타나지 않음
- split manifest를 재현하여 같은 결과를 다시 만들 수 있음

---

### Phase 3. Q' 판정 기준값 탐색 엔진 구현

목표

- 기준 문서의 Q' 판정 기준값 탐색 규칙을 코드로 구현한다.
- 탐색 범위 안의 기준값별 성능을 계산하고, 이후 하한·상한 기준값을 자동 생성한다.

작업 항목

- Q' 판정 기준값 생성 (`0.1~400` 범위, 로그 공간 10구간을 초기 설정으로 사용)
- `Q'_BH`에만 기준값을 적용하여 3단계 의사결정 결과 생성
- 시뮬레이션의 `Q'_face`는 기준값 산출·평가에 사용하는 핵심 참조 자료로 취급하되, 실제 운영 판정 입력과 분리
- Q' 구간별 참조 프로파일 분포와 인접 구간 변화를 계산
- 각 프로파일 상태를 `PR`/`TR`/`POST`로 표현하고 공통 PR/POST 교집합을 계산
- 각 기준값별 구간 표본 수와 프로파일 상태를 저장
- 입력 설정은 YAML(`config/qprime_cutoff_search.yml`)로 관리한다.
- 요약 결과는 JSON으로 저장하며, 비유한 값은 JSON `null`로 기록한다.
- 시뮬레이션 참조 분석은 시추공 행의 `Qp_bh_mean`과 `Qp_face_mean` 및 기타 참조지표를 사용한다.
- `Qp_face_mean`을 단일 threshold로 변환해 사후 라벨을 만드는 방식은 사용하지 않는다.
- 비교 결과 행은 `build_search_records()`로 보존·변환하며, 사후 라벨은 외부에서 명시적으로 주입한다.
- 기준값 탐색의 관측 단위는 시추공 하나로 고정하며, 시추공 행의 `Qp_bh_mean`을 사용한다.
- face-level `Qp_borehole_mean`은 보고용 요약값으로만 보존하고 기준값 탐색 입력으로 사용하지 않는다.
- 시추공 관측값이 없을 때 `0.0`으로 대체하지 않고 결측(`NaN`)으로 유지하여 탐색에서 배제한다.
- 필요할 때의 이진 처분 적합성 결과는 EFPC 또는 독립 평가 adapter가 생성한 결과로만 사용하며, 탐색 엔진은 라벨의 의미를 추론하거나 `Qp_face_mean`으로 생성하지 않는다.
- EFPC는 현재 Phase 3의 필수 의존성이 아니다. QSimEx는 `Qp_bh_mean`과 가상굴착 참조 프로파일만으로 hold·uncertain·excavate 후보 구간의 표본 분포를 먼저 탐색한다.
- EFPC 또는 독립 안정성 평가 결과는 향후 adapter를 통해 선택적으로 `simulation_outcome`, 위험도, 기대손실 근거로 연결한다.
- EFPC 결과가 없는 단계에서는 안전성 통과나 false-safe/false-reject를 주장하지 않고, 구간별 노출량과 Q' 분포만 보고한다.

산출물

- `src/core/qprime_cutoff_search.py`
- `src/test/test_qprime_cutoff_search.py`
- `config/qprime_cutoff_search.yml`
- `config/profile_mc_exploration.yml`
- `results/qprime_cutoff_search_<timestamp>.json` 또는 parquet
- CLI 실행: `python -m src.core.qprime_cutoff_search --input ... --config ... --output ...`
- MC 실행 준비: `conda run -n dlo-cq python run_profile_mc.py --config config/profile_mc_exploration.yml`

완료 기준

- `Qp_bh_mean` 시추공 단위 입력으로 Q' 구간별 참조 프로파일을 재현할 수 있음
- 각 프로파일의 `PR`/`TR`/`POST` 상태와 공통 PR/POST 교집합을 저장할 수 있음
- 공통 영역이 없거나 기준값이 역전되면 `not_identifiable`을 반환함
- `Qp_face_mean`을 단일 threshold로 이진 라벨화하지 않음
- EFPC 없이도 탐색 결과를 생성하되 안전성 보증으로 해석하지 않음
- 대규모 MC 실행은 case·seed·face 위치·시추공 window를 YAML로 재현할 수 있음
- MC 결과는 레거시 결과와 분리된 `results/profile_mc_exploration/`에 저장함

---

### Phase 4. 변화점·안정 구간의 통계적 재현성 확인

목표

- 기준값 후보별 참조지표 변화와 안정성이 domain 재표본에서도 반복되는지 확인한다.
- 새로운 정책 허용치나 종합지수를 도입하지 않고, 변화점 위치의 불확실성을 기록한다.

작업 항목

- bootstrap / hierarchical bootstrap으로 변화점·안정 구간의 변동 범위 계산
- `Q'_face`와 절리·처분 적합성 참조지표별 변화 패턴 저장
- domain·조건군별 재현성 및 표본 부족 여부 기록

산출물

- `src/core/statistics.py`
- `src/test/test_statistics.py`
- 경계값 별 신뢰구간 결과 저장

완료 기준

- 공통 변화점과 안정 구간의 변동 범위가 계산된다.
- 재표본에서 경향성이 유지되지 않으면 기준값을 제시하지 않는다.

---

### Phase 5. 시뮬레이션 기반 기준값 제안과 역전 처리

목표

- Train 결과에서 공통 변화점과 안정 구간을 바탕으로 `Q'_lowerbound`와 `Q'_upperbound`를 제안하는 로직을 코드화한다.
- 프로파일 결합과 기준값 산출은 `QPrimeCutoffSelectionMethod_20260924.md`의 교집합 방법을 따른다.
- 제안값은 잠정 가이드로 기록하며, 안전성 보증이나 정책 승인값으로 해석하지 않는다.

작업 항목

- `Q'_lowerbound` = 불리한 참조지표 영역과 변화 영역을 나누는 가장 높은 후보
- `Q'_upperbound` = 변화 영역과 양호한 안정 영역을 나누는 가장 낮은 후보
- lower >= upper, 공통 변화점 부재, 표본 부족, 경향성 불안정 시 기준값 산출 불가 처리
- rounding rule 및 문서화

산출물

- `src/core/boundary_selector.py`
- `src/test/test_boundary_selector.py`

완료 기준

- 정상 케이스는 유효한 경계값을 반환
- 역전 또는 표본 부족 케이스는 명시적으로 경고 혹은 불가 상태를 반환

---

### Phase 6. Blind Validation 파이프라인

목표

- 기준 문서의 Train/Validation split 절차와 blind validation 프로세스를 구현한다.

작업 항목

- Train에서 결정한 경계값을 Validation에 고정 적용
- Validation에서 경계값을 재튜닝하지 않음
- 최악 조건별 성능 보고
- 결과 요약 리포트 생성

산출물

- `src/core/validation.py`
- `results/validation_report_<timestamp>.json`
- `reports/validation_summary_<timestamp>.md`
- `src/test/test_validation.py`

완료 기준

- Train에서 고정된 경계값이 Validation 결과에 그대로 적용됨
- 기준 문서의 blind validation 의도가 코드로 보장됨

---

### Phase 7. 적용성 범위(DOA) 및 판정 불가 로직

목표

- 기준 문서의 현장 적용성 체크와 판정 불가 규칙을 코드로 반영한다.

작업 항목

- 절리군 수, P32, 방향성, 교차각, 규모 조건을 체크
- 조건별 적용 가능 여부 판정
- 네 가지 적용성 질문과 판정 상태 연결
- `판정 불가` 시 추가 조사/보류 로직 구현

산출물

- `src/core/doa.py`
- `src/test/test_doa.py`
- `domain_of_applicability` 관련 CSV/JSON 리포트

완료 기준

- 조건 범위를 벗어나면 `판정 불가`로 떨어짐
- 명시된 조건군별 경계값과 범위가 리포트에 저장됨

---

### Phase 8. 문서·테스트·실행 엔트리 정리

목표

- 현재 구조와 문서가 일치하도록 정리하고, 구현이 실제로 재현가능한 상태인지 검증한다.

작업 항목

- `README.md`와 `setup.txt` 재정비
- `src/test` 관리 방식 정리
- 로컬 smoke test / CLI smoke check 추가
- 구현 진척과 결과를 기준 문서와 연결

산출물

- 문서 정비
- 테스트 통과 로그
- 실행 예시 문서

완료 기준

- 새로 구현한 기능이 CLI 또는 test script로 검증됨
- 기준 문서와 실행 문서가 서로 충돌하지 않음

---

## 5. 작업 실행 순서

1. Phase 1: 명명 표준화
2. Phase 2: split manifest
3. Phase 3: Q' cutoff search
4. Phase 4: CI/bootstrap
5. Phase 5: boundary selector
6. Phase 6: blind validation
7. Phase 7: DOA/판정 불가
8. Phase 8: 문서와 테스트 정리

이 순서는 기준 문서의 논리적 흐름과 구현 의존성을 반영한다. 특히 Phase 3~6은 하나의 연속 파이프라인으로 진행해야 하며, Phase 7은 이후 현장 적용 제약을 다루는 단계이다.

---

## 6. 구현 중 필수 원칙

- `Task_20260922.md`와 `DesignSpec_20260922.md`를 수정하지 않고 기준으로 유지한다.
- 구현 과정에서 발견된 불일치가 있으면, 해당 불일치는 기준 문서에 반영할지 여부를 확인한 뒤 별도 문서 정리를 수행한다.
- 코드 수정은 작은 단계로 나누어 검증한다.
- 각 phase는 결과를 산출물과 테스트로 남긴다.
- Q' 경계값의 최종 숫자 발표는 기준 문서가 정한 통계적 검증 조건을 통과했을 때만 수행한다.

---

## 7. 작업 로그

### 2026-09-24

- 상태: STARTED
- 작업: 구현 계획서 신규 작성
- 기준 문서 접속: `Task_20260922.md`, `DesignSpec_20260922.md`
- 내용: 기준 문서를 유지하면서 실제 구현을 수행할 단계별 계획 수립
- 비고: 기존 구현 계획 파일은 덮어쓰지 않고 신규 파일로 기록

### 2026-09-25

- 상태: Phase 1 사전 정리 완료, 공식 Phase 1 명명 표준화는 아직 미완료
- 스펙 정합성 점검: DesignSpec, ImplementationPlan, QPrimeCutoffSelectionMethod 간
  가상굴착·실제굴착·PR/TR/POST 정의와 lower/upper 산정 원칙을 대조함
- 스펙 보완: 가상굴착은 DFN domain에서 계산한 `Q'_face` 참조 결과로, 실제굴착은
  현장 관측·조사·계측 절차로 명시함
- 스펙 보완: 처분 적합·부적합은 EFPC 또는 독립 평가 adapter의 공학적 결과로
  정의하고, Phase 3에서는 이를 가정하지 않도록 명시함
- 스펙 보완: `PR/TR/POST`는 적합·부적합 라벨이 아닌 프로파일 변화 상태로 고정함
- 코드 정리: 임시 `4.0` 단일 분류 및 구형 보고서 경로를 `LEGACY_DO_NOT_USE`로
  격리하고, 활성 보고서가 `not_identifiable`을 기록하도록 차단함
- 검증: `conda run -n dlo-cq python -m unittest discover -s src/test -p
'test_*.py' -v` 결과 37개 테스트 통과
- 다음 작업: 공식 Phase 1 명명 표준화를 먼저 완료하고, 이후 Phase 2 입력 계약과
  seed/domain split 재현성을 점검한 뒤, Phase 3에서 가상굴착 참조 프로파일 기반
  후보 탐색을 구현함. EFPC 또는 독립 평가 adapter가
  연결되기 전에는 적합성 성능·false-safe·false-reject를 계산하지 않음

---

## 8. 이후 진행 체크리스트

- [ ] Phase 1: 명명 표준화 완료
- [ ] Phase 2: seed/domain split manifest 완료
- [ ] Phase 3: Q' 판정 기준값 탐색 완료
- [ ] Phase 4: CI/bootstrap 완료
- [ ] Phase 5: boundary selector 완료
- [ ] Phase 6: blind validation 완료
- [ ] Phase 7: DOA/판정 불가 로직 완료
- [ ] Phase 8: 문서 및 실행 정리 완료

이 체크리스트는 기준 문서와의 정합성을 유지하면서 실제 구현 마감 상태를 추적하는 용도로 사용한다.
