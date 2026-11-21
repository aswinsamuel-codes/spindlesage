"""Generate simulated CNC cell telemetry to CSV (SYNTHETIC DATA).

Example:
    uv run python -m integrations.simulator --days 1 --machines 3 --faults 4 \
        --out data/sim/cell.csv
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from integrations.simulator.cnc import SimulationConfig, simulate_cell


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulate a CNC cell (synthetic data)")
    parser.add_argument("--out", type=Path, required=True, help="CSV output path")
    parser.add_argument("--days", type=float, default=1.0)
    parser.add_argument("--machines", type=int, default=3)
    parser.add_argument("--faults", type=int, default=0, help="faults per machine")
    parser.add_argument("--interval", type=float, default=30.0, help="sample interval, seconds")
    parser.add_argument("--start", default="2026-01-05T00:00:00+00:00", help="ISO start time")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    start = datetime.fromisoformat(args.start)
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    result = simulate_cell(
        SimulationConfig(
            n_machines=args.machines,
            start=start,
            duration=timedelta(days=args.days),
            sample_interval=timedelta(seconds=args.interval),
            faults_per_machine=args.faults,
            seed=args.seed,
        )
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    result.readings.to_csv(args.out, index=False)
    events_path = args.out.with_suffix(".events.json")
    events_path.write_text(
        json.dumps(
            {"data_nature": "synthetic", "events": [e.to_dict() for e in result.events]}, indent=2
        ),
        "utf-8",
    )
    print(f"Wrote {len(result.readings):,} synthetic readings to {args.out}")
    print(f"Wrote {len(result.events)} fault events to {events_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
