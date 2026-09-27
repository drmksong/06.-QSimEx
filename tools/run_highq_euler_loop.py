"""Run a bounded, response-driven high-Q density Euler loop."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path

import yaml

TARGET_LOW = 76.14615754863519
TARGET_HIGH = 174.5235314204193
TARGET_MID = (TARGET_LOW + TARGET_HIGH) / 2.0


def summarize_csv(path: Path) -> dict:
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
    if not rows:
        raise ValueError(f"no rows in {path}")
    q_values = [float(row["Qp_bh_mean"]) for row in rows]
    rqd_values = [float(row["RQD_bh_mean"]) for row in rows]
    return {
        "n_rows": len(rows),
        "qprime_mean": sum(q_values) / len(q_values),
        "qprime_min": min(q_values),
        "qprime_max": max(q_values),
        "rqd_mean": sum(rqd_values) / len(rqd_values),
        "in_target": TARGET_LOW <= sum(q_values) / len(q_values) <= TARGET_HIGH,
    }


def next_density_scale(previous: dict, current: dict) -> float:
    """Estimate one damped log-density Euler step from two responses."""
    previous_q = float(previous["qprime_mean"])
    current_q = float(current["qprime_mean"])
    previous_p32 = float(previous["total_p32"])
    current_p32 = float(current["total_p32"])
    if current_q == previous_q or current_p32 == previous_p32:
        return 2.0 if current_q > TARGET_HIGH else 0.5
    slope = (current_q - previous_q) / (
        math.log10(current_p32) - math.log10(previous_p32)
    )
    if not math.isfinite(slope) or slope == 0.0:
        return 2.0 if current_q > TARGET_HIGH else 0.5
    desired_log_step = (TARGET_MID - current_q) / slope
    damped_log_step = max(-math.log10(2.0), min(math.log10(2.0), 0.5 * desired_log_step))
    return 10.0 ** damped_log_step


def build_next_case(case: dict, scale: float, iteration: int) -> dict:
    updated = yaml.safe_load(yaml.safe_dump(case, sort_keys=False))
    for joint_set in updated["joint_sets"]:
        joint_set["P32"] = float(joint_set["P32"]) * scale
    updated["name"] = f"{case['name']}__iter{iteration:03d}"
    updated.setdefault("tags", {})
    updated["tags"].update(
        {
            "euler_loop_iteration": iteration,
            "euler_density_scale": scale,
            "euler_target_interval": [TARGET_LOW, TARGET_HIGH],
        }
    )
    return updated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", default="config/profile_highq_euler_round_015.yml")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--screening-seed", type=int, default=333)
    parser.add_argument("--output-root", default="results/profile_mc_highq_euler_round_015")
    args = parser.parse_args(argv)
    if args.iterations <= 0:
        raise ValueError("iterations must be positive")

    repo_root = Path.cwd()
    base_config = yaml.safe_load(Path(args.base_config).read_text(encoding="utf-8"))
    source_case_path = Path(base_config["profile_mc_exploration"]["case_paths"][0])
    current_case = yaml.safe_load(source_case_path.read_text(encoding="utf-8"))
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    history = []

    for iteration in range(args.iterations):
        iteration_dir = output_root / f"iteration_{iteration:03d}"
        if iteration_dir.exists():
            raise FileExistsError(f"refusing to overwrite {iteration_dir}")
        iteration_dir.mkdir(parents=True)
        case_path = iteration_dir / f"{current_case['name']}.yaml"
        current_case["seed"] = args.screening_seed
        case_path.write_text(
            yaml.safe_dump(current_case, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        config = dict(base_config)
        profile = dict(config["profile_mc_exploration"])
        profile["case_paths"] = [str(case_path)]
        profile["seed_range"] = {"start": args.screening_seed, "stop": args.screening_seed, "step": 1}
        profile["output_dir"] = str(iteration_dir / "simulation")
        config["profile_mc_exploration"] = profile
        config_path = iteration_dir / "config.yml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

        subprocess.run(
            [sys.executable, "run_profile_mc.py", "--config", str(config_path)],
            cwd=repo_root,
            check=True,
        )
        csv_path = iteration_dir / "simulation" / "all_cases_borehole_rows.csv"
        summary = summarize_csv(csv_path)
        summary.update(
            {
                "iteration": iteration,
                "case_path": str(case_path),
                "total_p32": sum(float(item["P32"]) for item in current_case["joint_sets"]),
            }
        )
        history.append(summary)
        if summary["in_target"]:
            break
        if iteration + 1 >= args.iterations:
            break
        previous = history[-2] if len(history) >= 2 else history[-1]
        scale = 2.0
        if len(history) >= 2:
            scale = next_density_scale(previous, summary)
        current_case = build_next_case(current_case, scale, iteration + 1)

    (output_root / "loop_manifest.json").write_text(
        json.dumps(
            {
                "target_interval": [TARGET_LOW, TARGET_HIGH],
                "iterations_requested": args.iterations,
                "iterations_completed": len(history),
                "history": history,
                "update_method": "bounded_explicit_euler_style_log_density",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(history, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
