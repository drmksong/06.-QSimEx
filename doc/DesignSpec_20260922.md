Updated todo list

6.  QSimEx를 기준으로 현재 코드 구조, 문서, 실행 진입점, 최근 Git 상태를 함께 확인해서 “어디까지 되었고 다음에 무엇을 하면 되는지” 중심으로 정리하겠습니다. 먼저 저장된 메모와 프로젝트의 핵심 파일 목록을 좁혀 보겠습니다.

메모상 QSimEx와 직접 연결된 기존 작업은 없고, 현재 작업 디렉터리는 QSimEx입니다. 이제 QSimEx의 README, 실행 스크립트, `src`, 테스트/케이스 폴더와 Git 변경 이력을 병렬로 확인해 실제 재개 지점을 잡겠습니다.

첫 확인에서 README는 현재 기능과 실행법을 꽤 잘 설명하지만, `setup.txt`는 예전 `core/cli/gui` 구조를 가리키는 문서로 보입니다. 또 터미널의 실제 현재 위치가 상위 `09. DFN`이라 Git 상태는 QSimEx 경로로 명시해 다시 확인하고, 코드가 README의 설명을 실제로 뒷받침하는지 핵심 모듈과 테스트를 대조하겠습니다.

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && git status --short && git log --oneline --decorate -12 && git branch --show-current

현재 Git은 `master`와 `origin/master`가 같은 단일 커밋(`first commit`)이고 작업 트리도 깨끗합니다. 실제 테스트 디렉터리는 README의 `tests`가 아니라 `src/test`이며, 이제 실행 흐름과 구현 범위를 확인한 뒤 최소한의 import/테스트 실행으로 현재 동작 상태를 검증하겠습니다.

코드 대조에서 중요한 재개 리스크가 하나 보입니다. `src/core/__init__.py`는 `tunnel_old`를 공개하지만 CLI는 `tunnel`을 직접 사용하고, README의 테스트 경로도 실제 구조와 어긋납니다. 이것이 단순 잔여 호환 코드인지 실행 장애인지 먼저 확인하기 위해 `tunnel*`, `grid_assigner`, 테스트 파일과 최신 분석 문서를 읽겠습니다.

현재 구현은 단순 골격을 넘어 DFN 생성, RQD 두 방식, Q/Q′ 계산, 시추공-막장면 비교, GPU/CPU 백엔드, VTK/PyVista 출력, 통계·Bayesian 분석까지 확장된 상태입니다. 다만 `grid_assigner.py`의 `pass`는 예외 처리 내부라 미완 구현은 아니고, `tunnel_old.py`와 문서 경로 표기가 남은 정리 대상입니다. 이제 실제 테스트와 대표 CLI 명령을 실행해 “문서상 진행”과 “현재 환경에서 재현 가능한 진행”을 분리하겠습니다.

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && python -m unittest discover -s src/test -p 'test\_\*.py' -v

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && python run_cli.py --list-cases

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && python - <<'PY'
import sys
sys.path.insert(0, '.')
from src.core.domain import AnalysisCase
from src.core import Tunnel
print('core import: OK', Tunnel.**module**)
PY

검증 명령은 시스템에 `python` 별칭이 없어 실패했지만, 과거 작업 문서에 기록된 `dlo-cq` conda 환경 실행법이 있습니다. 같은 환경으로 단위 테스트, 케이스 목록, 패키지 import, 대표 케이스의 짧은 end-to-end 실행을 다시 확인하겠습니다. 이 결과가 현재 재개 시 필요한 환경 조건을 확정해 줄 것입니다.

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && conda run -n dlo-cq python -m unittest discover -s src/test -p 'test\_\*.py' -v

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && conda run -n dlo-cq python run_cli.py --list-cases

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && conda run -n dlo-cq python - <<'PY'
import sys
sys.path.insert(0, '.')
from src.core import Tunnel
from src.core.tunnel import Tunnel as CurrentTunnel
print('public Tunnel:', Tunnel.**module**)
print('current Tunnel:', CurrentTunnel.**module**)
print('same class:', Tunnel is CurrentTunnel)
PY

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && conda run -n dlo-cq python run_cli.py --case scenario_07_isotropic --face-positions 10 20 30 --backend cpu --batch-size 100 --export /tmp/qsimex_resume_smoke.json

Ran terminal command: cd '/Users/myungkyusong/Documents/Develop/09. DFN/06. QSimEx' && conda run -n dlo-cq python -m compileall -q run_cli.py src && echo 'compileall: OK'

재현 결과는 명확합니다. `dlo-cq` 환경에서 케이스 스캔, 대표 케이스 end-to-end 실행, 전체 문법 컴파일은 통과했고, scenario 07은 46,475개 절리를 생성해 CPU로 약 32초에 분석을 끝냈습니다. 반면 `unittest discover`는 테스트 0개를 찾았으므로, 테스트가 실제로 어떤 프레임워크/형식인지 확인하고 문서·무시 파일까지 점검해 재개 우선순위를 마무리하겠습니다.

**QSimEx 현재 상태**

QSimEx는 단순 프로토타입을 넘어, DFN 기반 Q/Q′ 공간 분석 파이프라인이 거의 완성된 상태입니다.

- DFN 생성: Power Law 절리 크기, Fisher 방향, 여러 절리군 지원
- RQD 계산: Deere 직접법, Priest-Hudson 근사
- Q 및 Q′ 필드 계산
- 시추공과 굴진면 비교
- CPU, CUDA, MPS, MLX 백엔드 지원
- YAML 기반 13개 케이스
- 배치 실행 및 CSV 집계
- ParaView/PyVista 출력
- ROC, 비용 기반 의사결정, Bayesian 분석 모듈
- 관련 분석 보고서 작성 완료: `qprime_adoption_assessment_2026-07-08.md`

**이미 완료된 분석**

5개 처분장 저절리 대표 케이스에 대해 300개 결과 행이 생성되어 있습니다.

- 전체 Q′ 상관: Pearson $r \approx 0.951$
- 하지만 케이스 내부 상관은 불안정
- Q′ 절차의 생략 대비 평균 정확도 개선: `-0.0433`
- 최종 판단:
  - 권고: 0개
  - 비권고: 1개
  - 비확정: 4개

따라서 현재 결론은 “Q′은 보조 지표로 유망하지만 단독 의사결정 기준으로 채택하기에는 검증이 부족하다”입니다.

**현재 실행 검증**

`dlo-cq` conda 환경에서 다음은 정상 동작했습니다.

- YAML 케이스 목록 로딩
- `scenario_07_isotropic` end-to-end 실행
- DFN 46,475개 생성
- CPU 계산 약 32초
- Q/Q′ 계산 및 시추공-막장면 비교
- 결과 JSON 저장
- 전체 Python 문법 컴파일

대표 실행 명령은 다음과 같습니다.

```bash
cd "06. QSimEx"
conda run -n dlo-cq python run_cli.py \
  --case scenario_07_isotropic \
  --face-positions 10 20 30 \
  --backend cpu \
  --batch-size 100 \
  --export /tmp/qsimex_resume_smoke.json
```

시스템 기본 `python` 명령은 현재 등록되어 있지 않아 반드시 `conda run -n dlo-cq python`을 사용하는 편이 안전합니다.

**정리 대상**

- `setup.txt`는 예전 `core/`, `cli/`, `gui/` 구조를 설명하고 있어 현재 `src/` 구조와 불일치합니다.
- `readme.md`의 테스트 경로는 `tests/`로 되어 있지만 실제 위치는 `src/test/`입니다.
- 테스트 파일 3개는 존재하지만 모두 비어 있어 `unittest` 실행 결과가 `Ran 0 tests`입니다.
- `src/core/__init__.py`는 공개 `Tunnel`을 `tunnel_old.py`에서 가져옵니다. CLI는 최신 `tunnel.py`를 직접 사용하므로, 현재 실행은 되지만 공개 API가 구버전 구현을 노출하고 있습니다.
- Git은 `master`와 `origin/master`가 동일한 단일 커밋이며 작업 트리는 깨끗합니다.

**재개 우선순위**

1. `src/test/`에 RQD, Power Law, Fisher, Q′ 비교에 대한 실제 테스트 추가
2. `src/core/__init__.py`의 `Tunnel` 연결을 최신 구현으로 정리
3. README와 `setup.txt`를 현재 구조에 맞게 갱신
4. PyVista 토글과 결과 자동 저장 기능 보완
5. 케이스 확장 및 bootstrap 기반 임계값 안정성 분석
6. Q′과 방향성·절리밀도 진단치를 결합한 판정 규칙 개발

현재 가장 좋은 재개 지점은 **코드 기능 추가보다 테스트 기반 정비와 Q′ 의사결정 검증 확장**입니다.

Created 4 todos

---

## QSimEx 최종 목적 및 의사결정 기준 Specification

### 1. 최종 목적

QSimEx의 최종 목적은 시추공에서 산정한 Q'을 이용하여 전방 구간의 굴착 여부를 다음 3개 구간으로 판정할 수 있는 안전 우선 가이드라인을 수립하는 것이다.

1. **확실히 굴착**: `Q'_BH >= Q'_upperbound`
2. **조건부 판단**: `Q'_lowerbound <= Q'_BH < Q'_upperbound`
3. **확실히 비굴착 또는 굴착 보류**: `Q'_BH < Q'_lowerbound`

여기서 `Q'_BH`는 동일한 측정·전처리·공간 윈도우 조건에서 산정한 시추공 Q'이다. 두 경계값은 단순한 경험적 분위수나 단일 케이스의 최적 분류점이 아니라, 굴착 후 확인되는 굴진면 상태와 연결된 검증 자료를 이용하여 사전에 정한 안전 성능 조건을 만족하도록 산정한다.

### 2. 판정의 의미

#### 2.1 확실히 굴착

`Q'_BH >= Q'_upperbound`이면 원칙적으로 굴착을 진행한다. 이는 Q'이 높다는 뜻만이 아니라, 이 기준 이상에서 굴착할 때 부적합 암반을 적합으로 오판하는 **false-safe 확률**이 허용 상한 이하임을 통계적으로 확인했다는 의미이다.

#### 2.2 확실히 비굴착

`Q'_BH < Q'_lowerbound`이면 원칙적으로 굴착을 보류하거나 비굴착으로 판정한다. 해당 구간을 비굴착으로 분류할 때 실제 적합 암반을 놓치는 **false-reject(FN) 확률**이 사전에 정한 허용 상한 이하인지 함께 확인해야 한다.

#### 2.3 중간 구간

`Q'_lowerbound <= Q'_BH < Q'_upperbound`이면 Q' 단독으로 결정하지 않는다. 절리 방향성·밀도·크기·교차각, RQD 방법 간 차이, 시추공 변동성, 단층·파쇄대·수리·응력 정보, fracture miss/detection 지표, Bayesian posterior와 기대손실을 함께 검토하여 굴착·보류·추가 조사 중 하나를 결정한다.

중간 구간은 실패한 판정이 아니라, Q'만으로는 안전한 단일 행동을 정당화하기 어려운 **추가 조건 확인 구간**이다.

#### 2.4 공항 검색대 비유와 조건부 위험도

이 의사결정 구조는 공항 검색대의 두 안전 다이얼로 직관화할 수 있다.

```text
시추공 Q' 센서의 다이얼
  |
  +-- Q'_BH >= Q'_upperbound: 안심 통과선 -> 굴착
  |      위험 암반을 통과시키는 위험을 통제
  |
  +-- Q'_lowerbound <= Q'_BH < Q'_upperbound: 조건부 확인 구간
  |      다른 조사·구조·수리 조건을 함께 검토
  |
  +-- Q'_BH < Q'_lowerbound: 무조건 차단선 -> 비굴착·보류
         좋은 암반을 차단하는 자원 유실을 통제
```

이 비유에서 상한은 “통과한 암반 중 실제로 위험한 암반의 비율”을 관리하는 안심 통과선이다. 하한은 “차단한 암반 중 실제로 좋은 암반의 비율”을 관리하는 무조건 차단선이다. 각각의 행동 조건부 위험도는 다음과 같이 별도로 정의한다.

- 상한의 조건부 false-safe 위험: `R_FS_pass = P(unsuitable face | Q'_BH >= Q'_upperbound)`
- 하한의 조건부 false-reject 위험: `R_FN_reject = P(suitable face | Q'_BH < Q'_lowerbound)`

이는 전체 부적합 암반 중 굴착으로 잘못 통과한 비율(`FP / actual_bad`)이나 전체 적합 암반 중 비굴착으로 잘못 분류한 비율(`FN / actual_good`)과 다른 지표다. 전자는 검색대가 통과시킨 표본의 안전성, 후자는 검색대가 차단한 표본의 자원 손실을 직접 나타내므로, 최종 경계값 보고서에는 두 종류의 분모를 모두 기록한다.

따라서 “거의 0”은 실제로 0이라는 뜻이 아니라, 사전에 승인한 허용치(초기 목표 예: 각 5%)와 그 95% 신뢰상한을 만족한다는 뜻으로 해석한다. 공항 비유는 이해를 돕기 위한 표현이며, 실제 운영 기준은 독립 굴진면 라벨과 사전 고정된 통계 검정으로 결정한다.

### 3. 상한·하한의 정량 산정 원칙

#### 3.1 기준 라벨

굴진면의 실제 상태를 독립적인 기준 라벨로 정의한다. 기본 기준은 `Q'_face`이며, 운영 단계에서는 지보 등급, 실제 굴착 안정성, 구조·수리 조건 등 현장 확인 자료를 함께 사용하여 `suitable`/`unsuitable` 라벨의 정의를 고정한다. 시추공 Q' 자체를 정답 라벨로 사용하지 않는다.

#### 3.2 상한값 산정

`Q'_upperbound`는 다음 조건을 모두 만족하는 후보값 중 가장 낮은 값으로 정한다.

- 해당 값 이상을 굴착으로 판정했을 때 false-safe rate의 **95% 신뢰상한**이 정책 허용치 `alpha_FS` 이하일 것
- 굴착으로 통과시킨 표본 중 실제 부적합 암반의 조건부 비율 `R_FS_pass`의 **95% 신뢰상한**도 `alpha_FS` 이하일 것
- 케이스·지질 조건별로 분리해도 안전 성능이 유지될 것
- bootstrap 또는 계층적 재표본추출에서 경계값 변동성이 허용폭 이내일 것
- 무조건 굴착 및 Q' 절차 생략 기준보다 기대손실이 크지 않을 것

안전 우선의 기본 목표는 false-safe rate의 점추정치가 아니라 그 95% 상한이 허용치 이하가 되는 것이다. `alpha_FS`는 사업 안전성 검토를 통해 승인하며 QSimEx가 임의로 정하지 않는다.

#### 3.3 하한값 산정

`Q'_lowerbound`는 다음 조건을 모두 만족하는 후보값 중 가장 높은 값으로 정한다.

- 해당 값 미만을 비굴착·보류로 판정했을 때 좋은 암반을 버리는 false-reject(FN) rate의 **95% 신뢰상한**이 정책 허용치 `alpha_FN` 이하일 것
- 비굴착·보류로 차단한 표본 중 실제 적합 암반의 조건부 비율 `R_FN_reject`의 **95% 신뢰상한**도 `alpha_FN` 이하일 것
- 특정 지질 시나리오, 방향성, 밀도 조건에서 성능이 붕괴하지 않을 것
- bootstrap 또는 계층적 재표본추출에서 경계값 변동성이 허용폭 이내일 것
- 필요한 경우 중간 구간보다 보수적인 추가 조사 규칙으로 연결될 것

두 경계값이 역전되거나(`Q'_lowerbound >= Q'_upperbound`), 안정적인 중간 구간이 확보되지 않으면 Q' 단독 3단계 판정은 채택하지 않는다. 본 검증 시나리오의 초기 목표 허용치는 `alpha_FN = alpha_FS = 0.05`로 둘 수 있으나, 운영값은 사업 안전성 검토와 승인으로 확정한다.

### 3.4 Train/Validation 검증 시나리오

경계값의 정량적 근거는 다음의 2단계 절차로 확보한다.

#### 단계 A. 학습용 Calibration

전체 가상 암반 데이터는 **단면 행이 아니라 DFN seed 또는 독립 DFN domain 단위**로 7:3 분할한다. 예를 들어 총 480개 단면을 생성하더라도 동일한 DFN domain에서 나온 단면들이 Train과 Validation에 나뉘지 않도록 한다. 예시 구성은 다음과 같다.

```text
전체 데이터: 약 480개 단면
Train Set: 약 70%, 약 330개 단면에 해당하는 DFN domain/seed 묶음
Validation Set: 약 30%, 약 150개 단면에 해당하는 미사용 DFN domain/seed 묶음
```

Train Set에서는 `Q'_BH` 후보값을 사전에 정한 범위(초기 범위: `1~40`)에서 촘촘히 sweep한다. 각 후보값에 대해 다음 지표를 계산한다.

- `Q'_BH < 후보값`을 비굴착·보류로 적용했을 때의 false-reject rate: 좋은 암반을 버리는 FN 위험
- `Q'_BH >= 후보값`을 굴착으로 적용했을 때의 false-safe rate: 나쁜 암반을 통과시키는 FP 위험
- 후보값별 표본수, 95% 신뢰구간, 기대손실 및 net benefit

이때 “변곡점”은 시각적으로 보이는 곡선의 꺾임만으로 정하지 않는다. 승인된 `alpha_FN`, `alpha_FS`와 비용비를 먼저 고정한 뒤, 다음 제약을 만족하는 후보 중에서 상·하한을 탐색한다.

- `Q'_lowerbound`: FN 위험의 95% 신뢰상한이 `alpha_FN` 이하가 되는 후보 중 가장 높은 값
- `Q'_upperbound`: FP 위험의 95% 신뢰상한이 `alpha_FS` 이하가 되는 후보 중 가장 낮은 값

예를 들어 Train 결과가 `5.8`과 `19.2`를 제시하더라도, 이는 자동으로 운영값이 되지 않는다. 소수점 정리 규칙을 검증 전에 고정하고, 예를 들어 `5.8 -> 5`, `19.2 -> 20`처럼 보수적으로 정리한 뒤 그 값들을 최종 후보로 기록한다. 반올림·절삭은 방향에 따라 안전성을 바꿀 수 있으므로, 정리된 값 자체를 Validation에 적용해야 한다.

#### 단계 B. 블라인드 Validation

Validation Set에서는 Train에서 선택한 경계값을 다시 최적화하거나 보정하지 않는다. Train에서 `5`와 `20`을 최종 후보로 고정했다면, Validation 전체에 그대로 적용하여 다음을 계산한다.

```text
Q'_BH < 5       -> 비굴착·보류
5 <= Q'_BH < 20 -> 추가 조건 검토
Q'_BH >= 20     -> 굴착
```

Validation에서는 다음을 독립적으로 보고한다.

- 하한 미만 비굴착 구간의 false-reject(FN) rate 및 95% 신뢰상한
- 상한 이상 굴착 구간의 false-safe rate 및 95% 신뢰상한
- 중간 구간의 비율과 실제 추가 조건 판단 결과
- 케이스·방향성·밀도별 성능과 최악 조건의 오류율
- Train 대비 Validation 성능 차이 및 경계값 적용 실패 여부

“오판율 5% 이내”라는 표현은 단순 관측 비율이 아니라, Validation에서 계산한 각 오류율의 **95% 신뢰상한이 5% 이하**라는 사전 기준으로 정의한다. 표본 수가 작아 5% 미만의 관측 오류가 나와도 신뢰상한이 5%를 초과하면 통과로 판정하지 않는다. 또한 상한·하한의 두 오류 통제를 각각 검정하므로, 필요하면 다중 검정 보정 또는 더 보수적인 전체 신뢰수준을 적용한다.

이 절차를 통과하면 “동일한 DFN 생성 모델에서 학습에 사용하지 않은 신규 seed/domain에 대해서도 사전에 승인한 오류 상한을 만족했다”고 기술할 수 있다. 이를 실제 현장 암반 전체에 대한 완전한 보증으로 확대 해석하지 않으며, 현장 자료 또는 외부 DFN 모델을 이용한 별도 외부 검증이 필요하다.

### 3.5 절리군 조건별 적용성 범위와 판정 불가 영역

Q'의 변동성과 시추공-굴진면 예측 오차는 절리군의 특성에 따라 크게 달라진다. 따라서 QSimEx는 모든 암반 조건에 공통으로 적용되는 단일 상한·하한의 존재를 전제하지 않는다. 운영용 경계값은 반드시 **적용성 범위(domain of applicability)**와 함께 제시한다.

최소한 다음 조건을 경계값 산정·검증의 층화 변수로 기록한다.

- 절리군 수와 절리군 간 상호작용
- 각 절리군의 P32 또는 절리 밀도 범위
- 절리면 방향, Fisher 집중도, 방향성 및 이방성
- 절리 크기 분포와 대형 구조절리의 포함 여부
- 시추공·터널 방향과 절리면의 상대적 교차각
- 층상·평행 절리, 단층·파쇄대와 같은 구조적 배열
- 터널 형상, 시추공 위치, 관측 윈도우와 공간 해상도

조건별 경계값은 해당 조건군에서 다음을 만족할 때만 사용할 수 있다.

1. Train에서 선택된 `Q'_lowerbound`, `Q'_upperbound`가 Validation에서 재튜닝 없이 유지될 것
2. 전체 조건군뿐 아니라 사전에 정의한 주요 하위 조건에서도 `R_FN_reject`와 `R_FS_pass`의 95% 신뢰상한이 허용치 이하일 것
3. 조건군별 표본 수와 신뢰구간 폭이 최소 품질 기준을 충족할 것
4. 경계값이 역전되지 않고(`Q'_lowerbound < Q'_upperbound`) 유효한 조건부 판단 구간이 확보될 것

조건별 경계값이 서로 다르면 단일 전역값으로 평균내지 않는다. 다음 중 하나로 처리한다.

- 조건군별 `Q'_lowerbound`, `Q'_upperbound`를 별도로 제시
- 모든 승인 조건군에서 오류 상한을 만족하는 공통 구간이 존재할 때만 전역 경계값 제시
- 공통 구간이 없거나 특정 조건군에서 성능이 붕괴하면 해당 조건군을 `판정 불가`로 지정

`판정 불가` 조건에서는 Q' 단독으로 굴착·비굴착을 확정하지 않는다. 추가 시추공, 구조지질·수리·응력 조사, 절리 방향성 보정, Bayesian 결합 판단 또는 보수적 보류 절차로 전환한다. 특히 시추공과 주요 절리군이 거의 평행하여 교차가 제한되는 경우, 시추공 Q'이 높더라도 `R_FS_pass` 검증 없이는 안심 통과선으로 사용할 수 없다.

따라서 기술서와 최종 보고서의 경계값 표기는 숫자만 기록하지 않고 다음 형식을 따른다.

```text
조건군: 절리군 수, P32 범위, 방향성/교차각, 크기분포, 공간 조건
Q'_lowerbound: 값, 95% 신뢰상한, 표본수, 적용 조건
Q'_upperbound: 값, 95% 신뢰상한, 표본수, 적용 조건
판정 상태: 적용 가능 / 추가 조건 필요 / 판정 불가
제외 조건: 검증되지 않은 절리군 특성 및 공간 조건
```

### 3.6 보편 경계값과 현장 적용의 단순화 원칙

최종 운영 목적은 현장 사용자가 절리군 조합마다 서로 다른 숫자를 선택하는 것이 아니라, 승인된 적용성 범위 전체에 대해 사용할 수 있는 **보편 상한·하한 한 쌍**을 제공하는 것이다. 이를 위해 연구 단계에서는 절리군 수, 밀도, 방향성, 크기, 상호작용 및 시추공 교차각의 가능한 범위를 넓게 탐색하되, 최종 경계값은 그 범위에서 가장 불리한 조건을 기준으로 정한다.

보편 경계값은 다음의 의미로 정의한다.

> 승인된 적용성 범위 안의 모든 검증 조건군에서 `R_FS_pass`와 `R_FN_reject`의 95% 신뢰상한이 각각 허용치 이하가 되도록 선택한 단일 `Q'_upperbound`와 `Q'_lowerbound`.

따라서 보편 경계값은 전체 데이터를 단순 평균하여 얻은 값이 아니며, 조건별 성능 중 최악 조건을 통과해야 한다. 조건별 결과가 서로 달라서 공통으로 만족하는 경계 구간이 존재하지 않으면 보편 경계값을 억지로 제시하지 않고, 해당 조건군을 적용성 범위 밖으로 선언한다. 보편성은 “물리적으로 가능한 모든 암반”을 뜻하는 것이 아니라, 기술서가 명시하고 검증을 완료한 **승인 적용성 범위 전체**를 뜻한다.

현장에서는 다음 네 가지 질문만으로 적용성을 1차 판정한다.

1. 검증된 범위 밖으로 보이는 새로운 대규모 단층·파쇄대 또는 구조절리가 있는가?
2. 주요 절리군이 시추공 방향과 거의 평행하여 시추공이 절리를 놓칠 가능성이 큰가?
3. 절리 밀도·절리군 수·절리 크기가 기존 검증 범위를 명백히 벗어나는가?
4. 시추공 Q'과 함께 사용할 구조·수리·응력 자료에 중대한 불일치가 있는가?

판정 규칙은 다음 세 단계로 단순화한다.

```text
네 질문 모두 아니오
  -> 보편 Q'_lowerbound / Q'_upperbound 적용

하나라도 경고 또는 불확실
  -> Q'은 참고값으로만 사용하고 추가 조건 검토

명백한 대규모 구조, 평행 교차 사각, 검증 범위 밖 조건
  -> Q' 단독 판정 불가; 추가 조사 또는 보수적 보류
```

현장 사용자는 절리군별 상·하한 표를 선택하지 않는다. 조건별 연구 결과는 보편 경계값의 검증 근거와 적용성 범위를 만드는 데 사용하고, 현장에는 최종 보편 경계값·네 가지 적용성 질문·판정 불가 시 조치만 제공한다. 이 단순화는 조건별 성능 차이를 숨기는 것이 아니라, 그 차이를 연구 단계에서 보수적으로 흡수한 뒤 현장 판단 절차를 짧게 만드는 원칙이다.

### 4. 경계값을 제시하기 위한 필수 산출물

QSimEx는 최종적으로 다음 산출물을 제공해야 한다.

- `threshold_sweep`: Q' 후보값별 confusion matrix, sensitivity, specificity, false-safe rate, false-alarm rate
- `confidence_bounds`: 각 비율의 95% 신뢰구간과 bootstrap 경계값 분포
- `stratified_performance`: 케이스, 절리 방향성, 밀도, 크기군별 성능
- `cost_sensitivity`: false-safe와 false-alarm 비용비를 바꾼 기대손실 및 net benefit
- `boundary_recommendation`: 승인된 허용오차와 비용 가정을 적용한 상한·하한 후보, 적용 조건, 제외 조건
- `domain_of_applicability`: 조건군별 적용 가능 범위, 경계값, 표본수, 신뢰구간, 판정 불가 조건

경계값 보고에는 점추정값만 기록하지 않고 다음 항목을 함께 기록한다.

`Q'_upperbound = 값 (95% CI 또는 bootstrap 범위, false-safe 상한, 표본수, 적용 조건)`

`Q'_lowerbound = 값 (95% CI 또는 bootstrap 범위, false-reject(FN) 상한, 표본수, 적용 조건)`

### 5. 현재 단계의 정량값 상태

현재 확보된 5개 대표 시나리오 300행 결과는 경계값 산정 절차를 설계하고 시험하는 파일럿 근거이다. 전체 데이터에서 Q' 상관은 높았지만 케이스 내부 예측력이 불안정했고 시나리오별 성능 편차도 컸다. 따라서 현재 자료만으로 운영용 `Q'_upperbound`와 `Q'_lowerbound`의 최종 숫자를 확정해서는 안 된다.

현재 코드의 `Q'=4.0`은 적합/부적합 기준 라벨을 만드는 예시 파라미터일 뿐, 시추공 3단계 판정의 상한 또는 하한으로 간주하지 않는다. 운영 숫자를 제시하려면 실제 또는 독립 검증용 굴진면 자료 확대, 지질 조건별 케이스 확장, 시나리오 분리 검증, bootstrap/계층적 신뢰구간, 허용오차·비용 승인, 독립 hold-out 자료의 사전 성능 재검증을 먼저 완료해야 한다.

이 절차를 통과한 숫자만 기술서의 운영용 상한·하한으로 승격한다. 그 전까지는 분석 결과를 **잠정 후보값**으로만 표시하고, 굴착 여부를 자동 확정하는 기준으로 사용하지 않는다.
