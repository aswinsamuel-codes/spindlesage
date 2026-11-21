"""OPC UA -> SpindleSage API collector. Read-only.

Connects to an OPC UA server, browses the machines under the SpindleSage
folder, and polls their variables. Each new sample (a changed SampleTime)
becomes one telemetry reading forwarded to the API.

The collector only browses and reads. It contains no write, method-call or
node-management operation, and tests/test_integrations.py checks this file's
source for them, so it cannot be turned into a control path by accident.

For real equipment use a secured endpoint, e.g.
    security="Basic256Sha256,SignAndEncrypt,client-cert.der,client-key.pem"
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from datetime import UTC

from asyncua import Client
from pydantic import ValidationError

from core.telemetry.schema import CncTelemetryReading
from integrations.opcua.nodes import NAMESPACE_URI, ROOT_FOLDER, VARIABLE_MAP

log = logging.getLogger(__name__)


@dataclass
class CollectorStats:
    polls: int = 0
    readings: int = 0
    unchanged: int = 0
    invalid: int = 0
    errors: list[str] = field(default_factory=list)


class OpcUaCollector:
    def __init__(
        self,
        endpoint: str,
        forward,
        interval_s: float = 1.0,
        security: str | None = None,
        timeout_s: float = 10.0,
    ):
        """`forward(reading)` is called for each new reading (e.g. TelemetryForwarder.add)."""
        self.endpoint = endpoint
        self.forward = forward
        self.interval_s = interval_s
        self.security = security
        self.timeout_s = timeout_s
        self.stats = CollectorStats()
        self._last_sample: dict[str, object] = {}

    async def _discover(self, client: Client) -> dict[str, dict[str, object]]:
        idx = await client.get_namespace_index(NAMESPACE_URI)
        folder = await client.nodes.objects.get_child(f"{idx}:{ROOT_FOLDER}")
        machines: dict[str, dict[str, object]] = {}
        for machine in await folder.get_children():
            machine_id = (await machine.read_browse_name()).Name
            variables = {}
            for child in await machine.get_children():
                name = (await child.read_browse_name()).Name
                if name in VARIABLE_MAP:
                    variables[name] = child
            missing = set(VARIABLE_MAP) - set(variables)
            if missing:
                log.warning("Skipping %s: missing variables %s", machine_id, sorted(missing))
                continue
            machines[machine_id] = variables
        if not machines:
            raise RuntimeError(f"No machines found under {ROOT_FOLDER} on {self.endpoint}")
        return machines

    async def poll_once(self, client: Client, machines: dict[str, dict[str, object]]) -> int:
        """Read every machine once and forward new samples. Returns readings forwarded."""
        self.stats.polls += 1
        names = list(VARIABLE_MAP)
        forwarded = 0
        for machine_id, variables in machines.items():
            values = await client.read_values([variables[n] for n in names])
            sample = dict(zip(names, values, strict=True))
            stamp = sample["SampleTime"]
            if self._last_sample.get(machine_id) == stamp:
                self.stats.unchanged += 1
                continue
            self._last_sample[machine_id] = stamp
            if stamp.tzinfo is None:  # OPC UA DateTime is UTC
                stamp = stamp.replace(tzinfo=UTC)
            try:
                reading = CncTelemetryReading(
                    machine_id=machine_id,
                    timestamp=stamp,
                    **{VARIABLE_MAP[n]: sample[n] for n in names if n != "SampleTime"},
                )
            except ValidationError as exc:
                self.stats.invalid += 1
                self.stats.errors = [*self.stats.errors[-9:], f"{machine_id}: {exc}"]
                continue
            await asyncio.to_thread(self.forward, reading)
            self.stats.readings += 1
            forwarded += 1
        return forwarded

    async def run(self, stop: asyncio.Event | None = None, max_polls: int | None = None) -> None:
        stop = stop or asyncio.Event()
        client = Client(url=self.endpoint, timeout=self.timeout_s)
        if self.security:
            await client.set_security_string(self.security)
        else:
            log.warning(
                "Connecting to %s without OPC UA security (development only)", self.endpoint
            )
        async with client:
            machines = await self._discover(client)
            log.info("Collecting from %d machines: %s", len(machines), ", ".join(machines))
            while not stop.is_set():
                await self.poll_once(client, machines)
                if max_polls is not None and self.stats.polls >= max_polls:
                    break
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=self.interval_s)
