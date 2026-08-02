# Handoff protocol

Every role handoff includes:

- `handoff_id`, source role, destination role, timestamp;
- one-sentence objective;
- frozen assumptions and explicitly open assumptions;
- authoritative files and immutable run IDs;
- acceptance criteria and kill criteria;
- compute/hardware/time budget;
- allowed writes and forbidden actions;
- expected dashboard patches;
- human approval required: yes/no and why.

A receiving role must reject a handoff that lacks enough information to evaluate success without guessing.
