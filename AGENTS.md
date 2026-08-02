# Repository instructions for coding agents

## Read first

1. Read `README.md` or `README_zh.md`.
2. Read `docs/README.md`, then only the document relevant to the task.
3. Read `docs/behavior-runtime.md` before changing Hooks, Packs, approvals, or policy injection.
4. Use `catalog/README.md` to locate the narrowest Skill; do not load every `skills/*/SKILL.md`.
5. When changing a Skill, read its `SKILL.md`, referenced files, evals, and license.

## Layer ownership

- `behavior/` contains compact cross-cutting policy, task classification, and deterministic risk checks.
- `hooks/` and plugin manifests contain Harness transport only; do not duplicate policy prose there.
- `skills/` contains user-routable procedures and artifact/acceptance owners.
- `components/` contains non-routed shared services.
- Platform permissions and sandboxing remain authoritative; do not claim Hook coverage is a complete security boundary.

## Repository invariants

- Prefer minimum sufficient changes: reuse existing code, standard library, platform features, and installed dependencies before adding abstractions or dependencies.
- Keep `SKILL.md` concise and move long conditional guidance to `references/`.
- Keep Behavior Packs concise; a long multi-step procedure belongs in a Skill.
- Preserve positive/negative trigger boundaries and update `tests/trigger-cases.json` when Skill descriptions change.
- Update `behavior/evals/cases.json` and `tests/behavior_smoke.py` when Pack selection, risk checks, or Hook output changes.
- Hard blocks must use deterministic configured checks, not an ambiguous semantic classification alone.
- Do not broaden hardware, deletion, external-provider, worktree, or implicit-invocation permissions silently.
- Runtime logs must remain metadata-only by default; do not add raw prompt/tool logging without an explicit privacy design.
- Do not vendor third-party content without pinned provenance, a compatible license, and security review.
- Do not create empty directories or duplicate generated/demo assets.
- Use `python3 -m rops`; do not add a root script when an existing command or internal module can own the operation.
- Do not hand-edit `catalog/*`, `release/MANIFEST.sha256`, or `release/VALIDATION.md`.

## Required checks

```bash
python3 -m rops validate
python3 -m rops validate --smoke
python3 -m rops package --out /tmp/researchops-toolkit-release
```

Do not claim checks passed unless they ran in the current working tree.
