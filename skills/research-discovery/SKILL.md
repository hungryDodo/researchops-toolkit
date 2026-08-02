---
name: research-discovery
description: >
  Use when building a traceable literature or technology survey, mapping closest work, or synthesizing a verified corpus into a taxonomy and Related Work structure. Do not use to score one proposed route after the corpus exists or to draft unsupported paper prose.
---
# Research Discovery

## Trigger contract

Own evidence-grounded discovery from question freezing through corpus synthesis. It combines survey and Related Work because both consume the same verified corpus, tools, provenance rules, and artifact family.

## Progressive loading

- question, query, inclusion, provenance, and adversarial search: `references/SURVEY_PROTOCOL.md`;
- closest-work matrix, taxonomy, lineage, and differentiation: `references/RELATED_WORK_PROTOCOL.md`;
- Supervisor-inspired discovery practices: `references/ADVISOR_DISCOVERY.md`.

Load only the branch matching the requested mode: `survey`, `closest-work`, or `synthesis`.

## Procedure

1. Freeze two or three answerable research questions, scope, reader, and exclusions.
2. Search from multiple perspectives: mainstream, critics/negative results, adjacent fields, methodology, and deployment constraints.
3. Keep model-recalled papers as unverified leads only. Verify metadata and load primary sources before using details.
4. Record query families, inclusion/exclusion decisions, source provenance, and unresolved evidence gaps.
5. For closest work, compare object, mechanism, input granularity, setting, assumptions, and evidence—not title similarity.
6. Synthesize with cross-comparison rather than one-paper-per-paragraph summaries.
7. Hand a bounded corpus and collision matrix to `research-route-evaluator`.

## Subagents

Parallelize independent search perspectives when clean-context workers are available. Workers return paths, citations, uncertainty, and a short synthesis; large notes remain on disk.

## Output contract

Produce `.research/survey/brief.md`, query log, screened corpus, provenance tags, closest-work matrix, taxonomy, tensions, gaps, and explicit answers to the frozen questions.
