"""
분석 케이스 관리
- YAML 파일 로드/저장
- 기존 프리셋 유지 (폴백)
- 디렉토리 스캔
"""

import os
import yaml
import glob
from pathlib import Path
from typing import Dict, Optional, List

from .joint_models import JointSetDefinition, DomainJointConfig
from .domain import AnalysisCase


# ================================================================
# YAML ↔ AnalysisCase 변환
# ================================================================
class CaseLoader:
    """YAML 파일에서 AnalysisCase를 로드/저장"""

    @staticmethod
    def load_yaml(filepath: str) -> AnalysisCase:
        """
        YAML 파일 → AnalysisCase 변환

        Args:
            filepath: .yaml 파일 경로

        Returns:
            AnalysisCase 객체
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"케이스 파일 없음: {filepath}")

        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        # 절리군 파싱
        joint_sets = []
        for js_data in data.get('joint_sets', []):
            js = JointSetDefinition(
                set_id=js_data['set_id'],
                name=js_data.get('name', f"JS-{js_data['set_id']}"),
                # 방향 (Fisher)
                mean_dip=float(js_data.get('mean_dip', 45)),
                mean_dip_dir=float(js_data.get('mean_dip_dir', 180)),
                fisher_kappa=float(js_data.get('fisher_kappa', 20)),
                # 크기 (Power Law)
                size_alpha=float(js_data.get('size_alpha', 3.0)),
                size_r_min=float(js_data.get('size_r_min', 0.5)),
                size_r_max=float(js_data.get('size_r_max', 20.0)),
                # 밀도
                density_type=js_data.get('density_type', 'P32'),
                P32=float(js_data.get('P32', 1.0)),
                mean_spacing=float(js_data.get('mean_spacing', 0.5)),
                # 역학
                Jr_mean=float(js_data.get('Jr_mean', 1.5)),
                Jr_std=float(js_data.get('Jr_std', 0.3)),
                Ja_mean=float(js_data.get('Ja_mean', 2.0)),
                Ja_std=float(js_data.get('Ja_std', 0.5)),
            )
            joint_sets.append(js)

        # 전역 파라미터
        gp = data.get('global_params', {})
        joint_config = DomainJointConfig(
            joint_sets=joint_sets,
            Jw_mean=float(gp.get('Jw_mean', 0.66)),
            Jw_std=float(gp.get('Jw_std', 0.15)),
            SRF_mean=float(gp.get('SRF_mean', 2.5)),
            SRF_std=float(gp.get('SRF_std', 1.0)),
        )

        # 도메인
        dom = data.get('domain', {})
        domain_size = (
            int(dom.get('nx', 100)),
            int(dom.get('ny', 50)),
            int(dom.get('nz', 50)),
        )
        grid_spacing = (
            float(dom.get('dx', 1.0)),
            float(dom.get('dy', 1.0)),
            float(dom.get('dz', 1.0)),
        )

        # 터널
        tun = data.get('tunnel', {})

        # 시추공
        bh_data = data.get('boreholes', [
            {'dy': 0.0, 'dz': 0.0},
            {'dy': 0.0, 'dz': 3.0},
            {'dy': 0.0, 'dz': -3.0},
        ])
        borehole_offsets = [(float(b['dy']), float(b['dz'])) for b in bh_data]

        # RQD
        rqd_conf = data.get('rqd', {})

        case = AnalysisCase(
            name=data.get('name', filepath.stem),
            description=data.get('description', ''),
            domain_size=domain_size,
            grid_spacing=grid_spacing,
            joint_config=joint_config,
            tunnel_center_y=float(tun.get('center_y', 25.0)),
            tunnel_center_z=float(tun.get('center_z', 25.0)),
            tunnel_radius=float(tun.get('radius', 5.0)),
            borehole_offsets=borehole_offsets,
            rqd_scan_length=float(rqd_conf.get('scan_length', 5.0)),
            seed=int(data.get('seed', 42)),
        )

        return case

    @staticmethod
    def save_yaml(case: AnalysisCase, filepath: str):
        """
        AnalysisCase → YAML 파일 저장

        기존 케이스를 수정 후 저장하거나,
        GUI에서 설정한 케이스를 파일로 내보낼 때 사용
        """
        jc = case.joint_config

        data = {
            'name': case.name,
            'description': case.description,
            'seed': case.seed,

            'domain': {
                'nx': case.domain_size[0],
                'ny': case.domain_size[1],
                'nz': case.domain_size[2],
                'dx': case.grid_spacing[0],
                'dy': case.grid_spacing[1],
                'dz': case.grid_spacing[2],
            },

            'tunnel': {
                'center_y': case.tunnel_center_y,
                'center_z': case.tunnel_center_z,
                'radius': case.tunnel_radius,
            },

            'boreholes': [
                {'dy': dy, 'dz': dz} for dy, dz in case.borehole_offsets
            ],

            'rqd': {
                'scan_length': case.rqd_scan_length,
            },

            'global_params': {
                'Jw_mean': jc.Jw_mean,
                'Jw_std': jc.Jw_std,
                'SRF_mean': jc.SRF_mean,
                'SRF_std': jc.SRF_std,
            },

            'joint_sets': [],
        }

        for js in jc.joint_sets:
            data['joint_sets'].append({
                'set_id': js.set_id,
                'name': js.name,
                'mean_dip': js.mean_dip,
                'mean_dip_dir': js.mean_dip_dir,
                'fisher_kappa': js.fisher_kappa,
                'size_alpha': js.size_alpha,
                'size_r_min': js.size_r_min,
                'size_r_max': js.size_r_max,
                'density_type': js.density_type,
                'P32': js.P32,
                'mean_spacing': js.mean_spacing,
                'Jr_mean': js.Jr_mean,
                'Jr_std': js.Jr_std,
                'Ja_mean': js.Ja_mean,
                'Ja_std': js.Ja_std,
            })

        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)

        print(f"  💾 케이스 저장: {filepath}")


# ================================================================
# 케이스 디렉토리 스캐너
# ================================================================
class CaseScanner:
    """cases/ 디렉토리에서 YAML 파일을 자동 탐색"""

    DEFAULT_DIRS = [
        'cases',
        'cases/',
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'cases'),
    ]

    @classmethod
    def find_case_dir(cls) -> Optional[Path]:
        """cases/ 디렉토리 찾기"""
        for d in cls.DEFAULT_DIRS:
            p = Path(d)
            if p.is_dir():
                return p
        return None

    @classmethod
    def scan_cases(cls, case_dir: str = None) -> Dict[str, str]:
        """
        디렉토리 내 .yaml 파일 목록 반환

        Returns:
            {'case_name': 'filepath', ...}
        """
        if case_dir:
            search_dir = Path(case_dir)
        else:
            search_dir = cls.find_case_dir()

        if search_dir is None or not search_dir.is_dir():
            return {}

        result = {}
        for f in sorted(search_dir.glob('*.yaml')):
            if f.name.startswith('_'):  # _template.yaml 등 제외
                continue
            result[f.stem] = str(f)

        return result

    @classmethod
    def load_all_cases(cls, case_dir: str = None) -> Dict[str, AnalysisCase]:
        """디렉토리 내 모든 YAML → AnalysisCase 로드"""
        files = cls.scan_cases(case_dir)
        cases = {}
        for name, path in files.items():
            try:
                cases[name] = CaseLoader.load_yaml(path)
            except Exception as e:
                print(f"  ⚠️ {name} 로드 실패: {e}")
        return cases


# ================================================================
# CaseLibrary: YAML 우선 + 하드코딩 폴백
# ================================================================
class CaseLibrary:
    """
    케이스 라이브러리

    우선순위:
    1. cases/ 디렉토리의 YAML 파일
    2. 하드코딩된 기본 프리셋 (YAML 없을 때 폴백)
    """

    @staticmethod
    def get_all_cases(case_dir: str = None) -> Dict[str, AnalysisCase]:
        """
        사용 가능한 모든 케이스 반환

        Args:
            case_dir: 케이스 디렉토리 경로 (None=자동 탐색)
        """
        # 1순위: YAML 파일
        cases = CaseScanner.load_all_cases(case_dir)

        if cases:
            return cases

        # 2순위: 하드코딩 폴백
        print("  ℹ️ cases/ 디렉토리에 YAML 파일이 없어 기본 프리셋 사용")
        return CaseLibrary._builtin_cases()

    @staticmethod
    def load_case(name_or_path: str, case_dir: str = None) -> AnalysisCase:
        """
        이름 또는 파일 경로로 단일 케이스 로드

        Args:
            name_or_path: 케이스 이름 또는 .yaml 파일 경로
            case_dir: 케이스 디렉토리
        """
        # 파일 경로인 경우
        if name_or_path.endswith('.yaml') or name_or_path.endswith('.yml'):
            return CaseLoader.load_yaml(name_or_path)

        # 이름으로 검색
        all_cases = CaseLibrary.get_all_cases(case_dir)
        if name_or_path in all_cases:
            return all_cases[name_or_path]

        # YAML 파일 직접 검색
        scanner = CaseScanner()
        case_directory = Path(case_dir) if case_dir else scanner.find_case_dir()
        if case_directory:
            yaml_path = case_directory / f"{name_or_path}.yaml"
            if yaml_path.exists():
                return CaseLoader.load_yaml(str(yaml_path))

        raise ValueError(
            f"케이스 '{name_or_path}'을(를) 찾을 수 없습니다.\n"
            f"사용 가능: {list(all_cases.keys())}"
        )

    @staticmethod
    def generate_default_yamls(output_dir: str = "cases"):
        """기본 프리셋을 YAML 파일로 생성 (초기 설정용)"""
        cases = CaseLibrary._builtin_cases()
        for name, case in cases.items():
            filepath = os.path.join(output_dir, f"{name}.yaml")
            CaseLoader.save_yaml(case, filepath)
        print(f"  ✅ {len(cases)}개 기본 케이스 YAML 생성: {output_dir}/")

    @staticmethod
    def _builtin_cases() -> Dict[str, AnalysisCase]:
        """하드코딩 기본 프리셋 (폴백)"""
        return {
            'granite_2sets': AnalysisCase(
                name="granite_2sets",
                description="화강암 2개 절리군 — 양호 암반",
                joint_config=DomainJointConfig(
                    joint_sets=[
                        JointSetDefinition(
                            set_id=1, name="수평 절리 (Sheeting)",
                            mean_dip=10, mean_dip_dir=0, fisher_kappa=50,
                            size_alpha=3.5, size_r_min=0.5, size_r_max=15.0,
                            density_type='P32', P32=0.8,
                            Jr_mean=2.0, Jr_std=0.3, Ja_mean=1.0, Ja_std=0.2,
                        ),
                        JointSetDefinition(
                            set_id=2, name="수직 절리",
                            mean_dip=85, mean_dip_dir=90, fisher_kappa=30,
                            size_alpha=3.0, size_r_min=0.3, size_r_max=12.0,
                            density_type='P32', P32=0.6,
                            Jr_mean=1.5, Jr_std=0.4, Ja_mean=1.5, Ja_std=0.3,
                        ),
                    ],
                    Jw_mean=0.8, Jw_std=0.1, SRF_mean=1.0, SRF_std=0.3,
                ),
                seed=42,
            ),
            'sedimentary_3sets': AnalysisCase(
                name="sedimentary_3sets",
                description="퇴적암 3개 절리군 — 보통 암반",
                joint_config=DomainJointConfig(
                    joint_sets=[
                        JointSetDefinition(
                            set_id=1, name="층리면 (Bedding)",
                            mean_dip=15, mean_dip_dir=180, fisher_kappa=40,
                            size_alpha=2.5, size_r_min=1.0, size_r_max=30.0,
                            density_type='P32', P32=1.5,
                            Jr_mean=1.0, Jr_std=0.2, Ja_mean=3.0, Ja_std=0.8,
                        ),
                        JointSetDefinition(
                            set_id=2, name="수직 절리 Set A",
                            mean_dip=80, mean_dip_dir=45, fisher_kappa=25,
                            size_alpha=3.0, size_r_min=0.5, size_r_max=15.0,
                            density_type='P32', P32=1.0,
                            Jr_mean=1.5, Jr_std=0.3, Ja_mean=2.0, Ja_std=0.5,
                        ),
                        JointSetDefinition(
                            set_id=3, name="수직 절리 Set B",
                            mean_dip=75, mean_dip_dir=135, fisher_kappa=20,
                            size_alpha=3.2, size_r_min=0.3, size_r_max=10.0,
                            density_type='P32', P32=0.8,
                            Jr_mean=1.5, Jr_std=0.4, Ja_mean=2.5, Ja_std=0.6,
                        ),
                    ],
                    Jw_mean=0.5, Jw_std=0.2, SRF_mean=2.5, SRF_std=1.0,
                ),
                seed=123,
            ),
            'fault_zone_4sets': AnalysisCase(
                name="fault_zone_4sets",
                description="단층대 4개 절리군 — 파쇄대, 불량 암반",
                joint_config=DomainJointConfig(
                    joint_sets=[
                        JointSetDefinition(
                            set_id=1, name="단층면",
                            mean_dip=60, mean_dip_dir=270, fisher_kappa=15,
                            size_alpha=2.5, size_r_min=0.3, size_r_max=25.0,
                            density_type='P32', P32=2.5,
                            Jr_mean=1.0, Jr_std=0.3, Ja_mean=6.0, Ja_std=2.0,
                        ),
                        JointSetDefinition(
                            set_id=2, name="전단 절리 A",
                            mean_dip=45, mean_dip_dir=0, fisher_kappa=10,
                            size_alpha=2.8, size_r_min=0.2, size_r_max=12.0,
                            density_type='P32', P32=2.0,
                            Jr_mean=0.5, Jr_std=0.2, Ja_mean=4.0, Ja_std=1.5,
                        ),
                        JointSetDefinition(
                            set_id=3, name="전단 절리 B",
                            mean_dip=50, mean_dip_dir=180, fisher_kappa=10,
                            size_alpha=3.0, size_r_min=0.2, size_r_max=10.0,
                            density_type='P32', P32=1.8,
                            Jr_mean=1.0, Jr_std=0.2, Ja_mean=4.0, Ja_std=1.0,
                        ),
                        JointSetDefinition(
                            set_id=4, name="인장 절리",
                            mean_dip=70, mean_dip_dir=90, fisher_kappa=20,
                            size_alpha=3.5, size_r_min=0.1, size_r_max=8.0,
                            density_type='P32', P32=1.5,
                            Jr_mean=1.5, Jr_std=0.5, Ja_mean=3.0, Ja_std=1.0,
                        ),
                    ],
                    Jw_mean=0.33, Jw_std=0.15, SRF_mean=7.5, SRF_std=3.0,
                ),
                seed=789,
            ),
        }