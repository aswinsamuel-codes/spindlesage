---
id: power-and-overstrain
title: Cutting power and overstrain
applies_to: cnc-sim-*
---

## Normal range

Mechanical cutting power is torque multiplied by angular speed. On the simulated cell jobs normally run at about 5 to 7 kW. Power far outside that band, in either direction, deserves attention.

## High power and overstrain

Sustained high power together with high tool wear increases the risk of overstrain failure: the tool or spindle is asked to remove more material than it can handle. Typical causes are an aggressive feed rate, a harder material batch than planned, or a worn tool that needs more force to cut.

## Low power

Very low power during a job can mean the tool is not engaging the workpiece, for example after a broken tool or a setup error.

## Recommended response

For high power with high tool wear, recommend a tool change and a review of feed and speed settings with the process engineer. For unexplained low power, recommend checking the tool and the setup before continuing.
