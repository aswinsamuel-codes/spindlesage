"""Download the UCI AI4I 2020 Predictive Maintenance Dataset and verify its checksum.

Source, licence and expected checksum come from datasets/metadata/ai4i2020.json.
The file is written to datasets/raw/ai4i2020/ (git-ignored) unless --dest is given.

Usage:
    uv run python datasets/download_scripts/download_ai4i.py
    uv run python datasets/download_scripts/download_ai4i.py --dest /shared/data/ai4i2020

This script uses only the standard library so it can run on any cluster node.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
METADATA_PATH = REPO_ROOT / "datasets" / "metadata" / "ai4i2020.json"
DEFAULT_DEST = REPO_ROOT / "datasets" / "raw" / "ai4i2020"
USER_AGENT = "spindlesage-dataset-downloader"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_metadata(path: Path = METADATA_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fetch(url: str, timeout: float = 60.0) -> bytes:
    if not url.startswith("https://"):
        raise ValueError(f"Refusing to download over a non-HTTPS URL: {url!r}")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310 (https only)
        return response.read()


def extract_member(archive: bytes, member: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        return zf.read(member)


def verify(data: bytes, expected_sha256: str) -> None:
    actual = sha256_bytes(data)
    if actual != expected_sha256:
        raise ValueError(
            f"Checksum mismatch: expected {expected_sha256}, got {actual}. "
            "The upstream file may have changed; review it and update the metadata deliberately."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST, help="output directory")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args(argv)

    meta = load_metadata()
    file_meta = meta["file"]
    target = args.dest / file_meta["name"]

    if target.exists() and not args.force:
        try:
            verify(target.read_bytes(), file_meta["sha256"])
        except ValueError as exc:
            print(f"Existing file failed verification: {exc}", file=sys.stderr)
            return 1
        print(f"Already present and verified: {target}")
        return 0

    print(f"Downloading {meta['name']} from {meta['download_url']}")
    data = extract_member(fetch(meta["download_url"]), file_meta["archive_member"])
    try:
        verify(data, file_meta["sha256"])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    args.dest.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    print(f"Saved {len(data):,} bytes to {target} (sha256 verified)")
    print(f"Licence: {meta['license']}. Cite as: {meta['citation']}")
    print(f"Note: {meta['data_nature_note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
