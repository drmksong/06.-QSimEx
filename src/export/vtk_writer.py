"""
ParaView 호환 VTK 파일 작성기
- .vti (ImageData): 격자 필드
- .vtp (PolyData): 절리 디스크, 터널, 시추공, Trace
- .pvd (Collection): 시계열
"""

import numpy as np
from typing import Dict, List, Tuple


class VTKWriter:
    """VTK XML 포맷 작성기"""

    # ────────────────────────────────────────
    # VTI: 구조격자 (암반 파라미터 필드)
    # ────────────────────────────────────────
    @staticmethod
    def write_image_data(filepath: str,
                          fields: Dict[str, np.ndarray],
                          spacing: Tuple[float, float, float] = (1, 1, 1),
                          origin: Tuple[float, float, float] = (0, 0, 0)):
        """3D 필드를 VTI (ASCII)로 출력"""
        first = next(iter(fields.values()))
        nx, ny, nz = first.shape

        with open(filepath, 'w') as f:
            f.write('<?xml version="1.0"?>\n')
            f.write('<VTKFile type="ImageData" version="1.0" byte_order="LittleEndian">\n')
            f.write(f'  <ImageData WholeExtent="0 {nx} 0 {ny} 0 {nz}" '
                    f'Spacing="{spacing[0]} {spacing[1]} {spacing[2]}" '
                    f'Origin="{origin[0]} {origin[1]} {origin[2]}">\n')
            f.write(f'    <Piece Extent="0 {nx} 0 {ny} 0 {nz}">\n')
            f.write('      <CellData>\n')

            for name, data in fields.items():
                f.write(f'        <DataArray type="Float64" Name="{name}" format="ascii">\n')
                flat = data.flatten(order='F')
                for i in range(0, len(flat), 6):
                    chunk = flat[i:i + 6]
                    f.write('          ' + ' '.join(f'{v:.6f}' for v in chunk) + '\n')
                f.write('        </DataArray>\n')

            f.write('      </CellData>\n')
            f.write('    </Piece>\n')
            f.write('  </ImageData>\n')
            f.write('</VTKFile>\n')

        print(f"  📦 VTI: {filepath} ({nx}×{ny}×{nz}, {len(fields)} fields)")

    # ────────────────────────────────────────
    # VTP: 절리 디스크 (폴리곤)
    # ────────────────────────────────────────
    @staticmethod
    def write_joint_disks(filepath: str, joints: list, n_seg: int = 16):
        """절리 디스크 → VTP 폴리곤"""
        all_points = []
        all_polys = []
        set_ids, jr_vals, ja_vals, radii = [], [], [], []
        offset = 0

        for joint in joints:
            pts = _disk_vertices(joint.center, joint.normal, joint.radius, n_seg)
            all_points.extend(pts)
            all_polys.append(list(range(offset, offset + n_seg)))
            set_ids.append(joint.set_id)
            jr_vals.append(joint.Jr)
            ja_vals.append(joint.Ja)
            radii.append(joint.radius)
            offset += n_seg

        _write_vtp_polys(filepath, all_points, all_polys, {
            'JointSetID': ('Int32', set_ids),
            'Jr': ('Float64', jr_vals),
            'Ja': ('Float64', ja_vals),
            'Radius': ('Float64', radii),
        })
        print(f"  📦 VTP(절리): {filepath} ({len(joints)} disks)")

    # ────────────────────────────────────────
    # VTP: 터널 원통 메쉬
    # ────────────────────────────────────────
    @staticmethod
    def write_tunnel(filepath: str, cy: float, cz: float, radius: float,
                      x_start: float, x_end: float,
                      n_circ: int = 32, n_len: int = 100):
        """터널 원통 → VTP 쿼드"""
        points = []
        quads = []
        theta = np.linspace(0, 2 * np.pi, n_circ, endpoint=False)
        x_vals = np.linspace(x_start, x_end, n_len)

        for x in x_vals:
            for t in theta:
                points.append((x, cy + radius * np.cos(t), cz + radius * np.sin(t)))

        for xi in range(n_len - 1):
            for ti in range(n_circ):
                ti2 = (ti + 1) % n_circ
                p0 = xi * n_circ + ti
                p1 = xi * n_circ + ti2
                p2 = (xi + 1) * n_circ + ti2
                p3 = (xi + 1) * n_circ + ti
                quads.append((p0, p1, p2, p3))

        _write_vtp_polys(filepath, points, quads)
        print(f"  📦 VTP(터널): {filepath}")

    # ────────────────────────────────────────
    # VTP: 시추공 라인
    # ────────────────────────────────────────
    @staticmethod
    def write_boreholes(filepath: str, borehole_specs: List[Dict]):
        """시추공 궤적 → VTP 라인"""
        all_points = []
        all_lines = []
        offset = 0

        for bh in borehole_specs:
            x_vals = np.linspace(bh['x_start'], bh['x_end'], bh.get('n_points', 100))
            for x in x_vals:
                all_points.append((x, bh['y'], bh['z']))
            n = len(x_vals)
            all_lines.append(list(range(offset, offset + n)))
            offset += n

        _write_vtp_lines(filepath, all_points, all_lines)
        print(f"  📦 VTP(시추공): {filepath} ({len(all_lines)} lines)")

    # ────────────────────────────────────────
    # VTP: Trace 라인
    # ────────────────────────────────────────
    @staticmethod
    def write_traces(filepath: str, traces: List[Dict]):
        """절리 Trace → VTP 라인"""
        all_points = []
        all_lines = []
        set_ids, jr_vals, ja_vals, lengths = [], [], [], []
        offset = 0

        for tr in traces:
            if tr.get('type') == 'face_trace':
                pts = [tr['p1'], tr['p2']]
            elif 'edge_points' in tr:
                pts = tr['edge_points']
            else:
                continue
            if len(pts) < 2:
                continue

            for p in pts:
                all_points.append(p)
            all_lines.append(list(range(offset, offset + len(pts))))
            set_ids.append(tr.get('set_id', 0))
            jr_vals.append(tr.get('Jr', 0))
            ja_vals.append(tr.get('Ja', 0))
            lengths.append(tr.get('length', 0))
            offset += len(pts)

        _write_vtp_lines(filepath, all_points, all_lines, {
            'JointSetID': ('Int32', set_ids),
            'Jr': ('Float64', jr_vals),
            'Ja': ('Float64', ja_vals),
            'TraceLength': ('Float64', lengths),
        })
        print(f"  📦 VTP(Trace): {filepath} ({len(all_lines)} traces)")

    # ────────────────────────────────────────
    # PVD: 시계열 컬렉션
    # ────────────────────────────────────────
    @staticmethod
    def write_pvd(filepath: str, timestep_files: List[Tuple[float, str]]):
        """PVD 시계열"""
        with open(filepath, 'w') as f:
            f.write('<?xml version="1.0"?>\n')
            f.write('<VTKFile type="Collection" version="1.0">\n')
            f.write('  <Collection>\n')
            for t, fname in timestep_files:
                f.write(f'    <DataSet timestep="{t}" file="{fname}"/>\n')
            f.write('  </Collection>\n')
            f.write('</VTKFile>\n')
        print(f"  📦 PVD: {filepath} ({len(timestep_files)} steps)")


# ================================================================
# 내부 헬퍼 함수
# ================================================================
def _disk_vertices(center, normal, radius, n_seg=16):
    """절리 디스크 정점 좌표 생성"""
    normal = normal / np.linalg.norm(normal)
    arb = np.array([0, 0, 1]) if abs(normal[2]) < 0.9 else np.array([1, 0, 0])
    u = np.cross(normal, arb)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    v /= np.linalg.norm(v)

    verts = []
    for i in range(n_seg):
        theta = 2 * np.pi * i / n_seg
        p = center + radius * (np.cos(theta) * u + np.sin(theta) * v)
        verts.append(tuple(p))
    return verts


def _write_vtp_polys(filepath, points, polys, cell_data=None):
    """VTP 폴리곤 파일 작성"""
    with open(filepath, 'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="PolyData" version="1.0" byte_order="LittleEndian">\n')
        f.write('  <PolyData>\n')
        f.write(f'    <Piece NumberOfPoints="{len(points)}" NumberOfPolys="{len(polys)}">\n')

        # Points
        f.write('      <Points>\n')
        f.write('        <DataArray type="Float64" NumberOfComponents="3" format="ascii">\n')
        for p in points:
            f.write(f'          {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n')
        f.write('        </DataArray>\n')
        f.write('      </Points>\n')

        # Polys
        f.write('      <Polys>\n')
        f.write('        <DataArray type="Int64" Name="connectivity" format="ascii">\n')
        for poly in polys:
            f.write('          ' + ' '.join(str(i) for i in poly) + '\n')
        f.write('        </DataArray>\n')
        f.write('        <DataArray type="Int64" Name="offsets" format="ascii">\n')
        off = 0
        for poly in polys:
            off += len(poly)
            f.write(f'          {off}\n')
        f.write('        </DataArray>\n')
        f.write('      </Polys>\n')

        # Cell Data
        if cell_data:
            f.write('      <CellData>\n')
            for name, (dtype, vals) in cell_data.items():
                f.write(f'        <DataArray type="{dtype}" Name="{name}" format="ascii">\n')
                for i in range(0, len(vals), 10):
                    chunk = vals[i:i + 10]
                    if dtype.startswith('Float'):
                        f.write('          ' + ' '.join(f'{v:.6f}' for v in chunk) + '\n')
                    else:
                        f.write('          ' + ' '.join(str(int(v)) for v in chunk) + '\n')
                f.write('        </DataArray>\n')
            f.write('      </CellData>\n')

        f.write('    </Piece>\n')
        f.write('  </PolyData>\n')
        f.write('</VTKFile>\n')


def _write_vtp_lines(filepath, points, lines, cell_data=None):
    """VTP 라인 파일 작성"""
    with open(filepath, 'w') as f:
        f.write('<?xml version="1.0"?>\n')
        f.write('<VTKFile type="PolyData" version="1.0">\n')
        f.write('  <PolyData>\n')
        f.write(f'    <Piece NumberOfPoints="{len(points)}" '
                f'NumberOfLines="{len(lines)}" NumberOfPolys="0">\n')

        f.write('      <Points>\n')
        f.write('        <DataArray type="Float64" NumberOfComponents="3" format="ascii">\n')
        for p in points:
            f.write(f'          {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}\n')
        f.write('        </DataArray>\n')
        f.write('      </Points>\n')

        f.write('      <Lines>\n')
        f.write('        <DataArray type="Int64" Name="connectivity" format="ascii">\n')
        for line in lines:
            f.write('          ' + ' '.join(str(i) for i in line) + '\n')
        f.write('        </DataArray>\n')
        f.write('        <DataArray type="Int64" Name="offsets" format="ascii">\n')
        off = 0
        for line in lines:
            off += len(line)
            f.write(f'          {off}\n')
        f.write('        </DataArray>\n')
        f.write('      </Lines>\n')

        if cell_data:
            f.write('      <CellData>\n')
            for name, (dtype, vals) in cell_data.items():
                f.write(f'        <DataArray type="{dtype}" Name="{name}" format="ascii">\n')
                for i in range(0, len(vals), 10):
                    chunk = vals[i:i + 10]
                    if dtype.startswith('Float'):
                        f.write('          ' + ' '.join(f'{v:.6f}' for v in chunk) + '\n')
                    else:
                        f.write('          ' + ' '.join(str(int(v)) for v in chunk) + '\n')
                f.write('        </DataArray>\n')
            f.write('      </CellData>\n')

        f.write('    </Piece>\n')
        f.write('  </PolyData>\n')
        f.write('</VTKFile>\n')