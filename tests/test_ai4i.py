import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from core.ingestion.ai4i import COLUMN_MAP, load_ai4i, sha256_file
from core.ingestion.validation import validate_frame

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load_download_script():
    path = REPO_ROOT / "datasets" / "download_scripts" / "download_ai4i.py"
    spec = importlib.util.spec_from_file_location("download_ai4i", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_load_renames_and_types(synthetic_ai4i_csv):
    df = load_ai4i(synthetic_ai4i_csv)
    assert list(df.columns) == list(COLUMN_MAP.values())
    assert df["machine_failure"].dtype == "int8"
    assert set(df["product_type"]) <= {"L", "M", "H"}
    assert validate_frame(df).ok


def test_missing_file_explains_how_to_download(tmp_path):
    with pytest.raises(FileNotFoundError, match="download_ai4i.py"):
        load_ai4i(tmp_path / "nope.csv")


def test_missing_column_raises(tmp_path, synthetic_ai4i_csv):
    path = tmp_path / "broken.csv"
    pd.read_csv(synthetic_ai4i_csv, encoding="utf-8-sig").drop(columns=["Torque [Nm]"]).to_csv(
        path, index=False
    )
    with pytest.raises(ValueError, match="Torque"):
        load_ai4i(path)


def test_non_binary_target_raises(tmp_path, synthetic_ai4i_csv):
    path = tmp_path / "bad_target.csv"
    raw = pd.read_csv(synthetic_ai4i_csv, encoding="utf-8-sig")
    raw.loc[0, "Machine failure"] = 2
    raw.to_csv(path, index=False)
    with pytest.raises(ValueError, match="binary"):
        load_ai4i(path)


def test_sha256_file(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"spindlesage")
    assert sha256_file(path) == hashlib.sha256(b"spindlesage").hexdigest()


class TestDownloadScript:
    def test_metadata_is_consistent(self):
        script = _load_download_script()
        meta = script.load_metadata()
        assert meta["license"] == "CC BY 4.0"
        assert meta["data_nature"] == "synthetic"
        assert len(meta["file"]["sha256"]) == 64
        assert [c["source"] for c in meta["columns"]] == list(COLUMN_MAP)
        assert [c["name"] for c in meta["columns"]] == list(COLUMN_MAP.values())

    def test_verify_and_extract(self):
        script = _load_download_script()
        payload = b"a,b\n1,2\n"
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("data.csv", payload)
        data = script.extract_member(buffer.getvalue(), "data.csv")
        script.verify(data, hashlib.sha256(payload).hexdigest())
        with pytest.raises(ValueError, match="Checksum mismatch"):
            script.verify(data, "0" * 64)
