import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from core.machine_registry.registry import MachineRegistry, MaintenanceRecord
from intelligence.agent.__main__ import main as agent_main
from intelligence.agent.agent import OperationsAgent
from intelligence.agent.demo import DEMO_MACHINE, SCENARIOS, build_demo_context
from intelligence.agent.engines import (
    DEFAULT_MODEL,
    FALLBACK_BETA,
    ClaudeEngine,
    EngineError,
    RuleBasedEngine,
)
from intelligence.agent.evidence import Evidence, EvidenceBundle
from intelligence.agent.guard import check_recommendation
from intelligence.agent.schema import (
    RECOMMENDATION_JSON_SCHEMA,
    Finding,
    ProposedAction,
    Recommendation,
)
from intelligence.agent.tools import gather_evidence
from intelligence.retrieval.bm25 import BM25Index, load_corpus, tokenize


@pytest.fixture(scope="module")
def contexts():
    # ai4i_path=None keeps tests independent of the downloaded dataset.
    return {s: build_demo_context(s, seed=0, ai4i_path=None) for s in SCENARIOS}


class TestRegistry:
    def test_loads_fixture(self):
        registry = MachineRegistry.from_json()
        assert registry.machine_ids() == ["cnc-sim-01", "cnc-sim-02", "cnc-sim-03"]
        assert registry.data_nature == "synthetic"
        history = registry.history("cnc-sim-01")
        assert [r.date for r in history] == sorted((r.date for r in history), reverse=True)
        assert len(registry.history("cnc-sim-01", limit=1)) == 1

    def test_unknown_machine(self):
        with pytest.raises(KeyError):
            MachineRegistry.from_json().get("cnc-sim-99")

    def test_rejects_history_for_unknown_machine(self):
        registry = MachineRegistry.from_json()
        machine = registry.get("cnc-sim-01")
        record = MaintenanceRecord(
            record_id="X",
            machine_id="ghost",
            date="2026-01-01",
            kind="inspection",
            component="c",
            description="d",
            outcome="o",
        )
        with pytest.raises(ValueError, match="unknown machines"):
            MachineRegistry([machine], [record])


class TestRetrieval:
    def test_corpus_chunks_have_unique_ids(self):
        chunks = load_corpus()
        assert len(chunks) >= 20
        assert len({c.chunk_id for c in chunks}) == len(chunks)
        assert all("#" in c.chunk_id and c.text for c in chunks)

    def test_light_stemming(self):
        assert tokenize("Overheating temperatures") == ["overheat", "temperature"]
        assert "the" not in tokenize("the spindle")

    @pytest.mark.parametrize(
        "query, expected_doc",
        [
            ("spindle overheating temperature rise coolant", "spindle-thermal"),
            ("torque spike chipped tool breakage", "tool-wear-and-breakage"),
            ("frozen sensor flatline data fault", "sensor-faults"),
            ("lockout inspection human approval", "alarm-response-and-safety"),
            ("spindle speed drift drive belt encoder", "spindle-speed-control"),
        ],
    )
    def test_top_hit(self, query, expected_doc):
        hits = BM25Index.from_directory().search(query, k=3)
        assert hits[0].chunk.doc_id == expected_doc
        assert hits[0].score >= hits[-1].score

    def test_no_match_returns_empty(self):
        assert BM25Index.from_directory().search("xylophone quasar", k=3) == []

    def test_empty_directory(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_corpus(tmp_path)


class TestEvidence:
    def test_sensor_only_mode_is_limited(self, contexts):
        bundle = gather_evidence(DEMO_MACHINE, contexts["healthy"], "sensor_only")
        assert bundle.ids() == {"TEL-1", "TEL-2", "VAL-1"}

    def test_full_mode_collects_everything(self, contexts):
        bundle = gather_evidence(DEMO_MACHINE, contexts["spindle_overheat"], "full")
        kinds = {e.kind for e in bundle.items}
        assert kinds == {
            "telemetry", "validation", "anomaly", "prediction", "machine", "history", "document"
        }  # fmt: skip
        assert bundle.get("PRED-1").content == {
            "available": False,
            "reason": "no trained failure-risk model loaded",
        }
        doc_ids = {e.content["chunk_id"].split("#")[0] for e in bundle.of_kind("document")}
        assert "spindle-thermal" in doc_ids
        assert "Machine: cnc-sim-01" in bundle.render()

    def test_unknown_machine_or_mode(self, contexts):
        with pytest.raises(ValueError):
            gather_evidence("cnc-sim-99", contexts["healthy"])
        with pytest.raises(ValueError):
            gather_evidence(DEMO_MACHINE, contexts["healthy"], "psychic")

    def test_duplicate_evidence_ids_rejected(self):
        item = Evidence("TEL-1", "telemetry", "t", {}, "s")
        with pytest.raises(ValueError):
            EvidenceBundle("m", "full", "now", (item, item))


EXPECTED = {
    "healthy": ("low", {"continue_monitoring"}),
    "spindle_overheat": ("high", {"inspect"}),
    "torque_spike": ("high", {"inspect"}),
    "sensor_flatline": ("unknown", {"check_sensor"}),
}


class TestRuleEngine:
    @pytest.mark.parametrize("scenario", list(EXPECTED))
    def test_scenarios(self, contexts, scenario):
        bundle = gather_evidence(DEMO_MACHINE, contexts[scenario], "full")
        rec = RuleBasedEngine().recommend(bundle)
        risk, actions = EXPECTED[scenario]
        assert rec.risk_level == risk
        assert {a.action_type for a in rec.actions} == actions
        assert check_recommendation(rec, bundle).passed

    @pytest.mark.parametrize("scenario", SCENARIOS)
    @pytest.mark.parametrize("mode", ["sensor_only", "full"])
    def test_always_passes_guard(self, contexts, scenario, mode):
        bundle = gather_evidence(DEMO_MACHINE, contexts[scenario], mode)
        rec = RuleBasedEngine().recommend(bundle)
        report = check_recommendation(rec, bundle)
        assert report.passed, report.to_dict()

    def test_thermal_action_cites_manual_history_and_safety(self, contexts):
        bundle = gather_evidence(DEMO_MACHINE, contexts["spindle_overheat"], "full")
        rec = RuleBasedEngine().recommend(bundle)
        (action,) = rec.actions
        cited_kinds = {bundle.get(i).kind for i in action.evidence_ids}
        assert {"anomaly", "document", "history"} <= cited_kinds
        assert "lockout" in action.description


def _rec(**overrides) -> Recommendation:
    base = {
        "machine_id": DEMO_MACHINE,
        "risk_level": "medium",
        "summary": "s",
        "findings": [Finding(statement="f", evidence_ids=["TEL-1"])],
        "actions": [
            ProposedAction(
                action_type="inspect", description="d", urgency="next_stop", evidence_ids=["TEL-1"]
            )
        ],
        "uncertainties": [],
    }
    return Recommendation(**{**base, **overrides})


class TestGuard:
    @pytest.fixture
    def bundle(self, contexts):
        return gather_evidence(DEMO_MACHINE, contexts["healthy"], "full")

    def test_valid(self, bundle):
        report = check_recommendation(_rec(), bundle)
        assert report.passed
        assert report.claims == 2

    def test_unknown_citation(self, bundle):
        rec = _rec(findings=[Finding(statement="made up", evidence_ids=["DOC-99"])])
        report = check_recommendation(rec, bundle)
        assert not report.passed
        assert report.unknown_citations == 1

    def test_uncited_claim(self, bundle):
        rec = _rec(findings=[Finding(statement="no source", evidence_ids=[])])
        report = check_recommendation(rec, bundle)
        assert report.uncited_claims == 1 and not report.passed

    def test_high_risk_needs_support(self, bundle):
        assert not check_recommendation(_rec(risk_level="high"), bundle).passed
        supported = _rec(
            risk_level="high", findings=[Finding(statement="alarm", evidence_ids=["ANO-1"])]
        )
        assert check_recommendation(supported, bundle).passed

    def test_machine_mismatch_and_no_actions(self, bundle):
        codes = {i.code for i in check_recommendation(_rec(machine_id="x"), bundle).issues}
        assert "machine_mismatch" in codes
        codes = {i.code for i in check_recommendation(_rec(actions=[]), bundle).issues}
        assert "no_actions" in codes

    def test_requires_approval(self):
        assert _rec().requires_approval
        monitor = ProposedAction(
            action_type="continue_monitoring", description="d", urgency="routine",
            evidence_ids=["TEL-1"],
        )  # fmt: skip
        assert not _rec(actions=[monitor]).requires_approval


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _fake_client(payload=None, stop_reason="end_turn", text=None):
    body = text if text is not None else json.dumps(payload)
    response = SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=body)],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        model=DEFAULT_MODEL,
    )
    messages = _FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


GOOD_PAYLOAD = {
    "risk_level": "high",
    "summary": "Spindle temperature is rising; inspect cooling.",
    "findings": [{"statement": "Temperature rise is far above normal.", "evidence_ids": ["ANO-1"]}],
    "actions": [
        {
            "action_type": "inspect",
            "description": "Inspect coolant flow after lockout.",
            "urgency": "immediate",
            "evidence_ids": ["ANO-1", "DOC-1"],
        }
    ],
    "uncertainties": ["Simulated data."],
}


class TestClaudeEngine:
    @pytest.fixture
    def bundle(self, contexts):
        return gather_evidence(DEMO_MACHINE, contexts["spindle_overheat"], "full")

    def test_request_shape_and_parsing(self, bundle):
        client, messages = _fake_client(GOOD_PAYLOAD)
        engine = ClaudeEngine(client=client)
        rec = engine.recommend(bundle)

        assert rec.machine_id == DEMO_MACHINE
        assert rec.risk_level == "high"
        (call,) = messages.calls
        assert call["model"] == "claude-opus-5-5"
        assert call["output_config"]["format"] == {
            "type": "json_schema",
            "schema": RECOMMENDATION_JSON_SCHEMA,
        }
        assert call["output_config"]["effort"] == "high"
        assert call["betas"] == [FALLBACK_BETA]
        assert call["fallbacks"] == "default"
        assert "[ANO-1]" in call["messages"][0]["content"]
        assert "thinking" not in call
        assert engine.last_usage["output_tokens"] == 50

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"payload": GOOD_PAYLOAD, "stop_reason": "refusal"}, "declined"),
            ({"payload": GOOD_PAYLOAD, "stop_reason": "max_tokens"}, "cut off"),
            ({"text": "not json"}, "schema"),
            ({"payload": {**GOOD_PAYLOAD, "risk_level": "catastrophic"}}, "schema"),
        ],
    )
    def test_bad_responses_raise(self, bundle, kwargs, message):
        client, _ = _fake_client(**kwargs)
        with pytest.raises(EngineError, match=message):
            ClaudeEngine(client=client).recommend(bundle)


class _StubEngine:
    name = "stub"

    def __init__(self, rec=None, error=None):
        self.rec, self.error = rec, error

    def recommend(self, bundle):
        if self.error:
            raise self.error
        return self.rec


class TestOperationsAgent:
    def test_uses_primary_engine_when_guard_passes(self, contexts):
        client, _ = _fake_client(GOOD_PAYLOAD)
        result = OperationsAgent(contexts["spindle_overheat"], ClaudeEngine(client=client)).run(
            DEMO_MACHINE
        )
        assert result.engine == "claude"
        assert result.fallback_reason is None
        assert result.approval_status == "pending_approval"
        assert result.llm_usage["input_tokens"] == 100

    def test_falls_back_when_citation_is_invented(self, contexts):
        bad = _rec(findings=[Finding(statement="invented", evidence_ids=["DOC-42"])])
        result = OperationsAgent(contexts["healthy"], _StubEngine(rec=bad)).run(DEMO_MACHINE)
        assert result.engine == "rules"
        assert "guard" in result.fallback_reason
        assert result.primary_guard.unknown_citations == 1
        assert result.guard.passed

    def test_falls_back_on_engine_error(self, contexts):
        engine = _StubEngine(error=EngineError("API down"))
        result = OperationsAgent(contexts["healthy"], engine).run(DEMO_MACHINE, "sensor_only")
        assert result.engine == "rules"
        assert result.fallback_reason == "API down"
        payload = result.to_dict()
        assert payload["evidence"]["mode"] == "sensor_only"
        json.dumps(payload, default=str)


def test_cli_rules_engine_writes_audit_log(tmp_path, capsys):
    log = tmp_path / "audit.jsonl"
    code = agent_main(["--scenario", "torque_spike", "--audit-log", str(log)])
    assert code == 0
    out = capsys.readouterr().out
    assert "SYNTHETIC DATA" in out and "Evidence guard: passed" in out
    (line,) = log.read_text("utf-8").splitlines()
    record = json.loads(line)
    assert record["scenario"] == "torque_spike"
    assert record["approval_status"] == "pending_approval"


def test_scenario_fault_ends_with_live_window():
    from datetime import UTC, datetime

    from intelligence.agent.demo import scenario_fault

    start = datetime(2026, 1, 1, tzinfo=UTC)
    (fault,) = scenario_fault("torque_spike", start, timedelta(hours=6))
    assert fault.end == start + timedelta(hours=6)
    assert scenario_fault("healthy", start, timedelta(hours=6)) == ()
    with pytest.raises(ValueError):
        scenario_fault("gremlins", start, timedelta(hours=6))
