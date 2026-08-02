# Top-level Skill granularity rules

Score a proposed top-level Skill on six questions, 0 or 1 each:

1. Stable user-recognizable intent?
2. Distinct authoritative artifact?
3. Distinct permission/tool/risk boundary?
4. Independently testable trigger and output?
5. Delayed loading saves meaningful context?
6. Not co-invoked with an existing Skill in most realistic cases?

Guidance:

- 5–6: usually separate top-level Skill.
- 3–4: usually a mode/reference; separate only for strong safety isolation.
- 0–2: merge into an owner or keep as a component/script.

Also merge when two Skills share the same state, inputs, permissions, and lifecycle owner. A different noun is not enough reason to create a Skill.
