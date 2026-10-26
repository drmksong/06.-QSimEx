"""Enumerate the user-approved, endpoint-discretized Q-prime score grid.

Source: Specification/q-handbook_2025_english_final.pdf, printed pp. 53-55
(PDF pp. 57-59), appendix tables 1-4. Range endpoints are the selected
discretization, not a claim that intermediate ratings are forbidden by NGI.
Jn portal/intersection multipliers and the Jr spacing increment are excluded.
All numeric Cartesian combinations are included, without contact-condition
filtering. Counts describe this grid, not geological occurrence probabilities.
This standalone analysis does not change the DFN campaign or its Q-prime model.
"""

from __future__ import annotations

import argparse
import csv
from bisect import bisect_left
from collections import Counter
from fractions import Fraction
from itertools import product
from pathlib import Path
from typing import Iterable

RQD_VALUES = tuple(range(0, 101, 2))
JN_VALUES = tuple(map(Fraction, ("0.5", "1", "2", "3", "4", "6", "9", "12", "15", "20")))
JR_VALUES = tuple(map(Fraction, ("0.5", "1", "1.5", "2", "3", "4")))
JA_VALUES = tuple(map(Fraction, ("0.75", "1", "2", "3", "4", "6", "8", "10", "12", "13", "20")))


def enumerate_scores() -> Iterable[tuple[int, int, Fraction, Fraction, Fraction, Fraction]]:
    for raw_rqd, jn, jr, ja in product(RQD_VALUES, JN_VALUES, JR_VALUES, JA_VALUES):
        calculation_rqd = max(raw_rqd, 10)
        qprime = Fraction(calculation_rqd) * jr / (jn * ja)
        yield raw_rqd, calculation_rqd, jn, jr, ja, qprime


def quantile(values: list[Fraction], probability: Fraction) -> Fraction:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = position.numerator // position.denominator
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _write_csv(path: Path, header: tuple[str, ...], rows: Iterable[Iterable[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)


def write_inverse_tables(
    output_dir: Path,
    rows: list[tuple[int, int, Fraction, Fraction, Fraction, Fraction]],
    primary_edges: tuple[float, ...],
) -> None:
    grouped: dict[int, list[tuple[int, int, Fraction, Fraction, Fraction, Fraction]]] = {
        index: [] for index in range(len(primary_edges))
    }
    for row in rows:
        index = bisect_left(primary_edges, float(row[-1])) - 1
        if not 0 <= index < len(primary_edges):
            raise RuntimeError("Inverse lookup encountered an invalid Q-prime bin")
        grouped[index].append(row)

    joint_rows = []
    summary_rows = []
    marginal_rows = []
    required_rows = []
    factor_grids = (
        ("rqd_raw", 0, RQD_VALUES),
        ("rqd_calculation", 1, tuple(range(10, 101, 2))),
        ("jn", 2, JN_VALUES),
        ("jr", 3, JR_VALUES),
        ("ja", 4, JA_VALUES),
    )
    for index, members in grouped.items():
        label = str(index + 1) if index < len(primary_edges) - 1 else "overflow"
        lower = primary_edges[index]
        upper: float | str = (
            primary_edges[index + 1] if index < len(primary_edges) - 1 else ""
        )
        effective_members = [row for row in members if row[0] >= 10]
        joint_rows.extend(
            (label, raw, calculation, float(jn), float(jr), float(ja), float(qp), str(qp))
            for raw, calculation, jn, jr, ja, qp in members
        )
        summary: list[object] = [
            label, lower, upper, len(members), len(effective_members),
            len({row[-1] for row in members}),
            len({row[2:5] for row in members}),
            min((row[0] for row in members), default=""),
            max((row[0] for row in members), default=""),
        ]
        for factor, column, grid in factor_grids:
            raw_counts = Counter(row[column] for row in members)
            effective_counts = Counter(row[column] for row in effective_members)
            summary.append(";".join(f"{float(value):g}" for value in grid if raw_counts[value]))
            for value in grid:
                marginal_rows.append((
                    label, factor, float(value), raw_counts[value],
                    len(members), raw_counts[value] / len(members) if members else "",
                    effective_counts[value], len(effective_members),
                    effective_counts[value] / len(effective_members) if effective_members else "",
                ))
        summary_rows.append(summary)

        rqd_by_scores: dict[tuple[Fraction, Fraction, Fraction], list[int]] = {}
        for raw, _, jn, jr, ja, _ in members:
            rqd_by_scores.setdefault((jn, jr, ja), []).append(raw)
        for jn, jr, ja in product(JN_VALUES, JR_VALUES, JA_VALUES):
            raw_values = rqd_by_scores.get((jn, jr, ja), [])
            calculation_values = sorted({max(value, 10) for value in raw_values})
            required_rows.append((
                label, lower, upper, float(jn), float(jr), float(ja),
                bool(raw_values), len(raw_values), len(calculation_values),
                min(raw_values) if raw_values else "",
                max(raw_values) if raw_values else "",
                ";".join(map(str, raw_values)),
                ";".join(map(str, calculation_values)),
            ))

    if len(joint_rows) != len(rows) or sum(len(members) for members in grouped.values()) != len(rows):
        raise RuntimeError("Inverse tables do not partition the full combination grid")
    _write_csv(
        output_dir / "qprime_bin_combinations.csv",
        ("bin", "rqd_raw", "rqd_calculation", "jn", "jr", "ja", "qprime", "qprime_exact"),
        joint_rows,
    )
    _write_csv(
        output_dir / "qprime_bin_signature_summary.csv",
        ("bin", "lower_exclusive", "upper_inclusive", "raw_grid_count",
         "calculation_grid_count", "unique_qprime_count", "reachable_score_triples",
         "raw_rqd_min", "raw_rqd_max", "rqd_raw_values",
         "rqd_calculation_values", "jn_values", "jr_values", "ja_values"),
        summary_rows,
    )
    _write_csv(
        output_dir / "qprime_bin_factor_distribution.csv",
        ("bin", "factor", "value", "raw_grid_count", "raw_bin_total",
         "raw_fraction_within_bin", "calculation_grid_count", "calculation_bin_total",
         "calculation_fraction_within_bin"),
        marginal_rows,
    )
    _write_csv(
        output_dir / "qprime_bin_required_rqd.csv",
        ("bin", "lower_exclusive", "upper_inclusive", "jn", "jr", "ja",
         "reachable_on_rqd_grid", "raw_rqd_count", "calculation_rqd_count",
         "raw_rqd_min", "raw_rqd_max", "raw_rqd_values", "calculation_rqd_values"),
        required_rows,
    )


def generate(output_dir: Path) -> dict[str, int | float]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    rows = list(enumerate_scores())
    per_rqd: dict[int, list[Fraction]] = {rqd: [] for rqd in RQD_VALUES}
    all_counts: Counter[Fraction] = Counter()
    effective_counts: Counter[Fraction] = Counter()
    for raw_rqd, _, _, _, _, qprime in rows:
        per_rqd[raw_rqd].append(qprime)
        all_counts[qprime] += 1
        if raw_rqd >= 10:
            effective_counts[qprime] += 1
    combinations_per_rqd = len(JN_VALUES) * len(JR_VALUES) * len(JA_VALUES)
    expected = len(RQD_VALUES) * combinations_per_rqd
    if len(rows) != expected or any(len(values) != combinations_per_rqd for values in per_rqd.values()):
        raise RuntimeError("Enumeration does not cover the complete approved Cartesian grid")
    if sum(all_counts.values()) != expected or sum(effective_counts.values()) != 46 * combinations_per_rqd:
        raise RuntimeError("Distribution counts do not reconcile with the enumerated grid")
    if min(all_counts) != Fraction(1, 80) or max(all_counts) != Fraction(3200, 3):
        raise RuntimeError("Q-prime extrema do not match the approved rating bounds")
    if any(per_rqd[rqd] != per_rqd[10] for rqd in range(0, 10, 2)):
        raise RuntimeError("RQD floor was not applied consistently")

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(
        output_dir / "qprime_combinations.csv",
        ("rqd_raw", "rqd_calculation", "jn", "jr", "ja", "qprime", "qprime_exact"),
        (
            (raw, calculation, float(jn), float(jr), float(ja), float(qp), str(qp))
            for raw, calculation, jn, jr, ja, qp in rows
        ),
    )
    _write_csv(
        output_dir / "qprime_value_distribution.csv",
        ("qprime", "qprime_exact", "raw_grid_count", "calculation_grid_count"),
        (
            (float(qp), str(qp), all_counts[qp], effective_counts[qp])
            for qp in sorted(all_counts)
        ),
    )
    summary_rows = []
    for raw_rqd, values in per_rqd.items():
        summary_rows.append((
            raw_rqd, max(raw_rqd, 10), len(values), len(set(values)),
            float(min(values)),
            float(quantile(values, Fraction(1, 20))),
            float(quantile(values, Fraction(1, 4))),
            float(quantile(values, Fraction(1, 2))),
            float(quantile(values, Fraction(3, 4))),
            float(quantile(values, Fraction(19, 20))),
            float(max(values)), float(sum(values) / len(values)),
        ))
    _write_csv(
        output_dir / "qprime_by_rqd.csv",
        ("rqd_raw", "rqd_calculation", "combination_count", "unique_qprime_count",
         "min", "p05", "p25", "median", "p75", "p95", "max", "mean"),
        summary_rows,
    )

    edges = np.geomspace(float(min(all_counts)), float(max(all_counts)), 41)
    edges[0] = np.nextafter(edges[0], -np.inf)
    edges[-1] = np.nextafter(edges[-1], np.inf)
    qvalues = np.array([float(qp) for qp in sorted(all_counts)])
    raw_weights = np.array([all_counts[qp] for qp in sorted(all_counts)])
    effective_weights = np.array([effective_counts[qp] for qp in sorted(all_counts)])
    raw_hist, _ = np.histogram(qvalues, bins=edges, weights=raw_weights)
    effective_hist, _ = np.histogram(qvalues, bins=edges, weights=effective_weights)
    if int(raw_hist.sum()) != expected or int(effective_hist.sum()) != sum(effective_counts.values()):
        raise RuntimeError("Histogram omitted enumerated values")
    _write_csv(
        output_dir / "qprime_histogram.csv",
        ("bin_lower_inclusive", "bin_upper", "upper_inclusive", "raw_grid_count",
         "calculation_grid_count"),
        (
            (float(lower), float(upper), index == len(raw_hist) - 1, int(raw), int(effective))
            for index, (lower, upper, raw, effective) in enumerate(
                zip(edges[:-1], edges[1:], raw_hist, effective_hist)
            )
        ),
    )

    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    axes[0, 0].stairs(raw_hist / raw_weights.sum() * 100, edges, label="Raw RQD grid (51 levels)")
    axes[0, 0].stairs(effective_hist / effective_weights.sum() * 100, edges, label="Calculation RQD grid (46 levels)")
    axes[0, 0].set(xscale="log", xlabel="Q-prime", ylabel="Grid combinations (%)", title="40 log-spaced bins")
    axes[0, 0].legend(fontsize=8)
    axes[0, 1].plot(qvalues, np.cumsum(raw_weights) / raw_weights.sum(), label="Raw RQD grid")
    axes[0, 1].plot(qvalues, np.cumsum(effective_weights) / effective_weights.sum(), label="Calculation RQD grid")
    axes[0, 1].set(xscale="log", xlabel="Q-prime", ylabel="Cumulative combination fraction", title="Cumulative distribution")
    axes[0, 1].legend(fontsize=8)
    summaries = np.array(summary_rows, dtype=float)
    axes[1, 0].fill_between(summaries[:, 0], summaries[:, 4], summaries[:, 10], alpha=0.15, label="Min-max")
    axes[1, 0].fill_between(summaries[:, 0], summaries[:, 5], summaries[:, 9], alpha=0.25, label="P05-P95")
    axes[1, 0].plot(summaries[:, 0], summaries[:, 7], label="Median")
    axes[1, 0].set(yscale="log", xlabel="Raw RQD", ylabel="Q-prime", title="Distribution at each RQD")
    axes[1, 0].legend(fontsize=8)
    primary_edges = np.geomspace(0.1, 400.0, 11)
    primary_edges[0] = 0.0
    primary_index = np.searchsorted(primary_edges, qvalues, side="left") - 1
    primary_counts = [
        int(raw_weights[primary_index == index].sum()) for index in range(10)
    ]
    overflow = int(raw_weights[qvalues > 400].sum())
    if sum(primary_counts) + overflow != expected:
        raise RuntimeError("Campaign-grid counts do not reconcile")
    write_inverse_tables(output_dir, rows, tuple(float(edge) for edge in primary_edges))
    _write_csv(
        output_dir / "qprime_campaign_bins.csv",
        ("bin", "lower_exclusive", "upper_inclusive", "raw_grid_count", "unique_qprime_count"),
        [
            (index + 1, float(primary_edges[index]), float(primary_edges[index + 1]),
             count, int(np.count_nonzero(primary_index == index)))
            for index, count in enumerate(primary_counts)
        ] + [("overflow", 400, "", overflow, int(np.count_nonzero(qvalues > 400)))],
    )
    axes[1, 1].bar([str(i) for i in range(1, 11)] + [">400"], primary_counts + [overflow])
    axes[1, 1].set(xlabel="Existing campaign bin (1-based)", ylabel="Raw grid combinations", title="Existing 10-bin grid + overflow")
    for axis in axes.flat:
        axis.grid(True, alpha=0.2)
    fig.suptitle(
        "Q-prime = max(RQD, 10) * Jr / (Jn * Ja)\n"
        "NGI 2025 base ratings; endpoint grid; unrestricted numeric combinations",
        fontsize=13,
    )
    fig.supxlabel("Enumeration frequencies are not geological probabilities. Conditional rating corrections excluded.", fontsize=9)
    fig.savefig(output_dir / "qprime_distribution.png", dpi=180)
    plt.close(fig)
    return {
        "raw_grid_rows": expected,
        "calculation_grid_rows": sum(effective_counts.values()),
        "combinations_per_rqd": combinations_per_rqd,
        "unique_qprime_values": len(all_counts),
        "qprime_min": float(min(all_counts)),
        "qprime_max": float(max(all_counts)),
        "median_raw_grid": float(quantile([row[-1] for row in rows], Fraction(1, 2))),
        "campaign_bins_observed": sum(count > 0 for count in primary_counts),
        "above_400_rows": overflow,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    result = generate(args.output_dir)
    for key, value in result.items():
        print(f"{key}: {value}")
    print(f"output_dir: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
