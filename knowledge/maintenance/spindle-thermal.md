---
id: spindle-thermal
title: Spindle thermal problems
applies_to: cnc-sim-*
---

## Symptoms

A spindle that is overheating shows a process temperature that keeps rising relative to ambient air temperature while the cutting load stays roughly the same. On the simulated cell the normal temperature rise over ambient is about 9 to 11 K. A rise that climbs steadily beyond that range over tens of minutes points to a thermal problem rather than a change of job.

## Likely causes

Common causes, roughly in order of how often they occur:

1. Coolant flow reduced or blocked (clogged filter, low coolant level, failed pump).
2. Spindle bearing lubrication degraded or insufficient.
3. Excessive bearing preload after recent spindle work.
4. Sustained cutting at high power without adequate coolant.
5. Ambient temperature far above normal (check the air temperature first).

## Checks

Perform these checks with the machine stopped and isolated according to the lockout procedure:

- Check coolant level and filter condition; confirm flow at the nozzle when the machine is safely restarted for a test.
- Check the spindle lubrication unit for level, pressure and recent alarms.
- Review the maintenance history for recent spindle or bearing work.
- Compare the temperature rise with the cutting power; a rise without a power increase is more serious.

## Recommended response

If the temperature rise keeps increasing, request that the operator reduce load or pause the job and schedule an inspection of coolant and spindle lubrication. Do not continue high-power cutting with an unexplained rising temperature. Any stop or inspection must be approved by the responsible maintenance lead.
