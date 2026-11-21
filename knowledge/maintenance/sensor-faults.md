---
id: sensor-faults
title: Sensor and data faults
applies_to: cnc-sim-*
---

## Frozen or flatlined sensor

A sensor whose value stops changing completely, while the other signals keep varying normally, is usually a data problem rather than a machine problem. Real sensors always show some noise. A rolling variability of exactly zero over several minutes is a strong sign of a frozen sensor, a lost connection, or a data pipeline that is repeating the last value.

## Why it matters

A frozen sensor hides real changes. A frozen temperature reading can hide an overheating spindle; a frozen torque reading can hide a broken tool. Until the sensor is fixed, decisions should not rely on that signal.

## Checks

- Compare the frozen value with a redundant or handheld measurement where possible.
- Check the sensor cable, connector and signal conditioning.
- Check the data pipeline: gateway status, MQTT or OPC UA connection, and whether timestamps are still advancing.

## Recommended response

Flag the affected signal as untrusted, request a sensor and data-path check, and lower confidence in any prediction that uses that signal. Do not treat a flatlined value as evidence that the machine is healthy.
