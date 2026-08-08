# State and memory

## Three different things

### Authoritative project state

Designs, runs, evidence, decisions, approvals, and registered artifacts under `.researchops/state/`.

### Authoritative model-intelligence state

Evaluation events, profiles, route decisions, endpoint/price/identity observations, failure patterns, mitigations, warmup, Judge calibration, and memory metadata in `.researchops/intelligence/state.sqlite`.

### Recall memory

Optional retrieval used to find similar tasks, past decisions, representative failures, or project terminology. Recall is helpful but non-authoritative.

## Why ROPS owns authority

A closed Harness memory service can change retention, ranking, schema, or product behavior. ROPS must remain reproducible and portable when that service is unavailable. External memory is therefore an adapter, not a dependency for correctness.

## Default retrieval stack

```text
exact SQL / explicit artifact lookup
  → SQLite FTS5 lexical recall
  → optional vector retrieval
  → optional external Harness/Agent-memory adapter
  → scope, time, confidence and provenance reranking
```

An old memory sentence such as “Model X is cheap” cannot override the current effective-dated price rule. A semantically similar failure cannot automatically become an active model pattern. Retrieval results must point back to provenance.

## Built-in Memory v2.1

The built-in implementation goes beyond a flat FTS index while remaining local-first:

- **episodic:** accepted work units and representative project events;
- **semantic:** current project facts, decisions, terminology, and stable conclusions;
- **procedural:** failure patterns, mitigations, checklists, and reusable execution lessons;
- **preference:** explicit user/project preferences that affect utility or presentation.

Each item has a scope, lifecycle (`candidate`, `active`, `superseded`, `retired`), confidence, salience, validity interval, source identity, metadata, and provenance. Scoped content hashes deduplicate repeated writes. Source-aware updates can supersede prior versions rather than silently mutating history. Relations include `supersedes`, `derived_from`, `supports`, `contradicts`, `mitigates`, and `related_to`.

`memory-sync` derives bounded recall items from the current intake, project decisions, accepted Evaluation Events, active failure patterns, and approved mitigations. Repeated synchronization is idempotent. `memory-context` returns a size-bounded, provenance-bearing context package explicitly marked non-authoritative.

```bash
python3 -m rops intelligence --root /path/to/project memory-status
python3 -m rops intelligence --root /path/to/project memory-sync
python3 -m rops intelligence --root /path/to/project memory-search \
  "why was this baseline retained" --scope project/my-project
python3 -m rops intelligence --root /path/to/project memory-context \
  "constraints for the next debugging task" --scope project/my-project/task/debug
```

A dedicated vector or graph database is not required for correctness. The Recall Adapter boundary permits vector, temporal-graph, or Harness-memory backends when an evaluation demonstrates better retrieval or context efficiency. Exact SQL and provenance checks remain ahead of semantic recall.

## Adapter boundary

An external adapter may search or publish approved memory items. It cannot:

- update a competence profile directly;
- approve or activate a mitigation;
- authorize a high-risk tool operation;
- replace exact current price or endpoint facts;
- merge project scopes without policy.

External publishing should default to off because it may disclose project information.

## Memory evaluation

The Product Benchmark checks deduplication, supersession, temporal validity, retired/superseded exclusion, project-scope isolation, provenance coverage, four-layer operation, bounded context assembly, search latency, and idempotent project synchronization. Future vector/graph adapters should be accepted only if they improve task-level retrieval or reduce context cost without increasing stale/conflicting recall.
