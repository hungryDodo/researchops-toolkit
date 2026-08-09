# Provider onboarding

## Procedure

1. Verify current official provider documentation before changing model IDs, endpoints, plan scope, or effort mappings.
2. Declare each behaviorally distinct model + endpoint/plan + reasoning mode as one non-secret execution arm. Do not create duplicate arms for API effort labels that the provider maps to identical behavior.
3. Put credential values in the process environment or `~/.config/rops/secrets.env`; keep only `credential_env` in project state.
4. For Codex-native providers, configure user `~/.codex/config.toml` with `env_key` and `wire_api = "responses"`. Do not hard-code bearer tokens. Project config cannot define model providers.
5. Sync the registry and run a bounded probe. Record endpoint/identity telemetry only; never treat connectivity as competence.
6. Run an Anchor or low-risk Shadow work unit with independent acceptance before normal routing.
7. Inspect disclosure boundary, plan terms, cost, endpoint health, returned identity, and effort behavior before enabling a wider risk ceiling.

## Verified compatibility snapshot

Snapshot date: 2026-08-09.

| Arm family | Protocol/base | Canonical modes | Codex |
|---|---|---|---|
| DeepSeek V4 Flash | Responses, `https://api.deepseek.com` | `none/high/max` | Native; V4 Pro excluded until its Responses support is verified |
| Z.AI/BigModel GLM-5.2 | Chat Completions, global or China general API | `none/high/max` | Gateway only |
| MiMo v2.5 Pro | Responses, pay-as-you-go or Token Plan endpoint | `none/high` | Native; Token Plan direct gateway calls disabled |
| MiniMax M3 | Responses, China or global endpoint | `none/high` | Native |

DeepSeek maps low/medium to high and xhigh to max. GLM-5.2 maps none/minimal to no thinking, low/medium to high, and xhigh to max. MiMo and MiniMax use any non-none effort as an on/off thinking switch without depth control.

Use `config/provider-recipes.json` in a source/package checkout for exact endpoints and official-documentation links. A provider may preserve one public model ID while changing hidden behavior, so use deployment epochs and observed drift without claiming an unobservable cause.
