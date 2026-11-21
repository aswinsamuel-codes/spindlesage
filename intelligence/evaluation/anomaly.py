"""Event-level evaluation of alarm streams against labelled fault windows.

Definitions (all per machine, rows ordered by machine then time):

* Alarm episode: a maximal run of consecutive alarmed samples.
* True episode: overlaps a fault window, extended by `grace` after the fault
  ends (rolling features and persistence make alarms outlast the fault).
* Detection recall: fraction of fault events with at least one alarm inside
  [start, end).
* Detection precision: true episodes / all episodes.
* False alarms per operating hour: false episodes / healthy operating hours
  (samples outside every fault window).
* Detection delay: time from fault start to the first alarm inside the window,
  over detected events only.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta

import numpy as np
import pandas as pd

from integrations.simulator.cnc import FaultEvent


def _delay_stats(delays: list[float]) -> dict | None:
    if not delays:
        return None
    arr = np.asarray(delays, dtype=float)
    return {"mean": float(arr.mean()), "median": float(np.median(arr)), "max": float(arr.max())}


def evaluate_alarms(
    readings: pd.DataFrame,
    alarm: np.ndarray,
    events: Iterable[FaultEvent],
    sample_interval: timedelta,
    grace: timedelta = timedelta(minutes=10),
) -> dict:
    alarm = np.asarray(alarm, dtype=bool)
    if len(alarm) != len(readings):
        raise ValueError("alarm must have one entry per reading")

    # Compare everything as naive UTC datetime64 for fast, unambiguous numpy maths.
    timestamps = pd.to_datetime(readings["timestamp"], utc=True).dt.tz_localize(None).to_numpy()
    machines = readings["machine_id"].to_numpy()
    in_fault = np.zeros(len(readings), dtype=bool)
    near_fault = np.zeros(len(readings), dtype=bool)

    events = list(events)
    by_type: dict[str, dict] = {}
    detected = 0
    delays: list[float] = []
    for event in events:
        start = pd.Timestamp(event.start).tz_convert("UTC").tz_localize(None).to_datetime64()
        end = pd.Timestamp(event.end).tz_convert("UTC").tz_localize(None).to_datetime64()
        same_machine = machines == event.machine_id
        window = same_machine & (timestamps >= start) & (timestamps < end)
        in_fault |= window
        near_fault |= same_machine & (timestamps >= start) & (timestamps < end + grace)

        stats = by_type.setdefault(event.fault_type, {"events": 0, "detected": 0, "delays": []})
        stats["events"] += 1
        hits = timestamps[window & alarm]
        if len(hits):
            detected += 1
            delay = float((hits.min() - start) / np.timedelta64(1, "s"))
            delays.append(delay)
            stats["detected"] += 1
            stats["delays"].append(delay)

    new_machine = np.r_[True, machines[1:] != machines[:-1]]
    previous_alarm = np.r_[False, alarm[:-1]] & ~new_machine
    episode_start = alarm & ~previous_alarm
    episode_id = np.cumsum(episode_start)
    alarmed = np.flatnonzero(alarm)
    if len(alarmed):
        episode_true = pd.Series(near_fault[alarmed]).groupby(episode_id[alarmed]).any()
        n_episodes = int(len(episode_true))
        n_true = int(episode_true.sum())
    else:
        n_episodes = n_true = 0
    n_false = n_episodes - n_true

    healthy_hours = float((~in_fault).sum()) * sample_interval.total_seconds() / 3600.0
    tp = int((alarm & in_fault).sum())
    fp = int((alarm & ~in_fault).sum())
    fn = int((~alarm & in_fault).sum())
    point_precision = tp / (tp + fp) if tp + fp else 0.0
    point_recall = tp / (tp + fn) if tp + fn else 0.0
    point_f1 = (
        2 * point_precision * point_recall / (point_precision + point_recall)
        if point_precision + point_recall
        else 0.0
    )

    return {
        "events": len(events),
        "detected_events": detected,
        "detection_recall": detected / len(events) if events else None,
        "alarm_episodes": n_episodes,
        "false_alarm_episodes": n_false,
        "detection_precision": n_true / n_episodes if n_episodes else 0.0,
        "healthy_hours": healthy_hours,
        "false_alarms_per_hour": n_false / healthy_hours if healthy_hours else None,
        "detection_delay_s": _delay_stats(delays),
        "per_fault_type": {
            fault_type: {
                "events": s["events"],
                "detected": s["detected"],
                "recall": s["detected"] / s["events"],
                "delay_s": _delay_stats(s["delays"]),
            }
            for fault_type, s in sorted(by_type.items())
        },
        "pointwise": {"precision": point_precision, "recall": point_recall, "f1": point_f1},
    }
