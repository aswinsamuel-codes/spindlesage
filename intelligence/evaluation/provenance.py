"""Run provenance shared by all experiments: environment, git revision, result files.

Every results.json records where and how it was produced, so runs from the
laptop and from different cluster nodes can be compared and traced.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess  # nosec B404 (used only to read the git revision)
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

import numpy as np

TRACKED_PACKAGES: tuple[str, ...] = ("numpy", "pandas", "scikit-learn", "xgboost", "pydantic")


def git_revision() -> dict:
    def run(*args: str) -> str:
        # Fixed "git" command with constant arguments and no shell; resolved via PATH.
        return subprocess.run(  # nosec B603 B607
            ["git", *args], capture_output=True, text=True, check=True, timeout=10
        ).stdout.strip()

    try:
        return {"commit": run("rev-parse", "HEAD"), "dirty": bool(run("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "dirty": None}


def environment() -> dict:
    versions = {}
    for package in TRACKED_PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "host": platform.node(),
        "cpu_count": os.cpu_count(),
        "packages": versions,
        "git": git_revision(),
    }


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def json_default(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Not JSON serialisable: {type(value).__name__}")


def write_run(results: dict, output_dir: Path, label: str, summary_markdown: str) -> Path:
    """Write results.json and summary.md into a new timestamped run directory."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(output_dir) / f"{stamp}_{label}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results.json").write_text(
        json.dumps(results, indent=2, default=json_default), "utf-8"
    )
    (run_dir / "summary.md").write_text(summary_markdown, "utf-8")
    return run_dir
