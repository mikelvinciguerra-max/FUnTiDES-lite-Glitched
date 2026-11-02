import argparse
import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path
from time import perf_counter


def statistics_pressure(snapshot_files, show_plot=True):
    metadata_file = snapshot_files[0].parent / "snapshots_meta.json"
    with metadata_file.open() as file:
        num_nodes = json.load(file)["snapshot_shape"][0]
    read_start = perf_counter()
    snapshot_arrays = [
        np.fromfile(snapshot_file, dtype=np.float32)
        for snapshot_file in snapshot_files
    ]
    pressure_snapshots = np.stack(snapshot_arrays)
    snapshot_read_seconds = perf_counter() - read_start
    if pressure_snapshots.shape[1] != num_nodes:
        raise ValueError(f"Expected {num_nodes} pressure values per snapshot")

    analysis_start = perf_counter()
    node_indices = np.arange(num_nodes)
    mean_pressure = pressure_snapshots.mean(axis=0)
    min_pressure = pressure_snapshots.min(axis=0)
    max_pressure = pressure_snapshots.max(axis=0)
    median_pressure = np.median(pressure_snapshots, axis=0)
    analysis_seconds = perf_counter() - analysis_start

    output_dir = snapshot_files[0].parent.parent
    statistics = {
        "mean": mean_pressure,
        "min": min_pressure,
        "max": max_pressure,
        "median": median_pressure,
    }
    write_start = perf_counter()
    for name, values in statistics.items():
        values.astype(np.float32, copy=False).tofile(output_dir / f"pressure_{name}.bin")
    statistics_write_seconds = perf_counter() - write_start

    plot_start = perf_counter()
    plt.figure()
    plt.plot(node_indices, mean_pressure, color="blue", label="Average Pressure")
    plt.plot(node_indices, min_pressure, color="green", label="Min pressure values")
    plt.plot(node_indices, max_pressure, color="red", label="Max pressure values")
    plt.plot(node_indices, median_pressure, color="orange", label="Median pressure")
    plt.legend()
    plt.xlabel("Node index")
    plt.ylabel("Pressure (Pa)")
    plt.title("Pressure statistics per node across snapshots")
    output_file = snapshot_files[0].parent.parent / "pressure_statistics_per_node.png"
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    if show_plot:
        plt.show()
    else:
        plt.close()
    plot_seconds = perf_counter() - plot_start

    print(f"Ad-hoc Snapshot Read Time: {snapshot_read_seconds:.6f} seconds")
    print(f"Ad-hoc Analysis Time: {analysis_seconds:.6f} seconds")
    print(f"Ad-hoc Statistics Write Time: {statistics_write_seconds:.6f} seconds")
    print(f"Ad-hoc Plot Time: {plot_seconds:.6f} seconds")



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot-dir", type=Path, default=Path("../snapshots"))
    parser.add_argument("--no-show", action="store_true")
    args = parser.parse_args()

    snapshot_dir = args.snapshot_dir
    snapshot_files = sorted(snapshot_dir.glob("snapshot_*.bin"))
    if not snapshot_files:
        raise FileNotFoundError(f"No snapshots found in {snapshot_dir}")
    statistics_pressure(snapshot_files, show_plot=not args.no_show)
