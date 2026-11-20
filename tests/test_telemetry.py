from datetime import datetime, timedelta

import pandas as pd
import pytest
from pydantic import ValidationError

from core.ingestion.validation import (
    OperatingEnvelope,
    Range,
    Severity,
    validate_frame,
    validate_reading,
)
from core.telemetry.schema import SENSOR_FIELDS, CncTelemetryReading


def _with(reading: CncTelemetryReading, **changes) -> CncTelemetryReading:
    return CncTelemetryReading(**{**reading.model_dump(), **changes})


class TestSchema:
    def test_valid_reading(self, reading):
        assert reading.machine_id == "cnc-sim-01"

    @pytest.mark.parametrize(
        "field, value",
        [
            ("air_temperature_k", 0.0),
            ("air_temperature_k", -5.0),
            ("torque_nm", -1.0),
            ("rotational_speed_rpm", float("nan")),
            ("tool_wear_min", float("inf")),
            ("product_type", "X"),
            ("machine_id", ""),
        ],
    )
    def test_rejects_impossible_values(self, reading, field, value):
        with pytest.raises(ValidationError):
            _with(reading, **{field: value})

    def test_rejects_naive_timestamp(self, reading):
        with pytest.raises(ValidationError):
            _with(reading, timestamp=datetime(2026, 1, 1, 12, 0))

    def test_rejects_unknown_fields(self, reading):
        with pytest.raises(ValidationError):
            CncTelemetryReading(**reading.model_dump(), spindle_vibration=1.0)


class TestValidateReading:
    def test_normal_reading_has_no_issues(self, reading):
        result = validate_reading(reading, now=reading.timestamp)
        assert result.ok
        assert result.issues == ()

    def test_outside_envelope_is_warning_not_error(self, reading):
        result = validate_reading(_with(reading, torque_nm=120.0), now=reading.timestamp)
        assert result.ok
        assert [w.field for w in result.warnings] == ["torque_nm"]

    def test_process_below_air_is_warning(self, reading):
        result = validate_reading(
            _with(reading, process_temperature_k=295.0), now=reading.timestamp
        )
        assert result.ok
        assert "process_below_air_temperature" in {w.rule for w in result.warnings}

    def test_future_timestamp_is_error(self, reading):
        result = validate_reading(reading, now=reading.timestamp - timedelta(hours=1))
        assert not result.ok
        assert result.errors[0].rule == "timestamp_in_future"

    def test_small_clock_skew_tolerated(self, reading):
        result = validate_reading(reading, now=reading.timestamp - timedelta(minutes=1))
        assert result.ok

    @pytest.mark.parametrize("offset", [timedelta(0), timedelta(seconds=10)])
    def test_non_increasing_timestamp_is_error(self, reading, offset):
        result = validate_reading(
            reading, previous_timestamp=reading.timestamp + offset, now=reading.timestamp
        )
        assert [e.rule for e in result.errors] == ["timestamp_not_increasing"]

    def test_custom_envelope(self, reading):
        envelope = OperatingEnvelope(rotational_speed_rpm=Range(1600.0, 2000.0))
        result = validate_reading(reading, envelope, now=reading.timestamp)
        assert [w.field for w in result.warnings] == ["rotational_speed_rpm"]

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            Range(10.0, 1.0)


class TestValidateFrame:
    def _frame(self, rows):
        return pd.DataFrame(rows, columns=list(SENSOR_FIELDS))

    def test_counts_and_error_rows(self):
        df = self._frame(
            [
                [300.0, 310.0, 1500.0, 40.0, 10.0],  # fine
                [300.0, 310.0, 1500.0, 99.0, 10.0],  # torque warning
                [300.0, 290.0, 1500.0, 40.0, 10.0],  # process below air (and envelope)
                [300.0, None, 1500.0, 40.0, 10.0],  # missing -> error
            ]
        )
        report = validate_frame(df)
        assert report.counts["outside_envelope:torque_nm"] == 1
        assert report.counts["process_below_air_temperature"] == 1
        assert report.counts["missing_or_non_numeric"] == 1
        assert report.severities["missing_or_non_numeric"] is Severity.ERROR
        assert report.error_rows.tolist() == [False, False, False, True]
        assert not report.ok
        assert report.to_dict()["n_error_rows"] == 1

    def test_missing_column_raises(self):
        with pytest.raises(ValueError, match="Missing sensor columns"):
            validate_frame(pd.DataFrame({"torque_nm": [1.0]}))
