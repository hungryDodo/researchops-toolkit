---
name: skill-system-engineering
description: >
  Use when creating, merging, splitting, packaging, auditing, or evaluating Agent Skills, trigger policies, proposal policies, provenance, permissions, and cross-harness compatibility. Do not use to execute the research domain task that a Skill describes.
---
# Skill System Engineering

## Trigger contract

Own the Skill architecture itself: progressive disclosure, granularity, trigger quality, proposal policy, security/provenance, packaging, and harness adapters. It does not act as the runtime orchestrator.

## Progressive loading

- structure and progressive disclosure: `references/HARNESS_PROTOCOL.md`;
- semantic triggers and negative boundaries: `references/TRIGGER_DESIGN.md`;
- provenance, license, permissions, injection and supply-chain audit: `references/GOVERNANCE_AUDIT.md`;
- top-level granularity rules: `references/GRANULARITY_RULES.md`;
- proposal-vs-execution policy: `references/PROPOSAL_POLICY.md`.

Use `scripts/scaffold_skill.py` for a new Skill and `scripts/audit_skill.py` before installation or publication.

## Granularity test

Create a top-level Skill only when most of these hold:

1. a stable, user-recognizable intent;
2. a distinct artifact contract;
3. a distinct tool, permission, or risk profile;
4. independent evaluation fixtures;
5. meaningful context savings from delayed loading;
6. it is not almost always invoked with one existing Skill.

Merge as a mode/reference when triggers, inputs, outputs, state, and permissions substantially overlap. Keep high-risk procedures separate only when isolation or approval boundaries materially differ.

## Runtime responsibility boundary

This Skill designs and tests the capability proposal broker. `research-program-orchestrator` runs the lightweight broker during projects. This separation prevents a meta-Skill from loading during every research turn.

## Output contract

Produce architecture decision, trigger/negative examples, artifact and permission contract, granularity score, overlap analysis, context budget, proposal policy, provenance/license record, harness compatibility, eval fixtures, and migration plan.
