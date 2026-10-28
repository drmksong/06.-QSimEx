"""Plot the completed multi-case Q' results from combined CSV outputs."""

import argparse
from pathlib import Path

import pandas as pd

from src.visualization.plots import Visualizer


def main():
    parser = argparse.ArgumentParser(description="Plot multi-case Q' results")
    parser.add_argument('--input-dir', type=str, default='legacy_results/outputs/disposal_lowfract_curated')
    parser.add_argument('--save-path', type=str, default=None)
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    summary_path = input_dir / 'all_cases_summary_rows.csv'
    face_path = input_dir / 'all_cases_face_rows.csv'

    if not summary_path.exists() or not face_path.exists():
        raise FileNotFoundError(f'Missing combined CSVs under {input_dir}')

    summary_df = pd.read_csv(summary_path)
    face_df = pd.read_csv(face_path)
    Visualizer.plot_multicase_qprime(summary_df, face_df, save_path=args.save_path)


if __name__ == '__main__':
    main()