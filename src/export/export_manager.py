"""
통합 내보내기 관리자
- ParaView VTK 파일 일괄 생성
- CadQuery Trace 내보내기
"""

import json
import numpy as np
from pathlib import Path
from typing import List, Optional

from .vtk_writer import VTKWriter
from .cadquery_traces import TraceExtractor, CQ_AVAILABLE


class ExportManager:
    """
    출력 디렉토리 구조:
    output/<case_name>/
    ├── domain_fields.vti
    ├── joints_all.vtp
    ├── joints_set_N.vtp
    ├── tunnel.vtp
    ├── boreholes.vtp
    ├── face_traces/
    │   ├── face_010m.vtp
    │   └── ...
    ├── excavation_series.pvd
    └── summary.json
    """

    def __init__(self, domain, tunnel, output_dir: str = "output"):
        self.domain = domain
        self.tunnel = tunnel
        self.case = domain.case
        self.base_dir = Path(output_dir) / self.case.name
        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / 'face_traces').mkdir(exist_ok=True)

        self.trace_ext = TraceExtractor(
            self.case.tunnel_center_y,
            self.case.tunnel_center_z,
            self.case.tunnel_radius,
        )

    def export_all(self, face_positions_m: List[float] = None):
        """전체 내보내기"""
        print(f"\n{'='*60}")
        print(f"  📁 내보내기: {self.base_dir}")
        print(f"{'='*60}")

        self._export_domain_fields()
        self._export_joints()
        self._export_tunnel()
        self._export_boreholes()

        if face_positions_m is None:
            Lx = self.case.domain_size[0] * self.case.grid_spacing[0]
            face_positions_m = np.arange(10, Lx - 10, 10).tolist()
        self._export_face_traces(face_positions_m)
        self._export_pvd(face_positions_m)
        self._export_summary()

        print(f"\n  ✅ 완료! ParaView로 열기:")
        print(f"     paraview {self.base_dir / 'domain_fields.vti'}")

    def _export_domain_fields(self):
        print("\n[1] 도메인 필드...")
        fields = dict(self.domain.fields)
        fields['Q'] = self.domain.Q_field
        fields['Qprime'] = self.domain.Qprime_field
        VTKWriter.write_image_data(
            str(self.base_dir / 'domain_fields.vti'),
            fields, self.case.grid_spacing
        )

    def _export_joints(self):
        print("\n[2] 절리 디스크...")
        VTKWriter.write_joint_disks(
            str(self.base_dir / 'joints_all.vtp'),
            self.domain.dfn.joints
        )
        for sid, js in self.domain.dfn.joints_by_set.items():
            VTKWriter.write_joint_disks(
                str(self.base_dir / f'joints_set_{sid}.vtp'), js
            )

    def _export_tunnel(self):
        print("\n[3] 터널...")
        Lx = self.case.domain_size[0] * self.case.grid_spacing[0]
        VTKWriter.write_tunnel(
            str(self.base_dir / 'tunnel.vtp'),
            self.case.tunnel_center_y, self.case.tunnel_center_z,
            self.case.tunnel_radius, 0, Lx
        )

    def _export_boreholes(self):
        print("\n[4] 시추공...")
        Lx = self.case.domain_size[0] * self.case.grid_spacing[0]
        specs = []
        names = ['Center', 'Top', 'Bottom']
        for i, (y_idx, z_idx) in enumerate(self.tunnel.borehole_positions):
            specs.append({
                'name': names[i] if i < 3 else f'BH-{i}',
                'y': (y_idx + 0.5) * self.domain.dy,
                'z': (z_idx + 0.5) * self.domain.dz,
                'x_start': 0, 'x_end': Lx, 'n_points': 200,
            })
        VTKWriter.write_boreholes(str(self.base_dir / 'boreholes.vtp'), specs)

    def _export_face_traces(self, positions_m: List[float]):
        print("\n[5] 막장면 Trace...")
        for x_m in positions_m:
            traces = self.trace_ext.extract_face_traces(x_m, self.domain.dfn.joints)
            if traces:
                fname = f'face_traces/face_{int(x_m):03d}m.vtp'
                VTKWriter.write_traces(str(self.base_dir / fname), traces)

                # DXF/STEP (CadQuery 있을 때)
                if CQ_AVAILABLE:
                    dxf_name = f'face_traces/face_{int(x_m):03d}m.dxf'
                    self.trace_ext.export_traces_dxf(traces, str(self.base_dir / dxf_name))

    def _export_pvd(self, positions_m: List[float]):
        print("\n[6] PVD 시계열...")
        steps = []
        for x_m in positions_m:
            fname = f'face_traces/face_{int(x_m):03d}m.vtp'
            if (self.base_dir / fname).exists():
                steps.append((x_m, fname))
        if steps:
            VTKWriter.write_pvd(str(self.base_dir / 'excavation_series.pvd'), steps)

    def _export_summary(self):
        summary = {
            'case_name': self.case.name,
            'description': self.case.description,
            'domain_size': list(self.case.domain_size),
            'grid_spacing': list(self.case.grid_spacing),
            'n_joint_sets': self.case.joint_config.n_sets,
            'Jn': self.case.joint_config.Jn,
            'total_joints': len(self.domain.dfn.joints),
            'dfn_stats': self.domain.dfn.statistics(),
        }
        with open(self.base_dir / 'summary.json', 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
        print(f"  📋 summary.json 저장")