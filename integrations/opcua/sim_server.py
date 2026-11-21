"""OPC UA server that simulates the CNC cell (SYNTHETIC DATA).

Stands in for machine controllers during development. Every variable is
read-only for clients: the server never calls set_writable(), so a client
write is refused by the server itself.

Security: the simulator offers only the unsecured endpoint and binds to
127.0.0.1 by default. Never expose it on a real network.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from asyncua import Server, ua

from integrations.opcua.nodes import DEFAULT_ENDPOINT, NAMESPACE_URI, ROOT_FOLDER, VARIABLE_MAP
from integrations.simulator.live import scenario_frames

log = logging.getLogger(__name__)

_INITIAL = {
    "AirTemperature": 0.0,
    "ProcessTemperature": 0.0,
    "SpindleSpeed": 0.0,
    "Torque": 0.0,
    "ToolWear": 0.0,
    "ProductType": "",
    "SampleTime": datetime(2000, 1, 1, tzinfo=UTC),
}


class SimulatedCellServer:
    def __init__(
        self,
        endpoint: str = DEFAULT_ENDPOINT,
        scenario: str = "healthy",
        seed: int = 0,
        speed: float = 30.0,
        hours: float = 6.0,
        loop: bool = False,
    ):
        self.endpoint = endpoint
        self.frames = scenario_frames(scenario, seed, hours)
        self.interval = 30.0 / speed
        self.loop = loop
        self.samples_served = 0
        self.ready = asyncio.Event()
        self._variables: dict[str, dict[str, object]] = {}

    async def _build(self) -> Server:
        server = Server()
        await server.init()
        server.set_endpoint(self.endpoint)
        server.set_server_name("SpindleSage simulated CNC cell (synthetic data)")
        server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        idx = await server.register_namespace(NAMESPACE_URI)
        folder = await server.nodes.objects.add_folder(idx, ROOT_FOLDER)
        for machine_id in sorted(self.frames[0]["machine_id"].unique()):
            machine = await folder.add_object(idx, machine_id)
            self._variables[machine_id] = {
                name: await machine.add_variable(idx, name, value)
                for name, value in _INITIAL.items()
            }
        return server

    async def _publish_frame(self, frame) -> None:
        stamp = datetime.now(UTC)
        for row in frame.to_dict("records"):
            nodes = self._variables[row["machine_id"]]
            for name, field in VARIABLE_MAP.items():
                if name == "SampleTime":
                    value = stamp
                elif name == "ProductType":
                    value = str(row[field])
                else:
                    value = float(row[field])
                await nodes[name].write_value(value)
        self.samples_served += 1

    async def run(self, stop: asyncio.Event | None = None) -> None:
        stop = stop or asyncio.Event()
        server = await self._build()
        async with server:
            await self._publish_frame(self.frames[0])
            self.ready.set()
            log.info("OPC UA simulator listening on %s", self.endpoint)
            index = 1
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=self.interval)
                    break
                except TimeoutError:
                    pass
                if index >= len(self.frames):
                    if not self.loop:
                        continue  # hold the last values until stopped
                    index = 0
                await self._publish_frame(self.frames[index])
                index += 1
