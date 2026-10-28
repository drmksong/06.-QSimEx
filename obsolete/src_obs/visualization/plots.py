"""
Matplotlib 기반 시각화
"""

import numpy as np
import matplotlib.pyplot as plt
from typing import List, Dict

import pandas as pd
from matplotlib.cm import get_cmap


class Visualizer:
    """분석 결과 시각화"""

    @staticmethod
    def plot_comparison(comparisons: List[Dict], save_path: str = None):
        """시추공 vs 막장면 Q값 비교 4분할 그래프"""
        fig, axes = plt.subplots(2, 2, figsize=(16, 10))
        x_coords = [c['face_x_coord'] for c in comparisons]

        # (a) Q값 비교
        ax = axes[0, 0]
        ax.plot(x_coords, [c['Q_face_mean'] for c in comparisons],
                'ro-', label='Face Q', lw=2, ms=5)
        ax.plot(x_coords, [c['Q_borehole_mean'] for c in comparisons],
                'b^--', label='Borehole Q', lw=2, ms=5)
        ax.set_xlabel('Chainage (m)')
        ax.set_ylabel('Q')
        ax.set_title('Q: Borehole vs Face')
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_yscale('log')

        # (b) Q' 비교
        ax = axes[0, 1]
        ax.plot(x_coords, [c['Qp_face_mean'] for c in comparisons],
                'ro-', label="Face Q'", lw=2, ms=5)
        ax.plot(x_coords, [c['Qp_borehole_mean'] for c in comparisons],
                'b^--', label="Borehole Q'", lw=2, ms=5)
        ax.set_xlabel('Chainage (m)')
        ax.set_ylabel("Q'")
        ax.set_title("Q': Borehole vs Face")
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_yscale('log')

        # (c) 비율 바 차트
        ax = axes[1, 0]
        ratios = [c['Q_ratio'] for c in comparisons]
        colors = ['green' if 0.5 < r < 2.0 else 'red' for r in ratios]
        ax.bar(x_coords, ratios, width=3, color=colors, alpha=0.7)
        ax.axhline(1.0, color='black', lw=2, ls='--')
        ax.axhline(0.5, color='orange', lw=1, ls=':')
        ax.axhline(2.0, color='orange', lw=1, ls=':')
        ax.set_xlabel('Chainage (m)')
        ax.set_ylabel('Q Ratio (BH/Face)')
        ax.set_title('Match Ratio (Green=OK)')
        ax.grid(True, alpha=0.3)

        # (d) 산포도
        ax = axes[1, 1]
        fQ = [c['Q_face_mean'] for c in comparisons]
        bQ = [c['Q_borehole_mean'] for c in comparisons]
        ax.scatter(fQ, bQ, c='steelblue', s=50, alpha=0.7, edgecolors='white')
        lims = [max(min(fQ + bQ) * 0.5, 0.01), max(fQ + bQ) * 2]
        ax.plot(lims, lims, 'k--', lw=2, label='1:1')
        ax.set_xscale('log')
        ax.set_yscale('log')
        ax.set_xlabel('Face Q')
        ax.set_ylabel('Borehole Q')
        ax.set_title('Scatter: Face vs Borehole')
        ax.legend()
        ax.grid(True, alpha=0.3)

        plt.suptitle('Borehole vs Face Q-Value Comparison', fontsize=15, fontweight='bold')
        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.show()

    @staticmethod
    def plot_domain_slice(domain, param: str = 'Q', z_idx: int = None,
                           save_path: str = None):
        """도메인 수평 단면"""
        if z_idx is None:
            z_idx = domain.nz // 2
        if param in domain.fields:
            data = domain.fields[param][:, :, z_idx]
        elif param == 'Q':
            data = domain.Q_field[:, :, z_idx]
        else:
            data = domain.Qprime_field[:, :, z_idx]

        fig, ax = plt.subplots(figsize=(14, 5))
        im = ax.imshow(data.T, origin='lower', aspect='auto',
                       extent=[0, domain.nx * domain.dx, 0, domain.ny * domain.dy],
                       cmap='RdYlGn')
        plt.colorbar(im, ax=ax, label=param)
        ax.set_xlabel('X - Tunnel Axis (m)')
        ax.set_ylabel('Y - Transverse (m)')
        ax.set_title(f'{param} @ Z={z_idx * domain.dz:.0f}m', fontsize=14, fontweight='bold')
        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.show()

    @staticmethod
    def plot_face_detail(face_data: Dict, domain, save_path: str = None):
        """막장면 상세 2D 분포"""
        x_idx = face_data['x_idx']
        cy = domain.case.tunnel_center_y / domain.dy
        cz = domain.case.tunnel_center_z / domain.dz
        r = domain.case.tunnel_radius / domain.dy

        params = ['RQD', 'Jr', 'Ja', 'Q']
        fig, axes = plt.subplots(1, 4, figsize=(20, 5))

        for idx, param in enumerate(params):
            ax = axes[idx]
            if param in domain.fields:
                d = domain.fields[param][x_idx, :, :]
            else:
                d = domain.Q_field[x_idx, :, :]
            im = ax.imshow(d.T, origin='lower', aspect='equal',
                           cmap='viridis' if param != 'Q' else 'RdYlGn')
            plt.colorbar(im, ax=ax, shrink=0.8)
            circle = plt.Circle((cy, cz), r, fill=False, color='red', lw=2, ls='--')
            ax.add_patch(circle)
            ax.set_title(f'{param} @ x={x_idx * domain.dx:.0f}m')

        plt.suptitle(f'Face Detail @ Chainage {x_idx * domain.dx:.0f}m', fontsize=14)
        plt.tight_layout()
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches='tight')
        plt.show()

    @staticmethod
    def plot_multicase_qprime(summary_df: pd.DataFrame, face_df: pd.DataFrame,
                              save_path: str = None):
        """멀티케이스 Q' 관계 시각화.

        전체 및 케이스별로 borehole Q'와 tunnel Q'의 양의 선형관계를 확인한다.
        """
        if summary_df is None or summary_df.empty or face_df is None or face_df.empty:
            raise ValueError('summary_df and face_df must be non-empty')

        cases = list(dict.fromkeys(face_df['case_name'].tolist()))
        cmap = get_cmap('tab10')

        fig, axes = plt.subplots(2, 3, figsize=(18, 10), constrained_layout=True)
        axes = axes.flatten()

        # overall scatter
        ax = axes[0]
        x = face_df['Qp_borehole_mean'].to_numpy()
        y = face_df['Qp_face_mean'].to_numpy()
        for i, case in enumerate(cases):
            sub = face_df[face_df['case_name'] == case]
            ax.scatter(sub['Qp_borehole_mean'], sub['Qp_face_mean'], s=18, alpha=0.65,
                       color=cmap(i % 10), label=case, edgecolors='none')
        if len(x) > 1:
            slope, intercept = np.polyfit(x, y, 1)
            x_line = np.linspace(x.min(), x.max(), 100)
            ax.plot(x_line, slope * x_line + intercept, color='black', lw=2,
                    label=f'fit y={slope:.2f}x+{intercept:.2f}')
            ax.plot(x_line, x_line, color='gray', lw=1.5, ls='--', label='1:1')
        ax.set_title("Overall Q' relation")
        ax.set_xlabel("Q'_borehole")
        ax.set_ylabel("Q'_tunnel")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=8)
        x_series = pd.Series(x)
        y_series = pd.Series(y)
        ax.text(0.02, 0.98,
            f"Pearson={x_series.corr(y_series):.3f}\nSpearman={x_series.corr(y_series, method='spearman'):.3f}",
                transform=ax.transAxes, va='top', ha='left',
                bbox=dict(boxstyle='round', facecolor='white', alpha=0.8), fontsize=9)

        # per-case scatter
        for idx, case in enumerate(cases, start=1):
            ax = axes[idx]
            sub = face_df[face_df['case_name'] == case]
            x = sub['Qp_borehole_mean'].to_numpy()
            y = sub['Qp_face_mean'].to_numpy()
            ax.scatter(x, y, s=18, alpha=0.7, color=cmap((idx - 1) % 10), edgecolors='none')
            if len(x) > 1:
                slope, intercept = np.polyfit(x, y, 1)
                x_line = np.linspace(x.min(), x.max(), 100)
                ax.plot(x_line, slope * x_line + intercept, color='black', lw=1.8)
                ax.plot(x_line, x_line, color='gray', lw=1.2, ls='--')
            ax.set_title(case)
            ax.set_xlabel("Q'_borehole")
            ax.set_ylabel("Q'_tunnel")
            ax.grid(True, alpha=0.25)
            if len(x) > 1:
                x_series = pd.Series(x)
                y_series = pd.Series(y)
                ax.text(0.02, 0.98,
                    f"r={x_series.corr(y_series):.3f}\nρ={x_series.corr(y_series, method='spearman'):.3f}",
                        transform=ax.transAxes, va='top', ha='left',
                        bbox=dict(boxstyle='round', facecolor='white', alpha=0.8), fontsize=8)

        for idx in range(len(cases) + 1, len(axes)):
            axes[idx].axis('off')

        fig.suptitle("Q' Predictive Relationship: Borehole vs Tunnel", fontsize=15, fontweight='bold')
        if save_path:
            plt.savefig(save_path, dpi=160, bbox_inches='tight')
            plt.close(fig)
        else:
            plt.show()

    @staticmethod
    def plot_dfn_verification(dfn, case_config):
        """DFN 분포 검증 (Power Law + Fisher)"""
        n_sets = case_config.n_sets
        fig, axes = plt.subplots(2, max(n_sets, 1), figsize=(6 * max(n_sets, 1), 10))
        if n_sets == 1:
            axes = axes.reshape(2, 1)

        for i, js_def in enumerate(case_config.joint_sets):
            joints = dfn.joints_by_set.get(js_def.set_id, [])
            if not joints:
                continue
            radii = np.array([j.radius for j in joints])

            # 상단: Log-Log CCDF (Power Law 검증)
            ax = axes[0, i]
            sr = np.sort(radii)
            ccdf = 1.0 - np.arange(1, len(sr) + 1) / len(sr)
            sub = np.unique(np.logspace(0, np.log10(max(len(sr) - 1, 1)), 300).astype(int))
            ax.loglog(sr[sub], ccdf[sub], 'b.', ms=2, alpha=0.5, label='Generated')

            from core.joint_models import PowerLawSampler
            pl = PowerLawSampler(js_def.size_alpha, js_def.size_r_min, js_def.size_r_max)
            r_th = np.logspace(np.log10(js_def.size_r_min), np.log10(js_def.size_r_max), 200)
            ax.loglog(r_th, 1 - pl.cdf(r_th), 'r-', lw=2, label='Theory')
            ax.set_title(f'JS-{js_def.set_id}: PL(α={js_def.size_alpha})')
            ax.set_xlabel('r (m)')
            ax.set_ylabel('P(R>r)')
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3, which='both')

            # 하단: 스테레오넷 (Fisher 검증)
            ax2 = axes[1, i]
            normals = np.array([j.normal for j in joints])
            # 하반구 → 상반구 반전
            normals[normals[:, 2] < 0] *= -1
            dip = np.arccos(np.clip(normals[:, 2], 0, 1))
            bearing = np.arctan2(normals[:, 0], normals[:, 1])
            r_proj = np.sqrt(2) * np.sin(dip / 2)

            ax2.scatter(r_proj * np.sin(bearing), r_proj * np.cos(bearing), s=1, alpha=0.3)
            circle = plt.Circle((0, 0), 1, fill=False, color='black', lw=1.5)
            ax2.add_patch(circle)
            ax2.set_xlim(-1.2, 1.2)
            ax2.set_ylim(-1.2, 1.2)
            ax2.set_aspect('equal')
            ax2.set_title(f'JS-{js_def.set_id}: Fisher(κ={js_def.fisher_kappa})')

        plt.suptitle('DFN Verification: Power Law + Fisher', fontsize=14, fontweight='bold')
        plt.tight_layout()
        plt.show()