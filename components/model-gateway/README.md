# Model Gateway

The gateway normalizes OpenAI Responses and Chat Completions provider calls, secret indirection, behaviorally distinct reasoning controls, endpoint health, pricing, retries, and returned identity metadata. It never interprets a connectivity probe as evidence of model competence. Semantic routing belongs to Model Intelligence.

Provider and plan restrictions remain hard boundaries. A Codex-only subscription arm can participate in routing but must reject direct gateway probes and dispatches.
