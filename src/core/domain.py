"""
3D 암반 도메인 & 분석 케이스 정의
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Tuple, List, Optional
from .joint_models import DomainJointConfig, JointSetDefinition
from .dfn_generator import DiscreteFractureNetwork
from .grid_assigner import GridParameterAssigner
from .rqd_calculator import DirectionalRQDCalculator


@dataclass
class AnalysisCase:
    """분석 케이스 정의"""
    name: str
    description: str

    # 도메인
    domain_size: Tuple[int, int, int] = (100, 50, 50)
    grid_spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0)

    # 절리 구성
    joint_config: DomainJointConfig = None

    # 터널
    tunnel_center_y: float = 25.0
    tunnel_center_z: float = 25.0
    tunnel_radius: float = 5.0

    # 시추공 (터널 중심 기준 오프셋: dy, dz)
    borehole_offsets: List[Tuple[float, float]] = field(default_factory=lambda: [
        (0.0, 0.0),      # 중앙
        (0.0, +3.0),     # 상부
        (0.0, -3.0),     # 하부
    ])

    # RQD 설정
    rqd_scan_length: float = 5.0

    seed: int = 42

    def __post_init__(self):
        if self.joint_config is None:
            self.joint_config = DomainJointConfig(
                joint_sets=[
                    JointSetDefinition(set_id=1, name="JS-1",
                                       mean_dip=10, mean_dip_dir=0,
                                       fisher_kappa=30, size_alpha=3.0,
                                       size_r_min=0.5, size_r_max=15.0,
                                       P32=0.8),
                    JointSetDefinition(set_id=2, name="JS-2",
                                       mean_dip=80, mean_dip_dir=90,
                                       fisher_kappa=20, size_alpha=3.0,
                                       size_r_min=0.3, size_r_max=12.0,
                                       P32=0.6),
                ])
    
    @classmethod
    def from_yaml(self, path: str) -> 'AnalysisCase':
        """YAML 파일에서 케이스 생성"""
        import yaml
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
        
        joint_config = DomainJointConfig.from_dict(data['joint_config'])
        borehole_offsets = [(b['dy'], b['dz']) for b in data.get('boreholes', [])]

        return AnalysisCase(
            name=data['name'],
            description=data['description'],
            domain_size=tuple(data['domain']['size']),
            grid_spacing=tuple(data['domain']['grid_spacing']),
            joint_config=joint_config,
            tunnel_center_y=data['tunnel']['center_y'],
            tunnel_center_z=data['tunnel']['center_z'],
            tunnel_radius=data['tunnel']['radius'],
            borehole_offsets=borehole_offsets,
            rqd_scan_length=data['rqd']['scan_length'],
            seed=data.get('seed', 42)
        )

class RockDomain:
    """3D 암반 도메인 (DFN 기반)"""

    def __init__(self, case: 'AnalysisCase'):
        self.case = case
        self.nx, self.ny, self.nz = case.domain_size
        self.dx, self.dy, self.dz = case.grid_spacing

        self.dfn = None
        self.dir_rqd_calc = None
        self.fields: Dict[str, np.ndarray] = {}
        self.Q_field = None
        self.Qprime_field = None
        self._generated = False

    def generate(self, verbose: bool = True,
                 backend: str = 'auto',
                 batch_size: int = 500):
        """
        도메인 생성

        Args:
            verbose: 상세 출력
            backend: 'auto', 'cuda', 'mps', 'mlx', 'cpu'
            batch_size: GPU 배치 크기
        """
        domain_physical = (
            self.nx * self.dx, self.ny * self.dy, self.nz * self.dz
        )

        # Step 1: DFN
        if verbose:
            print("[Step 1] DFN 생성...")
        self.dfn = DiscreteFractureNetwork(
            self.case.joint_config, domain_size=domain_physical,
            seed=self.case.seed
        )
        self.dfn.generate(verbose=verbose)

        # Step 2: 격자 할당 (GPU 가속)
        if verbose:
            print("\n[Step 2] 격자 파라미터 할당...")
        assigner = GridParameterAssigner(
            dfn=self.dfn, config=self.case.joint_config,
            nx=self.nx, ny=self.ny, nz=self.nz,
            dx=self.dx, dy=self.dy, dz=self.dz,
            seed=self.case.seed + 100
        )
        assigner.assign_all(
            scan_length=self.case.rqd_scan_length,
            backend=backend,
            batch_size=batch_size,
        )
        self.fields = {k: v for k, v in assigner.fields.items()
                       if not k.startswith('_')}

        # Step 3: Q, Q'
        if verbose:
            print("\n[Step 3] Q, Q' 필드 계산...")
        self._compute_Q_fields()

        # Step 4: 방향별 RQD
        from .rqd_calculator import DirectionalRQDCalculator
        self.dir_rqd_calc = DirectionalRQDCalculator(self.dfn)
        self._generated = True

        if verbose:
            self._print_summary()

    def _compute_Q_fields(self):
        RQD = self.fields['RQD']
        Jn = np.maximum(self.fields['Jn'], 0.5)
        Jr = self.fields['Jr']
        Ja = np.maximum(self.fields['Ja'], 0.75)
        Jw = self.fields['Jw']
        SRF = np.maximum(self.fields['SRF'], 0.5)
        self.Q_field = (RQD / Jn) * (Jr / Ja) * (Jw / SRF)
        self.Qprime_field = (RQD / Jn) * (Jr / Ja)

    def _print_summary(self):
        print(f"\n{'='*50}")
        print(f"  도메인 생성 완료: {self.nx}×{self.ny}×{self.nz}")
        print(f"  절리군: {self.case.joint_config.n_sets} → Jn={self.case.joint_config.Jn}")
        print(f"  총 절리: {len(self.dfn.joints)}개")
        for name, fld in self.fields.items():
            print(f"  {name:>4}: mean={fld.mean():.2f}, std={fld.std():.2f}, "
                  f"[{fld.min():.2f}, {fld.max():.2f}]")
        print(f"  Q  : mean={self.Q_field.mean():.3f}, median={np.median(self.Q_field):.3f}")
        print(f"  Q' : mean={self.Qprime_field.mean():.3f}, median={np.median(self.Qprime_field):.3f}")
        print(f"{'='*50}")

    def get_value_at(self, xi, yi, zi):
        result = {n: float(self.fields[n][xi, yi, zi]) for n in self.fields}
        result['Q'] = float(self.Q_field[xi, yi, zi])
        result['Qprime'] = float(self.Qprime_field[xi, yi, zi])
        return result