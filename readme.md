# QSimEx v4

현재 작업 영역은 v4 구현 준비를 위한 소스와 기준 문서로 구성합니다.
새 `rqd_exploration` 모듈은 아직 골격이며, 파일럿 실행 기능은 구현 전입니다.
루트 실행 진입점은 CLI에 연결되어 있지만, 현재는 미구현 오류와 종료 코드 2를 반환하며
simulation이나 DB 생성을 수행하지 않습니다.

## 기준 문서

- [전략 및 요구사항 계획](Specification/RQDExplorationStrategy_20261026/plan.md)
- [ImplementationPlan_v4](Specification/ImplementationPlan_v4.md)

두 문서를 구현의 주 기준으로 삼고, 과거 계약·분석·소스는 필요한 근거를 확인할 때만
보관 영역에서 참조합니다. 파일럿 실행과 후속 자동 탐색은 각 계획의 승인 경계를 따릅니다.

## 폴더 구조

```text
QSimEx/
├── readme.md
├── run_rqd_exploration.py      # CLI에 연결된 미구현 안내 진입점
├── config/
│   └── rqd_exploration_pilot.yml  # 주석만 있는 입력 계약 placeholder
├── Specification/
│   ├── ImplementationPlan_v4.md
│   └── RQDExplorationStrategy_20261026/
├── src/
│   ├── rqd_exploration/       # 새 v4 모듈 골격
│   ├── euler_campaign/        # v4가 재사용할 계산/backend 경계
│   ├── core/                 # 재사용 경계에 필요한 joint_models
│   └── test/                 # 재사용 계산 경계의 회귀 테스트
├── results/
│   └── rqd_exploration/       # 출력 위치만 준비; run 결과는 실행 시 생성
└── obsolete/                 # 이전 소스·문서·설정·분석·결과·실행 도구
```

`.git/`, `.gitignore`, `.vscode/`는 저장소·개발 환경 설정으로 루트에 유지합니다.
새 v4 설정과 결과 폴더는 보관 영역과 별개로 준비했습니다. 설정 파일은 아직 유효한
pilot 입력이 아니며 T002 자료 계약 검토 후 값을 채웁니다. 결과 폴더의 `.gitkeep`만
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
