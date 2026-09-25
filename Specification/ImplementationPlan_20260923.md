# QSimEx 구현·검증 작업계획서

작성일: 2026-09-23
담당: (작성자 기입)

요약

- 목적: Specification 문서(`Task_20260922.md`, `DesignSpec_20260922.md`)에 명시된 Q' 경계값 검증 파이프라인을 단계적으로 구현하고, 각 단계 완료 시 진행 로그를 남겨 연속성을 확보한다.
- 주요 결과: 재현 가능한 Train/Validation 분할, 경계값 탐색 엔진, 조건부 위험도 계산 및 95% 신뢰구간, Blind Validation 리포트, `domain_of_applicability` 리포트, 유닛테스트 및 사용법 문서.

우선순위 단계

1. 정의·표준화 (정의 정리)

- 목표
  - FP/FN 명칭과 비용 명칭 통일(코드·문서 전역)
  - `reference label`(굴진면 라벨)과 `decision score`(Q'\_BH) 분리
- 작업
  - `src/core/constants.py` 또는 `src/config/nomenclature.yml`에 표준명명 추가
  - 코드 검색(현존 혼용된 이름 목록화) 및 일괄 치환 계획 수립
  - 간단한 유닛테스트 추가: 명명 매핑 검증
- 산출물
  - `src/config/nomenclature.yml` (또는 `src/core/constants.py`)
  - `src/test/test_nomenclature.py`
- 예상 소요: 30–90분

2. 데이터 분할 및 manifest (Train/Validation)

- 목표
  - DFN seed/domain 단위로 7:3 분할하고 manifest 저장
  - 동일 domain이 Train/Validation에 섞이지 않도록 보장
- 작업
  - `src/core/split_manifest.py`: seed/domain 기반 split 함수 및 manifest(예: CSV/JSON) 생성
  - CLI 옵션(`run_cli.py`)에 `--make-manifest` 추가(선택)
  - 테스트: 작은 가짜 seed 세트에 대해 분할 결과의 domain 중복 없음 단위테스트
- 산출물
  - `manifests/train_manifest.json`, `manifests/validation_manifest.json`
  - `src/test/test_split_manifest.py`
- 예상 소요: 1–2시간

3. Q' 판정 기준값 탐색 엔진

- 목표
  - Q' 판정 기준값(초기 `0.1~400`, 로그 공간 10구간) 탐색, 각 기준값에서 `R_FS_pass`, `R_FN_reject` 계산
  - 기준값별 confusion matrix, 표본수, 점추정치 저장
- 작업
  - `src/core/qprime_cutoff_search.py` 구현
  - 결과 저장 포맷: `results/qprime_cutoff_search_{train|validation}.parquet` 또는 JSON
  - 핵심 함수: `compute_confusion_by_threshold(data, thresh)`
  - 테스트: 합성 데이터에서 기대값 확인
- 산출물
  - `src/core/qprime_cutoff_search.py`, `src/test/test_qprime_cutoff_search.py`
- 예상 소요: 2–4시간

4. 신뢰구간·부트스트랩 (statistical CI)

- 목표
  - Wilson/Clopper-Pearson(또는 exact binomial)과 bootstrap(계층적 포함)으로 95% CI 계산
  - 계층적 bootstrap: DFN domain을 군집 단위로 재표본
- 작업
  - `src/core/statistics.py`에 `binomial_ci`, `hierarchical_bootstrap` 추가
  - `qprime_cutoff_search`와 연동해 각 기준값의 CI 저장
  - 테스트: 알려진 분포의 CI 재현
- 산출물
  - `src/core/statistics.py`, `src/test/test_statistics.py`
- 예상 소요: 3–6시간

5. 경계값 선택 및 역전 처리 로직

- 목표
  - Train 결과 기준으로 `Q'_lowerbound`(FN 조건)과 `Q'_upperbound`(FP 조건) 선정 규칙 구현
  - 역전(`lower >= upper`) 또는 표본 부족시 처리(경고 또는 판정 불가)
- 작업
  - `src/core/boundary_selector.py` 작성: 정책 파라미터(`alpha_FN`, `alpha_FS`, rounding_rule`) 입력
  - 테스트: 합성 케이스로 정상·역전 케이스 확인
- 산출물
  - `src/core/boundary_selector.py`, `src/test/test_boundary_selector.py`
- 예상 소요: 2–4시간

6. Blind Validation 파이프라인

- 목표
  - Train에서 고정된 경계값을 Validation에 적용, 결과 리포트(조건별+최악조건 포함)
- 작업
  - `src/core/validation.py` 작성: 고정 경계 적용, stratified 성능 보고서 생성
  - 리포트 포맷: CSV/JSON + 요약 Markdown 리포트
  - 테스트: manifest에 따라 Validation이 Train seed와 분리되어 동작함을 확인
- 산출물
  - `results/validation_report_{timestamp}.json`, `reports/validation_summary_{timestamp}.md`
  - `src/test/test_validation.py`
- 예상 소요: 2–4시간

7. DOA(도메인 적용성) 리포트 및 현장 게이트

- 목표
  - 네 가지 적용성 질문을 코드에서 체크하고 리포트에 포함
  - 조건군별 표 출력(절리군 수, P32 범위, 방향성 등)
- 작업
  - `src/core/doa.py` 작성: 조건 검사 함수 + 리포트 생성
  - UI/CLI: `--doa-check` 옵션(요약 출력)
  - 테스트: 조건 케이스에 대한 판정 로직 단위테스트
- 산출물
  - `src/core/doa.py`, `src/test/test_doa.py`
- 예상 소요: 2–3시간

8. 문서화·테스트·CI 연결

- 목표
  - README 업데이트(실행 예제 포함), 테스트 스위트 보강, 간단한 CI(로컬 스크립트)
- 작업
  - `README.md`의 Q' 워크플로우 섹션 추가
  - `src/test/*`에 핵심 유닛테스트 추가
  - 로컬 실행 스크립트: `scripts/run_smoke.sh`
- 산출물
  - 문서 업데이트, 테스트 통과 확인
- 예상 소요: 1–3시간

운영·배포 노트

- 권장 실행 환경: `conda` 환경(`dlo-cq`) 사용(종속성은 `requirements.txt` 또는 `environment.yml`에 기록)
- 권장 실행 예

```bash
cd "06. QSimEx"
conda run -n dlo-cq python run_cli.py --make-manifest --manifest-out manifests/train_manifest.json
conda run -n dlo-cq python -m src.core.qprime_cutoff_search --manifest manifests/train_manifest.json --out results/qprime_cutoff_search_train.parquet
```

진행 로그(이 파일 하단에 기록)

- 형식(템플릿):

```
- 날짜: YYYY-MM-DD
- 작성자: 이름
- 단계: (예: 1) 정의·표준화)
- 상태: TODO / IN-PROGRESS / DONE
- 변경 파일: (경로 목록)
- 요약: 한 문장 요약
- 세부: 필요 시 상세 변경점, 테스트 결과, 남은 이슈
```

진행 로그 (초기값)

- 날짜: 2026-09-23
- 작성자: (자동 생성: GitHub Copilot)
- 단계: 프로젝트 계획 작성
- 상태: DONE
- 변경 파일: `Specification/ImplementationPlan_20260923.md`
- 요약: 단계별 작업계획서 및 진행 로그 템플릿 생성
- 세부: 향후 각 단계 완료 시 동일 파일 하단에 진행 정보를 순차적으로 추가바람

추가 제안

- 매 단계 완료 후 이 파일 하단에 진행 로그를 추가하거나, 별도 `Specification/progress_log.md`를 두어 PR 번호와 변경 요약을 기록하면 리포트 추적이 쉬움
- 각 주요 변경(코드·테스트·문서)은 가능한 한 작은 커밋으로 나누고 PR 템플릿에 `Specification` 파일 링크를 포함할 것

---

끝.

진행 로그 (업데이트)

- 날짜: 2026-09-23
- 작성자: GitHub Copilot
- 단계: 1) 정의·표준화
- 상태: DONE
- 변경 파일:
  - `src/core/constants.py`
  - `src/test/test_nomenclature.py`
- 요약: 명명 통일을 위한 `constants` 모듈 추가 및 해당 모듈 검증용 단위테스트 추가
- 세부: `src/core/constants.py`는 레거시 지표명과 표준 키 간 매핑 및 `standardize_metrics()` 헬퍼를 제공. 기본 유닛테스트(`src/test/test_nomenclature.py`)를 추가하여 입력이 None일 때와 기본 매핑이 작동하는지를 확인함. 향후 다른 모듈에서 legacy metric dict를 받아 리포트/선택기로 전달하기 전에 `standardize_metrics()`를 호출하도록 점진적으로 적용 권장.

추가 작업

- 날짜: 2026-09-23
- 작성자: GitHub Copilot
- 단계: 1) 정의·표준화 (입력 정규화 훅 적용)
- 상태: DONE
- 변경 파일:
  - `src/core/decision_test.py` (metrics 표준화 호출 추가)
  - `src/core/reporting.py` (요약 및 best-row canonicalization 추가)
  - `src/test/test_normalize_metrics.py` (정규화 헬퍼 단위테스트)
- 요약: 집계 및 리포팅 진입점에서 `standardize_metrics()` 호출을 추가해 legacy/혼용된 metric key를 canonical로 정리하도록 함. 소규모 함수 변경만 적용했으며, 관련 단위테스트를 `dlo-cq` 환경에서 실행하여 패스함.
- 세부: 이 단계는 외부 출력/입력 포맷을 변경하지 않음. 내부적으로 canonical 키가 우선 사용되도록 하였으며, 후속 작업으로 내부 모듈을 canonical 키로 일관되게 수정할 계획임.

추가 작업

- 날짜: 2026-09-23
- 작성자: GitHub Copilot
- 단계: 1) 정의·표준화 (출력 표준화 적용)
- 상태: DONE
- 변경 파일:
  - `multi_case_descision.py` (집계 결과에 대한 표준화 적용)
  - `batch_runner.py` (CSV 직전에 metric 키 표준화 적용)
- 요약: CSV 저장 및 집계 지점에서 `standardize_metrics()`를 호출해 출력 파일 헤더와 내부 집계가 canonical metric 키를 사용하도록 함. 기존 외부 입력 포맷과의 호환성은 유지하도록 설계됨(legacy keys는 내부 정규화에서 수용됨).
- 세부: 파일 출력 전 표준화로 인해 `outputs/*_face_rows.csv`, `*_borehole_rows.csv`, `*_summary_rows.csv`의 헤더가 canonical 키로 정리됩니다. downstream 파이프라인을 위해 필요한 경우 `both-keys` 출력 옵션을 향후 추가 예정.
