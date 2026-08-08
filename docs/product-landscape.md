# Product landscape and integration boundaries

ResearchOps overlaps several product categories, but no single category is an exact
substitute. This document prevents misleading comparisons and identifies practical
integration points.

## 1. Agent observability and LLM evaluation platforms

Representative products include AgentOps, Langfuse, Arize Phoenix, and Braintrust.
Their official documentation emphasizes traces, token/cost/latency inspection,
datasets, experiments, deterministic or LLM-based scorers, and comparison across runs.

- AgentOps: <https://docs.agentops.ai/v2/concepts/traces>
- Langfuse: <https://langfuse.com/docs>
- Phoenix: <https://arize.com/docs/phoenix>
- Braintrust: <https://www.braintrust.dev/docs/evaluate/run-evaluations>

### Overlap

- model calls, cost, latency, and traces;
- offline and online evaluation;
- datasets and experiment comparisons;
- dashboards and human review.

### ResearchOps distinction

ResearchOps treats a multi-stage project and its verified state change as the primary
unit. It adds existing-project adoption, Research/Development workflows, project gates,
model routing, warmup/soft transfer, failure-pattern/mitigation governance, and a
portable local authority under `.researchops/`.

These platforms are therefore plausible telemetry/evaluation backends, not necessarily
head-to-head replacements. A future OpenTelemetry/export adapter can send ResearchOps
spans outward while SQLite remains the project authority.

## 2. Scientific literature and research agents

PaperQA2 focuses on high-accuracy retrieval and synthesis over scientific literature,
including search, summarization, and contradiction-oriented tasks.

- PaperQA2 repository: <https://github.com/future-house/paper-qa>
- FutureHouse announcement: <https://www.futurehouse.org/research-announcements/wikicrow>

### Overlap

- traceable research discovery;
- literature-grounded answers;
- scientific task evaluation.

### ResearchOps distinction

ResearchOps is a lifecycle and governance layer spanning problem formulation,
experimental design/execution, research engineering, validation, writing,
communication, and model selection. PaperQA2 or another literature agent can be a
specialist used by `research-discovery`; ResearchOps should not reimplement its entire
retrieval stack without evidence that doing so improves the product.

## 3. Software-development agents and benchmarks

OpenHands provides an agent platform/SDK for software-engineering work. SWE-bench
provides reproducible tasks built from real GitHub issues and execution-based patch
verification.

- OpenHands: <https://github.com/OpenHands/openhands>
- SWE-bench: <https://github.com/swe-bench/SWE-bench>

### Overlap

- repository inspection and modification;
- tests and execution evidence;
- long-horizon task orchestration;
- agent/model comparison.

### ResearchOps distinction

ResearchOps does not attempt to replace the execution Harness. It supplies portable
workflow constraints, research-specific evidence semantics, project-state adoption,
model intelligence, and independent acceptance around whichever coding agent executes
the work.

SWE-bench is useful for the Development-led slice. It is insufficient by itself for
Research-led tasks, project adoption, Memory correctness, routing adaptation, or
multi-stage scientific outcomes.

## 4. Agent-memory systems

Representative systems include Mem0, Graphiti/Zep, and TencentDB Agent Memory.

- Mem0: <https://docs.mem0.ai/platform/features/graph-memory>
- Graphiti: <https://github.com/getzep/graphiti>
- TencentDB Agent Memory: <https://github.com/Tencent/TencentDB-Agent-Memory>

Their designs motivate extraction/consolidation, temporal validity, provenance,
hierarchical memory, hybrid retrieval, and graph relationships.

### Overlap

- persistent cross-session recall;
- consolidation rather than raw-history dumping;
- relationships and superseded facts;
- local or external retrieval backends.

### ResearchOps distinction

ResearchOps v2.1 uses Memory for project continuity and reuse while preserving a strict
boundary: Evaluation Events, approvals, prices, routing profiles, and verified evidence
remain authoritative relational state. Recall can suggest context but cannot silently
change policy. The built-in implementation provides four layers, lifecycle states,
source-aware deduplication/supersession, temporal validity, relations, project sync, and
provenance-bearing context bundles. External memory products can be connected through a
Recall Adapter when their added retrieval quality justifies operational complexity.

### Evaluation references

Longitudinal Memory must be tested as an evolving state rather than a static retrieval set.
Memora explicitly penalizes use of obsolete memories, while MemoryArena evaluates
interdependent multi-session tasks in which earlier experience must improve later actions.
These are better references for ResearchOps than a one-shot vector-search recall score.

- Memora: <https://arxiv.org/abs/2604.20006>
- MemoryArena: <https://digitaleconomy.stanford.edu/publication/memoryarena-benchmarking-agent-memory-in-interdependent-multi-session-agentic-tasks/>

## 5. Harness plugin systems

Codex and Claude Code expose installable skills/plugins and lifecycle hooks. ResearchOps
uses these as distribution/runtime surfaces rather than treating a single Harness as the
product authority.

- OpenAI plugin/skill concepts: <https://developers.openai.com/plugins/concepts/skills>
- Claude Code plugin reference: <https://code.claude.com/docs/en/plugins-reference>

## Comparison rule

A feature matrix is not a performance benchmark. Claims such as “better” are allowed
only when:

1. the compared tools execute an equivalent task and scope;
2. inputs, configuration, versions, and environment are recorded;
3. deterministic acceptance or calibrated human/Judge evaluation is available;
4. coverage differences are shown rather than hidden;
5. the result distinguishes complementarity from direct competition.

The executable Product Benchmark currently supports ResearchOps version-to-version
regression and a standardized external-report adapter. Third-party head-to-head results
must be produced by explicit adapters and equivalent fixtures.
