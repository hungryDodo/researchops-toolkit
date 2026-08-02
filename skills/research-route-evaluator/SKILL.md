---
name: research-route-evaluator
description: >
  Use when generating and ranking at most three falsifiable research routes or judging whether a proposed idea merits major implementation. Do not use for unconstrained brainstorming from nothing, broad corpus collection, or experiment execution.
---
# Research Route Evaluator

## Trigger contract

Own the commitment decision between verified discovery and expensive implementation. It incorporates advisor-style idea judgment but remains evidence- and resource-grounded.

## Progressive loading

- route cards, scoring, feasibility probes, and kill criteria: `references/ROUTE_PROTOCOL.md`;
- fatal flaws, lifecycle/resource fit, novelty axes, and short-circuit rules: `references/ADVISOR_EVALUATION.md`.

## Procedure

1. Require a verified closest-work snapshot. Absence of a retrieved collision is not proof of novelty.
2. Express each route as problem, mechanism, measurable hypothesis, simplest decisive experiment, expected contribution, dependencies, and kill criterion.
3. Run fatal-flaw checks **before** aggregate scoring. A data-refuted mechanism, unavailable prerequisite, invalid measurement, or indistinguishable closest work can short-circuit the route.
4. Match the route to actual time, hardware, data, implementation skill, and target venue—not an abstract ideal lab.
5. Judge contribution axes such as effectiveness, efficiency, robustness, cost, generality, problem novelty, and mechanism clarity. Do not force every project into every axis.
6. Separate mechanism-based promise from measured evidence.
7. Rank at most three routes and recommend one next feasibility probe; retain negative routes with reasons.

## Supervisor lens absorbed

Useful patterns from Supervisor-Skills are implemented here as general rules: early fatal-flaw gate, one-sentence story test, method/paradigm classification, retrieval-grounded novelty, capability/lifecycle matching, and rejection short-circuit. They are adapted to ResearchOps Toolkit evidence and gate contracts rather than copied as a parallel scoring Skill.

## Output contract

Write route cards, collision matrix references, fatal flaws, resource fit, score rationale, uncertainty, Top 1–3 ranking, decisive probe, and a human commitment proposal.
