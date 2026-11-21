import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from experiments.exp_b_anomaly import main as exp_b_main
from integrations.simulator.cnc import FaultEvent, SimulationConfig, simulate_cell
from intelligence.anomaly.detectors import (
    IsolationForestDetector,
    ThresholdDetector,
    apply_alarm_policy,
    calibrate_threshold,
    make_detector,
)
from intelligence.anomaly.experiment import ExperimentBConfig, run_experiment_b
from intelligence.anomaly.features import build_anomaly_features
from intelligence.evaluation.anomaly import evaluate_alarms

T0 = datetime(2026, 1, 5, tzinfo=UTC)
STEP = timedelta(minutes=1)


@pytest.fixture(scope="module")
def healthy():
    config = SimulationConfig(n_machines=2, duration=timedelta(hours=12), seed=7)
    return simulate_cell(config).readings


class TestFeatures:
    def test_raw_is_sensor_columns(self, healthy):
        X = build_anomaly_features(healthy, "raw")
        assert X.shape == (len(healthy), 5)

    def test_contextual_aligns_and_only_first_sample_is_missing(self, healthy):
        shuffled = healthy.sample(frac=1.0, random_state=0)
        X = build_anomaly_features(shuffled, "contextual", window=5)
        assert X.index.equals(shuffled.index)
        assert {"temp_rise_k", "mech_power_w", "torque_nm_log_rolling_std"} <= set(X.columns)
        # Only each machine's first sample lacks rolling history.
        first = healthy.groupby("machine_id")["timestamp"].idxmin()
        missing = X.index[X.isna().any(axis=1)]
        assert set(missing) == set(first)

    def test_frozen_signal_is_far_below_normal_variability(self, healthy):
        frozen = healthy.copy()
        rows = frozen.index[frozen["machine_id"] == "cnc-sim-01"][-30:]
        frozen.loc[rows, "torque_nm"] = frozen.loc[rows[0], "torque_nm"]
        X = build_anomaly_features(frozen, "contextual", window=10)
        normal = build_anomaly_features(healthy, "contextual", window=10)
        col = "torque_nm_log_rolling_std"
        assert X.loc[rows[-1], col] < normal[col].quantile(0.001) - 1.0

    def test_detectors_fill_missing_values_from_training(self, healthy):
        X = build_anomaly_features(healthy, "contextual", window=5)
        for detector in (ThresholdDetector(), IsolationForestDetector(seed=0)):
            scores = detector.fit(X).score(X)
            assert np.isfinite(scores).all()

    def test_rolling_is_per_machine_and_backward_looking(self, healthy):
        X = build_anomaly_features(healthy, "contextual", window=5)
        changed = healthy.copy()
        # Changing a later sample must not alter earlier features.
        last = changed.index[changed["machine_id"] == "cnc-sim-01"][-1]
        changed.loc[last, "torque_nm"] += 50.0
        Y = build_anomaly_features(changed, "contextual", window=5)
        earlier = changed.index[changed["machine_id"] == "cnc-sim-01"][:-1]
        pd.testing.assert_frame_equal(X.loc[earlier], Y.loc[earlier])
        other = changed.index[changed["machine_id"] == "cnc-sim-02"]
        pd.testing.assert_frame_equal(X.loc[other], Y.loc[other])

    def test_rejects_bad_arguments(self, healthy):
        with pytest.raises(ValueError):
            build_anomaly_features(healthy, "magic")
        with pytest.raises(ValueError):
            build_anomaly_features(healthy, "contextual", window=1)


class TestDetectors:
    @pytest.mark.parametrize("detector", [ThresholdDetector(), IsolationForestDetector(seed=0)])
    def test_obvious_outlier_scores_higher(self, healthy, detector):
        X = build_anomaly_features(healthy, "raw")
        detector.fit(X)
        probe = X.iloc[[0, 0]].copy()
        probe.iloc[1, probe.columns.get_loc("process_temperature_k")] += 25.0
        normal, outlier = detector.score(probe)
        assert outlier > normal

    def test_unknown_detector(self):
        with pytest.raises(ValueError):
            make_detector("oracle")

    def test_calibration_hits_target_rate(self):
        scores = np.arange(1000, dtype=float)
        threshold = calibrate_threshold(scores, 0.01)
        assert (scores > threshold).mean() == pytest.approx(0.01, abs=0.002)
        with pytest.raises(ValueError):
            calibrate_threshold(scores, 0.0)

    def test_persistence_and_machine_boundaries(self):
        scores = np.array([5, 5, 0, 5, 5, 5, 5, 5, 5, 5])
        machines = np.array(["a"] * 5 + ["b"] * 5)
        alarm = apply_alarm_policy(scores, machines, threshold=1.0, persistence=3)
        # Machine a: runs of 2 split by a gap, so no alarm. Machine b: alarm from 3rd sample.
        assert alarm.tolist() == [False] * 5 + [False, False, True, True, True]
        with pytest.raises(ValueError):
            apply_alarm_policy(scores, machines, 1.0, persistence=0)


class TestEvaluation:
    def _frame(self, n=120):
        return pd.DataFrame(
            {
                "timestamp": pd.date_range(T0, periods=n, freq=STEP),
                "machine_id": "m1",
            }
        )

    def test_hand_computed_metrics(self):
        df = self._frame()
        events = [
            FaultEvent("m1", "torque_spike", T0 + 20 * STEP, T0 + 40 * STEP, 0.5),
            FaultEvent("m1", "spindle_overheat", T0 + 80 * STEP, T0 + 90 * STEP, 5.0),
        ]
        alarm = np.zeros(len(df), dtype=bool)
        alarm[25:45] = True  # detects event 1 after 5 min, runs into the grace period
        alarm[60:63] = True  # false alarm
        result = evaluate_alarms(df, alarm, events, STEP, grace=timedelta(minutes=10))

        assert result["events"] == 2
        assert result["detected_events"] == 1
        assert result["detection_recall"] == 0.5
        assert result["alarm_episodes"] == 2
        assert result["false_alarm_episodes"] == 1
        assert result["detection_precision"] == 0.5
        assert result["healthy_hours"] == pytest.approx(90 / 60)
        assert result["false_alarms_per_hour"] == pytest.approx(1 / 1.5)
        assert result["detection_delay_s"]["median"] == 300.0
        assert result["per_fault_type"]["torque_spike"]["recall"] == 1.0
        assert result["per_fault_type"]["spindle_overheat"]["delay_s"] is None
        assert result["pointwise"]["recall"] == pytest.approx(15 / 30)

    def test_no_alarms(self):
        df = self._frame()
        events = [FaultEvent("m1", "torque_spike", T0 + 20 * STEP, T0 + 40 * STEP, 0.5)]
        result = evaluate_alarms(df, np.zeros(len(df), dtype=bool), events, STEP)
        assert result["detection_recall"] == 0.0
        assert result["alarm_episodes"] == 0
        assert result["false_alarms_per_hour"] == 0.0
        assert result["detection_delay_s"] is None

    def test_episodes_split_at_machine_boundary(self):
        df = pd.concat(
            [self._frame(10), self._frame(10).assign(machine_id="m2")], ignore_index=True
        )
        result = evaluate_alarms(df, np.ones(20, dtype=bool), [], STEP)
        assert result["alarm_episodes"] == 2
        assert result["detection_recall"] is None

    def test_length_mismatch(self):
        with pytest.raises(ValueError):
            evaluate_alarms(self._frame(), np.zeros(3, dtype=bool), [], STEP)


SMALL = {
    "seeds": (0,),
    "n_machines": 2,
    "train_days": 0.5,
    "calibration_days": 0.25,
    "test_days": 1.0,
    "faults_per_machine": 3,
}


def test_experiment_b_end_to_end():
    results = run_experiment_b(ExperimentBConfig(**SMALL))
    assert set(results["summary"]) == {
        "threshold/raw",
        "isolation_forest/raw",
        "threshold/contextual",
        "isolation_forest/contextual",
    }
    assert results["dataset"]["nature"] == "synthetic"
    assert results["dataset"]["per_seed"][0]["test_events"] == 6
    for run in results["runs"]:
        assert 0.0 <= run["metrics"]["detection_recall"] <= 1.0


def test_experiment_b_cli(tmp_path, capsys):
    out = tmp_path / "b"
    code = exp_b_main(
        [
            "--output", str(out),
            "--seeds", "0",
            "--machines", "1",
            "--train-days", "0.5",
            "--calibration-days", "0.25",
            "--test-days", "1",
            "--faults", "2",
            "--detectors", "threshold",
            "--feature-sets", "contextual",
        ]
    )  # fmt: skip
    assert code == 0
    (run_dir,) = out.iterdir()
    results = json.loads((run_dir / "results.json").read_text("utf-8"))
    assert list(results["summary"]) == ["threshold/contextual"]
    assert "synthetic" in capsys.readouterr().out


@pytest.mark.parametrize(
    "overrides",
    [{"detectors": ("oracle",)}, {"feature_sets": ()}, {"seeds": ()}, {"test_days": 0}],
)
def test_config_validation(overrides):
    with pytest.raises(ValueError):
        ExperimentBConfig(**overrides)
