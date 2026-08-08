# Repository instructions for coding agents

## Read first

1. Read `README.md` or `README_zh.md`.
2. Read `docs/README.md` and only the document relevant to the task.
3. Use `catalog/README.md` to locate the narrowest Skill; do not load every `skills/*/SKILL.md`.
4. When changing a Skill, read its `SKILL.md`, referenced files, evals, and license.

## Repository invariants

- `skills/` contains user-routable capabilities; `components/` contains internal non-routed services.
- Keep `SKILL.md` concise and move long guidance to conditional `references/`.
- Preserve positive/negative trigger boundaries and update `tests/trigger-cases.json` when descriptions change.
- Do not broaden hardware, deletion, external-provider, or implicit-invocation permissions silently.
- Do not vendor third-party content without pinned provenance, a compatible license, and security review.
- Do not create empty directories or duplicate generated/demo assets.
- Use `python3 -m rops`; do not add a new root script when an existing subcommand or internal module can own the operation.
- Do not hand-edit `catalog/*`, `release/MANIFEST.sha256`, or `release/VALIDATION.md`.

## Required checks

```bash
python3 -m rops validate
python3 -m rops validate --smoke
python3 -m rops package --out /tmp/researchops-toolkit-release
```

Do not claim checks passed unless they ran in the current working tree.
