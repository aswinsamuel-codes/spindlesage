---
id: tool-wear-and-breakage
title: Tool wear, chipping and breakage
applies_to: cnc-sim-*
---

## Tool wear limits

Tool wear on the simulated cell is tracked as minutes of cutting since the last tool change. Tools are normally replaced between 180 and 220 minutes of cutting. Beyond about 200 minutes the risk of tool wear failure rises quickly, and above 240 minutes the tool should be treated as overdue.

## Torque spike symptoms

A sudden step increase in spindle torque of 30 percent or more, with the spindle speed unchanged, is a typical sign of a chipped or broken cutting edge or of a tool that has picked up material. Because the speed has not changed, the mechanical cutting power rises by the same proportion. A new job usually changes speed and torque together, which distinguishes it from a tool problem.

## Checks

With the machine stopped and isolated:

- Inspect the cutting edges for chipping, built-up edge or breakage.
- Check the tool holder and clamping.
- Check the last parts produced for surface finish or dimensional problems.
- Compare the recorded tool wear with the planned replacement interval.

## Recommended response

For a torque spike with unchanged speed, request a tool inspection before further cutting. For a tool past its wear limit, schedule a tool change at the next safe opportunity. Repeated torque spikes on new tools suggest a process or material problem rather than tool wear, and should be escalated to the process engineer.
