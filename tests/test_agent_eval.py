import json

import pytest

from experiments.exp_c_agent import main as exp_c_main
from intelligence.evaluation.agent_eval import (
    ExperimentCConfig,
    build_cases,
    render_summary_markdown,
    run_experiment_c,
)

SMALL = {
    "scenarios": ("healthy", "torque_spike", "sensor_flatline"),
    "seeds": (0,),
    "stages": ("late",),
    "ai4i_path": None,
}


@pytest.fixture(scope="module")
def results():
    return run_experiment_c(ExperimentCConfig(**SMALL))


def test_cases_pair_faults_with_a_healthy_machine():
    cases = build_cases(ExperimentCConfig(**SMALL))
    assert len(cases) == 6
    assert {c.expected for c in cases if c.machine_id == "cnc-sim-02"} == {"healthy"}
    assert {c.expected for c in cases if c.machine_id == "cnc-sim-01"} == set(SMALL["scenarios"])


def test_rules_full_context_scores(results):
    full = results["summary"]["rules/full"]
    assert full["runs"] == 6
    assert full["accuracy"] == 1.0
    assert full["false_alarm_rate"] == 0.0
    assert full["right_document_cited_rate"] == 1.0
    assert full["approval_compliance_rate"] == 1.0
    assert full["unsupported_claims_per_run"]["mean"] == 0.0
    assert full["cost_usd_total"] == 0.0


def test_sensor_only_misses_faults(results):
    sensor = results["summary"]["rules/sensor_only"]
    assert sensor["fault_detection_rate"] == 0.0
    assert sensor["right_document_cited_rate"] == 0.0


def test_runs_record_scoring_details(results):
    run = next(
        r for r in results["runs"] if r["expected"] == "sensor_flatline" and r["mode"] == "full"
    )
    assert run["actions"] == ["check_sensor"]
    assert run["approvals_opened"] == run["operational_actions"] == 1
    assert run["approvals_auto_approved"] == 0
    assert run["tool_success_rate"] < 1.0  # failure-risk model deliberately not loaded
    assert results["dataset"]["nature"] == "synthetic"
    assert "synthetic" in render_summary_markdown(results).lower()


def test_cli_writes_results(tmp_path, capsys):
    code = exp_c_main(
        ["--output", str(tmp_path), "--scenarios", "healthy", "--seeds", "0",
         "--stages", "early", "--no-risk-model"]
    )  # fmt: skip
    assert code == 0
    (run_dir,) = tmp_path.iterdir()
    payload = json.loads((run_dir / "results.json").read_text("utf-8"))
    assert payload["config"]["cases"] == 2
    assert "Saved to" in capsys.readouterr().out


def test_claude_run_asks_before_spending(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    code = exp_c_main(
        ["--output", str(tmp_path), "--engines", "claude", "--scenarios", "healthy",
         "--seeds", "0", "--stages", "late", "--no-risk-model"]
    )  # fmt: skip
    assert code == 1
    assert "Cancelled" in capsys.readouterr().out
    assert not any(tmp_path.iterdir())


@pytest.mark.parametrize(
    "overrides",
    [{"engines": ("gpt",)}, {"modes": ()}, {"scenarios": ("meteor",)}, {"stages": ("noon",)},
     {"seeds": ()}],
)  # fmt: skip
def test_config_validation(overrides):
    with pytest.raises(ValueError):
        ExperimentCConfig(**overrides)
