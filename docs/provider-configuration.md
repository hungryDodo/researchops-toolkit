# External model provider configuration

Verified against official provider documentation on 2026-08-09. Re-check the linked pages before enabling a provider because model IDs, plan restrictions, and compatibility can change.

## Where API keys belong

There are two consumers with different secret-loading behavior:

| Consumer | Key location | Non-secret provider configuration |
|---|---|---|
| ResearchOps gateway | process environment, or `~/.config/rops/secrets.env` with mode `0600` | project `.researchops/governance/models.json` |
| Codex native custom provider | environment of the process that starts Codex | user `~/.codex/config.toml` |

Codex does not read the ResearchOps secret file automatically. If the same key should work in both paths, export it before starting Codex and optionally keep the same value in the protected ResearchOps secret file. Never put a key value in this repository, `models.json`, a task contract, a log, or a Codex agent TOML file.

Create or update the ResearchOps secret template without replacing existing values:

```bash
python3 -m rops models --root /path/to/project secret-template
chmod 600 ~/.config/rops/secrets.env
```

Fill these lines locally:

```dotenv
DEEPSEEK_API_KEY=
ZAI_API_KEY=
MIMO_API_KEY=
MINIMAX_API_KEY=
```

For Codex, export the same variable names in the shell or service environment that launches it:

```bash
export DEEPSEEK_API_KEY='...'
export ZAI_API_KEY='...'
export MIMO_API_KEY='...'
export MINIMAX_API_KEY='...'
```

If the values are stored in the protected ResearchOps file, load them only into the current shell before starting Codex:

```bash
set -a
. ~/.config/rops/secrets.env
set +a
```

Avoid commands that echo real keys into terminal history. Prefer a protected environment manager, shell file with restrictive permissions, or an OS secret manager.

## Codex native provider setup

Codex custom providers are user-level configuration. Project `.codex/config.toml` cannot override `model_provider` or define `model_providers`, so install the provider tables in `~/.codex/config.toml`:

```bash
python3 -m rops models codex-config --install
```

The command preserves the current default model/provider, manages only marked provider tables, and writes separately layered `~/.codex/researchops_*.config.toml` profile files required by current Codex. It writes `env_key` references, never bearer-token values. See the official [Codex profile documentation](https://developers.openai.com/codex/config-advanced#profiles). Inspect the resulting non-secret status with:

```bash
python3 -m rops models codex-config
```

Start an explicitly selected provider session with the managed profiles:

```bash
codex -p researchops_deepseek
codex -p researchops_mimo_paygo
codex -p researchops_mimo_token_plan
codex -p researchops_minimax_cn
codex -p researchops_minimax_global
```

Override the profile's default `high` effort when a routed arm requests another canonical mode, for example `codex -p researchops_deepseek -c model_reasoning_effort=max`. Managed third-party profiles default to `web_search = "disabled"`: MiMo Token Plan rejects Codex's built-in declaration before model execution, and the other heterogeneous endpoints should not be assumed to implement the same provider-native tool. Enable it only for a separately validated arm.

Choose exactly the MiMo plan and MiniMax region that issued the key. Do not pool their endpoint observations or costs under one arm.

## Provider matrix

| Provider/model | Endpoint and protocol | Meaningful modes | Codex native | Important boundary |
|---|---|---|---|---|
| DeepSeek `deepseek-v4-flash` | `https://api.deepseek.com/responses` | `none`, `high`, `max` | Yes | V4 Pro did not support Responses/Codex on the verification date. `low/medium → high`; `xhigh → max`. |
| Z.AI `glm-5.2` | `https://api.z.ai/api/paas/v4/chat/completions` | `none`, `high`, `max` | No | Official API exposes Chat Completions, while Codex custom providers require Responses. Use the ResearchOps gateway. |
| BigModel China `glm-5.2` | `https://open.bigmodel.cn/api/paas/v4/chat/completions` | `none`, `high`, `max` | No | Use only with a key issued by the China platform. Keep its endpoint evidence separate from Z.AI global. |
| Xiaomi `mimo-v2.5-pro` pay-as-you-go | `https://api.xiaomimimo.com/v1/responses` | `none`, `high` | Yes | Pay-as-you-go keys start with `sk-`. Low/medium/high enable identical thinking behavior. |
| Xiaomi `mimo-v2.5-pro` Token Plan | `https://token-plan-cn.xiaomimimo.com/v1/responses` | `none`, `high` | Yes | Token Plan keys start with `tp-` and are restricted to approved programming tools. Direct ResearchOps probe/dispatch is disabled, and its Codex profile disables the unsupported built-in web-search declaration. |
| MiniMax `MiniMax-M3` China | `https://api.minimaxi.com/v1/responses` | `none`, `high` | Yes | Non-`none` effort enables Adaptive Thinking but does not tune depth. |
| MiniMax `MiniMax-M3` global | `https://api.minimax.io/v1/responses` | `none`, `high` | Yes | Use the endpoint matching the platform that issued the key. |

GLM Coding Plan has a separate coding endpoint, but its official terms restrict it to listed supported tools. ResearchOps therefore does not declare it as a generic direct-dispatch arm or a Codex-native provider.

Official references: [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference), [DeepSeek Responses](https://api-docs.deepseek.com/guides/responses_api/), [DeepSeek thinking](https://api-docs.deepseek.com/guides/thinking_mode), [Z.AI Chat Completions](https://docs.z.ai/api-reference/llm/chat-completion), [Z.AI thinking](https://docs.z.ai/guides/capabilities/thinking), [MiMo Codex configuration](https://mimo.mi.com/docs/en-US/tokenplan/integration/codex-configuration), [MiMo Responses](https://mimo.mi.com/docs/en-US/api/chat/responses), [MiniMax global Codex](https://platform.minimax.io/docs/token-plan/codex), [MiniMax China Responses](https://platform.minimaxi.com/docs/api-reference/responses-create).

## Enabling and calibrating arms

Provider arms ship disabled. After setting the matching credential:

1. Enable only the endpoint/plan and modes actually available in `.researchops/governance/models.json`.
2. Run `python3 -m rops models --root PROJECT sync`.
3. Run `python3 -m rops models --root PROJECT doctor --probe`. A probe updates endpoint and identity telemetry only.
4. Run bounded Anchor or low-risk Shadow tasks with independent acceptance.
5. Record Evaluation Events against the exact arm ID and rebuild profiles.
6. Compare quality, verified progress, correction, disagreement, cost, latency, and endpoint health before widening its risk ceiling.

Every accepted route writes one row per eligible candidate to `route_candidate_scores`, linked to the route decision. Model, endpoint/plan, and behaviorally meaningful reasoning mode therefore converge into the same task-specific scoring system without collapsing evidence across arms.
