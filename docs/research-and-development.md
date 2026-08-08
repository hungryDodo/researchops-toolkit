# Research-led and Development-led R&D

Research and Development are not mutually exclusive. The distinction is which result is primary and which trade-offs are acceptable.

## Shared skeleton

```text
Frame → Investigate → Decide → Implement → Verify → Learn
```

Both orientations may survey prior work, compare algorithms, write code, run experiments, debug, and document decisions. The shared `engineering-assurance` component owns machine-checkable task contracts, observed baseline/RED evidence, diff analysis, risk-scaled checks, and acceptance coverage.

## Research-led R&D

Primary objective: produce valid knowledge and evidence.

- Code is often an experiment instrument.
- A complex or niche method may remain a candidate if it isolates the research variable.
- Negative results can be valuable.
- Evaluation can focus on a deliberately narrow research axis.
- Protocol, metric, data lineage, baseline integrity, and claim linkage are mandatory.
- The relevant top-level owner for result-affecting code is `research-engineering`.

## Development-led R&D

Primary objective: produce a reliable, maintainable, deployable deliverable.

- Investigation is used to reduce implementation risk and choose sound trade-offs.
- Novelty alone does not justify dependency, runtime, operational, or maintenance cost.
- Candidate routes are pruned when system-level value is insufficient.
- Correctness, regression safety, operability, compatibility, security, and lifecycle cost dominate acceptance.
- The top-level owner is `software-development`.

Its internal modes are technical investigation, implementation, debugging, refactoring, review, and release. These are modes, not six extra Skills.

## Mixed projects

A single project can contain both orientations. A work unit has one primary operation and an orientation at routing/evaluation time:

```json
{
  "orientation": "research-led",
  "operation": "design",
  "primary_artifact": "experiment"
}
```

or:

```json
{
  "orientation": "development-led",
  "operation": "debug",
  "primary_artifact": "code"
}
```

Large requests should be decomposed into work units so that model assignment and acceptance are attributable. Secondary tags can retain cross-domain context without creating a high-dimensional profile key.

## Unknown is valid

At project start, the technology stack or final method may be unknown. The first work unit can be only:

```text
research-led / discover / analysis
```

Repository scan, survey, and early execution progressively fill metadata. The system does not require a complete technical taxonomy before research begins.
