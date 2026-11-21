"""Named fault scenarios shared by the agent demo, the API demo mode and the
live MQTT / OPC UA replays (SYNTHETIC DATA).

Each scenario puts one fault on DEMO_MACHINE during the last 90 minutes of a
window, so the fault is active, and growing, when the window ends.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from integrations.simulator.cnc import FAULT_TYPES, FaultEvent

SCENARIOS: tuple[str, ...] = ("healthy", *FAULT_TYPES)
DEMO_MACHINE = "cnc-sim-01"
FAULT_LEAD_TIME = timedelta(minutes=90)
_MAGNITUDE = {
    "spindle_overheat": 7.0,
    "torque_spike": 0.5,
    "speed_drift": 200.0,
    "sensor_flatline": 0.0,
}


def scenario_fault(
    scenario: str, window_start: datetime, window_duration: timedelta
) -> tuple[FaultEvent, ...]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unknown scenario {scenario!r}; choose from {SCENARIOS}")
    if scenario == "healthy":
        return ()
    end = window_start + window_duration
    return (
        FaultEvent(
            machine_id=DEMO_MACHINE,
            fault_type=scenario,
            start=end - FAULT_LEAD_TIME,
            end=end,
            magnitude=_MAGNITUDE[scenario],
            sensor="torque_nm" if scenario == "sensor_flatline" else None,
        ),
    )
