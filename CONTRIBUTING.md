# Contributing

Keep the two control planes separate:

- Skills own user-meaningful workflows, artifacts, and acceptance contracts.
- Behavior Packs contain compact cross-cutting policy and must not become hidden full workflows.
- Hooks and middleware are thin adapters; policy belongs in `behavior/`, not duplicated per host.

Prefer extending the unified `rops` CLI or an existing owner over adding another top-level utility. A new Behavior Pack requires a registry entry, positive and negative eval cases, conflict/priority notes, and adapter smoke coverage when output or decisions change. A new Skill must have a distinct intent, artifact owner, permission or tool boundary, and trigger fixtures.

Before submitting changes, run:

```bash
python3 -m rops validate
python3 tests/behavior_smoke.py
python3 tests/smoke.py
python3 -m compileall -q rops skills components behavior hooks tests
```

Pull requests that change Gate semantics, evidence schemas, implicit invocation, Hook output, deletion, external-provider, hardware, approval, or fail-open behavior must include a compatibility and security note. Do not vendor third-party implementation text without compatible licensing and provenance.
