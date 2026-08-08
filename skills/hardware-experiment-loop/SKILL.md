---
name: hardware-experiment-loop
description: >
  Use when experiments touch physical devices, power supplies, profilers, radios, sensors, batteries, or exclusive hardware resources. Do not use for software-only runs or to bypass preflight, leases, calibration, and human safety limits.
---
# Hardware Experiment Loop

## Trigger contract

Own hardware-specific safety, topology, calibration, exclusive-resource leases, actuation, and measurement provenance. Invocation is normally proposed before execution and always requires the configured approval boundary.

## Progressive loading

Read `references/HARDWARE_PROTOCOL.md` and the project hardware envelope only after the user approves this capability. Use `scripts/preflight.py` before any write or power action.

## Procedure

1. Discover exact boards, instruments, ports, firmware, switches, power sources, and shared grounds.
2. Load the approved voltage/current/radio/thermal envelope from `.researchops/state/hardware/`.
3. Acquire exclusive leases and record topology photographs or diagrams when wiring matters.
4. Run read-only preflight first; ask for human confirmation for ambiguous physical state.
5. Separate flashing/debug configuration from measurement configuration.
6. Calibrate or quantify instrument offset and background load.
7. Execute bounded runs with emergency stop conditions and raw plus derived data manifests.
8. Release devices and restore a known-safe state.

## Output contract

Return topology, preflight result, approval, leases, calibration, commands, firmware/config hashes, measurements, failures, safety events, and restoration status.
