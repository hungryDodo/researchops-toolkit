# Model Control Plane

The Model Control Plane is the persistent, non-Skill runtime for adding and using local or third-party model workers. The progressively loaded `adaptive-agent-orchestration` Skill owns human decisions and workflow; this component owns repeatable mechanics.

## Responsibilities

- provider recipes and non-secret provider configuration;
- environment/user-secret resolution without displaying key values;
- current model-list discovery when an endpoint exists;
- connectivity probes and deterministic smoke tests;
- enrollment into `.research/agents/providers.json` and `models.json`;
- candidate-Agent attachment;
- bounded direct dispatch for OpenAI-compatible, Anthropic Messages, and Google Generate Content protocols;
- task-specific routing handoffs;
- model dossiers, human notes, and approved prompt overlays.

## Secret storage

Secrets are resolved from process environment variables first and then `~/.config/rops/secrets.env` or `$ROPS_SECRETS_FILE`. They must never be committed, copied into `.research/`, written into a Skill, pasted into chat, passed as command-line arguments, or recorded in output metadata.

## State

```text
.research/agents/
├── providers.json
├── models.json
├── agents.json
├── routing-policy.json
├── task-history.jsonl
├── profiles.json
├── onboarding/
├── smoke/
├── dispatches/
└── model-profiles/
```

Smoke/probe results establish API connectivity only. Model dossiers learn exclusively from evaluated real-task events. Generated prompt overlays require human approval before activation.
