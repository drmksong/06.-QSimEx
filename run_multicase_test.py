"""
Curated multi-case runner for disposal-relevant, low-fracture conditions.

Selection intent:
- keep fracture intensity low to moderate (exclude obviously high-density rejects)
- vary orientation regime
- vary number of joint sets (1, 2, 3)
"""

from multi_batch_runner import MultiCaseBatchConfig, MultiCaseBatchRunner


def main():
    case_paths = [
        # 1-set, low density
        "cases/scenario_03_sparse_large.yaml",
        "cases/scenario_07_isotropic.yaml",

        # 2-set, low-to-moderate density with directional contrast
        "cases/scenario_05_orthogonal_two_sets.yaml",
        "cases/scenario_10_fieldlike.yaml",

        # 3-set, moderate density (boundary check for applicability)
        "cases/scenario_06_layered_density.yaml",
    ]

    config = MultiCaseBatchConfig(
        case_paths=case_paths,
        seeds=list(range(40, 60)),
        face_positions=[10, 20, 30],
        borehole_window=3,
        backend="auto",
        batch_size=100,
        verbose=True,
        output_dir="legacy_results/outputs/disposal_lowfract_curated",
        save_each_case=True,
        save_combined=True,
        correction_mode="pure",
    )

    runner = MultiCaseBatchRunner(config)
    result = runner.run()

    print("\n[SMOKE] face rows count:", len(result.face_rows))
    print("[SMOKE] borehole rows count:", len(result.borehole_rows))
    print("[SMOKE] summary rows count:", len(result.summary_rows))


if __name__ == "__main__":
    main()
