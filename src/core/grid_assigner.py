"""
3D 격자 기반 Q-System 파라미터 할당기

가속 백엔드 우선순위:
  1. CUDA  (torch.cuda — NVIDIA GPU)
  2. MPS   (torch.mps  — Apple Silicon GPU)
  3. MLX   (mlx        — Apple Silicon 전용)
  4. NumPy (CPU 벡터화 — 폴백)

자동 감지하여 최적 백엔드 사용
"""

import numpy as np
import time
from typing import Dict, Tuple, Optional

from .joint_models import DomainJointConfig
from .dfn_generator import DiscreteFractureNetwork
from .rqd_calculator import RQDCalculator


# ================================================================
# 백엔드 감지
# ================================================================
def detect_backend() -> str:
    """사용 가능한 최적 가속 백엔드 감지"""
    # Preferred order: MLX (Apple Silicon) -> CUDA -> MPS -> CPU
    # 1. MLX (Apple Silicon)
    try:
        import mlx.core as mx

        print(f"  🟢 MLX 감지: Apple Silicon")
        return "mlx"
    except Exception:
        pass

    # 2. CUDA (PyTorch)
    try:
        import torch

        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            print(f"  🟢 CUDA 감지: {name}")
            return "cuda"
    except Exception:
        pass

    # 3. MPS (Apple Silicon, PyTorch)
    try:
        import torch

        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            print(f"  🟢 MPS 감지: Apple Silicon GPU")
            return "mps"
    except Exception:
        pass

    # 4. CPU
    print(f"  🟡 GPU 미감지 → NumPy CPU 사용")
    return "cpu"


# ================================================================
# 메인 할당기
# ================================================================
class GridParameterAssigner:
    """
    격자 셀별 파라미터 할당 (자동 GPU 가속)

    사용법:
        assigner = GridParameterAssigner(dfn, config, nx, ny, nz)
        assigner.assign_all(backend='auto')  # 자동 감지
        assigner.assign_all(backend='cuda')  # 강제 지정
    """

    def __init__(
        self,
        dfn: DiscreteFractureNetwork,
        config: DomainJointConfig,
        nx: int,
        ny: int,
        nz: int,
        dx: float = 1.0,
        dy: float = 1.0,
        dz: float = 1.0,
        seed: int = 42,
    ):
        self.dfn = dfn
        self.config = config
        self.nx, self.ny, self.nz = nx, ny, nz
        self.dx, self.dy, self.dz = dx, dy, dz
        self.rng = np.random.RandomState(seed)
        self.fields: Dict[str, np.ndarray] = {}

    def assign_all(
        self,
        rqd_scanline_dir: Optional[np.ndarray] = None,
        scan_length: float = 5.0,
        backend: str = "auto",
        batch_size: int = 500,
    ):
        """
        모든 파라미터 격자 할당

        Args:
            rqd_scanline_dir: RQD 스캔 방향 (기본: x축)
            scan_length: 스캔 길이 (m)
            backend: 'auto', 'cuda', 'mps', 'mlx', 'cpu'
            batch_size: GPU 배치 크기 (메모리 제어)
        """
        if rqd_scanline_dir is None:
            rqd_scanline_dir = np.array([1.0, 0.0, 0.0])
        scanline_dir = rqd_scanline_dir / np.linalg.norm(rqd_scanline_dir)

        # 백엔드 선택
        if backend == "auto":
            backend = detect_backend()
        else:
            print(f"  ⚙️ 강제 백엔드: {backend}")

        # Jn, Jw, SRF (CPU — 빠름)
        print("  [1/3] Jn, Jw, SRF 할당...")
        self.fields["Jn"] = np.full((self.nx, self.ny, self.nz), self.config.Jn)
        self.fields["Jw"] = np.clip(
            self.rng.normal(
                self.config.Jw_mean, self.config.Jw_std, (self.nx, self.ny, self.nz)
            ),
            0.05,
            1.0,
        )
        self.fields["SRF"] = np.clip(
            self.rng.normal(
                self.config.SRF_mean, self.config.SRF_std, (self.nx, self.ny, self.nz)
            ),
            0.5,
            20.0,
        )

        # RQD, Jr, Ja (GPU 가속)
        print(f"  [2/3] RQD, Jr, Ja 할당 (backend={backend})...")
        t0 = time.time()

        if backend in ("cuda", "mps"):
            self._assign_torch(scanline_dir, scan_length, backend, batch_size)
        elif backend == "mlx":
            self._assign_mlx(scanline_dir, scan_length, batch_size)
        else:
            self._assign_numpy(scanline_dir, scan_length, batch_size)

        elapsed = time.time() - t0
        print(f"  [3/3] 완료! ({elapsed:.1f}초)")
        print(
            f"    RQD: mean={self.fields['RQD'].mean():.1f}, "
            f"std={self.fields['RQD'].std():.1f}"
        )
        linear_freq = self.fields.get("_joint_count", np.zeros(1))
        if isinstance(linear_freq, np.ndarray) and linear_freq.size > 1:
            print(f"    교차빈도: mean={linear_freq.mean():.2f} joints per scan")

    # ================================================================
    # PyTorch 백엔드 (CUDA / MPS)
    # ================================================================
    def _assign_torch(self, scanline_dir, scan_length, device_name, batch_size):
        """PyTorch GPU 가속 (CUDA 또는 MPS)"""
        import torch

        device = torch.device(device_name)
        print(f"    PyTorch device: {device}")

        # 절리 데이터 텐서화
        n_joints = len(self.dfn.joints)
        joint_centers = np.array([j.center for j in self.dfn.joints])  # (N, 3)
        joint_normals = np.array([j.normal for j in self.dfn.joints])  # (N, 3)
        joint_radii = np.array([j.radius for j in self.dfn.joints])  # (N,)
        joint_jr = np.array([j.Jr for j in self.dfn.joints])  # (N,)
        joint_ja = np.array([j.Ja for j in self.dfn.joints])  # (N,)

        t_centers = torch.tensor(joint_centers, dtype=torch.float32, device=device)
        t_normals = torch.tensor(joint_normals, dtype=torch.float32, device=device)
        t_radii = torch.tensor(joint_radii, dtype=torch.float32, device=device)
        t_jr = torch.tensor(joint_jr, dtype=torch.float32, device=device)
        t_ja = torch.tensor(joint_ja, dtype=torch.float32, device=device)

        t_scandir = torch.tensor(scanline_dir, dtype=torch.float32, device=device)
        half_scan = scan_length / 2.0

        # d·n for all joints
        d_dot_n = torch.matmul(t_normals, t_scandir)  # (N,)

        # 유효 절리 (평행 제외)
        valid_mask = torch.abs(d_dot_n) > 1e-8
        valid_idx = torch.where(valid_mask)[0]
        n_valid = valid_idx.shape[0]
        print(f"    유효 절리: {n_valid}/{n_joints}")

        v_centers = t_centers[valid_idx]  # (V, 3)
        v_normals = t_normals[valid_idx]  # (V, 3)
        v_radii = t_radii[valid_idx]  # (V,)
        v_jr = t_jr[valid_idx]  # (V,)
        v_ja = t_ja[valid_idx]  # (V,)
        v_d_dot_n = d_dot_n[valid_idx]  # (V,)

        # 셀 중심 좌표
        ci = (torch.arange(self.nx, device=device, dtype=torch.float32) + 0.5) * self.dx
        cj = (torch.arange(self.ny, device=device, dtype=torch.float32) + 0.5) * self.dy
        ck = (torch.arange(self.nz, device=device, dtype=torch.float32) + 0.5) * self.dz

        # 스캔라인 원점의 셀 좌표
        # origin = cell_center - half_scan * scanline_dir
        # 각 셀: (ci[i], cj[j], ck[k])
        # origin_x[i] = ci[i] - half_scan * sd[0], ...

        joint_count = torch.zeros(
            (self.nx, self.ny, self.nz), dtype=torch.float32, device=device
        )
        jr_sum = torch.zeros_like(joint_count)
        ja_sum = torch.zeros_like(joint_count)

        # 배치 처리 (절리 배치)
        n_batches = (n_valid + batch_size - 1) // batch_size
        print(f"    배치 처리: {n_batches} batches × {batch_size} joints")

        for b in range(n_batches):
            if b % max(1, n_batches // 10) == 0:
                print(f"      batch {b+1}/{n_batches}")

            b_start = b * batch_size
            b_end = min(b_start + batch_size, n_valid)
            B = b_end - b_start

            bc = v_centers[b_start:b_end]  # (B, 3)
            bn = v_normals[b_start:b_end]  # (B, 3)
            br = v_radii[b_start:b_end]  # (B,)
            b_jr = v_jr[b_start:b_end]  # (B,)
            b_ja = v_ja[b_start:b_end]  # (B,)
            b_dn = v_d_dot_n[b_start:b_end]  # (B,)

            # 모든 셀에 대해 t 계산
            # t[b, i, j, k] = n[b]·(center[b] - origin[i,j,k]) / d_dot_n[b]
            # origin[i,j,k] = (ci[i]-hs*sd[0], cj[j]-hs*sd[1], ck[k]-hs*sd[2])

            # diff = joint_center - cell_origin
            # diff_x[b,i] = bc[b,0] - (ci[i] - hs*sd[0])
            diff_x = bc[:, 0].unsqueeze(1) - (
                ci.unsqueeze(0) - half_scan * t_scandir[0]
            )  # (B, nx)
            diff_y = bc[:, 1].unsqueeze(1) - (
                cj.unsqueeze(0) - half_scan * t_scandir[1]
            )  # (B, ny)
            diff_z = bc[:, 2].unsqueeze(1) - (
                ck.unsqueeze(0) - half_scan * t_scandir[2]
            )  # (B, nz)

            # n·diff = nx*diff_x + ny*diff_y + nz*diff_z
            # 이를 4D 텐서로: (B, nx, ny, nz)
            # n_dot_diff[b,i,j,k] = bn[b,0]*diff_x[b,i] + bn[b,1]*diff_y[b,j] + bn[b,2]*diff_z[b,k]

            term_x = bn[:, 0].view(B, 1) * diff_x  # (B, nx)
            term_y = bn[:, 1].view(B, 1) * diff_y  # (B, ny)
            term_z = bn[:, 2].view(B, 1) * diff_z  # (B, nz)

            # Broadcasting: (B, nx, 1, 1) + (B, 1, ny, 1) + (B, 1, 1, nz)
            n_dot_diff = (
                term_x.view(B, self.nx, 1, 1)
                + term_y.view(B, 1, self.ny, 1)
                + term_z.view(B, 1, 1, self.nz)
            )  # (B, nx, ny, nz)

            # t = n_dot_diff / d_dot_n
            t_vals = n_dot_diff / b_dn.view(B, 1, 1, 1)  # (B, nx, ny, nz)

            # 유효 범위: 0 ≤ t ≤ scan_length
            valid_t = (t_vals >= 0) & (t_vals <= scan_length)

            # 교차점 좌표
            # p = origin + t * scandir
            # p_x[b,i,j,k] = (ci[i] - hs*sd[0]) + t * sd[0]
            origin_x = ci.unsqueeze(0) - half_scan * t_scandir[0]  # (1, nx) broadcast
            origin_y = cj.unsqueeze(0) - half_scan * t_scandir[1]
            origin_z = ck.unsqueeze(0) - half_scan * t_scandir[2]

            px = origin_x.view(1, self.nx, 1, 1) + t_vals * t_scandir[0]
            py = origin_y.view(1, 1, self.ny, 1) + t_vals * t_scandir[1]
            pz = origin_z.view(1, 1, 1, self.nz) + t_vals * t_scandir[2]

            # 디스크 반경 체크: |p - joint_center|² ≤ r²
            dist_sq = (
                (px - bc[:, 0].view(B, 1, 1, 1)) ** 2
                + (py - bc[:, 1].view(B, 1, 1, 1)) ** 2
                + (pz - bc[:, 2].view(B, 1, 1, 1)) ** 2
            )

            valid_disk = dist_sq <= (br.view(B, 1, 1, 1) ** 2)

            # 최종 교차 마스크
            hit = valid_t & valid_disk  # (B, nx, ny, nz)

            # 카운트 & 누적
            joint_count += hit.sum(dim=0).float()
            jr_sum += (hit.float() * b_jr.view(B, 1, 1, 1)).sum(dim=0)
            ja_sum += (hit.float() * b_ja.view(B, 1, 1, 1)).sum(dim=0)

        # GPU → CPU
        joint_count_np = joint_count.cpu().numpy()
        jr_sum_np = jr_sum.cpu().numpy()
        ja_sum_np = ja_sum.cpu().numpy()

        self._finalize(joint_count_np, jr_sum_np, ja_sum_np, scan_length)

    # ================================================================
    # MLX 백엔드 (Apple Silicon)
    # ================================================================
    # ================================================================
    # MLX 백엔드 (Apple Silicon)
    # ================================================================
    def _assign_mlx(self, scanline_dir, scan_length, batch_size):
        """MLX 가속 (Apple Silicon 전용)"""
        import mlx.core as mx

        print(f"    MLX backend")

        n_joints = len(self.dfn.joints)
        joint_centers = np.array([j.center for j in self.dfn.joints], dtype=np.float32)
        joint_normals = np.array([j.normal for j in self.dfn.joints], dtype=np.float32)
        joint_radii = np.array([j.radius for j in self.dfn.joints], dtype=np.float32)
        joint_jr = np.array([j.Jr for j in self.dfn.joints], dtype=np.float32)
        joint_ja = np.array([j.Ja for j in self.dfn.joints], dtype=np.float32)

        sd = scanline_dir.astype(np.float32)

        # d·n 계산 (NumPy에서 유효 절리 필터링)
        d_dot_n_np = joint_normals @ sd
        valid_mask_np = np.abs(d_dot_n_np) > 1e-8
        v_idx = np.where(valid_mask_np)[0]
        n_valid = len(v_idx)
        print(f"    유효 절리: {n_valid}/{n_joints}")

        # 유효 절리만 추출 (NumPy에서 인덱싱 후 MLX로 전송)
        vc_np = joint_centers[v_idx]
        vn_np = joint_normals[v_idx]
        vr_np = joint_radii[v_idx]
        vjr_np = joint_jr[v_idx]
        vja_np = joint_ja[v_idx]
        vdn_np = d_dot_n_np[v_idx]

        # MLX 텐서 변환
        v_centers = mx.array(vc_np)
        v_normals = mx.array(vn_np)
        v_radii = mx.array(vr_np)
        v_jr = mx.array(vjr_np)
        v_ja = mx.array(vja_np)
        v_d_dot_n = mx.array(vdn_np)
        m_scandir = mx.array(sd)

        half_scan = scan_length / 2.0

        ci = (mx.arange(self.nx).astype(mx.float32) + 0.5) * self.dx
        cj = (mx.arange(self.ny).astype(mx.float32) + 0.5) * self.dy
        ck = (mx.arange(self.nz).astype(mx.float32) + 0.5) * self.dz

        joint_count = mx.zeros((self.nx, self.ny, self.nz), dtype=mx.float32)
        jr_sum = mx.zeros((self.nx, self.ny, self.nz), dtype=mx.float32)
        ja_sum = mx.zeros((self.nx, self.ny, self.nz), dtype=mx.float32)

        n_batches = (n_valid + batch_size - 1) // batch_size
        print(f"    배치: {n_batches} × {batch_size}")

        for b in range(n_batches):
            if b % max(1, n_batches // 10) == 0:
                print(f"      batch {b+1}/{n_batches}")

            bs = b * batch_size
            be = min(bs + batch_size, n_valid)
            B = be - bs

            bc = v_centers[bs:be]  # (B, 3)
            bn = v_normals[bs:be]  # (B, 3)
            br = v_radii[bs:be]  # (B,)
            b_jr = v_jr[bs:be]  # (B,)
            b_ja = v_ja[bs:be]  # (B,)
            b_dn = v_d_dot_n[bs:be]  # (B,)

            # diff = joint_center - scan_origin
            diff_x = mx.expand_dims(bc[:, 0], 1) - mx.expand_dims(
                ci - half_scan * m_scandir[0], 0
            )  # (B, nx)
            diff_y = mx.expand_dims(bc[:, 1], 1) - mx.expand_dims(
                cj - half_scan * m_scandir[1], 0
            )  # (B, ny)
            diff_z = mx.expand_dims(bc[:, 2], 1) - mx.expand_dims(
                ck - half_scan * m_scandir[2], 0
            )  # (B, nz)

            # n·diff 각 성분
            term_x = mx.expand_dims(bn[:, 0], 1) * diff_x  # (B, nx)
            term_y = mx.expand_dims(bn[:, 1], 1) * diff_y  # (B, ny)
            term_z = mx.expand_dims(bn[:, 2], 1) * diff_z  # (B, nz)

            # Broadcasting → (B, nx, ny, nz)
            n_dot_diff = (
                mx.reshape(term_x, (B, self.nx, 1, 1))
                + mx.reshape(term_y, (B, 1, self.ny, 1))
                + mx.reshape(term_z, (B, 1, 1, self.nz))
            )

            # t 계산
            t_vals = n_dot_diff / mx.reshape(b_dn, (B, 1, 1, 1))

            # 유효 범위
            valid_t = (t_vals >= 0) & (t_vals <= scan_length)

            # 교차점 좌표
            ox = mx.reshape(ci - half_scan * m_scandir[0], (1, self.nx, 1, 1))
            oy = mx.reshape(cj - half_scan * m_scandir[1], (1, 1, self.ny, 1))
            oz = mx.reshape(ck - half_scan * m_scandir[2], (1, 1, 1, self.nz))

            px = ox + t_vals * m_scandir[0]
            py = oy + t_vals * m_scandir[1]
            pz = oz + t_vals * m_scandir[2]

            # 디스크 반경 체크
            dist_sq = (
                (px - mx.reshape(bc[:, 0], (B, 1, 1, 1))) ** 2
                + (py - mx.reshape(bc[:, 1], (B, 1, 1, 1))) ** 2
                + (pz - mx.reshape(bc[:, 2], (B, 1, 1, 1))) ** 2
            )

            valid_disk = dist_sq <= (mx.reshape(br, (B, 1, 1, 1)) ** 2)

            # 교차 마스크
            hit = valid_t & valid_disk
            hit_f = hit.astype(mx.float32)

            # 누적
            joint_count = joint_count + mx.sum(hit_f, axis=0)
            jr_sum = jr_sum + mx.sum(hit_f * mx.reshape(b_jr, (B, 1, 1, 1)), axis=0)
            ja_sum = ja_sum + mx.sum(hit_f * mx.reshape(b_ja, (B, 1, 1, 1)), axis=0)

            # MLX lazy evaluation 강제 실행 (메모리 관리)
            mx.eval(joint_count, jr_sum, ja_sum)

        # MLX → NumPy
        joint_count_np = np.array(joint_count)
        jr_sum_np = np.array(jr_sum)
        ja_sum_np = np.array(ja_sum)

        self._finalize(joint_count_np, jr_sum_np, ja_sum_np, scan_length)

    # ================================================================
    # NumPy CPU 백엔드 (최적화)
    # ================================================================
    def _assign_numpy(self, scanline_dir, scan_length, batch_size):
        """NumPy 벡터화 CPU (기존 대비 최적화)"""
        print(f"    NumPy CPU backend")

        n_joints = len(self.dfn.joints)
        joint_centers = np.array([j.center for j in self.dfn.joints], dtype=np.float32)
        joint_normals = np.array([j.normal for j in self.dfn.joints], dtype=np.float32)
        joint_radii = np.array([j.radius for j in self.dfn.joints], dtype=np.float32)
        joint_jr = np.array([j.Jr for j in self.dfn.joints], dtype=np.float32)
        joint_ja = np.array([j.Ja for j in self.dfn.joints], dtype=np.float32)

        half_scan = scan_length / 2.0
        sd = scanline_dir.astype(np.float32)

        # d·n
        d_dot_n = joint_normals @ sd
        valid = np.abs(d_dot_n) > 1e-8
        v_idx = np.where(valid)[0]
        n_valid = len(v_idx)
        print(f"    유효 절리: {n_valid}/{n_joints}")

        vc = joint_centers[v_idx]
        vn = joint_normals[v_idx]
        vr = joint_radii[v_idx]
        vjr = joint_jr[v_idx]
        vja = joint_ja[v_idx]
        vdn = d_dot_n[v_idx]

        ci = (np.arange(self.nx, dtype=np.float32) + 0.5) * self.dx
        cj = (np.arange(self.ny, dtype=np.float32) + 0.5) * self.dy
        ck = (np.arange(self.nz, dtype=np.float32) + 0.5) * self.dz

        joint_count = np.zeros((self.nx, self.ny, self.nz), dtype=np.float32)
        jr_sum = np.zeros_like(joint_count)
        ja_sum = np.zeros_like(joint_count)

        n_batches = (n_valid + batch_size - 1) // batch_size
        print(f"    배치: {n_batches} × {batch_size}")

        for b in range(n_batches):
            if b % max(1, n_batches // 5) == 0:
                print(f"      batch {b+1}/{n_batches}")

            bs = b * batch_size
            be = min(bs + batch_size, n_valid)
            B = be - bs

            bc = vc[bs:be]
            bn = vn[bs:be]
            br = vr[bs:be]
            b_jr = vjr[bs:be]
            b_ja = vja[bs:be]
            b_dn = vdn[bs:be]

            diff_x = bc[:, 0:1] - (ci[None, :] - half_scan * sd[0])
            diff_y = bc[:, 1:2] - (cj[None, :] - half_scan * sd[1])
            diff_z = bc[:, 2:3] - (ck[None, :] - half_scan * sd[2])

            term_x = bn[:, 0:1] * diff_x
            term_y = bn[:, 1:2] * diff_y
            term_z = bn[:, 2:3] * diff_z

            n_dot_diff = (
                term_x.reshape(B, self.nx, 1, 1)
                + term_y.reshape(B, 1, self.ny, 1)
                + term_z.reshape(B, 1, 1, self.nz)
            )

            t_vals = n_dot_diff / b_dn.reshape(B, 1, 1, 1)

            valid_t = (t_vals >= 0) & (t_vals <= scan_length)

            ox = (ci - half_scan * sd[0]).reshape(1, self.nx, 1, 1)
            oy = (cj - half_scan * sd[1]).reshape(1, 1, self.ny, 1)
            oz = (ck - half_scan * sd[2]).reshape(1, 1, 1, self.nz)

            px = ox + t_vals * sd[0]
            py = oy + t_vals * sd[1]
            pz = oz + t_vals * sd[2]

            dist_sq = (
                (px - bc[:, 0].reshape(B, 1, 1, 1)) ** 2
                + (py - bc[:, 1].reshape(B, 1, 1, 1)) ** 2
                + (pz - bc[:, 2].reshape(B, 1, 1, 1)) ** 2
            )

            hit = valid_t & (dist_sq <= br.reshape(B, 1, 1, 1) ** 2)

            hit_f = hit.astype(np.float32)
            joint_count += hit_f.sum(axis=0)
            jr_sum += (hit_f * b_jr.reshape(B, 1, 1, 1)).sum(axis=0)
            ja_sum += (hit_f * b_ja.reshape(B, 1, 1, 1)).sum(axis=0)

        self._finalize(joint_count, jr_sum, ja_sum, scan_length)

    # ================================================================
    # 공통 후처리
    # ================================================================
    def _finalize(
        self,
        joint_count: np.ndarray,
        jr_sum: np.ndarray,
        ja_sum: np.ndarray,
        scan_length: float,
    ):
        """RQD, Jr, Ja 필드 최종 계산"""
        # RQD (Priest-Hudson 이론식)
        linear_freq = joint_count / scan_length
        lt = linear_freq * 0.1
        self.fields["RQD"] = np.clip(100.0 * np.exp(-lt) * (lt + 1.0), 0, 100).astype(
            np.float64
        )

        # Jr, Ja (교차 절리 평균)
        has_joints = joint_count > 0
        global_jr = (
            np.mean([js.Jr_mean for js in self.config.joint_sets])
            if self.config.joint_sets
            else 1.5
        )
        global_ja = (
            np.mean([js.Ja_mean for js in self.config.joint_sets])
            if self.config.joint_sets
            else 2.0
        )

        safe_count = np.maximum(joint_count, 1)
        self.fields["Jr"] = np.where(has_joints, jr_sum / safe_count, global_jr).astype(
            np.float64
        )
        self.fields["Ja"] = np.where(has_joints, ja_sum / safe_count, global_ja).astype(
            np.float64
        )

        # 디버그용 저장
        self.fields["_joint_count"] = joint_count
