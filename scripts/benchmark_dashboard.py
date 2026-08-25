"""Small local benchmark for dashboard file-to-DataFrame reads.

This benchmark is intentionally read-only.  It compares the configured fast
reader against pandas for the largest local CSV sources.  It is a directional
measurement; production latency must additionally include EFS, callback
serialization and Plotly rendering.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.data.catalog import dashboard_data_root
from src.data.fast_io import engine_name, read_csv


def _targets(root: Path, client: str) -> list[Path]:
    base = root
    candidates = [
        base / "predictive" / "golden" / client.lower() / "motor.csv",
        base / "predictive" / "golden" / client.lower() / "transmision.csv",
        base / "telemetry" / "golden" / client.lower() / "alerts_detail_wide_with_gps.csv",
    ]
    return [path for path in candidates if path.is_file()]


def _measure(path: Path, forced_engine: str, repeats: int) -> dict:
    os.environ["DASHBOARD_FRAME_ENGINE"] = forced_engine
    timings = []
    rows = columns = 0
    for _ in range(repeats):
        start = time.perf_counter()
        frame = read_csv(path)
        timings.append((time.perf_counter() - start) * 1000)
        rows, columns = len(frame), len(frame.columns)
    return {
        "engine": engine_name(),
        "median_ms": round(statistics.median(timings), 2),
        "min_ms": round(min(timings), 2),
        "rows": rows,
        "columns": columns,
        "size_mb": round(path.stat().st_size / (1024 * 1024), 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Mounted data root")
    parser.add_argument("--client", default="CAPSTONE")
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()

    results = []
    for path in _targets(dashboard_data_root(args.root), args.client):
        engines = ["pandas"]
        # Avoid reporting a fake comparison when the optional dependency is
        # not installed in the current environment.
        try:
            import polars  # noqa: F401
            engines.append("polars")
        except ImportError:
            pass
        results.append({
            "path": str(path),
            "measurements": [_measure(path, engine, args.repeats) for engine in engines],
        })
    print(json.dumps({"client": args.client, "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
