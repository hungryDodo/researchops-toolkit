# ResearchOps Toolkit

ResearchOps Toolkit is an **evidence-driven research workflow** for Codex, Claude Code, Gemini CLI, and optional third-party model workers. It organizes discovery, route selection, experiments, independent validation, writing, review, communication, and project hygiene into an auditable and progressively loaded research loop.

> The goal is not to have an agent automatically “write a paper.” The goal is to give every question, hypothesis, result, failure, decision, risk, and human approval an explicit owner and durable record.

The current release includes **12 top-level Skills, two non-triggered components, cross-framework installers, sub-agent/model routing, capability proposals, safe cleanup, and a full-screen research dashboard**.

## 🚀 One-liner quick start

> **Skip the docs?** Send this to your Agent and it will clone, install, and bootstrap everything automatically:

**🤖 Send to your Agent:**

> Clone git@github.com:hungryDodo/researchops-toolkit.git, cd in, then run `python3 -m rops install --target codex --scope project --project . --mode link --with-agents`, then `python3 -m rops bootstrap . --title "My Research Project"`, then `python3 -m rops doctor --target codex --project .`.

## Quick start

Project-scoped installation with the default `research-core` bundle is recommended:

```bash
git clone git@github.com:hungryDodo/researchops-toolkit.git
cd researchops-toolkit

python3 -m rops install \
  --target codex \
  --scope project \
  --project /path/to/project \
  --mode link \
  --with-agents

python3 -m rops bootstrap /path/to/project \
  --title "My Research Project" \
  --upgrade

python3 -m rops doctor --target codex --project /path/to/project
```

Start the dashboard:

```bash
python3 -m rops dashboard serve \
  --root /path/to/project \
  --port 8765
```

Hardware, cleanup, and Skill-development capabilities are opt-in bundles:

```bash
python3 -m rops bundles
python3 -m rops install --target codex --scope project --project . --bundle hardware
python3 -m rops install --target codex --scope project --project . --bundle hygiene
python3 -m rops install --target codex --scope project --project . --bundle platform-dev
```

See [Getting started](docs/getting-started.md) for complete installation, framework, and upgrade instructions.

## Documentation

| Document | Purpose |
|---|---|
| [Documentation index](docs/README.md) | Shortest reading path for humans and agents |
| [Getting started](docs/getting-started.md) | Install, bootstrap, dashboard, upgrade, and multi-host deployment |
| [Architecture and state](docs/architecture.md) | Repository layout, control/execution planes, and `.research/` authority |
| [Research workflows](docs/workflows.md) | Stages, gates, evidence states, proposals, and handoffs |
| [Skills and bundles](docs/skills-and-bundles.md) | The 12 Skills, progressive loading, triggers, and granularity rules |
| [Agents and model routing](docs/agents-and-model-routing.md) | Subtasks, cheaper/third-party models, independent verification, and profiles |
| [Safety and hygiene](docs/safety-and-hygiene.md) | Hardware, archive-first cleanup, two-phase purge, worktrees, and privacy |
| [Development and release](docs/development.md) | Skill authoring, harness adapters, tests, provenance, and publishing |

Agents working directly in this repository should read [`AGENTS.md`](AGENTS.md) before modifying files.

## Architecture

```text
researchops-toolkit/
├── skills/                 # 12 progressively loaded top-level Skills
├── components/             # evidence ledger and dashboard; not routed semantically
├── rops/                   # one cross-platform CLI and its internal modules
├── config/                 # framework paths, bundles, triggers, proposals, contracts
├── catalog/                # generated Skill catalog for human/agent routing
├── tests/                  # trigger fixtures and end-to-end smoke test
├── templates/              # one rendered project-agent policy template
├── release/                # validation report and internal file manifest
└── docs/                   # stable user and maintainer documentation
```

After bootstrap, `.research/` is the authoritative project state. Terminal scrollback, chat summaries, and transient notes do not replace registered designs, runs, evidence, decisions, and approvals.

## Top-level Skills

| Skill | Responsibility |
|---|---|
| `research-program-orchestrator` | Lifecycle, gates, next action, evidence/dashboard, capability proposals |
| `research-discovery` | Survey, closest work, Related Work, verified corpus synthesis |
| `research-route-evaluator` | Fatal flaws, resource fit, Top 1–3 routes, minimum decisive validation |
| `experimental-research` | Software experiment design, execution, analysis, reproducible evidence |
| `hardware-experiment-loop` | Hardware topology, safety, calibration, leases, restoration |
| `research-engineering` | Result-affecting code changes: SPEC → RED → GREEN → gauntlet |
| `adaptive-agent-orchestration` | Subtask design, model routing, independent acceptance, model profiles |
| `research-validation` | Independent reproduction, artifact audit, manuscript red-team review |
| `research-writing` | Evidence-gated drafting, LaTeX revision, feedback ledger, rendered checks |
| `research-communication` | Academic figures, result plots, and research presentations |
| `project-hygiene` | Archive-first cleanup, data/logs, worktrees, temporary tests, two-phase purge |
| `skill-system-engineering` | Skill design, merging/splitting, triggers, safety, provenance, adapters |

See [`catalog/README.md`](catalog/README.md) for the generated catalog and startup-context estimate.

## Consequential capabilities: propose before loading

The orchestrator uses a small capability advisor only at meaningful hinges. It may recommend a specialist before hardware writes, external-provider disclosure, independent validation, submission review, or permanent purge:

```text
lightweight discovery → proposal → user approves specialist loading → specialist safety gate
```

A proposal does **not** load the full Skill, run tools, or authorize the underlying consequential action. Dismissed, snoozed, and completed proposals are persisted to prevent repeated prompting.

## Acknowledgements and design references

We studied the following open-source projects, specifications, and platform documentation to understand their workflow, Skill/Harness structure, evaluation boundaries, and design decisions. **This distribution does not copy, modify, or vendor their Skills, prompts, scripts, templates, handbooks, or visual assets.** The implementation was written specifically for ResearchOps Toolkit. Machine-readable provenance is in [`PROVENANCE.json`](PROVENANCE.json).

| Project / documentation | Design lessons used here |
|---|---|
| [Orchestra Research AI-research-SKILLs](https://github.com/Orchestra-Research/AI-research-SKILLs) | Modular research capabilities and AutoResearch-style execution |
| [OpenJudge](https://github.com/agentscope-ai/OpenJudge) | Independent evaluators, weakness analysis, iterative acceptance |
| [ARS-Codex](https://github.com/Imbad0202/academic-research-skills-codex) | End-to-end academic workflows, cross-model review, adapter boundaries |
| [phd-skills](https://github.com/fcakyon/phd-skills) | Experiment design, reproduction, research integrity, paper verification |
| [CCFA-Skills](https://github.com/mikubaka88/CCFA-Skills) | Owner boundaries, positive/negative triggers, shared references, artifact contracts |
| [old-coder](https://github.com/AmazingAng/old-coder) | SPEC, observed RED, minimum GREEN, gauntlet, fresh evidence |
| [revise-paper](https://github.com/CISLab-HKUST/revise-paper) | LaTeX source/rendered-PDF dual authority and feedback-led revision |
| [ResearchStudio-Idea](https://github.com/microsoft/ResearchStudio/tree/main/ResearchStudio-Idea) | Disk-backed state, idempotent next actions, novelty axes, clean-context workers |
| [Supervisor-Skills](https://github.com/HKUSTDial/Supervisor-Skills) | Guide/Skill layering, fatal-flaw idea gates, evidence-gated writing, paradigm-aware review |
| [Anthropic Skills](https://github.com/anthropics/skills) and [frontend-design](https://github.com/anthropics/skills/tree/main/skills/frontend-design) | Self-contained Skills, progressive disclosure, accessibility, artifact self-critique |
| [Google Skills](https://github.com/google/skills) | Selective installation, evaluation flywheels, machine/human reports |
| [Ponytail](https://github.com/DietrichGebert/ponytail) | Minimum sufficient change, dependency restraint, executable checks |
| [distill-design](https://github.com/ake77-code/distill-design) | Only the compact reusable visual-contract abstraction; URL/brand distillation is out of scope |
| [Agent Skills specification](https://agentskills.io/) | Skill directory structure, discovery descriptions, progressive loading |
| [OpenAI Codex](https://developers.openai.com/codex/), [Claude Code](https://docs.anthropic.com/en/docs/claude-code/overview), [Gemini CLI](https://geminicli.com/docs/) | Native agent/Skill configuration, permissions, and harness conventions |
| [LiteLLM](https://docs.litellm.ai/) and [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/) | Optional model gateways, provider unification, handoffs, tracing, human-in-the-loop |

Any future vendoring of third-party Skills must pin a commit, preserve the applicable license, pass a security audit, and update provenance. No third-party implementation is included by default.

## Validation

```bash
python3 -m rops validate
python3 -m rops validate --smoke
python3 -m rops package --out /tmp/researchops-toolkit-release
```

These checks validate structure, fixture coverage, installation, tool behavior, cleanup safety, and internal hashes. They do not claim perfect routing accuracy for every model/harness version or guarantee that a research direction will reach a particular venue.

## License

ResearchOps Toolkit is released under the [MIT License](LICENSE). Referenced projects remain subject to their own licenses.
