from __future__ import annotations

import argparse
from pathlib import Path

from SmartVoyage.evaluation.adapters import execute_offline_case
from SmartVoyage.evaluation.runner import (
    compute_sha256,
    load_cases,
    run_evaluation,
    write_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SmartVoyage evaluation runner")
    parser.add_argument("--mode", choices=("offline", "integration"), required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-network", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "integration" and not args.allow_network:
        raise SystemExit("integration 模式必须显式提供 --allow-network")
    if args.mode == "integration":
        raise SystemExit("integration 执行器将在真实链路任务中启用")

    cases = load_cases(args.dataset)
    report = run_evaluation(
        cases,
        execute_offline_case,
        mode=args.mode,
        dataset_sha256=compute_sha256(args.dataset),
        dataset_path=str(args.dataset),
    )
    paths = write_report(report, args.output)
    print(paths["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
