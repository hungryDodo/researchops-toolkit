---
name: research-writing
description: >
  Use when drafting evidence-gated paper prose or revising an existing LaTeX manuscript from author, advisor, or reviewer feedback. Do not use before the logic and key claims are settled, or to invent results, citations, novelty, or unsupported fixes.
---
# Research Writing

## Trigger contract

Own linguistic realization and manuscript revision. Drafting and revision share the same evidence map, claim calibration, authorship boundary, and rendered-document validation, so they are modes.

## Progressive loading

- `draft`: `references/WRITING_PROTOCOL.md`;
- `revise`: `references/REVISION_PROTOCOL.md`;
- LaTeX discovery/inspection: `scripts/latex_audit.py`.

## Hard rules

1. Every factual claim traces to user materials, verified retrieval, or field-common knowledge without specific numbers/names/comparisons.
2. Claim strength never exceeds evidence strength.
3. Real, planned, expected, and hypothetical results are phrased differently.
4. Internal IDs and planning notes do not leak into public prose.
5. Feedback that requires new scientific evidence routes back to experimentation; it is not repaired by wording.
6. For LaTeX, source is the editable authority and compiled PDF is the visual authority.

## Draft mode

Use approved claims and outline to draft clean prose, maintain an evidence map, verify citations independently where possible, and surface unresolved scientific gaps separately from the manuscript.

## Revise mode

Map each comment to location, type, severity, proposed change, evidence need, decision, and verification. Preserve author intent, compile, and inspect the rendered PDF after structural or visual changes.

## Output contract

Produce manuscript text or patch, evidence map, feedback ledger when applicable, citation verification status, compile/visual QA result, unresolved evidence needs, and files changed.
