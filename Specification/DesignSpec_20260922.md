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
- MLX, MPS, CUDA, CPU 백엔드 지원
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

여기서 `Q'_BH`는 동일한 측정·전처리·공간 윈도우 조건에서 산정한 시추공 Q'이다. 두 기준값은 단일 케이스의 최적 분류점이나 별도의 정책값으로 정하지 않고, 동일 시뮬레이션 domain에서 얻은 `Q'_face`와 절리 교차·밀도·방향성·처분 적합성 관련 참조지표가 함께 변하는 구간과 안정되는 구간을 분석하여 제안한다.

### 1.1 가상굴착과 실제굴착의 구분

이 문서에서 **가상굴착**은 동일한 DFN domain에 터널·굴진면 조건을 적용하여
시뮬레이션으로 굴진면 참조지표를 계산하는 절차를 의미한다. 가상굴착의 결과인
`Q'_face`와 절리 교차·밀도·방향성 지표는 시추공 `Q'_BH` 기준값을 탐색하기 위한
시뮬레이션 참조 프로파일이다.

**실제굴착**은 현장에서 암반을 실제로 굴착한 뒤 관측·조사·계측을 통해 확인하는
절차를 의미한다. 실제굴착 결과는 시뮬레이션의 `Q'_face`와 동일한 개념이 아니며,
현장 암반의 처분 적합성 또는 부적합성을 자동으로 의미하지 않는다.

따라서 Phase 3의 시뮬레이션 분석은 가상굴착 참조 프로파일을 이용한 잠정 경계값
후보 탐색까지 수행한다. 실제 처분 적합·부적합 판정과 현장 안전성 검증은 EFPC 또는
향후 연결되는 독립 평가 adapter가 제공하는 공학적 결과를 이용하는 후속 단계로
분리한다.

### 2. 판정의 의미

#### 2.1 확실히 굴착

`Q'_BH >= Q'_upperbound`이면 시뮬레이션에서 굴착 후 참조지표가 일관되게 양호하고 변동성이 안정된 구간으로 분류하여 굴착 진행 후보로 제안한다. 이는 최종 현장 안전을 보증하는 값이 아니라, 시뮬레이션상 굴착을 고려할 수 있는 기준값이다.

#### 2.2 확실히 비굴착

`Q'_BH < Q'_lowerbound`이면 시뮬레이션에서 굴착 후 참조지표가 지속적으로 불리하거나 위험 변동성이 큰 구간으로 분류하여 굴착 보류·생략 후보로 제안한다. 이 역시 실제 현장 결정을 자동 확정하는 값이 아니다.

#### 2.3 중간 구간

`Q'_lowerbound <= Q'_BH < Q'_upperbound`이면 Q' 단독으로 결정하지 않는다. 절리 방향성·밀도·크기·교차각, RQD 방법 간 차이, 시추공 변동성, 단층·파쇄대·수리·응력 정보, fracture miss/detection 지표를 함께 검토한다. EFPC 또는 독립 평가 결과가 연결된 경우에만 그 결과를 이용한 Bayesian posterior와 기대손실을 추가로 검토하여 굴착·보류·추가 조사 중 하나를 결정한다.

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

이 비유에서 상한은 시뮬레이션 참조지표가 안정되는 굴착 후보 구간의 시작점이고, 하한은 참조지표가 불리하게 나타나는 보류 후보 구간의 끝점이다. 각각의 조건부 결과는 다음처럼 별도로 기록한다.

아래의 false-safe와 false-reject 식은 처분 적합·부적합을 정의하는 EFPC 또는 독립
평가 결과가 연결된 경우에만 적용한다. 해당 결과가 없는 Phase 3에서는 이 식을
계산하지 않고, 가상굴착 참조 프로파일의 변화·안정 구간과 표본 분포만 기록한다.

- 상한의 조건부 false-safe 위험: `R_FS_pass = P(unsuitable face | Q'_BH >= Q'_upperbound)`
- 하한의 조건부 false-reject 위험: `R_FN_reject = P(suitable face | Q'_BH < Q'_lowerbound)`

이는 전체 부적합 암반 중 굴착으로 잘못 통과한 비율(`FP / actual_bad`)이나 전체 적합 암반 중 비굴착으로 잘못 분류한 비율(`FN / actual_good`)과 다른 지표다. 전자는 검색대가 통과시킨 표본의 안전성, 후자는 검색대가 차단한 표본의 자원 손실을 직접 나타내므로, 최종 경계값 보고서에는 두 종류의 분모를 모두 기록한다.

따라서 이 단계의 기준값은 시뮬레이션 결과에서 관찰된 경향을 요약한 잠정 가이드이다. 공항 비유는 이해를 돕기 위한 표현이며, 실제 운영 기준으로 승격하려면 별도의 현장·처분 적합성 검증이 필요하다.

### 3. 상한·하한의 정량 산정 원칙

프로파일별 참조지표를 결합하여 하한·상한을 제안하는 구체적인 수식과
`not identifiable` 조건은 별도 방법론 문서
[`QPrimeCutoffSelectionMethod_20260924.md`](QPrimeCutoffSelectionMethod_20260924.md)에 정의한다.
이 문서는 본 DesignSpec의 기준값 선정 방법론을 보완하며, 프로파일을
가중합하거나 새로운 종합지수로 변환하지 않는 원칙을 따른다.

#### 3.1 기준 라벨

시뮬레이션의 가상굴착 결과 `Q'_face`는 시추공 기준값을 평가하는 핵심 참조값으로 사용한다. 다만 `Q'_face` 하나를 별도의 단일 threshold로 잘라 처분 적합·부적합 정답 라벨로 만들지 않는다. `PR/TR/POST`는 참조 프로파일의 변화 전·변화·변화 후 안정 상태를 의미할 뿐 처분 적합·부적합을 의미하지 않는다. 처분 적합·부적합은 EFPC 또는 독립 평가 adapter가 제공하는 별도 공학적 결과로 정의하며, 해당 결과가 연결되기 전에는 안전성 성능이나 false-safe/false-reject를 주장하지 않는다.

#### 3.2 상한값 산정

`Q'_upperbound`는 다음 조건을 함께 만족하는 후보값 중 가장 낮은 값으로 제안한다.

- 해당 값 이상에서 `Q'_face`와 관련 참조지표가 함께 양호한 방향으로 안정될 것
- 여러 독립 domain과 주요 조건군에서 같은 경향이 반복될 것
- 해당 구간의 표본수와 변동성이 기준값 제안에 충분할 것
- 별도의 정책 허용치 없이도 인접 기준값 대비 변화가 작아지는 안정 구간이 확인될 것

이 값은 시뮬레이션상 굴착 후보 구간의 시작점이며, 현장 안전을 자동 보증하는 운영값으로 해석하지 않는다.

#### 3.3 하한값 산정

`Q'_lowerbound`는 다음 조건을 함께 만족하는 후보값 중 가장 높은 값으로 제안한다.

- 해당 값 미만에서 `Q'_face`와 관련 참조지표가 함께 불리한 방향으로 나타날 것
- 여러 독립 domain과 주요 조건군에서 같은 경향이 반복될 것
- 해당 구간의 표본수와 변동성이 기준값 제안에 충분할 것
- 낮은 값 영역과 중간 변화 영역을 구분하는 경향성이 확인될 것

두 기준값이 역전되거나(`Q'_lowerbound >= Q'_upperbound`), 공통 변화점과 안정 구간이 확인되지 않으면 Q' 단독 3단계 가이드를 제시하지 않는다.

### 3.4 Train/Validation 검증 시나리오

경계값의 정량적 근거는 다음의 2단계 절차로 확보한다.

#### 단계 A. 학습용 Calibration

전체 가상 암반 데이터는 **단면 행이 아니라 DFN seed 또는 독립 DFN domain 단위**로 7:3 분할한다. 예를 들어 총 480개 단면을 생성하더라도 동일한 DFN domain에서 나온 단면들이 Train과 Validation에 나뉘지 않도록 한다. 예시 구성은 다음과 같다.

```text
전체 데이터: 약 480개 단면
Train Set: 약 70%, 약 330개 단면에 해당하는 DFN domain/seed 묶음
Validation Set: 약 30%, 약 150개 단면에 해당하는 미사용 DFN domain/seed 묶음
```

Train Set에서는 `Q'_BH` 판정 기준값 후보를 `[0, 400]`에서 탐색한다. 기존 로그 경계 `[0.1, ..., 400]`은 유지하되 첫 경계 `0.1`만 `0`으로 교체한다. 따라서 경계값은 11개, primary profile grid는 총 10 bins이며 첫 구간은 `[0, 다음 양수 로그 경계)`다. 가상굴착 참조 프로파일의 변화·안정 구간과 표본수를 기록한다. 처분 적합·부적합을 전제로 하는 다음 성능 지표는 EFPC 또는 독립 평가 결과가 연결된 경우에만 계산한다.

- `Q'_BH < 후보값`을 비굴착·보류로 적용했을 때의 false-reject rate: 좋은 암반을 버리는 FN 위험
- `Q'_BH >= 후보값`을 굴착으로 적용했을 때의 false-safe rate: 나쁜 암반을 통과시키는 FP 위험
- 후보값별 표본수, 95% 신뢰구간, 기대손실 및 net benefit

이때 변곡점은 한 지표의 시각적 꺾임만으로 정하지 않는다. `Q'_face`와 절리·처분 적합성 관련 참조지표에서 공통으로 나타나는 변화와 안정 구간을 확인하고, 독립 domain·조건군에서도 반복되는지를 본다.

- `Q'_lowerbound`: 불리한 참조지표가 지속되는 영역과 변화 영역을 나누는 가장 높은 기준값
- `Q'_upperbound`: 변화 영역과 양호한 참조지표가 안정되는 영역을 나누는 가장 낮은 기준값

이렇게 얻은 값은 시뮬레이션 기반 잠정 기준값으로 기록한다. 뚜렷한 공통 변화나 안정 구간이 없으면 기준값을 억지로 제시하지 않고 `Q' 단독 기준값 산출 불가`로 기록한다.

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

독립적인 처분 적합성 평가 결과가 아직 연결되지 않은 경우에는 위의 false-safe,
false-reject 및 오류율을 계산하지 않는다. 대신 Validation domain에서 가상굴착
참조 프로파일의 변화·안정 경향, 표본수, 적용 가능 범위와 판정 불가 사유를 보고한다.

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

- `qprime_cutoff_search`: 범위 내 Q' 판정 기준값별 confusion matrix, sensitivity, specificity, false-safe rate, false-alarm rate
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

현재 코드의 `Q'=4.0`은 과거 구현에 남아 있던 적합/부적합 기준 라벨 예시일 뿐이며,
스펙상 유효한 기준값이 아니다. 시추공 3단계 판정의 상한 또는 하한으로 간주하지
않으며, 레거시 감사·재현 기록으로만 보존하고 활성 분석 경로에서는 사용하지 않는다.
시뮬레이션 기반 lower/upper cutoff 후보를 제시하려면 가상굴착 참조 프로파일의
재현성, 지질 조건별 케이스 확장, bootstrap/계층적 신뢰구간을 먼저 완료해야 한다.
EFPC 또는 독립 평가 adapter는 cutoff 후보를 산출하기 위한 선행조건이 아니라,
후속 처분 적합성·false-safe·false-reject 검증을 위한 선택적 연계 수단이다.

이 절차를 통과한 숫자만 기술서의 운영용 상한·하한으로 승격한다. 그 전까지는 분석 결과를 **잠정 후보값**으로만 표시하고, 굴착 여부를 자동 확정하는 기준으로 사용하지 않는다.

### 5.2 가설 검정 방법 정의서 참조

Phase 3의 주 가설과 Phase 4의 통계적 재현성 검정은 별도 정의서
[`HypothesisTestingMethod_20260925.md`](HypothesisTestingMethod_20260925.md)를
기준으로 한다. 해당 정의서는 이 설계 스펙의 가설을 코드와 결과 산출물에 연결하기
위해 다음 사항을 구체화한다.

- 관측 단위는 borehole row로 유지하되 통계적 독립 단위는 `domain_id`로 한다.
- 동일 domain의 여러 face·borehole row는 하나의 cluster로 묶고, domain cluster
  bootstrap을 1차 검정으로 사용한다.
- pooled row p-value는 탐색적 보조 결과이며 lower/upper 확정의 단독 근거로 사용하지
  않는다.
- 표본 또는 최소 독립 domain이 부족한 bin은 `TR`이 아니라 `UNOBSERVED`로 기록한다.
- `provisional`, `identified`, `conflicting`, `not_identifiable` 상태와 판정 조건은
  위 정의서의 규칙을 따른다.
- `suitable`/`unsuitable`, false-safe, false-reject, sensitivity, specificity 및
  AUC는 EFPC 또는 독립 평가 adapter가 연결된 이후에만 계산한다.

따라서 이 설계 스펙의 95% 오류율 상한과 허용오차 기준은 EFPC 또는 독립 평가 결과가
연결된 후속 Validation 단계에만 적용한다. EFPC가 없는 Phase 3/4에서도 profile 변화,
공통 PR/POST 재현성, coverage 상태, lower/upper cutoff 후보와 bootstrap 불확실성을
핵심 결과로 보고한다.
두 문서 사이에 해석 차이가 생기면, 기준 정의와 적용 범위는 이 설계 스펙이 정하고
구체적인 표본화·bootstrap·상태 계산 절차는 위 가설 검정 방법 정의서가 정한다.

### 5.3 가정과 가설의 업데이트 이력

기존 가정과 가설은 재현성과 감사 가능성을 위해 삭제하지 않는다. 다만 현재까지의
시뮬레이션 결과와 통계 검토에 따라 주 가설과 보조 가설의 역할을 구분하여 기록한다.

| 기존 가정·가설                                         | 현재까지 확인된 내용                                                                          | 업데이트된 역할                                                                    |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| `Q'_BH`가 `Q'_face`를 대표하는가                       | 전체 상관은 높지만 케이스 내부 변동이 존재한다. 평균 차이 검정만으로 등가성을 입증할 수 없다. | 평균 차이 검정이 아닌 허용오차·domain 재현성·equivalence 관점의 보조 가설로 유지   |
| 밀도가 높을수록 borehole-face 오차가 감소한다          | 전체 pooled 자료에서는 방향성이 보였으나 row 독립성 문제와 낮은 설명력이 있다.                | 탐색적 보조 가설로 유지하고 seed/domain 계층 검증으로 재검토                       |
| 희소 절리망에서 누락 영향으로 오차가 커진다            | 일부 신호가 보였으나 sparse를 사후 분위수로 정의한 결과이며 독립성 보정이 필요하다.           | configuration으로 사전 정의할 조건군 가설로 업데이트                               |
| 밀도 효과가 방향성에 의해 조절된다                     | pooled 상호작용 신호가 있으나 case/domain 재현성은 확인되지 않았다.                           | 조건군별 재현성을 확인하는 보조 가설로 유지                                        |
| 희소·불리한 방향에서 `Q'_BH`가 체계적으로 과대평가된다 | 현재 파일럿 결과는 이 방향을 지지하지 않았다.                                                 | 확정 가설에서 제외하고 독립 configuration에서 재검증할 보류 가설로 기록            |
| 고정 로그 구간에서 PR/TR/POST를 바로 판정할 수 있다    | 현재 `Q'_BH` 표본이 일부 구간에 집중되어 빈 구간과 변화 구간을 구분하기 어렵다.               | 빈 구간은 `UNOBSERVED`로 분리하고, coverage gap을 configuration 보강 대상으로 취급 |

Phase 3의 주 가설은 다음으로 업데이트한다.

> 독립 DFN seed/domain을 기준으로 관측 범위를 충분히 확보했을 때, 낮은
> `Q'_BH` 구간의 불리한 참조 프로파일과 높은 `Q'_BH` 구간의 안정된 참조
> 프로파일이 여러 조건군에서 공통으로 반복되는가?

이 주 가설이 확인되면 lower/upper 후보를 제안한다. 현재 관측 구간에 자료가 없다는
것은 즉시 `not_identifiable`로 종료한다는 뜻이 아니다. 먼저 해당 Q' 구간을 만들
가능성이 있는 P32, 절리 방향, 절리 크기, 구조 배열, 터널·시추공 방향과 seed
configuration을 추가 설계한다. 추가 configuration을 사용해도 충분한 독립 domain이
확보되지 않거나 프로파일이 서로 충돌할 때에만 최종 `not_identifiable` 또는 적용
범위 밖으로 기록한다.

### 5.5 Coverage 보강용 signature 설계 원칙

Coverage 보강은 signature를 먼저 임의로 대량 생성하는 방식으로 수행하지 않는다.
각 iteration에서 먼저 coverage audit을 수행하고, 그 결과에 반응하여 필요한 후보만
추가한다.

- 후보는 `UNOBSERVED` gap, 관측 범위, 인접 configuration, pilot의 실제 Q' 이동
  근거를 바탕으로 계획한다.
- 무작위 feature 조합이나 Q' cutoff를 직접 목표로 하는 생성은 사용하지 않는다.
- parent signature, 변경 feature, 변경 방향, 예상 coverage 영향, 선택 이유를 후보
  계획에 기록한다.
- 한 iteration에서 추가할 후보 수는 고정하지 않으며, audit 결과에 따라 결정한다.
- 같은 iteration에서는 모든 signature에 공통 seed를 사용하여 signature 효과와 seed
  변동을 분리한다.
- 새 bin을 만들지 못하고 기존 분포와 중복되는 signature는 반복 결과를 확인한 뒤
  후순위화 또는 제거 대상으로 검토한다.

구체적인 feature 변경 폭, parent 선택 점수, 중복 판정 기준과 후보 수는 별도 설계
논의 후 확정한다. 그 전까지 signature 생성기는 확정된 물리 법칙이나 자동 승인기로
간주하지 않는다.

### 5.4 실행 탐색 방식의 변경 이력

기존 설계의 목적과 판정 원칙은 유지하되, Q' coverage를 확보하기 위한 실행 탐색
방식은 다음과 같이 확장한다.

| 시점          | 기존 접근                                                      | 변경된 접근                                                                         | 변경 사유 및 영향                                                                                |
| ------------- | -------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| 초기 계획     | 소수 scenario의 seed를 대량 실행하여 domain 반복성을 먼저 확보 | 기존 500개 domain 결과는 baseline으로 보존하고 재사용                               | 이미 확보한 중간 Q' 정보를 불필요하게 반복하지 않음                                              |
| coverage 확장 | 기존 configuration의 seed를 늘리는 방식 중심                   | 저Q·고Q 및 중간 gap을 확인한 뒤 필요한 신규 generation signature를 단계적으로 추가  | 현재 공백은 표본 수보다 configuration 다양성 부족일 수 있으므로 signature 공간을 점진적으로 넓힘 |
| 후보 비교     | signature별 seed가 달라 효과와 seed 변동이 섞일 수 있음        | 한 iteration에서 전체 signature를 동일한 공통 seed 1개로 순회                       | signature 차이를 seed 차이와 분리해 비교                                                         |
| 반복 검증     | 유효 후보를 바로 대량 확장                                     | 다음 iteration에서 공통 seed를 바꿔 전체 pool을 재-sweep한 뒤 기여 signature만 확장 | 우연한 단일 seed 효과를 배제하고 재현성을 확인                                                   |

이 변경은 cutoff를 임의로 목표화하거나 DesignSpec의 Train/Validation 원칙을 바꾸는
것이 아니다. 신규 후보는 `low_q_gap`, `middle_gap`, `high_q_gap`의 coverage를
확인한 뒤 필요한 만큼 단계적으로 추가하는 잠정 탐색 자료이며, cutoff 후보·calibration·
validation 자료로 자동 승격하지 않는다. 기존 500개 domain과 pilot 결과는 provenance를
보존한 baseline/reachability 근거로 사용하고, 새 공통-seed sweep 결과는 별도 round
artifact로 기록한다.

signature의 구체적인 생성 로직, feature 변경 폭, 후보 수와 추가 순서는 아직 확정하지
않았다. 해당 규칙은 coverage 결과와 기존 signature의 중복·기여를 확인한 뒤 별도
합의와 검토를 거쳐 정의한다.

### 5.6 Coverage 전략 catalog

Coverage 보강 후보는 개별 YAML을 즉시 실행하는 대신, 먼저 **전략 catalog**에
검토 가능한 가설로 등록한다. 전략 catalog는 coverage audit과 이전 round 결과를
바탕으로 다음 iteration에서 시험할 generation signature 후보를 관리하는 설계
계약이다.

각 catalog 항목은 최소한 다음 정보를 포함한다.

```yaml
strategy_id: unique_identifier
target_gap: low_q_gap | internal_gap | high_q_gap
parent_signature: existing_signature_identifier
immutable_context: canonical_domain_tunnel_borehole_and_structure
mutable_features:
  - name: normalized_feature_name
    value: normalized_value
    bounds: [lower, upper]
changed_features:
  - name: feature_name
    direction: increase | decrease | replace
    magnitude: explicitly_recorded_value
expected_effect: expected_coverage_or_profile_direction
selection_reason: evidence_from_coverage_audit_or_pilot
validity_constraints: physical_and_configuration_constraints
generation_signature_hash: hash_of_canonical_generation_features_only
domain_identity_inputs: canonical_features_plus_seed_domain_and_generator_version
status: proposed
```

전략 catalog의 항목은 다음 조건을 만족해야 한다.

- 특정 `UNOBSERVED` gap 또는 domain 부족 구간과 연결되어야 한다.
- parent signature와 parent를 선택한 근거를 기록해야 한다.
- 변경 feature, 방향, 변경 폭과 예상 영향이 명시되어야 한다.
- P32, spacing, 방향성, 크기분포, 절리군 구조와 같은 입력이 물리적·구성적 유효
  범위를 벗어나지 않아야 한다.
- `generation_signature_hash`는 canonical generation feature만 hash하며 `name`, `tags`,
  seed, runtime, round metadata를 포함하지 않는다.
- `domain_id`는 canonical generation features, seed, domain identity와 generator
  version으로 계산하여 동일 DFN 재생성과 다른 domain을 구분한다.
- 실행 round, backend, 시간과 같은 정보는 `execution_id`와 screening ledger에만 둔다.
- cutoff 숫자를 직접 맞추거나 suitability label을 생성하는 목적이어서는 안 된다.

전략은 다음 상태를 거친다.

```text
proposed
  -> approved_for_screening
  -> screened
  -> retain | deprioritized | rejected
```

`approved_for_screening` 전략만 simulation manifest에 포함한다. 같은 iteration의
screening에서는 모든 후보에 공통 seed를 사용하고, Q' 범위·새 bin·gap 감소·profile
변화·기존 구간 중복도·실행 provenance를 기록한다. 한 번의 seed 결과만으로 전략을
제거하지 않으며, 반복 screening에서 새 bin을 만들지 못하고 중복이 큰 경우에만
`deprioritized` 또는 `rejected`로 전환한다.

전략 catalog는 처음부터 큰 목록을 만드는 방식이 아니다. 각 iteration의 audit 결과에
따라 필요한 항목만 추가·수정·후순위화하며, 효과가 확인된 전략만 후속 독립 seed
확장과 calibration 검토 대상으로 승격한다. 구체적인 feature 변경 규칙, 후보 수,
parent 선택 점수와 중복 판정 threshold는 후속 설계 논의에서 확정한다.

#### 5.6.1 반복적인 gap 보강과 방향성 추정

`UNOBSERVED` gap 사이에는 우선순위를 부여하지 않는다. 관측된 모든 빈 구간은 각
iteration에서 최소 한 번의 보강 기회를 가져야 하며, 후보가 많을 때는 특정 gap을
영구히 제외하지 않도록 순환 방식으로 검토한다.

후보 생성은 다음의 반복 절차를 따른다.

1. 빈 구간의 양쪽에 관측된 signature가 있으면 두 이웃 signature를 parent 후보로
   선택한다.
2. immutable context는 유지하고, mutable feature만 normalized signature space에서
   업데이트한다.
3. 연속형 mutable feature에 대해서는 양쪽 이웃의 중간값을 우선적인 시험 후보로
   만든다.
4. 외부 reachability gap에는 가장 가까운 관측 signature와 기존 pilot에서 확인된
   이동 방향을 parent 근거로 사용한다.
5. 공통 seed로 후보를 실행하고 normalized feature 변화량 `Δx`와 coverage 변화량
   `ΔC`를 기록한다.
6. 다음 iteration에서는 관측된 방향 `ΔC/Δx`를 이용해 gap 쪽으로 mutable feature를
   보정한다.

이는 미지의 gradient를 알고 있다고 가정하는 Newton 해법이 아니다. 이웃 signature의
실제 실행 결과로부터 유한차분 방향을 추정하고, 매 iteration에서 새 결과로 갱신하는
반복 탐색 방식이다. 범주형 feature나 중간값이 물리적으로 유효하지 않은 feature는
중간값을 자동 생성하지 않고 별도 후보 계획으로 검토한다.

#### 5.6.2 중복 coverage의 분산

여러 signature가 같은 Q' bin과 profile 범위를 반복하면 이를 실패로 즉시 폐기하지
않고 공통 coverage 영역으로 기록한다. 다음 후보는 해당 공통 영역을 반복하는 대신
이웃 signature와 실제 `Δx`·`Δy` 관계를 이용하여 아직 관측되지 않은 방향으로
분산하는 것을 우선 검토한다.

중복 평가는 단일 지표가 아니라 다음 정보를 함께 사용한다.

- coverage bin 집합의 겹침
- Q' 분포의 중첩
- profile 상태와 유효값의 공통성
- 독립 domain과 generation signature의 다양성

#### 5.6.3 정보량과 반복 종료

초기 screening에서는 정보량에 임의의 가중치를 주지 않는다. 각 항목을 비교 가능한
범위로 정규화한 뒤 다음 변화량을 합산하여 기록한다.

- 새로 관측한 bin 수
- gap 감소량
- 독립 domain/signature 수 증가
- profile 유효 coverage 및 판정 가능성 증가
- 중복 coverage 감소량

후속 round에서 각 정보량의 예측 기여가 충분히 축적되면 가중치 도입을 검토할 수
있지만, 초기 결과에 가중치를 소급 적용하지 않는다.

시간 예산은 초기에는 충분히 여유 있게 설정하고, 후보를 강제로 배제하는 절대 cutoff로
사용하지 않는다. 각 Q' 구간의 실제 수행시간과 정보획득량을 round별로 기록하여 예산
예측을 점진적으로 보정한다. low-Q 후보가 구조적으로 오래 걸린다는 이유만으로
screening에서 제외하지 않는다.

하나의 signature는 최소 세 번의 공통-seed 변경 screening에서 새 bin, gap 감소 또는
profile 방향성을 만들지 못할 때 `deprioritized` 또는 `rejected`로 전환을 검토한다.
세 번은 초기 기본값이며, 충분한 근거가 쌓이면 round 계획에서 조정할 수 있다.

#### 5.6.4 Signature space와 coverage space의 잠정 함수화

전략 catalog의 탐색 대상은 다음 두 공간의 관계로 잠정 표현한다.

- **Signature space** `S`: P32, spacing, 방향성, Fisher 집중도, 절리 크기분포,
  절리군 구조, 터널·시추공 교차각 등 generation feature의 공간
- **Coverage space** `C`: Q' bin 관측량, gap 상태, profile 유효 coverage, profile
  변화량, 독립 domain/signature 수와 중복 coverage의 요약 공간

하나의 signature `x`를 실행하면 seed와 DFN domain에 따른 확률적 coverage 결과가
생성된다. 따라서 관계는 단일 결정 함수로 확정하지 않고 다음과 같이 잠정 표현한다.

```text
C = F(x, seed, domain)
E[C | x] = 평균적인 coverage/profile 경향
```

현재의 목적은 `F`를 완전히 추정하는 것이 아니라, 관측된 이웃 signature 사이의
변화량으로 gap을 줄이는 국소 방향을 추정하는 것이다. 두 실행 결과에서
`Δx = x_(k+1) - x_k`, `ΔC = C_(k+1) - C_k`를 기록하고, 가능한 feature 축에 대한
유한차분 방향을 계산한다.

#### 5.6.5 Explicit-Euler-style signature update

국소 방향 `d_k`가 추정되면 다음 signature는 **bounded explicit-Euler-style iterative
update**로 제안한다.

```text
x_(k+1) = Project_Ω(x_k + η_k * d_k)
```

여기서 `η_k`는 screening step size이고, `Project_Ω`는 normalized mutable feature를
물리적 허용 범위 안으로 투영하는 연산이다. immutable context는 이 연산의 대상이
아니다. 이 방법은
Newton 최적화나 cutoff 최적화가 아니라, coverage gap을 줄이기 위한 한 단계의 후보
생성 규칙이다.

여기서 Euler라는 표현은 시간에 따른 미분방정식을 직접 적분하거나 전역 최적화를
수행한다는 뜻이 아니다. 이전 simulation에서 얻은 `Δx`, `ΔC`와 coverage residual로
국소 방향을 추정한 뒤, 명시적 Euler 갱신식의 구조를 차용하여 다음 signature 후보를
한 단계 생성한다는 의미다. 따라서 이 방법은 **simulation-guided bounded iterative
update**이며, 전통적인 수치해석 Euler solver로 해석하지 않는다.

다음 안전조건을 적용한다.

- feature를 정규화한 공간에서 step을 계산한다.
- 한 번에 변경하는 연속형 feature 수와 step 크기를 제한한다.
- 범주형 feature와 물리적으로 중간값이 정의되지 않는 feature는 Euler 보정에서
  제외하고 별도 catalog 전략으로 검토한다.
- 같은 iteration의 후보는 공통 seed로 비교한다.
- 방향이 충분히 추정되지 않으면 양쪽 이웃의 midpoint를 우선 사용한다.
- gap에서 멀어지거나 overshoot가 발생하면 다음 step을 줄이거나 방향을 재추정한다.
- 최소 세 번의 공통-seed screening에서 방향성과 coverage 기여가 재현되지 않으면
  해당 update 방향 또는 signature를 후순위화한다.

이 관계는 simulation 결과가 쌓일수록 갱신되는 잠정 모델이다. 충분한 domain과
변화량 자료가 축적되기 전에는 전역 gradient, Newton step, 가중 정보량 또는 최종
cutoff를 추정하지 않는다.

#### 5.6.6 Feature 탐색 순서와 제한적 순서 randomization

초기 generation feature 탐색은 다음 순서를 기본으로 한다.

```text
D. joint-set structure
  -> A. density
  -> B. size distribution
  -> C. orientation
  -> E. seed realization
```

- **D**: 절리군 수와 절리군 구조 조합
- **A**: `P32` 또는 `mean_spacing` 중 하나의 밀도 표현
- **B**: `size_alpha`, `size_r_min`, `size_r_max`
- **C**: `mean_dip`, `mean_dip_dir`, `fisher_kappa`
- **E**: signature를 바꾸는 feature가 아니라 독립 domain realization 검증

이 순서는 절대적인 우선순위나 고정 최적화 순서가 아니다. 앞선 단계의 coverage 결과와
Euler 방향 추정에 따라 다음 feature로 이동하거나 같은 feature를 반복할 수 있다.

전체 screening schedule의 약 90%는 위 기본 순서를 따르고, 약 10%는 사전에 기록한
randomization seed로 feature 탐색 순서를 재배열한다. randomization은 feature 값을
무작위로 만들거나 물리적 bounds를 무시하는 random search가 아니다. immutable context,
mutable feature bounds, 공통 seed, catalog 승인 상태와 provenance 규칙은 모든 순서에서
동일하게 유지한다.

randomized schedule에는 다음을 기록한다.

- `schedule_mode`: `default` 또는 `randomized`
- `feature_order`
- `randomization_seed`
- 각 feature 단계의 `Δx`, `ΔC`, residual과 coverage 결과

90/10 비율은 초기 운영값이며, round가 축적된 뒤 feature별 coverage 기여와 시간효율을
검토하여 조정할 수 있다.

#### 5.6.7 Update 정책의 적용 범위 (2026-09-27 재확인)

5.6.1~5.6.6의 2026-09-26 합의를 우선한다. 모든 `UNOBSERVED` gap에 순환 기회를
주고, 내부 gap에서는 양쪽 이웃 signature의 midpoint를 먼저 시험한다. midpoint는
여러 feature가 달라도 성립하는 보간 후보이며, 이후 효과를 해석하기 위한 probe는
가능하면 한 번에 하나의 normalized mutable feature 축만 변경한다. 단일 축 probe를
midpoint 자체나 joint-set 구조 변경의 필수 조건으로 소급 적용하지 않는다.

`Δx`는 probe의 두 signature에서 실제 적용한 normalized feature 차이이고 `ΔC`는
동일한 bin 정의와 공통 seed로 비교한 coverage 변화다. 어느 쪽도 사전 gradient를
안다는 뜻이 아니다. 잔여 coverage는 `UNOBSERVED` bin과 독립 domain/signature가
부족한 bin을 기준으로 표시하고, bin별 signature와 교차빈도를 기록하여 중복과
재현성을 구분한다. 목표 bin과 바로 인접한 bin까지 비었더라도 현재 관측된 bin 중
목표에 가장 가까운 signature에서 탐색을 시작한다. 동일 seed의 단일 feature probe가
관측된 bin을 목표에 더 가까운 쪽으로 옮겼다면 그 로그 bin 거리 감소를 방향 근거로
사용한다. 관측 이동이 없는 경우에는 빈 bin에서 구배를 만들어내지 않고 그
signature의 새 probe가 필요함을 기록한다. 시뮬레이션의 이산 Q' 관측을 연속 분포로
가정하지 않는다.

10개 경계 `[0, g1, ..., 400]`에서 첫 경계만 0으로 교체한 10-bin primary grid를 공통
PR/POST 프로파일 판정의 주 분석에 사용한다. `g1` 이후 양수 경계는 기존 로그 간격을
유지한다. 같은 방식으로 첫 경계만 0으로 교체한 20-bin grid로 별도 audit하여
signature-bin 연결, 중복,
빈 bin과 독립 domain 지원을 기록한다. 두 결과는 역할이 다르므로 bin 정의가 다른
`ΔC`를 직접 비교하거나, 20구간을 모두 채웠다는 이유만으로 공통 PR/POST의
`identified` 판정을 내리지 않는다. 양쪽 로그 bin은 동일한 Q' 양수 범위의
양 끝점을 공유하며 각각 로그 공간에서 등간격이다.

`Project_Ω`의 bounds는 generation 입력의 물리적·구성적 유효성에 따른다. P32에
임의의 정책 상한을 두지 않고 방향에도 탐색 편의를 위한 추가 제약을 두지 않는다.
다만 양의 밀도·크기 관계, 생성기가 요구하는 유한 값과 각도 표현의 유효 범위를
유지하며, 실제 시추공-절리면 사잇각은 `0~90`도이다. 정규화 mapping과 수치적
probe 범위는 물리적 상한과 구분해 기록한다.

`η=0.5`는 구배를 알기 전 시험할 고정 step 제안값이지 추정된 최적 step이 아니다.
한 signature에 대한 최소 3회의 공통-seed 변경 screening은 후순위화 판단 기준으로
유지한다. 30회 연속으로 효과가 없는 Euler update 후 종료하는 규칙은 별도 campaign
상한 후보로 검증한다. 효과는 새 bin뿐 아니라 gap 감소, 독립 domain/profile 지원과
중복 분산을 함께 판단한다. 상한에 걸리더라도 자동으로 unreachable이나
`not_identifiable`로 분류하지 않고 원인·시도 내역을 보고한다.

#### 5.6.8 Signature update 후속 설계 (2026-10-03, 2026-10-04 보완)

이 절은 signature update의 feature 탐색에 관해 2026-10-03과 2026-10-04에 합의한
내용을 기록한다. 이 절의 round-robin 순서와 갱신·검증 정책은 기존 5.6.5~5.6.7의
제안보다 우선한다. 특히 기존의 고정 `η=0.5`, 최소 3회 screening 및 순서
randomization은 이 절에서 정한 정책으로 대체한다.

탐색 대상은 다음 세 feature block이다. 모든 block을 탐색 대상으로 포함하며, 한 probe에서는
한 block만 변경한다.

- 밀도: joint set별 `P32`
- 크기: `size_r_min`과 `size_r_max` 쌍
- 방향: `(mean_dip, mean_dip_dir)` 쌍. 갱신 좌표는 관측공 축과 절리면 사이의 사잇각으로
  표현하고, 변경된 사잇각에 맞는 dip/dip direction 후보를 역변환한다.

세 block은 **밀도 → 크기 → 방향** 순서로 round-robin 시험한다. 각 probe는 해당 순서의
한 block만 변경한다. 밀도 block에서는 joint set별 `P32`를 정해진 순서로 하나씩 변경해
각 절리군의 민감도를 구분한다. 무작위 순서나 무작위 feature 값으로 대체하지 않는다.

갱신은 backpropagation의 파라미터 업데이트에서 영감을 받은, 목표 coverage 오차와
관측 민감도를 이용하는 bounded update로 설계한다. 정규화된 feature block을
`x`, 현재 관측 반응을 `q(x)`, 목표 `UNOBSERVED` 구간을 대표하는 값 또는 경계값을
`q_target`이라 두면 다음 gradient-style 식을 후보 규칙으로 삼는다.

$$
L(x) = \frac{1}{2}(q_{target} - q(x))^2,
\qquad
x_{k+1} = \operatorname{Project}_{\Omega}
\left(x_k - \eta_k \nabla L(x_k)\right)
= \operatorname{Project}_{\Omega}
\left(x_k + \eta_k (q_{target} - q(x_k)) \nabla q(x_k)\right)
$$

여기서 `∇q`는 controlled probe 반응으로 추정하는 국소 민감도이며, 실제 전역 gradient로
간주하지 않는다. 갱신 목적은 Q′를 무조건 키우는 것이 아니라 목표 `UNOBSERVED` 구간으로
coverage를 확장하는 것이다. Feature와 Q′는 기록된 좌표계에서 정규화하고, block별 민감도와
갱신량을 산출한다. 양수 파라미터의 초기 probe는 로그 좌표의 10% 배율 변화
(`×1.1` 또는 `÷1.1`), 방향 사잇각은 5° 변화를 기본값으로 한다. 이 값은 실행 설정에서
바꿀 수 있는 screening 시작값이지 과학적 경계값이 아니다. 반응이 없으면 간격을 단계적으로
넓히고 목표에서 멀어지면 줄이며, 항상 물리적 유효 범위에 투영한다. 기존의 고정
`η=0.5`는 확정된 값으로 사용하지 않는다.

크기 block은 `log(size_r_min)`과 `log(size_r_max)`의 2차원 좌표로 탐색한다. 민감도 probe는
한 번에 한 경계만 변경해 두 경계의 반응을 식별하고, 갱신에서는 두 좌표를 함께 조정할 수
있다. 투영 후에도 `size_r_max > size_r_min > 0`을 만족해야 한다. 두 경계에 공통 배율만
적용해 반경 비율을 고정하는 방식은 사용하지 않는다.

방향 변환에서 관측공의 축 방향을 고정값으로 가정하지 않는다. 관측공 configuration은
물리 좌표계의 시작점, 방향, 길이를 canonical 표현으로 삼는다. 시작점과 끝점 입력은 이
표현으로 정규화한다. 관측공 위치와 축 방향은 borehole sampling 및 plane-angle 계산 모두에
전달해야 한다. 현재 구현은
`src/core/tunnel.py`의 borehole sampling과 `src/core/comparison.py`의 plane-angle 계산에서
`[1, 0, 0]`을 사용하고, case 입력은 borehole 위치 offset만 제공한다. 사잇각에 대응하는
방향 해가 여러 개일 때는 parent 방향에서 각도 변화가 가장 작은 해를 우선 후보로 삼는다.
다른 방위 변화는 별도 probe로 다룬다. 법선·각도 복원이 정의되지 않거나 퇴화하거나 물리적
범위를 벗어나는 후보는 제외한다. 기존 offset 입력은 호환성을 위해 유지하면서 새 선형
configuration으로 변환한다.

크기 block은 현재 truncated power-law 반경 분포의 `size_r_min`과 `size_r_max`를 각각
독립적으로 변경하며 `size_alpha`는 고정한다. 크기 분포 변경은 고정 `P32`에서 기대 절리
개수에도 영향을 주므로 그 반응을 size probe 결과에 포함한다. 현재 반경 샘플러의 기준
분포와 역CDF는 다음과 같다. 여기서 `size_alpha`는 survival-tail 지수이며 PDF의 지수는
`α+1`이다.

$$
f(r) = \frac{\alpha r_{\min}^{\alpha}}
{1-(r_{\min}/r_{\max})^{\alpha}} r^{-(\alpha+1)},
\quad r_{\min} \le r \le r_{\max}
$$

$$
r = r_{\min}\left[1-U\left(1-(r_{\min}/r_{\max})^{\alpha}\right)\right]^{-1/\alpha},
\quad U \sim \mathrm{Uniform}(0,1)
$$

현재 생성기는 `P32`가 고정된 경우 이 분포의 기대 면적을 사용해 기대 절리 개수를
정한다. `α > 2`에서 구현된 식은 다음과 같으며, `α <= 2`에서는 코드가 중간 반경 기반
근사값을 사용한다.

$$
\mathbb{E}[\pi r^2] =
\pi\frac{\alpha r_{\min}^{\alpha}}
{1-(r_{\min}/r_{\max})^{\alpha}}
\frac{r_{\min}^{2-\alpha}-r_{\max}^{2-\alpha}}{\alpha-2},
\qquad
N_{\mathrm{expected}} = \frac{P_{32}V}{\mathbb{E}[\pi r^2]}
$$

탐색 중 효과가 관측된 signature는 실행 설정에 명시된 탐색 미사용 독립 seed 3개에서 동일
조건으로 검증한다. Seed 목록은 검증 전에 고정하고 탐색 seed와 겹치지 않아야 한다. 각
seed에서 parent와 candidate를 같은 seed로 짝지어 실행하여 signature 효과와 seed 변동을
구분한다. 한 seed에서 효과가 재현된 것으로 보려면 (a) 목표 bin까지의 거리가 감소하거나
목표 bin 또는 인접 bin이 새로 관측되고, 동시에 (b) 전체 관측 bin 수가 parent보다 줄지
않아야 한다. 같은 판정으로 3개 중 2개 이상 seed에서 효과가 재현되면 해당 signature의
효과가 입증된 것으로 기록한다. 이는 경험적 재현성 기준이며, 통계적 유의성이나 운영
cutoff의 승인으로 해석하지 않는다.

#### 5.6.9 후속 결정 기록: profile coverage와 update 채택 규칙 (2026-10-04)

이 절은 5.6.8을 대체하거나 과거 합의를 소급 수정하지 않는다. 아래 항목은 2026-10-04에
추가로 합의한 변경·정밀화 기록이다. 구현 전 설계 계약이며, 경험적 성능이나 과학적
유효성이 이미 입증되었다는 뜻은 아니다.

**Coverage 대상의 변경.** 앞선 signature 설계에서 scalar Q′ 또는 목표 bin 거리로 요약하던
비교를 profile 관측에 기반하도록 구체화한다. Profile 값이 실제로 들어간 bin만 점유로
인정하고, 해당 bin에 양의 길이 support가 있으면 observed로 본다. min–max 또는 분위수
envelope가 지나가는 미관측 bin은 점유 처리하지 않는다. Profile의 요약 범위와 분위수는
bin 점유와 별개로 보존한다.

각 paired parent/candidate seed 비교에서 gap 집합 `G`는 해당 seed의 parent profile이
점유하지 않은 bin으로 정의한다. Candidate가 새로 점유한 bin의 수와 parent gap별
proximity를 별도로 평가한다. Gap bin `b`의 proximity는 profile 구간 길이로 가중한다.

$$
P_b = \frac{\sum_i \ell_i w_i}{\sum_i \ell_i},
\qquad
w_i = 10^{-\delta_i/9}
$$

여기서 `ℓ_i`는 profile segment/round의 실제 대표 길이이고, `δ_i`는 log10 Q′ 공간에서
bin 폭 단위로 정규화한 거리이다. 첫 bin `[0,U₀]`에서는 `q≤U₀`일 때 `δ=0`,
`q>U₀`일 때 `δ=log10(q/U₀)`로 계산한다. 거리 변화와 새 점유 bin 비율을 50:50으로
결합한다.

$$
D = \frac{1}{|G|}\sum_{b\in G}(P_b^{candidate}-P_b^{parent}),
\qquad
C = \frac{|\{b\in G: b\text{ is newly observed}\}|}{|G|},
\qquad
\Delta S = 0.5D + 0.5C
$$

`D`는 gap bin 전반의 평균 proximity 변화, `C`는 parent gap 중 candidate가 새로 점유한
비율이다. Parent와 candidate는 같은 seed와 같은 `G`로 paired 비교한다. 따라서 검증
seed마다 해당 seed의 parent로 gap을 정하며, 최초 탐색 seed의 gap 목록을 모든 seed에
고정하지 않는다.

**민감도와 update 크기의 정밀화.** 기존 BP-inspired 제안은 update 수식과 probe 간격은
정했으나, 중앙차분을 이용한 score 민감도와 update 변화량은 확정하지 않았다. 후속 결정으로
중앙차분 coverage-score 민감도를 사용하고, score가 증가하는 방향으로 bounded
gradient-ascent 후보를 생성한다. 양수 파라미터는 계산에만 로그 좌표를 쓰며 입력·저장값은
실제 단위로 유지한다. 양수 파라미터의 한 번의 update 크기는 약 5%를 기준으로 한다.
이는 기존의 ×/÷1.1 probe 간격(약 10%)과 다른 값이며, probe는 민감도 측정, 5%는 update
변화량에 적용한다. 방향 update는 시추공 축과 절리면 법선 사이 상대각
`β=asin(|n·d|)` 좌표를 쓰고 probe는 ±5°, 한 번의 update는 최대 5°로 제한한다. 법선은
최소 대원 회전으로 변환해 `dip`/`dip_dir` 후보를 얻는다.

**Seed 재현성 판정의 정밀화.** 5.6.8의 2026-10-03/04 기록은 목표 bin 거리 또는 새 bin을
사용한 효과 판정을 설명한다. 2026-10-04의 후속 합의에서는 위 profile coverage score를
paired 판정 기준으로 구체화한다. 최초 탐색 seed에서 효과를 찾은 뒤 서로 다른 추가 seed
3개로 검증한다. 추가 3개 중 2개 이상에서 paired `ΔS>0`이고 observed-bin 수가 감소하지
않으면 update 방향을 채택한다. 이 기준은 경험적 재현성 정책이며, 통계적 유의성이나
운영 cutoff 승인으로 해석하지 않는다. 별도의 최소 1% 개선 임계값은 두지 않는다.

**탐색 순서·정지 조건의 명확화.** Feature block 순서는 밀도 → 크기 → 방향이며,
`fisher_kappa`는 이번 update 범위에서 고정한다. 경계에 걸린 파라미터는 해당 방향에서
고정하고 다른 조정 가능한 주 파라미터를 계속 탐색한다. 주 파라미터가 모두 경계에 도달해
진행 가능한 방향이 없으면 현재 campaign을 중단한다. 이 자동 흐름에서 `fisher_kappa`나
파라미터가 아닌 조건을 변경해 재시도하지 않는다. 새 campaign에서 다른 조건을 바꿀지는
결과를 검토한 사용자가 결정한다.

이 절의 핵심 제안은 논문에서 설계 선택과 검증 결과를 구분해 평가한다. 평가 항목은
profile 기반 점유가 scalar 평균 방식과 비교해 coverage 정보를 얼마나 보존하는지, 50:50
score와 길이 가중 proximity가 다른 합리적 집계 방식에 비해 어떤 특성을 갖는지, 중앙차분
민감도와 약 5% update가 seed 변동·bounds·parameter coupling 아래서 안정적인지, 3개 seed 중
2개 기준이 재현성에 어떤 영향을 주는지이다. 결론은 실제 실험 결과로 뒷받침하며, 본 스펙의
선택 자체를 검증 결과로 주장하지 않는다.

### 5.7 수행시간과 정보 효율

Coverage 탐색은 제한된 실행시간 안에서 최대한 많은 정보를 얻는 것을 목표로 한다.
전략 catalog는 후보의 과학적 가설과 물리적 타당성을 기록한다. 수행시간, 시간 예산과
실행 결과는 catalog에 중복하여 넣지 않고 별도의 screening ledger에서 관리한다.

Coverage 보강 자료는 다음 세 계층으로 분리한다.

1. **Coverage Audit**: 현재 무엇이 부족한지 기록한다.

- `gap_bin`, Q' 범위, 상태, domain 수, signature 수, 불확실성

2. **Strategy Catalog**: 무엇을 시험할지 기록한다.

- 전략 식별자, target gap, parent, 변경 feature, 예상 효과, 선택 근거, 상태

3. **Screening Ledger**: 실제 어떻게 실행했는지 기록한다.

- seed, 예상·실제 수행시간, 시간 예산, coverage 변화, timeout, 다음 조치

수행시간은 최종 cutoff의 근거가 아니며, 어떤 후보를 다음 screening에 포함할지 결정하는
운영 제약이다.

각 screening ledger와 round에는 다음 시간 정보를 기록한다.

- `estimated_runtime_seconds`: 실행 전 예상 wall-clock 시간
- `runtime_basis`: parent benchmark, 동일 domain 규모, backend, 최근 round 등
  예상시간의 근거
- `actual_runtime_seconds`: 실행 후 실제 wall-clock 시간
- `runtime_breakdown`: domain 생성, profile 계산, 결과 저장 등 단계별 시간
- `time_budget_seconds`: round 또는 전략에 허용한 시간
- `timeout_status`: `completed`, `timed_out`, `failed`, `cancelled`
- `checkpoint`: 중단 시 보존된 seed/domain과 재개 정보

정보 획득량은 단순 row 수가 아니라 다음 변화로 평가한다.

- 새로 관측한 Q' bin 수와 gap 감소량
- 독립 `domain_id` 및 generation signature 수의 증가
- 기존 구간과의 중복 감소량
- profile 유효값 coverage와 상태 판정 가능성의 변화
- 다음 전략 선택에 추가로 제공한 provenance·profile 정보

screening 우선순위는 다음 순서로 정한다.

1. low-Q, middle/internal-gap, high-Q 각 구간에 최소 screening 예산을 먼저 보장한다.
2. 각 구간 안에서 목표 gap을 줄일 가능성과 기존 결과와의 차별성이 있는 후보를 우선한다.
3. 같은 구간 안에서 예상 정보획득량을 예상 수행시간으로 나눈 효율을 참고하여 후보를
   정렬한다.
4. 짧지만 기존 구간만 반복하는 후보보다, 조금 더 오래 걸려도 새로운 gap이나
   profile 정보를 제공하는 후보를 선택할 수 있다.
5. 한 전략 또는 한 signature가 round 예산을 독점하지 않도록 portfolio별 시간 상한을
   둔다.

구간별 최소 예산을 먼저 배정한 뒤 남은 예산은 Q' 분포와 coverage 부족 정도에 따라
동적으로 배분한다. 전체 후보를 raw runtime 효율 하나로 비교하지 않으며, 절리가 많아
구조적으로 오래 걸리는 low-Q 후보가 runtime 때문에 배제되지 않도록 같은 구간 안에서
효율을 비교한다.

실행 후에는 예상시간과 실제시간의 차이를 기록하고, 다음 round의 예상시간을 갱신한다.
시간 초과 전략은 실패로 즉시 폐기하지 않고 checkpoint와 부분 coverage를 보존한다.
다만 반복적으로 시간 예산을 초과하면서 새로운 bin이나 profile 정보를 만들지 못하면
`deprioritized` 또는 `rejected`로 전환한다.

시간 효율 기준은 coverage의 질을 대체하지 않는다. 최종 선택은 `정보획득량`,
`독립성`, `중복도`, `profile 재현성`, `수행시간`을 함께 고려하며, 실행이 빠르다는
이유만으로 전략을 유지하지 않는다.

### 5.8 Q′ 계산 및 시추공·터널 profile 계약 (2026-10-04)

이 절은 2026-10-04 논의에서 추가로 합의한 Q′ 계산, 입력 geometry, profile 및 굴진장
계약을 날짜별로 기록한다. 기존 설계·가설·계산식 기록을 삭제하거나 소급 수정하지 않는다.
여기에 적힌 값 중 QSimEx 편의상 도입한 convention은 Barton/NGI의 지질 판정 기준과
구분하여 provenance에 표시한다.

#### 5.8.1 Q′ 및 Barton 매개변수 사용

Q′는 다음 식으로 산정하며 지하수 및 응력 인자는 제외한다.

$$
Q' = \left(\frac{RQD}{J_n}\right)\left(\frac{J_r}{J_a}\right)
$$

RQD가 10 이하인 경우 계산에 사용하는 RQD는 10으로 둔다. `Jn`은 해당 위치의 case/domain
설정에 정의된 절리군 수로 정하고, profile 구간의 교차 수로 대체하지 않는다.

절리 교차가 있는 구간은 교차한 joint별 `Jr/Ja`를 산출하고, 비율이 가장 작은 joint의
`Jr`와 `Ja`를 한 쌍으로 사용한다. `Jr`와 `Ja`를 서로 다른 joint에서 독립적으로 골라
조합하지 않는다. 이 계산이 Barton 표의 여러 joint 상태를 대표하는 적절한 집계인지 여부는
실제 자료와 대안 집계 방식에 대한 비교 평가 대상이다.

`Jr` 및 `Ja` 입력은 Barton Q-system 표의 이산 평가 범주를 사용하며 joint별 정규분포
샘플링으로 대체하지 않는다. 범위형 표 항목은 범주를 보존하고 범위의 중간값을 계산에
사용한다. 예를 들어 `Ja=8–12`는 계산값 10, `Ja=13–20`은 16.5로 둔다. 선택 범주와
산출 수치는 provenance에 모두 기록한다.

교차가 없는 구간은 QSimEx convention으로 `RQD=100, Jr=4, Ja=0.75`를 사용한다. 이
fallback은 무교차 관측만으로 거칠고 맞물린 무변질 절리벽 조건이 입증되었다는 뜻이 아니다.
산출값에는 관측값이 아닌 fallback convention임을 식별할 수 있는 provenance를 붙인다.
제공된 Barton Q 등급 경계와 기존 코드의 `ROCK_CLASSES` 경계가 일치하는지도 구현 때
대조하고, 불일치가 있으면 출처와 적용 정책을 명시한다.

#### 5.8.2 시추공 geometry와 Q′BH profile

일반 시추공은 터널 geometry와 독립적인 물리 좌표 `(x,y,z)`의 선형 geometry다. 입력은
시작점, 방향, 요청 길이로 표현하며, 시작점-끝점 입력도 같은 canonical 형식으로 정규화할
수 있다. 방향은 정규화하고, domain clipping 이후 실제 계산 길이를 기록한다. 기존의
`borehole_offsets` 입력과 그에 의존하는 case 설정은 새 물리 geometry 입력으로 이전하고
활성 계약에서는 제거한다.

Q′BH profile 간격 `dx′`는 기본 1m로 하고 설정 가능하게 한다. 이는 전역 grid spacing과
독립이다. domain clipping 뒤 길이가 `dx′`의 정수배가 아닌 경우 완전한 구간만 계산하고
남은 불완전 구간은 버린다. 계산된 profile 전체와 그로부터 산출한 summary를 모두 보존한다.

터널 진행과 같은 방향에 해당하는 구간만 선택적으로 face profile과 비교한다. 수직 등 다른
방향의 일반 시추공은 독립 Q′BH 자료로 유지하며 tunnel face profile에 억지로 대응시키지
않는다. 시추공은 터널 chainage 순서대로 처리하며, 한 시점에 현재 차례의 시추공 하나만
분석하고 완료 결과를 저장한 다음 다음 시추공으로 이동한다.

#### 5.8.3 Tunnel polyline, Q′Face profile 및 비교 범위

터널은 시작점에서 종점 방향으로 진행하는 순서 있는 직선 polyline segment로 표현한다.
각 segment에는 시작점·방향·길이를 명시하고, 연속 segment의 연결성을 검증한다. 현재
차례의 시추공 및 대응 profile은 tunnel chainage 순서를 따른다.

굴진면 `Q′Face`는 station마다 산출해 거리순 시퀀스로 보존한다. 전체 터널 구간의 평균 하나로
축약하지 않는다. 이는 기존 station별 face 계산 모델의 longitudinal 결과 보존에 관한 결정이며,
새 cell별 face Q′ 모델을 도입한다는 의미는 아니다. Face와 시추공 profile의 비교는 tunnel
segment와 시추공의 실제 overlap 범위에서만 수행한다. overlap 밖의 Q′BH 값은 독립 profile에
그대로 보존한다.

비교는 station별 일대일 차이가 아니라 비짝지음 profile 분포 비교로 한다. 원본 profile과
station 표식을 유지하며 Wasserstein-1 거리 및 기술통계를 산출한다. 방향이 바뀌는 polyline
vertex에서는 round를 직전 직선 segment 끝에서 종료하고 다음 segment에서 새 round를
시작한다. vertex face 방향은 도달한 직전 segment 방향으로 평가한다.

domain 경계에서 원형 face의 domain 안쪽 부분만 계산한다. in-domain face area가 전체 face
area의 50% 미만이면 해당 station을 무효 처리하고 경계에서 tunnel 진행을 멈춘다. 마지막
유효 face와 중단 사유를 결과에 기록한다. 이 50% 기준은 모델 운용 계약이며, 경계 근처 결과의
민감도와 대안 threshold 영향은 검증에서 평가한다.

#### 5.8.4 Q′ 기반 자동 굴진장

`face_step`은 고정 공간 sampling 간격이 아니라 암질에 따라 정하는 1회 굴진장(round
length)이다. 자동 굴진장 선택에는 `Jw=SRF=1`로 취급한 Q′를 사용한다. 이는 굴진장
정책에만 적용하는 convention이며 Q′ 또는 full Q 계산식을 바꾸지 않는다.

현재 굴진면의 `Q′Face`는 다음 round 길이를 정한다. 시작 face는 첫 round 길이 결정에
사용하지만, 미래 face 비교 profile에는 포함하지 않는다. 유한 길이 범위의 대표 굴진장은
범위 중간값으로 정하고, `Q′>10`이면 4.0m, `Q′≤0.1`이면 0.75m로 둔다. Round가 직선
polyline segment 끝을 넘으려 하면 segment 끝에서 잘라 round를 종료한다.

이에 따라 face station의 chainage 간격은 불균등할 수 있다. 분포 통계에서는 실제 대표
굴진장으로 가중한다. 각 미래 face 값은 그 face에 도달하기까지의 직전 실제 굴진장으로
가중한다. 이 결정의 영향은 일정 간격 sampling 및 비가중 통계와 비교해 논문/검증에서
평가한다.

#### 5.8.5 본문·논문에서의 평가 원칙

이 절의 수치·집계 정책은 구현 전에 합의한 설계 계약이지, 모두가 Barton 표의 직접 지시이거나
이미 실증된 최선의 선택이라는 주장이 아니다. 논문에서는 적어도 다음을 근거와 함께 평가한다.

- 무교차 fallback과 범위형 `Ja` 중간값 사용이 결과에 미치는 영향 및 provenance로 관측과
  convention을 구분하는 방식
- 교차 joint 중 최소 `Jr/Ja` 쌍을 대표로 선택하는 것이 profile Q′ 및 대안 집계와 어떻게
  다른지
- 1m 기본 profile 간격, 불완전 마지막 구간 폐기, face area 50% 유효 조건의 민감도
- 실제 overlap 기반·비짝지음 profile 비교가 scalar/일대일 비교와 제공하는 정보 차이
- 암질별 굴진장과 길이 가중 통계가 face profile 결과에 주는 영향
- profile-based coverage, 50:50 coverage score, 중앙차분 update, 약 5% step, 추가 3개 seed 중
  2개 채택 기준의 안정성 및 대안에 대한 민감도

논문은 합의된 규칙을 단순히 권위 있는 기준으로 인용하지 않고, 출처가 있는 지질학적
정의·QSimEx 계산 convention·경험적으로 검증해야 할 정책을 분리한다. 대안 비교 결과와
한계는 합의된 사양과 별도로 기록하여 이후 변경 이력도 추적 가능하게 한다.

#### 5.8.6 활성 계산에서 제외할 경험적 보정 (이전 합의; 당시 날짜 미기록, 2026-10-04 기록)

Practice realism 보정은 활성 계산 경로와 public API에서 제거하고 Git history에만 보존한다.
적용 대상에는 mechanical break, microfracture 추가, core recovery 보정, `Jr/Ja` scale 및
face conservative estimator가 포함된다. 이는 본 절의 Q′ 산식이나 geology category 값을
바꾸는 근거로 사용하지 않는다. 논문에서는 해당 보정을 기본 Q′ 계산에서 제외한 이유와,
필요하다면 별도 민감도/대안 분석으로 다룰 범위를 명확히 구분한다.
