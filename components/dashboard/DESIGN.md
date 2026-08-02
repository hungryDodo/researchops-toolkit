# Research Dashboard Design Contract

## Thesis
A full-screen research control surface that makes the next decision, blockers, evidence coverage, active experiments, agent activity, storage pressure, and required human actions visible without reading terminal streams.

## Layout
Use the full viewport. Desktop uses a dense but breathable grid with local card scrolling rather than a narrow centered column or long page scroll. Small screens collapse to a single readable flow.

## Tokens
- Typography: system sans for interface; monospace only for IDs/paths/metrics.
- Spacing: 4/8/12/16/24/32 px scale.
- Surfaces: restrained neutral layers; status is never conveyed by color alone.
- Motion: only state transitions and attention cues; honor `prefers-reduced-motion`.

## Information order
1. Objective, phase, next gate, health, blocker.
2. Human actions and decisions.
3. Routes/experiments/evidence.
4. Agents, storage/worktrees, hygiene, literature.
5. Compact event history linked to artifacts.

## Signature
A persistent “next gate” rail that connects current evidence to the next human/agent action.

## Prohibitions
No secret values, raw logs, giant tables, ornamental gradients that reduce legibility, bare internal IDs as public labels, or animation without information value.
