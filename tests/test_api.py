"""API and approval-workflow tests (hypothesis H4: unauthorized actions are blocked)."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from apps.api.app import create_app
from apps.api.auth import ApiKeyRegistry, hash_key
from apps.api.keys import main as keys_main
from apps.api.services import build_services
from apps.api.settings import Settings
from core.event_engine.approvals import (
    ApprovalService,
    ForbiddenError,
    InvalidTransitionError,
)
from core.event_engine.roles import Principal, Role
from core.event_engine.store import OperationsStore
from core.telemetry.buffer import TelemetryBuffer
from intelligence.agent.agent import OperationsAgent
from intelligence.agent.schema import Finding, ProposedAction, Recommendation

KEYS = {
    "k-viewer": ("vera", Role.VIEWER),
    "k-ingest": ("gateway", Role.INGEST),
    "k-alice": ("alice", Role.TECHNICIAN),
    "k-bob": ("bob", Role.TECHNICIAN),
    "k-carol": ("carol", Role.MAINTENANCE_LEAD),
    "k-dave": ("dave", Role.MAINTENANCE_LEAD),
    "k-admin": ("root", Role.ADMIN),
}


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)

    def __call__(self):
        return self.now


@pytest.fixture(scope="module")
def base_services():
    settings = Settings(db_path=":memory:", ai4i_path=None, demo_scenario="spindle_overheat")
    return build_services(settings)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def services(base_services, clock):
    """Fresh database, buffer and approval service per test; models shared."""
    store = OperationsStore(":memory:")
    buffer = TelemetryBuffer()
    for machine_id in base_services.buffer.machine_ids():
        buffer.load_frame(base_services.buffer.frame(machine_id))
    return replace(
        base_services,
        store=store,
        buffer=buffer,
        approvals=ApprovalService(store, ttl=timedelta(hours=8), clock=clock),
    )


@pytest.fixture
def client(services):
    app = create_app(Settings(db_path=":memory:", ai4i_path=None), services,
                     ApiKeyRegistry.from_plain_keys(KEYS))  # fmt: skip
    return TestClient(app)


def h(key: str) -> dict:
    return {"X-API-Key": key}


def recommend(client, key="k-alice", machine="cnc-sim-01", mode="full"):
    response = client.post(
        f"/machines/{machine}/recommendations", headers=h(key), json={"mode": mode}
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestAuth:
    def test_health_is_public_and_honest(self, client):
        body = client.get("/health").json()
        assert body["data_nature"] == "synthetic"
        assert body["machine_control"].startswith("none")
        assert body["api_keys_configured"] == len(KEYS)

    @pytest.mark.parametrize("headers", [{}, h("wrong-key")])
    def test_missing_or_bad_key(self, client, headers):
        assert client.get("/machines", headers=headers).status_code == 401

    def test_me(self, client):
        body = client.get("/me", headers=h("k-carol")).json()
        assert body["role"] == "maintenance_lead"
        assert "decide_approval" in body["permissions"]

    @pytest.mark.parametrize(
        "key, method, path, expected",
        [
            ("k-ingest", "get", "/machines", 403),
            ("k-viewer", "post", "/machines/cnc-sim-01/recommendations", 403),
            ("k-viewer", "post", "/telemetry", 403),
            ("k-alice", "get", "/audit", 403),
            ("k-viewer", "get", "/audit/verify", 403),
            ("k-viewer", "get", "/machines", 200),
            ("k-admin", "get", "/audit/verify", 200),
        ],
    )
    def test_role_matrix(self, client, key, method, path, expected):
        kwargs = {"json": {"readings": []}} if path == "/telemetry" else {}
        response = getattr(client, method)(path, headers=h(key), **kwargs)
        assert response.status_code == expected, response.text

    def test_keys_are_stored_as_hashes(self):
        registry = ApiKeyRegistry.from_plain_keys({"secret": ("x", Role.VIEWER)})
        assert registry.authenticate("secret") == Principal("x", Role.VIEWER)
        assert registry.authenticate("Secret") is None
        assert registry.authenticate(None) is None

    def test_keys_cli(self, tmp_path, capsys):
        path = tmp_path / "keys.json"
        assert keys_main(["--file", str(path), "add", "--user", "erin", "--role", "viewer"]) == 0
        key = next(line.strip() for line in capsys.readouterr().out.splitlines()
                   if line.strip().startswith("ss_"))  # fmt: skip
        stored = path.read_text("utf-8")
        assert key not in stored
        assert hash_key(key) in stored
        assert ApiKeyRegistry.from_file(path).authenticate(key).user_id == "erin"
        keys_main(["--file", str(path), "list"])
        assert "erin" in capsys.readouterr().out


class TestMachinesAndTelemetry:
    def test_list_machines(self, client):
        machines = client.get("/machines", headers=h("k-viewer")).json()
        assert [m["machine_id"] for m in machines] == ["cnc-sim-01", "cnc-sim-02", "cnc-sim-03"]
        assert all(m["readings_buffered"] > 0 for m in machines)

    def test_unknown_machine(self, client):
        assert client.get("/machines/cnc-sim-99", headers=h("k-viewer")).status_code == 404

    def test_machine_detail_and_telemetry(self, client):
        detail = client.get("/machines/cnc-sim-01", headers=h("k-viewer")).json()
        assert detail["maintenance_history"]
        telemetry = client.get(
            "/machines/cnc-sim-01/telemetry?limit=5", headers=h("k-viewer")
        ).json()
        assert len(telemetry["readings"]) == 5
        assert telemetry["data_nature"] == "synthetic"

    def test_status_shows_alarm(self, client):
        status = client.get("/machines/cnc-sim-01/status", headers=h("k-viewer")).json()
        assert status["anomaly"]["alarm"] is True
        healthy = client.get("/machines/cnc-sim-02/status", headers=h("k-viewer")).json()
        assert healthy["anomaly"]["alarm"] is False

    def test_ingest_validation(self, client):
        last = client.get("/machines/cnc-sim-02/telemetry?limit=1", headers=h("k-viewer")).json()
        reading = last["readings"][0]
        newer = {
            **reading,
            "timestamp": (
                datetime.fromisoformat(reading["timestamp"]) + timedelta(seconds=30)
            ).isoformat(),
        }
        batch = [
            newer,                                   # accepted
            reading,                                 # out of order -> rejected
            {**newer, "machine_id": "cnc-sim-99"},   # unknown machine -> rejected
            {**newer, "timestamp": "2099-01-01T00:00:00+00:00"},  # future -> rejected
        ]  # fmt: skip
        body = client.post("/telemetry", headers=h("k-ingest"), json={"readings": batch}).json()
        assert body["accepted"] == 1
        rules = sorted(i["rule"] for r in body["rejected"] for i in r["issues"])
        assert rules == ["timestamp_in_future", "timestamp_not_increasing", "unknown_machine"]

    def test_ingest_rejects_impossible_values(self, client):
        bad = {
            "machine_id": "cnc-sim-02", "timestamp": "2026-01-06T20:00:00+00:00",
            "product_type": "M", "air_temperature_k": -5, "process_temperature_k": 310,
            "rotational_speed_rpm": 1500, "torque_nm": 40, "tool_wear_min": 10,
        }  # fmt: skip
        response = client.post("/telemetry", headers=h("k-ingest"), json={"readings": [bad]})
        assert response.status_code == 422


class TestRecommendations:
    def test_fault_creates_pending_approvals(self, client):
        body = recommend(client)
        assert body["recommendation"]["risk_level"] == "high"
        assert body["approval_status"] == "pending_approval"
        assert body["guard"]["passed"]
        (approval,) = body["approvals"]
        assert approval["status"] == "pending"
        assert approval["action_type"] == "inspect"
        assert approval["requested_by"] == "alice"

    def test_healthy_machine_needs_no_approval(self, client):
        body = recommend(client, machine="cnc-sim-02")
        assert body["approval_status"] == "not_required"
        assert body["approvals"] == []

    def test_sensor_only_mode(self, client):
        body = recommend(client, mode="sensor_only")
        assert body["evidence"]["mode"] == "sensor_only"

    def test_listing_and_detail(self, client):
        rec_id = recommend(client)["recommendation_id"]
        listing = client.get("/recommendations?machine_id=cnc-sim-01", headers=h("k-viewer"))
        assert listing.json()[0]["id"] == rec_id
        detail = client.get(f"/recommendations/{rec_id}", headers=h("k-viewer")).json()
        assert detail["payload"]["recommendation"]["machine_id"] == "cnc-sim-01"
        assert len(detail["approvals"]) == 1
        assert client.get("/recommendations/nope", headers=h("k-viewer")).status_code == 404

    def test_not_enough_telemetry(self, services, clock):
        empty = replace(services, buffer=TelemetryBuffer())
        app = create_app(Settings(db_path=":memory:", ai4i_path=None), empty,
                         ApiKeyRegistry.from_plain_keys(KEYS))  # fmt: skip
        response = TestClient(app).post(
            "/machines/cnc-sim-01/recommendations", headers=h("k-alice")
        )
        assert response.status_code == 409


class TestApprovalWorkflow:
    def _pending(self, client, requester="k-alice"):
        return recommend(client, key=requester)["approvals"][0]["id"]

    def test_happy_path_is_fully_audited(self, client):
        approval_id = self._pending(client)
        approved = client.post(f"/approvals/{approval_id}/approve", headers=h("k-carol"),
                               json={"note": "Inspect at shift change"}).json()  # fmt: skip
        assert approved["status"] == "approved"
        assert approved["decided_by"] == "carol"
        done = client.post(f"/approvals/{approval_id}/complete", headers=h("k-bob"),
                           json={"note": "Coolant filter clogged; replaced"}).json()  # fmt: skip
        assert done["status"] == "completed"

        actions = [e["action"] for e in client.get("/audit", headers=h("k-carol")).json()]
        assert actions == [
            "recommendation.created",
            "approval.requested",
            "approval.approved",
            "approval.completed",
        ]
        assert client.get("/audit/verify", headers=h("k-carol")).json()["ok"] is True

    @pytest.mark.parametrize("key", ["k-alice", "k-bob", "k-viewer", "k-admin", "k-ingest"])
    def test_only_maintenance_leads_can_decide(self, client, key):
        approval_id = self._pending(client)
        for verb in ("approve", "reject"):
            response = client.post(f"/approvals/{approval_id}/{verb}", headers=h(key),
                                   json={"note": "x"})  # fmt: skip
            assert response.status_code == 403
        listing = client.get("/approvals?status=pending", headers=h("k-viewer")).json()
        assert [a["id"] for a in listing] == [approval_id]

    def test_four_eyes_rule(self, client):
        approval_id = self._pending(client, requester="k-carol")
        own = client.post(f"/approvals/{approval_id}/approve", headers=h("k-carol"))
        assert own.status_code == 403
        assert "Four-eyes" in own.json()["detail"]
        other = client.post(f"/approvals/{approval_id}/approve", headers=h("k-dave"))
        assert other.json()["status"] == "approved"

    def test_decisions_are_final(self, client):
        approval_id = self._pending(client)
        client.post(f"/approvals/{approval_id}/approve", headers=h("k-carol"))
        again = client.post(f"/approvals/{approval_id}/reject", headers=h("k-dave"),
                            json={"note": "changed my mind"})  # fmt: skip
        assert again.status_code == 409

    def test_rejection_needs_a_note(self, client):
        approval_id = self._pending(client)
        bare = client.post(f"/approvals/{approval_id}/reject", headers=h("k-carol"))
        assert bare.status_code == 409
        noted = client.post(f"/approvals/{approval_id}/reject", headers=h("k-carol"),
                            json={"note": "Inspected yesterday; known sensor offset"})  # fmt: skip
        assert noted.json()["status"] == "rejected"

    def test_cannot_complete_unapproved(self, client):
        approval_id = self._pending(client)
        response = client.post(f"/approvals/{approval_id}/complete", headers=h("k-bob"))
        assert response.status_code == 409
        assert client.post("/approvals/nope/complete", headers=h("k-bob")).status_code == 404
        assert client.post("/approvals/nope/approve", headers=h("k-carol")).status_code == 404

    def test_expired_requests_cannot_be_approved(self, client, clock):
        approval_id = self._pending(client)
        clock.now += timedelta(hours=9)
        response = client.post(f"/approvals/{approval_id}/approve", headers=h("k-carol"))
        assert response.status_code == 409
        assert "expired" in response.json()["detail"]
        audit = client.get(f"/audit?subject_id={approval_id}", headers=h("k-carol")).json()
        assert [e["action"] for e in audit] == ["approval.requested", "approval.expired"]
        listing = client.get("/approvals?status=expired", headers=h("k-viewer")).json()
        assert [a["id"] for a in listing] == [approval_id]

    def test_listing_expires_stale_requests(self, client, clock):
        self._pending(client)
        clock.now += timedelta(hours=9)
        assert client.get("/approvals?status=pending", headers=h("k-viewer")).json() == []


def _stop_result(services):
    class StopEngine:
        name = "stub"

        def recommend(self, bundle):
            return Recommendation(
                machine_id=bundle.machine_id,
                risk_level="high",
                summary="Temperature rising fast.",
                findings=[Finding(statement="Alarm", evidence_ids=["ANO-1"])],
                actions=[ProposedAction(action_type="request_stop", description="Stop",
                                        urgency="immediate", evidence_ids=["ANO-1"])],
                uncertainties=[],
            )  # fmt: skip

    from intelligence.agent.tools import AgentContext

    context = AgentContext(
        readings=services.buffer.frame("cnc-sim-01"),
        anomaly_monitor=services.monitor,
        registry=services.registry,
        retriever=services.retriever,
    )
    return OperationsAgent(context, StopEngine()).run("cnc-sim-01")


class TestApprovalService:
    def test_stop_request_needs_justification(self, services):
        result = _stop_result(services)
        tech = Principal("alice", Role.TECHNICIAN)
        lead = Principal("carol", Role.MAINTENANCE_LEAD)
        _, (approval,) = services.approvals.record_recommendation(result, tech, "full")
        assert approval["action_type"] == "request_stop"
        with pytest.raises(InvalidTransitionError, match="justification"):
            services.approvals.decide(approval["id"], lead, approve=True)
        decided = services.approvals.decide(
            approval["id"], lead, approve=True, note="Temperature rise confirmed on HMI"
        )
        assert decided["status"] == "approved"

    def test_viewer_cannot_record(self, services):
        result = _stop_result(services)
        with pytest.raises(ForbiddenError):
            services.approvals.record_recommendation(result, Principal("v", Role.VIEWER), "full")


class TestAuditChain:
    def _populated(self, services):
        result = _stop_result(services)
        services.approvals.record_recommendation(result, Principal("a", Role.TECHNICIAN), "full")
        services.approvals.record_recommendation(result, Principal("b", Role.TECHNICIAN), "full")
        return services.store

    def test_intact_chain_verifies(self, services):
        store = self._populated(services)
        check = store.verify_audit_chain()
        assert check.ok and check.records == 4

    def test_edited_record_is_detected(self, services):
        store = self._populated(services)
        store._conn.execute(
            "UPDATE audit_events SET details = ? WHERE seq = 2",
            (json.dumps({"action_type": "continue_monitoring"}),),
        )
        check = store.verify_audit_chain()
        assert not check.ok
        assert check.first_broken_seq == 2
        assert check.reason == "content modified"

    def test_deleted_record_is_detected(self, services):
        store = self._populated(services)
        store._conn.execute("DELETE FROM audit_events WHERE seq = 2")
        check = store.verify_audit_chain()
        assert not check.ok and check.first_broken_seq == 3
        assert check.reason == "broken link"

    def test_persists_across_restarts(self, tmp_path, services):
        path = tmp_path / "ops.db"
        store = OperationsStore(path)
        approvals = ApprovalService(store)
        approvals.record_recommendation(
            _stop_result(services), Principal("a", Role.TECHNICIAN), "full"
        )
        store.close()
        reopened = OperationsStore(path)
        assert reopened.verify_audit_chain().records == 2
        assert len(reopened.list_approvals(status="pending")) == 1


def test_serves_built_dashboard_same_origin(services, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>SpindleSage Operations</title>", "utf-8")
    app = create_app(
        Settings(db_path=":memory:", ai4i_path=None),
        services,
        ApiKeyRegistry.from_plain_keys(KEYS),
        dashboard_dir=dist,
    )
    client = TestClient(app)
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "/dashboard/"
    page = client.get("/dashboard/")
    assert page.status_code == 200
    assert "SpindleSage Operations" in page.text
    # Static files never bypass auth on data endpoints.
    assert client.get("/machines").status_code == 401


def test_no_dashboard_route_without_build(services, tmp_path):
    app = create_app(
        Settings(db_path=":memory:", ai4i_path=None),
        services,
        ApiKeyRegistry.from_plain_keys(KEYS),
        dashboard_dir=tmp_path / "missing",
    )
    assert TestClient(app).get("/dashboard/").status_code == 404
