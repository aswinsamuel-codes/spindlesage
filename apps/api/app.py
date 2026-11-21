"""SpindleSage REST API.

Read-only by design towards machines: there is no endpoint that sends
anything to a PLC or CNC. Write endpoints only add telemetry, ask the agent
for a recommendation, or record human approval decisions, and every one of
those writes an audit record.
"""

# No "from __future__ import annotations" in this module: FastAPI must resolve
# the dependency aliases defined inside create_app() when routes are declared.

from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from apps.api.auth import ApiKeyRegistry
from apps.api.services import Services, build_services
from apps.api.settings import Settings
from core.event_engine.approvals import ApprovalError
from core.event_engine.roles import Permission, Principal
from core.telemetry.schema import CncTelemetryReading
from intelligence.agent.agent import OperationsAgent
from intelligence.agent.tools import AgentContext

API_VERSION = "0.1.0"
MIN_READINGS_FOR_AGENT = 10


class TelemetryBatch(BaseModel):
    readings: list[CncTelemetryReading] = Field(min_length=1, max_length=1000)


class RecommendationRequest(BaseModel):
    mode: Literal["full", "sensor_only"] = "full"


class DecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


def create_app(
    settings: Settings | None = None,
    services: Services | None = None,
    keys: ApiKeyRegistry | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    services = services or build_services(settings)
    keys = keys if keys is not None else ApiKeyRegistry.from_file(settings.api_keys_file)

    app = FastAPI(
        title="SpindleSage API",
        version=API_VERSION,
        description="Evidence-grounded maintenance recommendations with human approval. "
        "All data in this research build is simulated or from synthetic benchmarks.",
    )
    app.state.services = services

    @app.exception_handler(ApprovalError)
    async def approval_error(_: Request, exc: ApprovalError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    def current_principal(
        x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    ) -> Principal:
        principal = keys.authenticate(x_api_key)
        if principal is None:
            raise HTTPException(status_code=401, detail="Missing or invalid API key")
        return principal

    def require(permission: Permission):
        def dependency(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
            if not principal.can(permission):
                raise HTTPException(
                    status_code=403,
                    detail=f"Role {principal.role} lacks permission {permission.value}",
                )
            return principal

        return dependency

    Reader = Annotated[Principal, Depends(require(Permission.READ))]

    def known_machine(machine_id: str) -> str:
        try:
            services.registry.get(machine_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"Unknown machine {machine_id}") from None
        return machine_id

    Machine = Annotated[str, Depends(known_machine)]

    # -- service --------------------------------------------------------------

    @app.get("/health")
    def health() -> dict:
        return {
            "status": "ok",
            "version": API_VERSION,
            "engine": services.engine.name,
            "data_nature": "synthetic",
            "demo_scenario": services.demo_scenario,
            "anomaly_monitor_calibration": services.monitor_calibration,
            "failure_risk_model": "loaded" if services.risk_model else "not loaded",
            "api_keys_configured": len(keys),
            "machine_control": "none (read-only towards machines)",
        }

    @app.get("/me")
    def me(principal: Annotated[Principal, Depends(current_principal)]) -> dict:
        return {
            "user_id": principal.user_id,
            "role": principal.role.value,
            "permissions": sorted(p.value for p in Permission if principal.can(p)),
        }

    # -- machines and telemetry --------------------------------------------------

    @app.get("/machines")
    def list_machines(_: Reader) -> list[dict]:
        out = []
        for machine_id in services.registry.machine_ids():
            latest = services.buffer.latest(machine_id, 1)
            out.append(
                {
                    **services.registry.get(machine_id).model_dump(mode="json"),
                    "readings_buffered": services.buffer.count(machine_id),
                    "last_reading_utc": latest[0].timestamp.isoformat() if latest else None,
                    "pending_approvals": len(
                        services.store.list_approvals(status="pending", machine_id=machine_id)
                    ),
                }
            )
        return out

    @app.get("/machines/{machine_id}")
    def get_machine(machine_id: Machine, _: Reader) -> dict:
        return {
            **services.registry.get(machine_id).model_dump(mode="json"),
            "maintenance_history": [
                r.model_dump(mode="json") for r in services.registry.history(machine_id)
            ],
        }

    @app.get("/machines/{machine_id}/telemetry")
    def get_telemetry(
        machine_id: Machine, _: Reader, limit: Annotated[int, Query(ge=1, le=2880)] = 120
    ) -> dict:
        readings = services.buffer.latest(machine_id, limit)
        return {
            "machine_id": machine_id,
            "data_nature": "synthetic",
            "readings": [r.model_dump(mode="json") for r in readings],
        }

    @app.get("/machines/{machine_id}/status")
    def machine_status(machine_id: Machine, _: Reader) -> dict:
        frame = services.buffer.frame(machine_id, 60)
        latest = services.buffer.latest(machine_id, 1)
        anomaly = None
        if len(frame) >= MIN_READINGS_FOR_AGENT:
            anomaly = services.monitor.assess(frame).to_dict()
        return {
            "machine_id": machine_id,
            "latest_reading": latest[0].model_dump(mode="json") if latest else None,
            "anomaly": anomaly,
            "pending_approvals": len(
                services.store.list_approvals(status="pending", machine_id=machine_id)
            ),
        }

    @app.post("/telemetry", status_code=202)
    def ingest(
        batch: TelemetryBatch,
        _: Annotated[Principal, Depends(require(Permission.INGEST_TELEMETRY))],
    ) -> dict:
        accepted, rejected, warnings = 0, [], 0
        for reading in batch.readings:
            if reading.machine_id not in services.registry.machine_ids():
                rejected.append(
                    {"machine_id": reading.machine_id, "timestamp": reading.timestamp.isoformat(),
                     "issues": [{"rule": "unknown_machine", "severity": "error"}]}
                )  # fmt: skip
                continue
            outcome = services.buffer.add(reading)
            warnings += len(outcome.validation.warnings)
            if outcome.accepted:
                accepted += 1
            else:
                rejected.append(
                    {
                        "machine_id": reading.machine_id,
                        "timestamp": reading.timestamp.isoformat(),
                        "issues": [
                            {"rule": i.rule, "severity": str(i.severity), "message": i.message}
                            for i in outcome.validation.errors
                        ],
                    }
                )
        return {"accepted": accepted, "rejected": rejected, "warnings": warnings}

    # -- recommendations ------------------------------------------------------------

    @app.post("/machines/{machine_id}/recommendations", status_code=201)
    def create_recommendation(
        machine_id: Machine,
        principal: Annotated[Principal, Depends(require(Permission.REQUEST_RECOMMENDATION))],
        body: RecommendationRequest | None = None,
    ) -> dict:
        mode = (body or RecommendationRequest()).mode
        frame = services.buffer.frame(machine_id)
        if len(frame) < MIN_READINGS_FOR_AGENT:
            raise HTTPException(
                status_code=409,
                detail=f"Need at least {MIN_READINGS_FOR_AGENT} readings for {machine_id}; "
                f"have {len(frame)}",
            )
        context = AgentContext(
            readings=frame,
            anomaly_monitor=services.monitor,
            risk_model=services.risk_model,
            registry=services.registry,
            retriever=services.retriever,
        )
        result = OperationsAgent(context, services.engine).run(machine_id, mode)
        recommendation_id, approvals = services.approvals.record_recommendation(
            result, principal, mode
        )
        return {
            "recommendation_id": recommendation_id,
            **result.to_dict(),
            "approvals": approvals,
        }

    @app.get("/recommendations")
    def list_recommendations(
        _: Reader,
        machine_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ) -> list[dict]:
        rows = services.store.list_recommendations(machine_id, limit)
        return [
            {
                k: row[k]
                for k in ("id", "machine_id", "created_utc", "requested_by", "engine", "mode",
                          "risk_level", "approval_status")
            }
            | {"summary": row["payload"]["recommendation"]["summary"]}
            for row in rows
        ]  # fmt: skip

    @app.get("/recommendations/{recommendation_id}")
    def get_recommendation(recommendation_id: str, _: Reader) -> dict:
        row = services.store.get_recommendation(recommendation_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        return {
            **row,
            "approvals": services.store.list_approvals(recommendation_id=recommendation_id),
        }

    # -- approvals ------------------------------------------------------------------

    @app.get("/approvals")
    def list_approvals(
        _: Reader,
        status: Literal["pending", "approved", "rejected", "expired", "completed"] | None = None,
        machine_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[dict]:
        services.approvals.expire_stale()
        return services.store.list_approvals(status=status, machine_id=machine_id, limit=limit)

    @app.post("/approvals/{approval_id}/approve")
    def approve(
        approval_id: str,
        principal: Annotated[Principal, Depends(current_principal)],
        body: DecisionRequest | None = None,
    ) -> dict:
        return services.approvals.decide(
            approval_id, principal, approve=True, note=(body or DecisionRequest()).note
        )

    @app.post("/approvals/{approval_id}/reject")
    def reject(
        approval_id: str,
        principal: Annotated[Principal, Depends(current_principal)],
        body: DecisionRequest | None = None,
    ) -> dict:
        return services.approvals.decide(
            approval_id, principal, approve=False, note=(body or DecisionRequest()).note
        )

    @app.post("/approvals/{approval_id}/complete")
    def complete(
        approval_id: str,
        principal: Annotated[Principal, Depends(current_principal)],
        body: DecisionRequest | None = None,
    ) -> dict:
        return services.approvals.complete(
            approval_id, principal, note=(body or DecisionRequest()).note
        )

    # -- audit ------------------------------------------------------------------------

    @app.get("/audit")
    def audit(
        _: Annotated[Principal, Depends(require(Permission.READ_AUDIT))],
        subject_id: str | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict]:
        return services.store.audit_events(subject_id, limit, offset)

    @app.get("/audit/verify")
    def verify_audit(_: Annotated[Principal, Depends(require(Permission.READ_AUDIT))]) -> dict:
        return services.store.verify_audit_chain().to_dict()

    return app
