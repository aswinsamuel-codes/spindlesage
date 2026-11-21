import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from core.telemetry.schema import CncTelemetryReading
from integrations.simulator.__main__ import main as simulator_main
from integrations.simulator.cnc import (
    FAULT_TYPES,
    NO_FAULT,
    SimulationConfig,
    simulate_cell,
)


def _config(**overrides) -> SimulationConfig:
    base = {"n_machines": 2, "duration": timedelta(hours=12), "seed": 3}
    return SimulationConfig(**{**base, **overrides})


def test_shape_and_synthetic_label():
    result = simulate_cell(_config())
    df = result.readings
    assert len(df) == 2 * 12 * 120  # 2 machines, 12 h at 30 s
    assert df.attrs["data_nature"] == "synthetic"
    assert set(df["machine_id"]) == {"cnc-sim-01", "cnc-sim-02"}
    assert not df["is_anomaly"].any()
    assert result.events == ()


def test_deterministic_per_seed():
    a = simulate_cell(_config(faults_per_machine=2)).readings
    b = simulate_cell(_config(faults_per_machine=2)).readings
    c = simulate_cell(_config(faults_per_machine=2, seed=4)).readings
    pd.testing.assert_frame_equal(a, b)
    assert not a.equals(c)


def test_readings_satisfy_schema():
    df = simulate_cell(_config(faults_per_machine=2)).readings
    for record in df.sample(200, random_state=0).to_dict("records"):
        CncTelemetryReading(
            **{k: v for k, v in record.items() if k not in ("is_anomaly", "fault_type")}
        )


def test_timestamps_aware_and_increasing_per_machine():
    df = simulate_cell(_config()).readings
    assert str(df["timestamp"].dt.tz) == "UTC"
    for _, group in df.groupby("machine_id"):
        assert group["timestamp"].is_monotonic_increasing


def test_fault_labels_match_events():
    result = simulate_cell(_config(duration=timedelta(days=2), faults_per_machine=4))
    df = result.readings
    assert len(result.events) == 8
    for event in result.events:
        assert event.fault_type in FAULT_TYPES
        mask = (
            (df["machine_id"] == event.machine_id)
            & (df["timestamp"] >= event.start)
            & (df["timestamp"] < event.end)
        )
        assert df.loc[mask, "is_anomaly"].all()
        assert (df.loc[mask, "fault_type"] == event.fault_type).all()
    labelled = df["is_anomaly"].sum()
    covered = sum(
        (
            (df["machine_id"] == e.machine_id)
            & (df["timestamp"] >= e.start)
            & (df["timestamp"] < e.end)
        ).sum()
        for e in result.events
    )
    assert labelled == covered
    assert (df.loc[~df["is_anomaly"], "fault_type"] == NO_FAULT).all()


def test_faults_do_not_overlap():
    events = simulate_cell(_config(duration=timedelta(days=2), faults_per_machine=5)).events
    for machine in {e.machine_id for e in events}:
        mine = sorted((e for e in events if e.machine_id == machine), key=lambda e: e.start)
        for earlier, later in zip(mine, mine[1:], strict=False):
            assert earlier.end <= later.start


@pytest.mark.parametrize("fault_type", FAULT_TYPES)
def test_each_fault_type_changes_the_signal(fault_type):
    config = _config(duration=timedelta(days=1), faults_per_machine=1, fault_types=(fault_type,))
    faulty = simulate_cell(config)
    clean = simulate_cell(_config(duration=timedelta(days=1), faults_per_machine=0))
    (event,) = [e for e in faulty.events if e.machine_id == "cnc-sim-01"]
    rows = (faulty.readings["machine_id"] == "cnc-sim-01") & faulty.readings["is_anomaly"]
    window = faulty.readings[rows]

    if fault_type == "sensor_flatline":
        assert window[event.sensor].nunique() == 1
    else:
        column = {
            "spindle_overheat": "process_temperature_k",
            "torque_spike": "torque_nm",
            "speed_drift": "rotational_speed_rpm",
        }[fault_type]
        # Same seed, same machine stream: only the fault differs in that window.
        assert not np.allclose(window[column], clean.readings.loc[rows[rows].index, column])


def test_too_many_faults_raises():
    with pytest.raises(ValueError, match="Could only place"):
        simulate_cell(_config(duration=timedelta(hours=4), faults_per_machine=10))


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_machines": 0},
        {"start": datetime(2026, 1, 1)},
        {"duration": timedelta(seconds=1)},
        {"fault_types": ("meteor_strike",)},
        {"min_fault_duration": timedelta(hours=3), "max_fault_duration": timedelta(hours=1)},
    ],
)
def test_config_validation(overrides):
    with pytest.raises(ValueError):
        _config(**overrides)


def test_cli_writes_csv_and_events(tmp_path, capsys):
    out = tmp_path / "cell.csv"
    code = simulator_main(
        ["--out", str(out), "--days", "0.5", "--machines", "1", "--faults", "1", "--seed", "2"]
    )
    assert code == 0
    df = pd.read_csv(out)
    assert len(df) == 1440
    events = json.loads(out.with_suffix(".events.json").read_text("utf-8"))
    assert events["data_nature"] == "synthetic"
    assert len(events["events"]) == 1
    assert datetime.fromisoformat(events["events"][0]["start"]).tzinfo == UTC
    assert "synthetic" in capsys.readouterr().out


def test_scheduled_fault_is_applied_and_labelled():
    from integrations.simulator.cnc import FaultEvent

    start = datetime(2026, 1, 5, 6, tzinfo=UTC)
    fault = FaultEvent("cnc-sim-02", "torque_spike", start, start + timedelta(hours=1), 0.5)
    result = simulate_cell(_config(scheduled_faults=(fault,)))
    assert result.events == (fault,)
    df = result.readings
    window = (df["machine_id"] == "cnc-sim-02") & (df["timestamp"] >= start)
    window &= df["timestamp"] < fault.end
    assert df.loc[window, "is_anomaly"].all()
    assert df["is_anomaly"].sum() == window.sum()


@pytest.mark.parametrize(
    "fault_kwargs",
    [
        {"machine_id": "cnc-sim-09"},
        {"fault_type": "gremlins"},
        {"fault_type": "sensor_flatline", "sensor": None},
    ],
)
def test_scheduled_fault_validation(fault_kwargs):
    from integrations.simulator.cnc import FaultEvent

    start = datetime(2026, 1, 5, 6, tzinfo=UTC)
    base = {
        "machine_id": "cnc-sim-01",
        "fault_type": "torque_spike",
        "start": start,
        "end": start + timedelta(hours=1),
        "magnitude": 0.5,
    }
    with pytest.raises(ValueError):
        _config(scheduled_faults=(FaultEvent(**{**base, **fault_kwargs}),))
