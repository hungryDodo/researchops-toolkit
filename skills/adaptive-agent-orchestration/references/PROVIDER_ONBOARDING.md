# Provider and model onboarding

Use this mode only when a user adds or changes a provider/model. It is a low-frequency configuration workflow, not a permanently active top-level Skill.

## Ownership split

- This Skill owns discovery, official-document verification, onboarding decisions, smoke design, candidate-agent assignment, and the human handoff.
- `components/model-control-plane/` and `python3 -m rops models ...` own secret-safe mechanics, protocol adapters, provider registry, probes, dispatch, and dossiers.
- The Behavior Runtime owns external-data-transfer proposals and policy checks.
- Harness permissions, the OS/container sandbox, and provider-side key scopes remain the security boundary.

## Workflow

1. Ask for the provider and intended model or capability. Never ask the user to paste an API key into chat.
2. Search current **official provider documentation** for authentication, base URL, protocol, exact model identifier, model-list endpoint, quota/project/region requirements, and data-use constraints. Treat remembered model names as unverified.
3. Prefer a built-in provider recipe. For an unknown provider, create a custom plan only after confirming an official API contract.
4. Create a non-secret plan:

   ```bash
   python3 -m rops models --root <project> onboard \
     --provider <provider> --model <model-id> \
     --capability <capability> --risk-ceiling low \
     --agent <optional-agent>
   ```

5. Tell the user where to put the credential. Preferred order:
   - provider-standard environment variable;
   - `~/.config/rops/secrets.env` with mode `0600`;
   - an organization secrets manager exposed as an environment variable.

   The repository, Skill directories, `.research/`, task prompts, command-line arguments, and chat are prohibited secret locations.
6. After the user says the secret is ready, run `doctor`, optional `remote-list`, then `probe`. A probe proves connectivity and output compliance, not model quality.
7. Enroll only after a successful probe and a privacy/trust-zone review. Attach the model only to explicit candidate agents.
8. Run deterministic smoke tests. Smoke results never update performance profiles.
9. Start with low-risk, independently checkable tasks. The router may perform bounded exploration, but high-risk, confidential, destructive, hardware, or paper-defining tasks require a strong verifier or human review.
10. Record evaluated outcomes. Rebuild the model dossier and propose—not silently activate—model-specific prompt overlays.

## Minimum user input

Usually the user only needs to provide:

- provider identity;
- intended model or desired capability;
- the API key, entered locally outside the Agent conversation.

Some providers additionally require project, region, deployment name, organization, endpoint, service-account, or gateway information. The Agent should discover and explain these from official documentation rather than guessing.

## Completion criteria

Onboarding is complete only when the provider/model is registered, the secret is outside the repository, a probe record exists, smoke tests are stored, trust/risk limits are explicit, candidate agents are listed, and no raw secret value appears in logs.
