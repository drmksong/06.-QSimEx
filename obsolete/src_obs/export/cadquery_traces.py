"""
CadQuery 기반 터널 굴착면 절리 Trace 추출
- 막장면 ∩ 절리 → 직선 Trace (해석적 계산)
- STEP/DXF 내보내기 (CadQuery 설치 시)
"""

import numpy as np
from typing import List, Dict, Tuple, Optional

try:
    import cadquery as cq
    from cadquery import exporters
    CQ_AVAILABLE = True
except ImportError:
    CQ_AVAILABLE = False


class TraceExtractor:
    """막장면 절리 Trace 추출기 (해석적 방법)"""

    def __init__(self, tunnel_cy: float, tunnel_cz: float, tunnel_radius: float):
        self.cy = tunnel_cy
        self.cz = tunnel_cz
        self.radius = tunnel_radius

    def extract_face_traces(self, face_x: float, joints: list) -> List[Dict]:
        """
        특정 굴진면(x좌표)에서의 절리 Trace 추출

        두 평면(막장면, 절리면)의 교선 → 두 원(막장원, 절리디스크)으로 클리핑
        """
        face_center = np.array([face_x, self.cy, self.cz])
        face_normal = np.array([1.0, 0.0, 0.0])
        traces = []

        for idx, joint in enumerate(joints):
            result = self._intersect(joint, face_center, face_normal, self.radius)
            if result is not None:
                p1, p2 = result
                traces.append({
                    'joint_idx': idx,
                    'set_id': joint.set_id,
                    'Jr': joint.Jr,
                    'Ja': joint.Ja,
                    'p1': p1.tolist(),
                    'p2': p2.tolist(),
                    'length': float(np.linalg.norm(p2 - p1)),
                    'type': 'face_trace',
                    'face_x': face_x,
                })

        print(f"  ✅ 막장면 Trace (x={face_x:.0f}m): {len(traces)}개")
        return traces

    def _intersect(self, joint, face_center, face_normal, face_radius):
        """절리-막장면 해석적 교차"""
        n1 = face_normal / np.linalg.norm(face_normal)
        n2 = joint.normal / np.linalg.norm(joint.normal)

        line_dir = np.cross(n1, n2)
        if np.linalg.norm(line_dir) < 1e-10:
            return None
        line_dir /= np.linalg.norm(line_dir)

        # 교선 위의 점
        d2 = np.dot(n2, joint.center)
        rhs = d2 - n2[0] * face_center[0]

        if abs(n2[1]) > abs(n2[2]):
            z0 = face_center[2]
            y0 = (rhs - n2[2] * z0) / (n2[1] + 1e-15)
        else:
            y0 = face_center[1]
            z0 = (rhs - n2[1] * y0) / (n2[2] + 1e-15)

        line_point = np.array([face_center[0], y0, z0])

        # 막장면 원으로 클리핑
        seg1 = self._clip_circle(line_point, line_dir, face_center[1:], face_radius)
        if seg1 is None:
            return None

        # 절리 디스크로 클리핑
        seg2 = self._clip_disk_3d(line_point, line_dir, joint.center, joint.normal, joint.radius)
        if seg2 is None:
            return None

        t_min = max(seg1[0], seg2[0])
        t_max = min(seg1[1], seg2[1])
        if t_max <= t_min + 0.01:
            return None

        return (line_point + t_min * line_dir, line_point + t_max * line_dir)

    @staticmethod
    def _clip_circle(lp, ld, center_2d, radius):
        """직선을 YZ 원으로 클리핑"""
        dp = np.array([lp[1] - center_2d[0], lp[2] - center_2d[1]])
        dd = np.array([ld[1], ld[2]])
        a = np.dot(dd, dd)
        b = 2 * np.dot(dp, dd)
        c = np.dot(dp, dp) - radius ** 2
        disc = b ** 2 - 4 * a * c
        if disc < 0 or a < 1e-15:
            return None
        sq = np.sqrt(disc)
        return ((-b - sq) / (2 * a), (-b + sq) / (2 * a))

    @staticmethod
    def _clip_disk_3d(lp, ld, dc, dn, dr):
        """직선을 3D 디스크로 클리핑"""
        dp = lp - dc
        d_n = np.dot(ld, dn)
        dp_n = np.dot(dp, dn)
        a = np.dot(ld, ld) - d_n ** 2
        b = 2 * (np.dot(dp, ld) - dp_n * d_n)
        c = np.dot(dp, dp) - dp_n ** 2 - dr ** 2
        if a < 1e-15:
            return (-1000, 1000) if c <= 0 else None
        disc = b ** 2 - 4 * a * c
        if disc < 0:
            return None
        sq = np.sqrt(disc)
        return ((-b - sq) / (2 * a), (-b + sq) / (2 * a))

    def export_traces_dxf(self, traces: List[Dict], filepath: str):
        """DXF 내보내기 (CadQuery 필요)"""
        if not CQ_AVAILABLE:
            print("  ⚠️ CadQuery 미설치, DXF 내보내기 불가")
            return
        edges = []
        for tr in traces:
            if tr['type'] == 'face_trace':
                edges.append(cq.Edge.makeLine(
                    cq.Vector(*tr['p1']), cq.Vector(*tr['p2'])
                ))
        if edges:
            compound = cq.Compound.makeCompound([cq.Shape.cast(e.wrapped) for e in edges])
            exporters.export(compound, filepath, exportType='DXF')
            print(f"  📐 DXF: {filepath} ({len(edges)} traces)")

    def export_traces_step(self, traces: List[Dict], filepath: str):
        """STEP 내보내기 (CadQuery 필요)"""
        if not CQ_AVAILABLE:
            print("  ⚠️ CadQuery 미설치, STEP 내보내기 불가")
            return
        edges = []
        for tr in traces:
            if tr['type'] == 'face_trace':
                edges.append(cq.Edge.makeLine(
                    cq.Vector(*tr['p1']), cq.Vector(*tr['p2'])
                ))
        if edges:
            compound = cq.Compound.makeCompound([cq.Shape.cast(e.wrapped) for e in edges])
            exporters.export(compound, filepath)
            print(f"  📐 STEP: {filepath} ({len(edges)} traces)")