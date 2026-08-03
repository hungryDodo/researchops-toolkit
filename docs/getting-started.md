# Getting started

## Requirements

- Python 3.10 or newer;
- Git for repository-aware cleanup and worktrees;
- Codex, Claude Code, Gemini CLI, or a portable Skill directory.

The default runtime uses only the Python standard library.

## Obtain the toolkit

Keep the toolkit checkout separate from the research project:

```bash
unzip researchops-toolkit-v1.7.0.zip
cd researchops-toolkit
python3 -m rops --version
```

## Initialize authoritative state

```bash
python3 -m rops bootstrap /path/to/project \
  --title "My Research Project" \
  --upgrade
```

Bootstrap creates `.research/`, the evidence ledger, dashboard state, policy snapshots, and a toolkit lock. Existing authoritative artifacts are preserved.

## Install Skills, native roles, and behavior hooks

```bash
python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --bundle research-core \
  --with-agents \
  --with-behavior \
  --behavior-mode guide
```

Supported targets are `codex`, `claude`, `gemini`, `portable`, and `all` for Skills. The Behavior Runtime supports `codex`, `claude`, `gemini`, and `all` at project scope.

- Project scope avoids changing unrelated repositories.
- Link mode follows updates in the toolkit checkout.
- Copy mode freezes a self-contained Skill snapshot.
- `--with-agents` renders native role files.
- `--with-behavior` copies the runtime into `.researchops/` and merges project hook settings.

Review the generated framework settings and accept the platform's trust prompt before expecting Hooks to run.


## Repository extension paths

The repository can also be consumed as a distribution package:

- Claude Code: add the repository as a marketplace and install `researchops-toolkit`; review the bundled Hooks before trusting them.
- Gemini CLI: `gemini extensions install https://github.com/hungryDodo/researchops-toolkit`; the extension auto-discovers `skills/` and `hooks/hooks.json`.
- Codex: prefer the project-level `python3 -m rops install --target codex ... --with-behavior` flow. The source includes a Codex plugin manifest, but this release does not claim that every Codex marketplace version handles a plugin rooted at the repository root identically.

Extension installation provides the default `guide` behavior. Use the cloned toolkit's CLI for explicit project mode and operator approvals.

## Inspect behavior before relying on it

```bash
python3 -m rops behavior --root /path/to/project status
python3 -m rops behavior --root /path/to/project classify \
  --text "Run an ablation and preserve negative results"
python3 -m rops behavior --root /path/to/project evaluate \
  --framework codex \
  --event PreToolUse \
  --tool-name Bash \
  --command 'rm -rf raw_traces'
```

Inspect normalization and policy findings without executing a command:

```bash
python3 -m rops behavior --root /path/to/project analyze \
  --command 'sudo /bin/rm --recursive --force /data'
```

Optional semantic review is disabled by default. Enable it only with a local or approved reviewer and after reviewing the data boundary:

```bash
python3 -m rops behavior --root /path/to/project semantic \
  --mode advisory \
  --scope uncertain \
  --command 'python3 /path/to/reviewer.py'
```

The recommended rollout is `observe` → `guide` → `enforce` after adapter validation. Use `required` semantic mode only together with `enforce` when reviewer unavailability should block selected tool calls.

## Add a third-party or local model

Tell the Agent the provider and intended model/capability. It should verify current official docs and create a non-secret onboarding plan. Do not paste the key into chat.

```bash
python3 -m rops models recipes
python3 -m rops models --root /path/to/project onboard \
  --provider openai --model <verified-model-id> \
  --capability code --risk-ceiling low
python3 -m rops models secret-template --provider openai --write
```

After editing `~/.config/rops/secrets.env` locally, run `models doctor`, `remote-list` when supported, `probe --enroll`, then `smoke`. Full workflow and profile semantics are in [Agents and model routing](agents-and-model-routing.md).

## Install by research stage

```bash
python3 -m rops bundles
python3 -m rops install --target codex --scope project \
  --project /path/to/project --mode link --bundle hygiene
```

The default bundle is `research-core`. Optional bundles include `discovery`, `execution`, `hardware`, `validation`, `writing`, `hygiene`, and `platform-dev`.

Installing a new Skill or Pack must not silently change a frozen experiment protocol, metric, code revision, safety envelope, or statistical plan. Apply it at the next task or Gate and record the version change.

## Dashboard and diagnostics

```bash
python3 -m rops doctor --target codex --project /path/to/project
python3 -m rops dashboard serve \
  --root /path/to/project \
  --host 127.0.0.1 \
  --port 8765
```

## Upgrade

1. Preserve `.research/`.
2. Check out the desired toolkit tag.
3. Rerun `rops install` with the chosen bundle and `--with-behavior`.
4. Rerun `rops bootstrap --upgrade`.
5. Review `.research/suite.lock.json`, Hook settings, and `rops doctor`.

`.researchops/` is replaceable. The installer rewrites its runtime copy while retaining `.research/runtime/` mode, approvals, and metadata state.

## Multiple machines

Filesystem Skills and Hooks are not account-synchronized. Clone the same tagged toolkit release on each machine, install at project scope, and keep secrets, private datasets, and local hardware limits outside Git.
