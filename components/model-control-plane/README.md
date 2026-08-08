# Model Control Plane compatibility component

`model-control-plane` was the v1.7 name for provider onboarding, dispatch and model dossiers. In v2 its responsibilities are split deliberately:

- [`../model-gateway/`](../model-gateway/) owns provider calls, secrets, endpoint health and pricing;
- [`../model-intelligence/`](../model-intelligence/) owns evaluation events, profiles, routing, warmup, failure patterns, mitigations, drift and Judge calibration.

The `rops models` command remains a compatibility facade. New integrations should depend on the two explicit components rather than this alias.
