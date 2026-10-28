#!/usr/bin/env python3
"""
DFN 분포 검증 스크립트
- Power Law (멱법칙) 크기 분포 검증
- Fisher 방향 분포 검증
- κ 추정 검증
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import matplotlib.pyplot as plt

from src.core.joint_models import PowerLawSampler, FisherDistribution


def verify_power_law():
    """Power Law 분포 검증"""
    print("\n[1] Power Law (멱법칙) 검증")
    print("─" * 40)

    fig, axes = plt.subplots(2, 3, figsize=(18, 10))
    rng = np.random.RandomState(42)

    params = [
        (2.0, 0.5, 20), (2.5, 0.5, 20), (3.0, 0.5, 20),
        (3.5, 0.5, 20), (4.0, 0.5, 20), (3.0, 0.2, 30),
    ]

    for idx, (alpha, rmin, rmax) in enumerate(params):
        ax = axes[idx // 3, idx % 3]
        pl = PowerLawSampler(alpha, rmin, rmax)
        samples = pl.sample(50000, rng)

        sorted_r = np.sort(samples)
        ccdf = 1.0 - np.arange(1, len(sorted_r) + 1) / len(sorted_r)
        sub = np.unique(np.logspace(0, np.log10(len(sorted_r) - 1), 300).astype(int))
        ax.loglog(sorted_r[sub], ccdf[sub], 'b.', ms=2, alpha=0.5, label='Generated')

        r_th = np.logspace(np.log10(rmin), np.log10(rmax), 200)
        ax.loglog(r_th, 1 - pl.cdf(r_th), 'r-', lw=2, label='Theory')

        emp_mean = samples.mean()
        th_mean = pl.mean()
        ax.set_title(f'α={alpha}, r=[{rmin},{rmax}]\nE[r]: {emp_mean:.3f} vs {th_mean:.3f}')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3, which='both')

        print(f"  α={alpha}: E[r] empirical={emp_mean:.3f}, theory={th_mean:.3f} "
              f"({'✅' if abs(emp_mean - th_mean) / th_mean < 0.05 else '⚠️'})")

    plt.suptitle('Power Law CCDF Verification', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('legacy_results/output/output_verify_powerlaw.png', dpi=150, bbox_inches='tight')
    plt.show()
    print("  → output_verify_powerlaw.png 저장")


def verify_fisher():
    """Fisher 분포 검증"""
    print("\n[2] Fisher 분포 검증")
    print("─" * 40)

    fig, axes = plt.subplots(2, 4, figsize=(18, 8))
    rng = np.random.RandomState(42)
    mean_vec = np.array([0, 0, 1])
    kappas = [5, 10, 30, 100]

    for i, kappa in enumerate(kappas):
        samples = FisherDistribution.sample(mean_vec, kappa, 5000, rng)
        cos_a = np.clip(samples @ mean_vec, -1, 1)
        angles = np.degrees(np.arccos(cos_a))

        # 히스토그램
        ax = axes[0, i]
        ax.hist(angles, bins=40, density=True, alpha=0.7, color='steelblue')
        std = angles.std()
        ax.set_title(f'κ={kappa}, σ={std:.1f}°')
        ax.set_xlabel('Angle from mean (°)')

        # 스테레오넷
        ax2 = axes[1, i]
        plot_v = samples.copy()
        plot_v[plot_v[:, 2] < 0] *= -1
        dip = np.arccos(np.clip(plot_v[:, 2], 0, 1))
        bearing = np.arctan2(plot_v[:, 0], plot_v[:, 1])
        r_proj = np.sqrt(2) * np.sin(dip / 2)
        ax2.scatter(r_proj * np.sin(bearing), r_proj * np.cos(bearing), s=1, alpha=0.3)
        circle = plt.Circle((0, 0), 1, fill=False, color='black', lw=1.5)
        ax2.add_patch(circle)
        ax2.set_xlim(-1.2, 1.2)
        ax2.set_ylim(-1.2, 1.2)
        ax2.set_aspect('equal')
        ax2.set_title(f'Stereonet κ={kappa}')

        print(f"  κ={kappa}: σ_measured={std:.1f}°")

    plt.suptitle('Fisher Distribution Verification', fontsize=14, fontweight='bold')
    plt.tight_layout()
    plt.savefig('legacy_results/output/output_verify_fisher.png', dpi=150, bbox_inches='tight')
    plt.show()
    print("  → output_verify_fisher.png 저장")


def verify_kappa_estimation():
    """κ 추정 검증"""
    print("\n[3] Fisher κ 추정 검증")
    print("─" * 40)
    print(f"  {'κ_true':>10} │ {'κ_est':>10} │ {'σ_theory':>10} │ {'σ_meas':>10} │ {'Status':>8}")
    print(f"  {'─'*10} │ {'─'*10} │ {'─'*10} │ {'─'*10} │ {'─'*8}")

    rng = np.random.RandomState(42)
    mean_vec = np.array([0, 0, 1])

    for k_true in [5, 10, 20, 50, 100, 200]:
        samples = FisherDistribution.sample(mean_vec, k_true, 2000, rng)
        k_est = FisherDistribution.estimate_kappa(samples)

        cos_a = np.clip(samples @ mean_vec, -1, 1)
        sigma_meas = np.degrees(np.std(np.arccos(cos_a)))
        sigma_theory = FisherDistribution.kappa_to_angular_std(k_true)

        err = abs(k_est - k_true) / k_true
        status = "✅" if err < 0.20 else "⚠️"
        print(f"  {k_true:>10} │ {k_est:>10.1f} │ {sigma_theory:>10.1f}° │ "
              f"{sigma_meas:>10.1f}° │ {status:>8}")


def verify_dfn_integration():
    """DFN 통합 검증"""
    print("\n[4] DFN 통합 검증")
    print("─" * 40)

    from core.case_library import CaseLibrary
    from core.domain import RockDomain
    from visualization.plots import Visualizer

    case = CaseLibrary.case_granite_2sets()
    case.domain_size = (50, 25, 25)  # 작은 도메인으로 빠른 테스트
    case.seed = 42

    domain = RockDomain(case)
    domain.generate(verbose=True)

    print(f"\n  DFN 통계:")
    stats = domain.dfn.statistics()
    for sid, s in stats['by_set'].items():
        print(f"    Set {sid}: N={s['count']}, "
              f"r_mean={s['radius_mean']:.2f}m, "
              f"r_range=[{s['radius_min']:.2f}, {s['radius_max']:.2f}]m")

    Visualizer.plot_dfn_verification(domain.dfn, case.joint_config)


if __name__ == '__main__':
    os.makedirs('output', exist_ok=True)

    print("=" * 60)
    print("  Q-Rock Simulator — 분포 검증")
    print("=" * 60)

    verify_power_law()
    verify_fisher()
    verify_kappa_estimation()
    verify_dfn_integration()

    print("\n✅ 전체 검증 완료!")