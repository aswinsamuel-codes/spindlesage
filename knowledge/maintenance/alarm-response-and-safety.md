---
id: alarm-response-and-safety
title: Alarm response and safety rules
applies_to: cnc-sim-*
---

## Human approval

SpindleSage only recommends. It never sends commands to a PLC or CNC controller. Every proposed operational action, including stopping a machine, scheduling maintenance or changing a tool, must be reviewed and approved by an authorised person before anyone acts on it.

## Lockout before inspection

Before any inspection that involves reaching into the machine, the machine must be stopped and isolated from energy sources using the site's lockout and tagout procedure. Recommendations that involve physical inspection should remind the reader of this.

## Triage of an anomaly alarm

1. Confirm the alarm is not a data problem: are timestamps advancing and are the signals still varying?
2. Identify which signals drove the alarm and whether they change together (for example torque and power) or alone.
3. Check the recent maintenance history for related work.
4. Decide on the least disruptive safe action: continue monitoring, inspect at the next stop, or request an immediate stop.

## Uncertainty

When the evidence is weak or conflicting, say so plainly and prefer continued monitoring with a clear trigger for escalation over a confident but unsupported conclusion. Predictions from models trained on benchmark or simulated data are not calibrated for a specific real machine.
