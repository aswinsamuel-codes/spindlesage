import json
import math

import numpy as np
import pandas as pd
import pytest
from sklearn.base import clone

from core.ingestion.ai4i import load_ai4i
from experiments.exp_a_predictive import main as exp_a_main
from intelligence.evaluation.classification import classification_metrics, mean_std
from intelligence.predictive.experiment import ExperimentAConfig, run_experiment_a
from intelligence.predictive.features import LEAKAGE_COLUMNS, build_features
from intelligence.predictive.models import MODEL_NAMES, SensorThresholdBaseline, make_model


@pytest.fixture
def df(synthetic_ai4i_csv):
    return load_ai4i(synthetic_ai4i_csv)


class TestFeatures:
    @pytest.mark.parametrize("feature_set", ["raw", "engineered"])
    def test_no_leakage(self, df, feature_set):
        X = build_features(df, feature_set)
        assert not LEAKAGE_COLUMNS & set(X.columns)
        assert len(X) == len(df)
        assert not X.isna().any().any()

    def test_one_hot_product_type(self, df):
        X = build_features(df)
        assert (X[["type_L", "type_M", "type_H"]].sum(axis=1) == 1).all()

    def test_engineered_values(self, df):
        X = build_features(df, "engineered")
        row = df.iloc[0]
        expected_power = row["torque_nm"] * row["rotational_speed_rpm"] * 2 * math.pi / 60
        assert X["mech_power_w"].iloc[0] == pytest.approx(expected_power)
        assert X["temp_delta_k"].iloc[0] == pytest.approx(
            row["process_temperature_k"] - row["air_temperature_k"]
        )

    def test_unknown_feature_set(self, df):
        with pytest.raises(ValueError):
            build_features(df, "magic")


class TestThresholdBaseline:
    def _data(self):
        X = pd.DataFrame(
            {
                "air_temperature_k": np.linspace(299, 301, 100),
                "process_temperature_k": np.linspace(309, 311, 100),
                "rotational_speed_rpm": np.linspace(1400, 1600, 100),
                "torque_nm": np.linspace(30, 50, 100),
                "tool_wear_min": np.linspace(0, 200, 100),
            }
        )
        return X, np.zeros(100, dtype=int)

    def test_flags_values_outside_healthy_band(self):
        X, y = self._data()
        model = SensorThresholdBaseline(quantile=0.0).fit(X, y)
        probe = X.iloc[[50, 50]].copy()
        probe.iloc[1, probe.columns.get_loc("torque_nm")] = 80.0
        assert model.predict(probe).tolist() == [0, 1]
        proba = model.predict_proba(probe)[:, 1]
        assert proba[0] < 0.5 < proba[1]

    def test_is_sklearn_clonable(self):
        model = SensorThresholdBaseline(quantile=0.05)
        assert clone(model).get_params()["quantile"] == 0.05

    def test_needs_healthy_samples(self):
        X, _ = self._data()
        with pytest.raises(ValueError):
            SensorThresholdBaseline().fit(X, np.ones(len(X), dtype=int))


@pytest.mark.parametrize("name", MODEL_NAMES)
def test_every_model_fits_and_scores(df, name):
    X = build_features(df)
    y = df["machine_failure"].to_numpy()
    model = make_model(name, y_train=y, seed=0).fit(X, y)
    proba = model.predict_proba(X)
    assert proba.shape == (len(X), 2)
    assert ((proba >= 0) & (proba <= 1)).all()


def test_unknown_model():
    with pytest.raises(ValueError):
        make_model("svm", y_train=[0, 1], seed=0)


def test_classification_metrics():
    m = classification_metrics([0, 0, 1, 1], [0, 1, 1, 0], [0.1, 0.6, 0.9, 0.4])
    assert m["confusion_matrix"] == {"tn": 1, "fp": 1, "fn": 1, "tp": 1}
    assert m["precision"] == m["recall"] == m["f1"] == 0.5
    assert 0.0 <= m["pr_auc"] <= 1.0
    assert mean_std([1.0, 3.0]) == {"mean": 2.0, "std": pytest.approx(math.sqrt(2))}


def test_experiment_a_end_to_end(synthetic_ai4i_csv):
    config = ExperimentAConfig(data_path=synthetic_ai4i_csv, seeds=(0, 1), cv_folds=2)
    results = run_experiment_a(config)

    assert set(results["summary"]) == set(MODEL_NAMES)
    assert len(results["runs"]) == 2 * len(MODEL_NAMES)
    assert results["dataset"]["nature"] == "synthetic"
    assert not LEAKAGE_COLUMNS & set(results["dataset"]["features"])
    # The synthetic rule is learnable, so tree models should clearly beat chance.
    assert results["summary"]["xgboost"]["pr_auc"]["mean"] > results["dataset"]["positives"] / 600


def test_experiment_a_cli_writes_results(synthetic_ai4i_csv, tmp_path, capsys):
    out = tmp_path / "results"
    code = exp_a_main(
        [
            "--data",
            str(synthetic_ai4i_csv),
            "--output",
            str(out),
            "--seeds",
            "0",
            "--cv-folds",
            "2",
            "--models",
            "threshold_baseline",
            "logistic_regression",
        ]
    )
    assert code == 0
    (run_dir,) = out.iterdir()
    results = json.loads((run_dir / "results.json").read_text("utf-8"))
    assert set(results["summary"]) == {"threshold_baseline", "logistic_regression"}
    assert "synthetic" in (run_dir / "summary.md").read_text("utf-8")
    assert "Saved to" in capsys.readouterr().out


@pytest.mark.parametrize(
    "kwargs",
    [
        {"models": ("svm",)},
        {"cv_folds": 1},
        {"test_size": 1.5},
        {"seeds": ()},
        {"feature_set": "x"},
    ],
)
def test_config_rejects_bad_values(kwargs):
    with pytest.raises(ValueError):
        ExperimentAConfig(**kwargs)
