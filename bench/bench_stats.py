#!/usr/bin/env python3
import argparse
import csv
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROXY_TIME_PATTERNS = {
    "kernel_seconds": r"Elapsed Kernel Time\s*:\s*([\d.eE+-]+)\s+seconds",
    "output_seconds": r"Elapsed Output Time\s*:\s*([\d.eE+-]+)\s+seconds",
    "proxy_total_seconds": r"Elapsed TotalExe Time\s*:\s*([\d.eE+-]+)\s+seconds",
    "snapshot_host_copy_seconds": r"Snapshot Host Copy Time\s*:\s*([\d.eE+-]+)\s+seconds",
    "snapshot_file_write_seconds": r"Snapshot File Write Time\s*:\s*([\d.eE+-]+)\s+seconds",
    "in_situ_analysis_seconds": r"In Situ Statistics Compute Time\s*:\s*([\d.eE+-]+)\s+seconds",
    "in_situ_host_copy_seconds": r"In Situ Statistics Host Copy Time\s*:\s*([\d.eE+-]+)\s+seconds",
    "in_situ_statistics_write_seconds": r"In Situ Statistics File Write Time\s*:\s*([\d.eE+-]+)\s+seconds",
}
AD_HOC_TIME_PATTERNS = {
    "ad_hoc_snapshot_read_seconds": r"Ad-hoc Snapshot Read Time:\s*([\d.eE+-]+)\s+seconds",
    "ad_hoc_analysis_seconds": r"Ad-hoc Analysis Time:\s*([\d.eE+-]+)\s+seconds",
    "ad_hoc_statistics_write_seconds": r"Ad-hoc Statistics Write Time:\s*([\d.eE+-]+)\s+seconds",
    "ad_hoc_plot_seconds": r"Ad-hoc Plot Time:\s*([\d.eE+-]+)\s+seconds",
}
FIELDS = [
    "ex",
    "repetition",
    "mode",
    "kernel_seconds",
    "solver_kernel_seconds",
    "output_seconds",
    "proxy_total_seconds",
    "snapshot_host_copy_seconds",
    "snapshot_file_write_seconds",
    "in_situ_analysis_seconds",
    "in_situ_host_copy_seconds",
    "in_situ_statistics_write_seconds",
    "ad_hoc_snapshot_read_seconds",
    "ad_hoc_analysis_seconds",
    "ad_hoc_statistics_write_seconds",
    "ad_hoc_plot_seconds",
    "analysis_seconds",
    "workflow_io_seconds",
    "descriptive_statistics_seconds",
    "workflow_seconds",
    "snapshot_count",
]


def parse_times(output, patterns):
    values = {}
    for field, pattern in patterns.items():
        match = re.search(pattern, output)
        if match is None:
            raise RuntimeError(f"Could not parse {field} from semproxy output")
        values[field] = float(match.group(1))
    return values


def run_proxy(command, work_dir):
    start = time.perf_counter()
    result = subprocess.run(
        command, cwd=work_dir, text=True, capture_output=True, check=False
    )
    elapsed = time.perf_counter() - start
    if result.returncode:
        output = result.stdout + result.stderr
        raise RuntimeError(
            f"semproxy failed with exit code {result.returncode}:\n"
            + "\n".join(output.splitlines()[-40:])
        )
    return parse_times(result.stdout, PROXY_TIME_PATTERNS), elapsed


def run_case(args, semproxy, statistics_script, ex, repetition, mode):
    with tempfile.TemporaryDirectory(prefix=f"semproxy_{mode}_ex{ex}_") as temp:
        work_dir = Path(temp)
        snapshot_dir = work_dir / "snapshots"
        snapshots_enabled = mode == "ad-hoc"
        stats_enabled = mode == "in_situ"
        command = [
            str(semproxy),
            "--ex",
            str(ex),
            "--timemax",
            str(args.timemax),
            "--snap-interval",
            str(args.snap_interval),
            f"--snapshots={str(snapshots_enabled).lower()}",
            f"--stats={str(stats_enabled).lower()}",
        ]
        if snapshots_enabled:
            command.append(f"--snap-folder={snapshot_dir}")

        proxy_times, proxy_wall = run_proxy(command, work_dir)
        stats_wall = 0.0
        ad_hoc_times = {field: 0.0 for field in AD_HOC_TIME_PATTERNS}
        snapshot_count = 0

        if snapshots_enabled:
            snapshot_count = len(list(snapshot_dir.glob("snapshot_*.bin")))
            env = os.environ.copy()
            env["MPLBACKEND"] = "Agg"
            start = time.perf_counter()
            result = subprocess.run(
                [
                    sys.executable,
                    str(statistics_script),
                    "--snapshot-dir",
                    str(snapshot_dir),
                    "--no-show",
                ],
                cwd=work_dir,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            stats_wall = time.perf_counter() - start
            if result.returncode:
                output = result.stdout + result.stderr
                raise RuntimeError(
                    "descriptive_statistics.py failed with exit code "
                    f"{result.returncode}:\n"
                    + "\n".join(output.splitlines()[-40:])
                )
            ad_hoc_times = parse_times(result.stdout, AD_HOC_TIME_PATTERNS)

        analysis_seconds = (
            proxy_times["in_situ_analysis_seconds"]
            if stats_enabled
            else ad_hoc_times["ad_hoc_analysis_seconds"]
        )
        workflow_io_seconds = sum(
            proxy_times[field]
            for field in (
                "snapshot_host_copy_seconds",
                "snapshot_file_write_seconds",
                "in_situ_host_copy_seconds",
                "in_situ_statistics_write_seconds",
            )
        ) + ad_hoc_times["ad_hoc_snapshot_read_seconds"] + ad_hoc_times[
            "ad_hoc_statistics_write_seconds"
        ]

        return {
            "ex": ex,
            "repetition": repetition,
            "mode": mode,
            **proxy_times,
            **ad_hoc_times,
            "solver_kernel_seconds": max(
                0.0,
                proxy_times["kernel_seconds"]
                - proxy_times["in_situ_analysis_seconds"],
            ),
            "analysis_seconds": analysis_seconds,
            "workflow_io_seconds": workflow_io_seconds,
            "descriptive_statistics_seconds": stats_wall,
            "workflow_seconds": proxy_wall + stats_wall,
            "snapshot_count": snapshot_count,
        }


def main():
    parser = argparse.ArgumentParser(
        description="Compare in-situ and ad-hoc SEM statistics."
    )
    parser.add_argument("--ex", type=int, nargs="+", default=[50])
    parser.add_argument("--timemax", type=float, default=1.5)
    parser.add_argument("--snap-interval", type=int, default=10)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--semproxy", type=Path, default=ROOT / "build/bin/semproxy"
    )
    parser.add_argument(
        "--statistics-script",
        type=Path,
        default=ROOT / "visu/descriptive_statistics.py",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    semproxy = args.semproxy.resolve()
    statistics_script = args.statistics_script.resolve()
    if not semproxy.is_file():
        parser.error(f"semproxy executable not found: {semproxy}")
    if not statistics_script.is_file():
        parser.error(f"statistics script not found: {statistics_script}")
    if args.repetitions <= 0:
        parser.error("--repetitions must be positive")
    if any(ex <= 0 for ex in args.ex):
        parser.error("all --ex values must be positive")
    if args.snap_interval <= 0:
        parser.error("--snap-interval must be positive")

    output = args.output
    if output is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = ROOT / "bench" / f"stats_benchmark_{stamp}.csv"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    modes = ("no_stats", "in_situ", "ad-hoc")
    with output.open("w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=FIELDS)
        writer.writeheader()
        for repetition in range(1, args.repetitions + 1):
            for ex in args.ex:
                for mode in modes:
                    row = run_case(
                        args, semproxy, statistics_script, ex, repetition, mode
                    )
                    writer.writerow(row)
                    csv_file.flush()
                    print(
                        f"ex={ex} mode={mode} "
                        f"proxy={row['proxy_total_seconds']:.3f}s "
                        f"ad-hoc={row['descriptive_statistics_seconds']:.3f}s "
                        f"workflow={row['workflow_seconds']:.3f}s",
                        flush=True,
                    )
    print(f"CSV written to {output}")


if __name__ == "__main__":
    main()