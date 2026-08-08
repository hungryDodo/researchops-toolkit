# Harness protocol

## Canonical contract

The directory is canonical. Platform adapters may add UI metadata or native agent definitions, but must not duplicate the workflow text.

## Ownership test

Create a separate Skill only when at least one is true: it owns a distinct artifact; it has a distinct safety/permission boundary; it has a distinct lifecycle state; it has a stable standalone trigger; or it needs independent evaluation/context. Otherwise keep it as a reference, script, or section of the stage owner.

## Body budget

The body must be sufficient after loading, yet navigational. Put volatile details, long taxonomies, API tables, schemas, and large examples in references. Scripts should report compact structured outputs rather than stream all logs into context.

## Cross-harness compatibility

Use portable Agent Skills frontmatter as the canonical layer. Keep always-on project invariants in `AGENTS.md`/equivalent, native subagent model/tool settings in framework-specific files, and research state under `.researchops/state/`.
