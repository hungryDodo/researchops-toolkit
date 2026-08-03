# Architecture and authoritative state

## First principles

ResearchOps Toolkit separates **capability discovery** from **execution behavior**:

- A Skill is a user-meaningful workflow owner. It answers what procedure to follow, what artifacts to create, and how acceptance is determined.
- A Behavior Pack is a compact cross-cutting policy. It answers how an applicable task should be performed before a full Skill is selected or while a Skill is executing.
- A Hook or middleware adapter exposes lifecycle events. It is transport, not policy content.
- The Model Control Plane is a non-routed component for secret-safe provider mechanics, bounded dispatch, and model dossiers; the orchestration Skill owns decisions.
- Platform permissions and sandboxing remain the final authority over tool execution.

This avoids two failure modes: turning every policy into a competing top-level Skill, and burying all workflows inside an always-on prompt.

## Four layers

```text
1. Distribution
   .codex-plugin/, .claude-plugin/, gemini-extension.json
   Packages Skills, hooks, and metadata.

2. Behavior control plane
   behavior/ + hooks/
   Runs a universal kernel, selects task packs, propagates compact parent policy to Sub-Agents, records metadata, and applies structured inspection, parsed command policy, and optional semantic escalation.

3. Workflow capability plane
   skills/
   Progressively loaded procedures, references, scripts, assets, artifacts, and acceptance contracts.

4. Execution authority
   Harness permission prompts, sandbox, tool ACLs, hardware interlocks, and human approvals.
```

MCP may provide external tools or shared state, but a mandatory policy cannot rely solely on an optional model-selected tool call.

## Repository layout

```text
researchops-toolkit/
├── behavior/             policy registry, task packs, runtime, schema, evals
├── hooks/                lifecycle adapter executable and manifests
├── skills/               12 top-level routed capabilities
├── components/           dashboard, evidence ledger, and model control plane
├── rops/                  unified CLI
├── config/               shared registries and contracts
├── catalog/              generated Skill discovery catalog
├── tests/                structural and end-to-end checks
├── templates/            compact project policy
├── release/              release validation and hash manifest
└── docs/                 stable documentation
```

## Installed project layout

```text
project/
├── .research/            authoritative research state
│   ├── designs/          frozen hypotheses, variables, metrics, protocols
│   ├── runs/             immutable run manifests and results
│   ├── evidence/         claim/evidence ledger and artifacts
│   ├── agents/           providers/models, onboarding, dispatches, acceptance, routing profiles, model dossiers
│   ├── proposals/        capability recommendations and decisions
│   ├── runtime/          behavior mode, approvals, metadata-only events
│   ├── hygiene/          inventories, plans, registries
│   ├── archive/          reversible retired content
│   ├── trash/            quarantine before permanent purge
│   └── dashboard/        semantic project state
├── .researchops/         installed replaceable behavior runtime and hook entry point
├── .codex/.claude/.gemini framework-native Skills, agents, and hook settings
└── AGENTS.md etc.        compact always-on project policy
```

## Authority rules

- Experiment design files are authoritative for hypotheses, baselines, metrics, and stopping rules.
- Run manifests and immutable run IDs are authoritative for execution.
- The evidence ledger links claims to artifacts; registration alone does not make an interpretation scientifically valid.
- LaTeX source is editable manuscript authority; rendered PDF is visual authority.
- Dashboard cards summarize state but do not replace underlying evidence.
- Chat history and terminal output are transient unless captured into an artifact.
- `.researchops/` may be reinstalled; `.research/` must be preserved across upgrades.
