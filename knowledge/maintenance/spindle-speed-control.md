---
id: spindle-speed-control
title: Spindle speed deviation
applies_to: cnc-sim-*
---

## Symptoms

A spindle that cannot hold its commanded speed shows a slow downward drift in measured rotational speed while the job and set point have not changed. Speed on the simulated cell normally stays within a few rpm of the set point during a job.

## Detection limits

The current SpindleSage telemetry does not include the commanded spindle speed. Without it, a slow speed drift looks very similar to the start of a new job at a lower speed, so it is hard to detect reliably from measured speed alone. Treat any conclusion about speed drift as uncertain unless the commanded speed or job schedule confirms it.

## Likely causes

- Drive belt slipping or worn (belt-driven spindles).
- Spindle drive or motor fault.
- Speed encoder fault giving a wrong reading.
- Mechanical drag from bearing damage, often together with a temperature rise.

## Recommended response

Confirm the commanded speed from the controller or job schedule before acting. If the drift is confirmed, schedule an inspection of the drive, belt and encoder. If it comes with a rising temperature, follow the spindle thermal procedure as well.
