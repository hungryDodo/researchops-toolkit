# Behavior runtime

Behavior packs are cross-cutting execution constraints. They are not user-facing workflow Skills and they do not own project state. The deterministic runtime may block or require explicit approval for risky actions; semantic guidance is loaded only when applicable.

High-risk operation approval and prompt-mitigation approval are intentionally separate. A mitigation can improve model behavior but can never authorize deletion, force-push, external disclosure, hardware writes, or other consequential actions.
