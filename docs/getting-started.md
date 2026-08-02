# Getting started

## Requirements

- Python 3.10 or newer;
- Git when using worktree management or repository-aware cleanup;
- Codex, Claude Code, Gemini CLI, or a portable Skill directory.

The default workflow has no third-party Python dependency and no model gateway requirement.

## Obtain the package

Keep the toolkit checkout separate from the research project.

```bash
git clone git@github.com:hungryDodo/researchops-toolkit.git
cd researchops-toolkit
python3 -m rops --version
```

## Install Skills into a project

```bash
python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --with-agents
```

- Project scope avoids changing unrelated repositories.
- Link mode is convenient during active toolkit development.
- Copy mode freezes a self-contained Skill snapshot.
- `--with-agents` renders native role files where supported.

Supported targets are `codex`, `claude`, `gemini`, `portable`, and `all`.

## Initialize authoritative project state

```bash
python3 -m rops bootstrap /path/to/project \
  --title "My Research Project" \
  --upgrade

python3 -m rops doctor \
  --target codex \
  --project /path/to/project
```

Bootstrap creates `.research/`, the evidence ledger, dashboard state, policy snapshots, project guidance files, and a toolkit lock. Existing authoritative artifacts are preserved.

## Start the dashboard

```bash
python3 -m rops dashboard serve \
  --root /path/to/project \
  --host 127.0.0.1 \
  --port 8765
```

The dashboard shows structured semantic state rather than raw terminal logs.

## Install by stage

```bash
python3 -m rops bundles
python3 -m rops install --target codex --scope project \
  --project /path/to/project --mode link --bundle hygiene
```

The default bundle is `research-core`. Optional bundles include `discovery`, `execution`, `hardware`, `validation`, `writing`, `hygiene`, and `platform-dev`. Use `all` only for maintenance or audit.

Installing a new Skill does not require stopping a running experiment, but it must not silently change a frozen protocol, metric, code revision, or statistical plan. Apply new behavior at the next task or Gate and record the version change.

## Upgrade or reinstall

The toolkit does not retain version-specific migration scripts in the public root. To upgrade an existing project:

1. keep `.research/` unchanged;
2. check out the desired tagged toolkit release;
3. rerun `rops install` for the chosen bundle;
4. rerun `rops bootstrap --upgrade`;
5. review `.research/suite.lock.json` and run `rops doctor`.

This keeps the persistent research state separate from replaceable Skill installations.

## Multiple machines

Filesystem Skills are not account-synchronized. Clone or pull the same tagged toolkit release on each machine, install at project scope, and keep secrets, private datasets, and local hardware envelopes outside Git.
