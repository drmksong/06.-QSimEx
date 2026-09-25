"""Run the reproducible Monte Carlo profile-exploration batch."""

import argparse
import time
from pathlib import Path

import yaml

from multi_batch_runner import MultiCaseBatchConfig, MultiCaseBatchRunner


def load_config(path: str) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    config = raw.get("profile_mc_exploration", raw)
    if not isinstance(config, dict):
        raise ValueError("profile_mc_exploration must be a mapping")
    return config


def expand_seeds(config: dict) -> list[int]:
    seed_range = config.get("seed_range")
    if not isinstance(seed_range, dict):
        raise ValueError("seed_range must define start, stop, and optional step")
    start = int(seed_range["start"])
    stop = int(seed_range["stop"])
    step = int(seed_range.get("step", 1))
    if step <= 0 or stop < start:
        raise ValueError("seed_range requires stop >= start and step > 0")
    return list(range(start, stop + 1, step))


def build_runner_config(config: dict) -> MultiCaseBatchConfig:
    case_paths = [str(path) for path in config.get("case_paths", [])]
    if not case_paths:
        raise ValueError("case_paths must not be empty")
    for path in case_paths:
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    return MultiCaseBatchConfig(
        case_paths=case_paths,
        seeds=expand_seeds(config),
        face_positions=config.get("face_positions"),
        borehole_window=int(config.get("borehole_window", 3)),
        backend=str(config.get("backend", "auto")),
        batch_size=int(config.get("batch_size", 100)),
        verbose=bool(config.get("verbose", True)),
        output_dir=str(config.get("output_dir", "results/profile_mc_exploration")),
        save_each_case=bool(config.get("save_each_case", True)),
        save_combined=bool(config.get("save_combined", True)),
        correction_mode=str(config.get("correction_mode", "pure")),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run profile-exploration Monte Carlo simulations.")
    parser.add_argument("--config", default="config/profile_mc_exploration.yml")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    runner_config = build_runner_config(config)
    total_runs = len(runner_config.case_paths) * len(runner_config.seeds)
    print(
        f"[ProfileMC] cases={len(runner_config.case_paths)} "
        f"seeds={len(runner_config.seeds)} "
        f"runs={total_runs} backend={runner_config.backend} "
        f"output={runner_config.output_dir}",
        flush=True,
    )
    print(f"[ProfileMC] 시작 시각={time.strftime('%Y-%m-%d %H:%M:%S')}", flush=True)
    MultiCaseBatchRunner(runner_config).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
