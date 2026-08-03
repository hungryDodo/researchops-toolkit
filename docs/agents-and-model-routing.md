# Sub-Agents, providers, and model routing

## Architecture

Model use is split between two layers:

- `adaptive-agent-orchestration` is the progressively loaded workflow owner. It verifies current official provider documentation, prepares onboarding, defines task contracts, selects workers/verifiers, and interprets evidence.
- the Model Control Plane (`components/model-control-plane/`, `python3 -m rops models ...`) is the persistent runtime. It resolves secrets, calls provider protocols, stores non-secret registries, runs probes/smoke tests, dispatches bounded requests, and maintains model dossiers.

Provider onboarding is intentionally a low-frequency mode of the existing Skill rather than another top-level Skill. Normal dispatch does not reload the full onboarding procedure.

## Secret boundary

Never paste an API key into an Agent conversation. ROPS resolves credentials in this order:

1. provider-standard process environment variable;
2. `~/.config/rops/secrets.env` or `$ROPS_SECRETS_FILE`;
3. an organization secret manager that exposes an environment variable.

The repository stores only provider ID, protocol, base URL, credential variable names, trust zone, model IDs, and routing policy. Secret values are prohibited in Git, Skills, `.research/`, prompt files, command-line arguments, output artifacts, and model dossiers.

Create a local template without values:

```bash
python3 -m rops models secret-template --provider openai --write
chmod 600 ~/.config/rops/secrets.env
```

Then edit that file locally outside the Agent conversation. Environment variables remain preferable in managed deployments.

## Onboarding a provider/model

Tell the Agent the provider and intended model or capability. The Agent should search current official documentation for authentication, endpoint, protocol, exact model identifier, model-list endpoint, quota/project/region requirements, and data-use constraints. API keys and model names are often sufficient for simple hosted APIs, but cloud deployments may also require a project, region, deployment, organization, service account, or custom endpoint.

Built-in recipes currently cover OpenAI, Anthropic, Google Gemini, DeepSeek, OpenRouter, LiteLLM, and local OpenAI-compatible servers. Recipes are starting points, not permanent truth; verify official docs because model IDs and API requirements change.

```bash
python3 -m rops models --root <project> recipes

python3 -m rops models --root <project> onboard \
  --provider anthropic \
  --model <verified-model-id> \
  --capability reasoning \
  --capability review \
  --risk-ceiling low \
  --agent independent_reviewer
```

After the user installs the key locally:

```bash
python3 -m rops models doctor --provider anthropic
python3 -m rops models --root <project> remote-list --provider anthropic
python3 -m rops models --root <project> probe --plan <plan.json> --enroll
python3 -m rops models --root <project> smoke --model-id anthropic/<model-id>
```

`doctor` never displays secret values. `probe` checks connectivity and exact output compliance. `smoke` checks a few deterministic API behaviors. Neither is evidence that a model is good at research or coding.

Unknown providers can be added using an official OpenAI-compatible, Anthropic Messages, or Google Generate Content contract:

```bash
python3 -m rops models --root <project> onboard \
  --provider my-provider \
  --model my-model \
  --protocol openai-chat \
  --base-url https://provider.example/v1 \
  --credential-env MY_PROVIDER_API_KEY
```

## Task contracts and routing

Each dispatch should record objective, task type, frozen inputs, allowed tools/writes/network/hardware, privacy, risk, mutability, acceptance tests, verifier requirement, budget, timeout, and expected handoff.

Routing first applies hard constraints:

1. privacy and provider trust;
2. required capabilities and tools;
3. write/hardware permissions;
4. risk ceiling and verifier requirements;
5. cost, latency, availability, and agent candidate lists.

Eligible models are ranked using task-specific verified history. While evidence is sparse, bounded exploration may try cheaper or unfamiliar models only on low/medium-risk work with deterministic acceptance. Core paper claims, confidential data, destructive actions, and hardware writes require a strong verifier or explicit human control.

Route and dispatch a bounded task:

```bash
python3 -m rops models --root <project> delegate \
  --task-file task-contract.json \
  --prompt-file worker-prompt.txt \
  --agent research_scout \
  --output-dir .research/agents/dispatches
```

This creates a routing decision, result, and handoff. It deliberately does **not** accept the result or update the profile. Run deterministic checks and an independent verifier when required, then record `event_for_registry` through `agent_registry.py record`.

## Model dossiers

Each exact model identity has a structured dossier under:

```text
.research/agents/model-profiles/<provider-model>.json
```

It summarizes observations, task-specific acceptance/quality, human correction, verifier disagreement, recurring failure modes, strengths, weaknesses, manual notes, and prompt-overlay revisions.

Only independently evaluated real tasks update the dossier. Model self-description, onboarding probe, and smoke tests do not. This prevents a model from teaching the router that it is capable merely because it returned a valid response.

Repeated weaknesses can generate a proposed model-specific prompt overlay, for example an instruction to run an edge-case checklist or return explicit uncertainty. Proposed overlays remain inactive until a human approves them:

```bash
python3 -m rops models --root <project> profile --model-id <provider/model>
python3 -m rops models --root <project> profile --model-id <provider/model> --approve-prompt
```

The active overlay is injected after the base Agent role and before task-specific instructions for direct ROPS dispatch and generated native Agent definitions. Human-authored prompt notes can be added with `profile-note --kind prompt`; they remain proposed until the same explicit `--approve-prompt` gate is completed, and are stored separately from the automatically generated overlay to prevent duplicate injection.

## Gateways

Direct adapters support OpenAI-compatible Chat Completions, Anthropic Messages, and Google Generate Content. A LiteLLM or organization gateway is useful when many providers require centralized authentication, retries, quotas, budgets, or usage accounting. The gateway normalizes transport; ROPS still owns semantic routing, privacy/risk constraints, independent acceptance, and model profiles.

## Safety and privacy

`rops models dispatch` and `delegate` are external-data events in the Behavior Runtime. In enforcement mode, non-dry-run dispatch requires the applicable approval. Use the minimum prompt context and never send unpublished papers, credentials, participant data, or restricted artifacts to a provider not approved for that classification.
