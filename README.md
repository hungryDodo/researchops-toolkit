# ResearchOps Toolkit

ResearchOps Toolkit is an **evidence-driven research workflow and agent-behavior toolkit** for Codex, Claude Code, Gemini CLI, and optional third-party model workers. It organizes discovery, route selection, experiments, independent validation, writing, communication, delegated work, and project hygiene into an auditable and recoverable loop.

It contains two complementary systems:

- **Skills System** — progressively loaded capabilities that own procedures, artifacts, and acceptance contracts.
- **Behavior Runtime** — lifecycle-hook policies that constrain how applicable tasks are executed, suggest specialist workflows, and evaluate exposed tool use through structured inspection, non-executing shell normalization, declarative risk policy, and optional semantic escalation.

> The goal is not to have an agent automatically “write a paper.” The goal is to give every question, hypothesis, result, failure, decision, risk, permission, and human approval an explicit owner and durable record.

The release includes **12 top-level Skills, seven task Behavior Packs, one universal behavior kernel, two internal components, three Harness adapters, sub-agent/model routing, capability proposals, safe cleanup, and a research dashboard**.

## 🚀 One-liner quick start

> **Skip the docs?** Send this to your Agent and it will clone, install, and bootstrap everything automatically:

**🤖 Send to your Agent:**

> Clone git@github.com:hungryDodo/researchops-toolkit.git, cd in, then run `python3 -m rops install --target codex --scope project --project . --mode link --bundle research-core --with-agents --with-behavior`, then `python3 -m rops bootstrap . --title "My Research Project"`, then `python3 -m rops doctor --target codex --project .`.

## Quick start

```bash
git clone git@github.com:hungryDodo/researchops-toolkit.git
cd researchops-toolkit

python3 -m rops bootstrap /path/to/project \
  --title "My Research Project" \
  --upgrade

python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --bundle research-core \
  --with-agents \
  --with-behavior \
  --behavior-mode guide

python3 -m rops doctor --target codex --project /path/to/project
```

Inspect the runtime and start the dashboard:

```bash
python3 -m rops behavior --root /path/to/project status
python3 -m rops dashboard serve --root /path/to/project --port 8765
```

See [Getting started](docs/getting-started.md) for installation, trust prompts, modes, and cross-framework notes.

## Two control planes, four layers

```text
Plugin / Extension                         distribution envelope
          ↓
Behavior Runtime + Harness Hooks           lifecycle interception and layered risk evaluation
          ├── Universal Kernel             cross-task scope, evidence, state, privilege, approvals
          └── Task Behavior Packs          coding, research, writing, hardware, hygiene, delegation
          ↓
Progressive Skills                         procedures, scripts, references, artifacts, acceptance
          ↓
Platform permissions / sandbox             final authority over tool execution
```

MCP remains useful for external tools and shared state, but it is not the mandatory policy plane because a model can elect not to call an MCP tool.

### Runtime modes

| Mode | Effect |
|---|---|
| `off` | No injection, records, or decisions |
| `observe` | Metadata-only classification and audit |
| `guide` | Default; compact task guidance and proposals without blocking ordinary work |
| `enforce` | Guide plus fail-closed blocking of high/critical static or semantic findings without a matching content-bound one-use approval |

Hooks do not replace the platform sandbox or permission system. Enforcement only covers lifecycle and tool paths exposed by the active Harness.

## Behavior Packs

| Pack | Purpose |
|---|---|
| `coding-minimal-change` | Ponytail-inspired minimum sufficient change, reuse-first design, and dependency restraint |
| `coding-evidence` | old-coder-inspired contract, RED/GREEN, risk-calibrated checks, and fresh evidence |
| `research-integrity` | Protocol, evidence-source, negative-result, and claim separation |
| `writing-claim-discipline` | Match scientific language to verified evidence strength |
| `hardware-safety` | Topology, power, calibration, leases, recovery, and physical confirmation |
| `hygiene-archive-first` | Inventory and reversible archive before separately approved purge |
| `delegation-quality` | Bounded delegation, resource isolation, independent acceptance, and model profiles |

Behavior Packs are not user-routed top-level Skills. Hooks select them from the task and active Skill, so they do not compete in the Skill catalog.

## Repository layout

```text
researchops-toolkit/
├── behavior/               universal kernel, packs, runtime, and evals
├── hooks/                  Codex, Claude Code, and Gemini CLI adapters
├── .codex-plugin/          Codex distribution metadata
├── .claude-plugin/         Claude Code distribution metadata
├── gemini-extension.json   Gemini CLI extension metadata
├── skills/                 12 progressively loaded top-level Skills
├── components/             evidence ledger and dashboard; not semantically routed
├── rops/                    unified CLI and internal modules
├── config/                 frameworks, bundles, triggers, proposals, contracts
├── catalog/                generated Skill catalog
├── tests/                  trigger, behavior, and end-to-end tests
├── templates/              rendered project policy
├── release/                validation and internal hashes
└── docs/                   stable user and maintainer documentation
```

`.research/` is authoritative project state. `.researchops/` is a replaceable installed runtime copy and hook entry point.

## Documentation

- [Documentation index](docs/README.md)
- [Getting started](docs/getting-started.md)
- [Architecture and state](docs/architecture.md)
- [Behavior Runtime](docs/behavior-runtime.md)
- [Research workflows](docs/workflows.md)
- [Skills and bundles](docs/skills-and-bundles.md)
- [Agents and model routing](docs/agents-and-model-routing.md)
- [Safety and hygiene](docs/safety-and-hygiene.md)
- [Development and release](docs/development.md)

Agents modifying this repository should read [`AGENTS.md`](AGENTS.md).

## The 12 top-level Skills

| Skill | Owner |
|---|---|
| `research-program-orchestrator` | Lifecycle, gates, next action, evidence/dashboard coordination, capability proposals |
| `research-discovery` | Survey, closest work, related-work synthesis, source status |
| `research-route-evaluator` | Fatal flaws, feasibility, Top 1–3 routes, minimum decisive tests |
| `experimental-research` | Software experiment design, execution, and analysis |
| `hardware-experiment-loop` | Physical topology, safety, calibration, leases, recovery |
| `research-engineering` | Research-critical code: SPEC → RED → GREEN → Gauntlet |
| `adaptive-agent-orchestration` | Subtasks, model routing, independent acceptance, profiles |
| `research-validation` | Reproduction, artifact audit, paper red-team review |
| `research-writing` | Evidence-gated drafting and LaTeX revision |
| `research-communication` | Academic figures, result plots, and presentations |
| `project-hygiene` | Archive-first cleanup, data/log lifecycle, worktrees, purge |
| `skill-system-engineering` | Skill/Pack boundaries, triggers, safety, provenance, Harness adapters |

## Layered risk guardrail

The Behavior Runtime does not treat regular expressions as the primary security mechanism. Exposed tool use passes through four layers:

1. structured tool-input inspection;
2. non-executing shell parsing and canonicalization, including common wrappers, executable paths, split/long options, nested `sh -c`, `xargs`, and `find -exec`;
3. declarative risk categories covering deletion, overwrite/device writes, recursive permissions, Git force/history operations, privileged containers, filesystem administration, persistence, egress/tunnels, remote execution, resource exhaustion, power control, hardware writes, and policy bypass;
4. an optional strict-JSON semantic reviewer for dynamic code or unfamiliar tools. It may only add or escalate risk and can never clear a static finding.

Inspect a command without executing it:

```bash
python3 -m rops behavior --root . analyze \
  --command 'sudo /bin/rm --recursive --force /data'
```

Enable an approved local or external reviewer explicitly; raw tool input is sent only after opt-in:

```bash
python3 -m rops behavior --root . semantic \
  --mode advisory \
  --scope uncertain \
  --command 'python3 /path/to/reviewer.py'
```

Discovery and execution approval remain separate:

```text
lightweight discovery → proposal → approve specialist loading → specialist operational approval
```

In `enforce` mode, approvable findings require a short-lived, one-use approval bound to the risk category, raw command hash, canonical command hash, and exact matched rule set:

```bash
python3 -m rops behavior --root . approve \
  --kind hardware-write \
  --command 'nrfjprog --program app.hex --reset' \
  --reason 'topology and recovery plan reviewed' \
  --ttl 15
```

The runtime is a guardrail, not a complete command sandbox. Platform permissions, container/OS isolation, repository protection, hardware interlocks, and human review remain the final boundary.

## References and acknowledgements

We studied open-source projects and platform documentation for workflow, Skill/Harness organization, middleware, lifecycle control, and validation boundaries. **This distribution does not copy, modify, or vendor their Skills, prompts, scripts, hooks, templates, handbooks, or assets.** See [`PROVENANCE.json`](PROVENANCE.json).

Key influences include Orchestra Research, OpenJudge, ARS-Codex, phd-skills, CCFA-Skills, old-coder, Ponytail, revise-paper, ResearchStudio-Idea, Supervisor-Skills, Anthropic Skills, Google Skills, the Agent Skills specification, Codex/Claude Code/Gemini CLI hook documentation, LangChain agent middleware, LiteLLM, and OpenAI Agents SDK. Upstream projects remain governed by their own licenses.

## Validation

```bash
python3 -m rops validate
python3 -m rops validate --smoke
python3 -m rops package --out /tmp/researchops-toolkit-release
```

The checks cover Skill structure, trigger fixtures, Behavior Pack evals, hook installation, 131 adversarial/benign risk cases, parsed and canonical content-bound approvals, optional semantic escalation, metadata-only logging, framework installation, model routing, archive/restore/purge, worktree safety, and internal hashes. They do not prove empirical routing accuracy for every Harness/model release or guarantee publication outcomes.

## License

ResearchOps Toolkit is released under the [MIT License](LICENSE).
