from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .common import atomic_json, load_json, now
from .intelligence.drift import record_endpoint_observation, record_identity_observation
from .intelligence.projections import rebuild_projections
from .intelligence.store import IntelligenceStore
from .layout import layout

SECRET_FILE = Path.home() / ".config" / "rops" / "secrets.env"
PROVIDER_APPROVAL_FILE = Path.home() / ".config" / "rops" / "provider-approvals.json"
CODEX_CONFIG_FILE = Path.home() / ".codex" / "config.toml"
CODEX_CONFIG_BEGIN = "# >>> ResearchOps managed model providers >>>"
CODEX_CONFIG_END = "# <<< ResearchOps managed model providers <<<"
CODEX_PROFILE_MARKER = "# ResearchOps managed Codex provider profile."
CODEX_GLM_MODEL_CATALOG = "researchops_glm_models.json"
CODEX_GLM_MODEL_CATALOG_MARKER = "codex-glm-model-catalog-v1"
LITELLM_CONFIG_FILE = Path.home() / ".config" / "rops" / "litellm" / "glm.yaml"
LITELLM_SERVICE_FILE = Path.home() / ".config" / "systemd" / "user" / "researchops-litellm-glm.service"
LITELLM_CONFIG_MARKER = "# ResearchOps managed LiteLLM GLM Responses bridge."
LITELLM_SERVICE_MARKER = "# ResearchOps managed LiteLLM GLM user service."


class ProviderHTTPError(RuntimeError):
    """A provider HTTP rejection with an explicit fallback/health scope."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"HTTP {status}: {detail}")
        self.status = status
        self.failure_scope = (
            "endpoint" if status in {401, 403, 408, 429} or status >= 500 else "arm"
        )

CODEX_PROVIDER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "model": "deepseek-v4-flash",
        "efforts": ["none", "high", "max"],
        "profile": "researchops_deepseek",
        "codex_overrides": {"web_search": "disabled"},
    },
    {
        "id": "glm_litellm",
        "name": "GLM 5.2 via local LiteLLM",
        "base_url": "http://127.0.0.1:4000/v1",
        "env_key": "LITELLM_MASTER_KEY",
        "model": "glm-5.2-high",
        "efforts": ["none", "high", "max"],
        "profile": "researchops_glm",
        "default_effort": "high",
        "model_catalog": "codex-glm-models.json",
        "supports_reasoning_summaries": False,
        "profile_variants": [
            {"profile": "researchops_glm_none", "model": "glm-5.2-none", "default_effort": "none"},
            {"profile": "researchops_glm_max", "model": "glm-5.2-max", "default_effort": "max"},
        ],
        "codex_overrides": {"web_search": "disabled"},
    },
    {
        "id": "mimo_paygo",
        "name": "Xiaomi MiMo pay-as-you-go",
        "base_url": "https://api.xiaomimimo.com/v1",
        "env_key": "MIMO_API_KEY",
        "model": "mimo-v2.5-pro",
        "efforts": ["none", "high"],
        "profile": "researchops_mimo_paygo",
        "codex_overrides": {"web_search": "disabled"},
    },
    {
        "id": "mimo_token_plan",
        "name": "Xiaomi MiMo Token Plan",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "env_key": "MIMO_API_KEY",
        "model": "mimo-v2.5-pro",
        "efforts": ["none", "high"],
        "profile": "researchops_mimo_token_plan",
        "codex_overrides": {"web_search": "disabled"},
    },
    {
        "id": "minimax_cn",
        "name": "MiniMax China",
        "base_url": "https://api.minimaxi.com/v1",
        "env_key": "MINIMAX_API_KEY",
        "model": "MiniMax-M3",
        "efforts": ["none", "high"],
        "profile": "researchops_minimax_cn",
        "codex_overrides": {"web_search": "disabled"},
    },
    {
        "id": "minimax_global",
        "name": "MiniMax Global",
        "base_url": "https://api.minimax.io/v1",
        "env_key": "MINIMAX_API_KEY",
        "model": "MiniMax-M3",
        "efforts": ["none", "high"],
        "profile": "researchops_minimax_global",
        "codex_overrides": {"web_search": "disabled"},
    },
)


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _parse_env(path: Path | None = None) -> dict[str, str]:
    path = path or SECRET_FILE
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, value = text.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _secret(name: str | None) -> str | None:
    if not name:
        return None
    return os.environ.get(name) or _parse_env().get(name)


def _models(root: Path) -> list[dict[str, Any]]:
    return (load_json(layout(root).governance / "models.json", {"models": []}) or {}).get("models", [])


def _trusted_provider_recipes() -> list[dict[str, Any]]:
    path = Path(__file__).resolve().parents[1] / "config" / "provider-recipes.json"
    return (load_json(path, {"recipes": []}) or {}).get("recipes", [])


def _trusted_arm_specs() -> dict[str, dict[str, Any]]:
    runtime_path = Path(__file__).resolve().parents[1] / "config" / "execution-arms.json"
    source_path = (
        Path(__file__).resolve().parents[1]
        / "skills/adaptive-agent-orchestration/assets/models.example.json"
    )
    path = runtime_path if runtime_path.exists() else source_path
    arms = (load_json(path, {"models": []}) or {}).get("models", [])
    return {
        str(item.get("arm_id") or item.get("id") or ""): item
        for item in arms
        if item.get("arm_id") or item.get("id")
    }


EXECUTION_IDENTITY_FIELDS = (
    "provider",
    "model",
    "model_family",
    "model_revision",
    "endpoint_id",
    "deployment_epoch",
    "base_url",
    "api_protocol",
    "credential_env",
    "upstream_credential_env",
    "reasoning_effort",
    "api_reasoning_effort",
    "reasoning_mode",
    "thinking_type",
    "codex_profile",
    "codex_overrides",
    "request_path",
    "chat_path",
    "headers",
    "direct_gateway_allowed",
    "adapter_revision",
    "tool_schema_revision",
    "returned_model_aliases",
    "trust_zone",
    "risk_ceiling",
    "privacy_ceiling",
    "allowed_operations",
    "capabilities",
    "region",
    "plan",
)


def _canonical_identity(model: dict[str, Any]) -> dict[str, Any]:
    identity: dict[str, Any] = {}
    for field in EXECUTION_IDENTITY_FIELDS:
        value = model.get(field)
        if field == "base_url":
            value = str(value or "").rstrip("/")
        elif field == "api_protocol":
            value = _protocol(model)
        elif field == "direct_gateway_allowed":
            value = bool(model.get(field, True))
        elif field in {"headers", "codex_overrides"}:
            value = dict(value or {})
        elif field in {"allowed_operations", "capabilities", "returned_model_aliases"}:
            value = sorted(map(str, value or []))
        elif value is None:
            value = ""
        identity[field] = value
    return identity


def validate_execution_arm_identity(model: dict[str, Any]) -> None:
    arm_id = str(model.get("arm_id") or model.get("id") or "")
    trusted = _trusted_arm_specs().get(arm_id)
    if not trusted or _canonical_identity(model) != _canonical_identity(trusted):
        raise ValueError(f"execution arm {arm_id} does not match its installed immutable identity")
    suffix = arm_id.rsplit("@", 1)[-1] if "@" in arm_id else ""
    if suffix != str(model.get("reasoning_effort") or ""):
        raise ValueError(f"execution arm {arm_id} effort suffix does not match reasoning_effort")


def governed_credential_names() -> set[str]:
    names: set[str] = set()
    for recipe in _trusted_provider_recipes():
        for field in ("credential_env", "upstream_credential_env"):
            if recipe.get(field):
                names.add(str(recipe[field]))
    return names


def _trusted_recipe_for(model: dict[str, Any]) -> dict[str, Any] | None:
    provider = str(model.get("provider") or "")
    model_name = str(model.get("model") or "")
    base_url = str(model.get("base_url") or "").rstrip("/")
    protocol = _protocol(model)
    credential = str(model.get("credential_env") or "")
    for recipe in _trusted_provider_recipes():
        allowed_models = {str(recipe.get("model") or ""), *map(str, recipe.get("model_aliases") or [])}
        if (
            provider == str(recipe.get("provider") or "")
            and model_name in allowed_models
            and base_url == str(recipe.get("base_url") or "").rstrip("/")
            and protocol == str(recipe.get("api_protocol") or "chat_completions")
            and credential == str(recipe.get("credential_env") or "")
            and dict(model.get("headers") or {}) == dict(recipe.get("headers") or {})
            and str(model.get("request_path") or model.get("chat_path") or "")
            == str(recipe.get("request_path") or "")
            and bool(model.get("direct_gateway_allowed", True))
            == bool(recipe.get("direct_gateway_allowed", True))
        ):
            try:
                validate_execution_arm_identity(model)
            except ValueError:
                return None
            return recipe
    return None


def _provider_fingerprint(model: dict[str, Any]) -> str:
    fields = {"arm_id": str(model.get("arm_id") or model.get("id") or ""), **_canonical_identity(model)}
    return hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _provider_approvals() -> dict[str, Any]:
    return load_json(PROVIDER_APPROVAL_FILE, {"schema_version": 2, "projects": {}}) or {
        "schema_version": 2,
        "projects": {},
    }


def _project_approval_identity(project_root: Path) -> tuple[str, str]:
    canonical_root = str(project_root.resolve())
    project_key = hashlib.sha256(canonical_root.encode()).hexdigest()
    return project_key, canonical_root


def approve_external_arm(model: dict[str, Any], project_root: Path) -> dict[str, Any]:
    recipe = _trusted_recipe_for(model)
    if not recipe:
        raise ValueError(
            "external arm does not match an installed trusted provider recipe; refusing to approve endpoint or credential transfer"
        )
    arm_id = str(model.get("arm_id") or model.get("id") or "")
    approvals = _provider_approvals()
    project_key, canonical_root = _project_approval_identity(project_root)
    approvals["schema_version"] = 2
    projects = approvals.setdefault("projects", {})
    project = projects.setdefault(project_key, {"canonical_root": canonical_root, "arms": {}})
    project["canonical_root"] = canonical_root
    project.setdefault("arms", {})[arm_id] = {
        "fingerprint": _provider_fingerprint(model),
        "recipe_id": recipe.get("id"),
        "approved_at": now(),
    }
    PROVIDER_APPROVAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(PROVIDER_APPROVAL_FILE, approvals)
    PROVIDER_APPROVAL_FILE.chmod(0o600)
    return {
        "arm_id": arm_id,
        "recipe_id": recipe.get("id"),
        "project_bound": True,
        "values_exposed": False,
    }


def validate_external_arm_approval(model: dict[str, Any], project_root: Path) -> None:
    if str(model.get("provider") or "") == "codex-native":
        return
    recipe = _trusted_recipe_for(model)
    if not recipe:
        raise ValueError("external arm does not match an installed trusted provider recipe")
    arm_id = str(model.get("arm_id") or model.get("id") or "")
    project_key, canonical_root = _project_approval_identity(project_root)
    project = (_provider_approvals().get("projects") or {}).get(project_key) or {}
    approval = (project.get("arms") or {}).get(arm_id) or {}
    if approval.get("fingerprint") != _provider_fingerprint(model):
        raise ValueError(
            f"external arm {arm_id} is not user-approved for project {canonical_root} and this exact execution identity; "
            f"run `rops models enable --arm-id {arm_id}` from that project"
        )


def _find(root: Path, arm_id: str) -> dict[str, Any]:
    model = next((item for item in _models(root) if str(item.get("arm_id") or item.get("id")) == arm_id), None)
    if not model:
        raise ValueError(f"unknown execution arm: {arm_id}")
    return model


def sync_registry(store: IntelligenceStore) -> dict[str, Any]:
    models = _models(store.layout.root)
    updated = 0
    with store.transaction() as connection:
        for model in models:
            arm_id = str(model.get("arm_id") or model.get("id"))
            if not arm_id:
                continue
            provider = str(model.get("provider") or "unknown")
            family = str(model.get("model_family") or model.get("model") or arm_id)
            revision = model.get("model_revision")
            endpoint = model.get("endpoint_id") or model.get("base_url")
            epoch = str(model.get("deployment_epoch") or "epoch-1")
            connection.execute(
                """
                INSERT INTO execution_arms(arm_id,provider,model_family,model_revision,endpoint_id,deployment_epoch,enabled,config_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(arm_id) DO UPDATE SET provider=excluded.provider,model_family=excluded.model_family,
                  model_revision=excluded.model_revision,endpoint_id=excluded.endpoint_id,deployment_epoch=excluded.deployment_epoch,
                  enabled=excluded.enabled,config_json=excluded.config_json,updated_at=excluded.updated_at
                """,
                (arm_id, provider, family, revision, endpoint, epoch, int(model.get("enabled", False)), json.dumps(model, ensure_ascii=False, sort_keys=True), now(), now()),
            )
            updated += 1
    return {"execution_arms": updated}


def set_enabled(store: IntelligenceStore, arm_ids: list[str], enabled: bool) -> dict[str, Any]:
    requested = [str(value).strip() for value in arm_ids if str(value).strip()]
    if not requested:
        raise ValueError("at least one --arm-id is required")
    path = store.layout.governance / "models.json"
    registry = load_json(path, {"models": []}) or {"models": []}
    by_id = {_arm_id: item for item in registry.get("models", []) if (_arm_id := str(item.get("arm_id") or item.get("id") or ""))}
    missing = sorted(set(requested) - set(by_id))
    if missing:
        raise ValueError("unknown execution arm: " + ", ".join(missing))
    changed: list[str] = []
    approvals: list[dict[str, Any]] = []
    for arm_id in requested:
        model = by_id[arm_id]
        if enabled and str(model.get("provider") or "") != "codex-native":
            approvals.append(approve_external_arm(model, store.layout.root))
        if bool(model.get("enabled", False)) != enabled:
            model["enabled"] = enabled
            changed.append(arm_id)
    atomic_json(path, registry)
    synced = sync_registry(store)
    return {
        "enabled": enabled,
        "requested": requested,
        "changed": changed,
        "registry": synced,
        "provider_approvals": approvals,
        "competence_updated": False,
    }


def secret_template(root: Path) -> dict[str, Any]:
    names = sorted({str(item.get("credential_env")) for item in _models(root) if item.get("credential_env")})
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = SECRET_FILE.read_text(encoding="utf-8") if SECRET_FILE.exists() else "# ResearchOps secrets. Never commit this file.\n"
    present = {
        line.split("=", 1)[0].strip()
        for line in existing.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    }
    missing = [name for name in names if name not in present]
    if missing:
        separator = "" if existing.endswith("\n") else "\n"
        existing += separator + "".join(f"{name}=\n" for name in missing)
        SECRET_FILE.write_text(existing, encoding="utf-8")
    elif not SECRET_FILE.exists():
        SECRET_FILE.write_text(existing, encoding="utf-8")
    try:
        SECRET_FILE.chmod(0o600)
    except OSError:
        pass
    return {"path": str(SECRET_FILE), "variables": names, "added": missing, "values_exposed": False}


def secret_status(root: Path) -> dict[str, Any]:
    file_values = _parse_env()
    entries = []
    for name in sorted({str(item.get("credential_env")) for item in _models(root) if item.get("credential_env")}):
        source = "environment" if os.environ.get(name) else "secrets-file" if file_values.get(name) else "missing"
        entries.append({"name": name, "configured": source != "missing", "source": source})
    return {"path": str(SECRET_FILE), "secrets": entries, "values_exposed": False}


def _headers(model: dict[str, Any]) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = _secret(model.get("credential_env"))
    if token:
        headers["Authorization"] = f"Bearer {token}"
    for key, value in (model.get("headers") or {}).items():
        if isinstance(value, str) and value.startswith("env:"):
            actual = _secret(value[4:])
            if actual:
                headers[str(key)] = actual
        else:
            headers[str(key)] = str(value)
    return headers


def _protocol(model: dict[str, Any]) -> str:
    raw = str(model.get("api_protocol") or model.get("protocol") or "chat_completions").strip().lower().replace("-", "_")
    aliases = {
        "openai_chat_compatible": "chat_completions",
        "openai_chat": "chat_completions",
        "chat_completion": "chat_completions",
        "openai_responses": "responses",
    }
    protocol = aliases.get(raw, raw)
    if protocol not in {"chat_completions", "responses"}:
        raise ValueError(f"unsupported API protocol: {raw}")
    return protocol


def _request_path(model: dict[str, Any]) -> str:
    protocol = _protocol(model)
    configured = model.get("request_path") or model.get("chat_path")
    path = str(configured or ("/responses" if protocol == "responses" else "/chat/completions"))
    return path if path.startswith("/") else "/" + path


def _prepare_payload(model: dict[str, Any], request_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize one execution arm onto its provider's declared wire protocol."""

    protocol = _protocol(model)
    payload = dict(request_data)
    payload.setdefault("model", model.get("model"))
    effort = model.get("api_reasoning_effort", model.get("reasoning_effort"))
    thinking_type = model.get("thinking_type")
    if protocol == "responses":
        if "input" not in payload and "messages" in payload:
            payload["input"] = payload.pop("messages")
        if "max_output_tokens" not in payload and "max_tokens" in payload:
            payload["max_output_tokens"] = payload.pop("max_tokens")
        if effort is not None and "reasoning" not in payload:
            payload["reasoning"] = {"effort": effort}
    else:
        if "messages" not in payload and "input" in payload:
            raw_input = payload.pop("input")
            payload["messages"] = raw_input if isinstance(raw_input, list) else [{"role": "user", "content": str(raw_input)}]
        if effort is not None and "reasoning_effort" not in payload:
            payload["reasoning_effort"] = effort
        if thinking_type and "thinking" not in payload:
            payload["thinking"] = {"type": thinking_type}
    return payload


def _direct_gateway_allowed(model: dict[str, Any]) -> bool:
    return bool(model.get("direct_gateway_allowed", True))


def _request(model: dict[str, Any], payload: dict[str, Any], *, timeout: float = 120.0) -> tuple[dict[str, Any], float, dict[str, str]]:
    base = str(model.get("base_url") or model.get("endpoint_id") or "").rstrip("/")
    if not base:
        raise ValueError("execution arm has no OpenAI-compatible base_url")
    path = _request_path(model)
    request = urllib.request.Request(base + path, data=json.dumps(payload).encode("utf-8"), headers=_headers(model), method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            headers = {key.lower(): value for key, value in response.headers.items()}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ProviderHTTPError(exc.code, body[:800]) from exc
    latency = time.monotonic() - started
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("provider returned a non-object response")
    return data, latency, headers


def probe(store: IntelligenceStore, arm_id: str, *, timeout: float = 60.0) -> dict[str, Any]:
    model = _find(store.layout.root, arm_id)
    validate_external_arm_approval(model, store.layout.root)
    if not _direct_gateway_allowed(model):
        return {
            "status": "skipped",
            "arm_id": arm_id,
            "reason": "provider plan is restricted to an approved coding client; direct gateway probes are disabled",
            "competence_updated": False,
        }
    endpoint = str(model.get("endpoint_id") or model.get("base_url") or arm_id)
    request_data: dict[str, Any]
    if _protocol(model) == "responses":
        request_data = {"input": "Return exactly the JSON object {\"status\":\"ok\"}.", "max_output_tokens": 32}
    else:
        request_data = {
            "messages": [{"role": "user", "content": "Return exactly the JSON object {\"status\":\"ok\"}."}],
            "temperature": 0,
            "max_tokens": 32,
        }
    payload = _prepare_payload(model, request_data)
    try:
        response, latency, headers = _request(model, payload, timeout=timeout)
        declared = {"requested_model": model.get("model"), "returned_model": response.get("model"), "api_version": headers.get("openai-version")}
        fingerprint = {
            "system_fingerprint": response.get("system_fingerprint"),
            "response_shape": sorted(response),
            "finish_reason": (((response.get("choices") or [{}])[0] or {}).get("finish_reason")) if _protocol(model) == "chat_completions" else response.get("status"),
            "api_protocol": _protocol(model),
        }
        endpoint_obs = record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=True, latency_seconds=latency, metadata={"kind": "probe", "usage": response.get("usage")})
        identity_obs = record_identity_observation(store, arm_id=arm_id, endpoint_id=endpoint, declared_identity=declared, fingerprint=fingerprint)
        return {"status": "healthy", "arm_id": arm_id, "latency_seconds": round(latency, 6), "endpoint_observation": endpoint_obs, "identity_observation": identity_obs, "competence_updated": False}
    except Exception as exc:
        endpoint_obs = None
        if not isinstance(exc, ProviderHTTPError) or exc.failure_scope == "endpoint":
            endpoint_obs = record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=False, latency_seconds=timeout, error_class=type(exc).__name__, metadata={"kind": "probe", "http_status": getattr(exc, "status", None)})
        return {"status": "failed", "arm_id": arm_id, "error": str(exc), "endpoint_observation": endpoint_obs, "competence_updated": False}


def dispatch(store: IntelligenceStore, arm_id: str, request_data: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    model = _find(store.layout.root, arm_id)
    validate_external_arm_approval(model, store.layout.root)
    if not _direct_gateway_allowed(model):
        raise ValueError("this execution arm is restricted to an approved coding client; direct gateway dispatch is disabled")
    endpoint = str(model.get("endpoint_id") or model.get("base_url") or arm_id)
    payload = _prepare_payload(model, request_data)
    try:
        response, latency, headers = _request(model, payload, timeout=timeout)
        record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=True, latency_seconds=latency, metadata={"kind": "dispatch", "usage": response.get("usage")})
        return {"dispatch_id": "dispatch-" + uuid.uuid4().hex[:16], "arm_id": arm_id, "model": model.get("model"), "reasoning_effort": model.get("reasoning_effort"), "api_protocol": _protocol(model), "latency_seconds": round(latency, 6), "response": response, "returned_model": response.get("model"), "evaluation_pending": True}
    except Exception as exc:
        if not isinstance(exc, ProviderHTTPError) or exc.failure_scope == "endpoint":
            record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=False, latency_seconds=timeout, error_class=type(exc).__name__, metadata={"kind": "dispatch", "http_status": getattr(exc, "status", None)})
        raise


def dossier(root: Path, arm_id: str | None = None) -> dict[str, Any]:
    store = IntelligenceStore(root)
    paths = rebuild_projections(store)
    index = json.loads((store.layout.exports / "model-dossiers.json").read_text(encoding="utf-8"))
    if not arm_id:
        return index
    entry = next((item for item in index.get("models", []) if item["execution_arm_id"] == arm_id), None)
    if not entry:
        raise ValueError(f"no dossier for {arm_id}; record accepted evidence first")
    return json.loads((store.layout.exports / entry["path"]).read_text(encoding="utf-8"))


def _codex_provider_block() -> str:
    lines = [CODEX_CONFIG_BEGIN, "# API keys are read from environment variables; no key value belongs in this file."]
    for spec in CODEX_PROVIDER_SPECS:
        lines.extend(
            [
                "",
                f"[model_providers.{spec['id']}]",
                f"name = {json.dumps(spec['name'])}",
                f"base_url = {json.dumps(spec['base_url'])}",
                f"env_key = {json.dumps(spec['env_key'])}",
                f"env_key_instructions = {json.dumps('Set ' + spec['env_key'] + ' in the environment before starting Codex.')}",
                'wire_api = "responses"',
            ]
        )
    lines.extend(["", CODEX_CONFIG_END, ""])
    return "\n".join(lines)


def _codex_profile_text(spec: dict[str, Any], *, config_dir: Path) -> str:
    lines = [
        CODEX_PROFILE_MARKER,
        "# API keys remain environment variables referenced by the provider table in config.toml.",
        f"model_provider = {json.dumps(spec['id'])}",
        f"model = {json.dumps(spec['model'])}",
        f"model_reasoning_effort = {json.dumps(spec.get('default_effort', 'high'))}",
        'model_reasoning_summary = "none"',
        f"model_supports_reasoning_summaries = {str(spec.get('supports_reasoning_summaries', True)).lower()}",
    ]
    if spec.get("model_catalog"):
        lines.append(f"model_catalog_json = {json.dumps(str(config_dir / CODEX_GLM_MODEL_CATALOG))}")
    for key, value in spec.get("codex_overrides", {}).items():
        lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def _codex_profile_specs() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for provider in CODEX_PROVIDER_SPECS:
        profiles.append(dict(provider))
        for variant in provider.get("profile_variants", []):
            profiles.append({**provider, **variant, "profile_variants": []})
    return profiles


def _atomic_text(target: Path, content: str, *, default_mode: int = 0o600) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(temporary, (target.stat().st_mode & 0o777) if target.exists() else default_mode)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _litellm_glm_config_text() -> str:
    return (Path(__file__).resolve().parents[1] / "config" / "litellm-glm.yaml").read_text(encoding="utf-8")


def _codex_glm_model_catalog_text() -> str:
    return (Path(__file__).resolve().parents[1] / "config" / "codex-glm-models.json").read_text(encoding="utf-8")


def _litellm_service_text() -> str:
    return (Path(__file__).resolve().parents[1] / "config" / "researchops-litellm-glm.service").read_text(encoding="utf-8")


def _ensure_generated_secret(name: str) -> dict[str, Any]:
    SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
    existing = SECRET_FILE.read_text(encoding="utf-8") if SECRET_FILE.exists() else "# ResearchOps secrets. Never commit this file.\n"
    matches = [line for line in existing.splitlines() if line.strip() and not line.lstrip().startswith("#") and "=" in line and line.split("=", 1)[0].strip() == name]
    if len(matches) > 1:
        raise ValueError(f"duplicate {name} entries in {SECRET_FILE}")
    if matches and matches[0].split("=", 1)[1].strip().strip('"').strip("'"):
        SECRET_FILE.chmod(0o600)
        return {"name": name, "generated": False, "configured": True, "value_exposed": False}
    value = "sk-rops-" + secrets.token_urlsafe(32)
    lines = existing.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if line.strip() and not line.lstrip().startswith("#") and "=" in line and line.split("=", 1)[0].strip() == name:
            lines[index] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")
    _atomic_text(SECRET_FILE, "\n".join(lines) + "\n")
    return {"name": name, "generated": True, "configured": True, "value_exposed": False}


def litellm_config(
    *,
    install: bool = False,
    path: Path | None = None,
    service_path: Path | None = None,
    generate_master_key: bool = False,
) -> dict[str, Any]:
    target = (path or LITELLM_CONFIG_FILE).expanduser()
    service_target = (service_path or LITELLM_SERVICE_FILE).expanduser()
    if install:
        for candidate, marker in ((target, LITELLM_CONFIG_MARKER), (service_target, LITELLM_SERVICE_MARKER)):
            if candidate.exists() and marker not in candidate.read_text(encoding="utf-8"):
                raise ValueError(f"unmanaged LiteLLM file already exists: {candidate}")
        _atomic_text(target, _litellm_glm_config_text())
        _atomic_text(service_target, _litellm_service_text())
    generated = _ensure_generated_secret("LITELLM_MASTER_KEY") if generate_master_key else {
        "name": "LITELLM_MASTER_KEY",
        "generated": False,
        "configured": bool(_secret("LITELLM_MASTER_KEY")),
        "value_exposed": False,
    }
    return {
        "installed": install,
        "config_path": str(target),
        "service_path": str(service_target),
        "listen": "127.0.0.1:4000",
        "responses_url": "http://127.0.0.1:4000/v1/responses",
        "upstream": "https://api.z.ai/api/paas/v4/chat/completions",
        "models": ["glm-5.2-none", "glm-5.2-high", "glm-5.2-max"],
        "upstream_key_configured": bool(_secret("ZAI_API_KEY")),
        "proxy_key": generated,
        "secret_values_exposed": False,
        "install_command": "uv tool install --force 'litellm[proxy]==1.96.0' --with 'fastapi==0.136.3'",
        "start_commands": [
            "systemctl --user daemon-reload",
            "systemctl --user enable --now researchops-litellm-glm.service",
            "codex -p researchops_glm",
        ],
    }


def codex_config(*, install: bool = False, path: Path | None = None) -> dict[str, Any]:
    target = (path or CODEX_CONFIG_FILE).expanduser()
    installed = False
    if install:
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        block = _codex_provider_block()
        if (CODEX_CONFIG_BEGIN in existing) != (CODEX_CONFIG_END in existing):
            raise ValueError(f"incomplete ResearchOps managed block in {target}")
        if CODEX_CONFIG_BEGIN in existing:
            pattern = re.compile(re.escape(CODEX_CONFIG_BEGIN) + r".*?" + re.escape(CODEX_CONFIG_END) + r"\n?", re.S)
            updated = pattern.sub(block, existing)
        else:
            collisions = [
                spec["id"]
                for spec in CODEX_PROVIDER_SPECS
                if re.search(rf"^\[model_providers\.{re.escape(spec['id'])}\]\s*$", existing, re.M)
            ]
            if collisions:
                raise ValueError("unmanaged Codex provider table already exists: " + ", ".join(collisions))
            separator = "" if not existing or existing.endswith("\n") else "\n"
            updated = existing + separator + ("\n" if existing else "") + block
        profile_targets = [(spec, target.parent / f"{spec['profile']}.config.toml") for spec in _codex_profile_specs()]
        for _, profile_path in profile_targets:
            if profile_path.exists() and CODEX_PROFILE_MARKER not in profile_path.read_text(encoding="utf-8"):
                raise ValueError(f"unmanaged Codex profile file already exists: {profile_path}")
        catalog_path = target.parent / CODEX_GLM_MODEL_CATALOG
        if catalog_path.exists():
            existing_catalog = load_json(catalog_path, {}) or {}
            if existing_catalog.get("researchops_managed") != CODEX_GLM_MODEL_CATALOG_MARKER:
                raise ValueError(f"unmanaged Codex model catalog already exists: {catalog_path}")
        _atomic_text(target, updated)
        _atomic_text(catalog_path, _codex_glm_model_catalog_text())
        for spec, profile_path in profile_targets:
            _atomic_text(profile_path, _codex_profile_text(spec, config_dir=target.parent))
        installed = True
    providers = [
        {
            "id": spec["id"],
            "model": spec["model"],
            "reasoning_efforts": spec["efforts"],
            "base_url": spec["base_url"],
            "credential_env": spec["env_key"],
            "codex_profile": spec["profile"],
            "codex_profile_path": str(target.parent / f"{spec['profile']}.config.toml"),
            "codex_profile_variants": [item["profile"] for item in spec.get("profile_variants", [])],
            "codex_model_catalog_path": str(target.parent / CODEX_GLM_MODEL_CATALOG) if spec.get("model_catalog") else None,
            "codex_overrides": spec.get("codex_overrides", {}),
        }
        for spec in CODEX_PROVIDER_SPECS
    ]
    return {
        "path": str(target),
        "installed": installed,
        "default_model_changed": False,
        "providers": providers,
        "glm_codex_native": False,
        "glm_codex_bridge": True,
        "glm_reason": "GLM remains a Chat Completions upstream; the glm_litellm provider exposes a local Responses bridge",
        "secret_values_written": False,
        "launch_examples": [
            "codex -p researchops_deepseek",
            "codex -p researchops_glm",
            "codex -p researchops_glm_none",
            "codex -p researchops_glm_max",
            "codex -p researchops_mimo_paygo",
            "codex -p researchops_mimo_token_plan",
            "codex -p researchops_minimax_cn",
            "codex -p researchops_minimax_global",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rops models")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync")
    sub.add_parser("list")
    sub.add_parser("secret-template")
    sub.add_parser("secret-status")
    codex = sub.add_parser("codex-config"); codex.add_argument("--install", action="store_true"); codex.add_argument("--path")
    bridge = sub.add_parser("litellm-config"); bridge.add_argument("--install", action="store_true"); bridge.add_argument("--path"); bridge.add_argument("--service-path"); bridge.add_argument("--generate-master-key", action="store_true")
    doctor = sub.add_parser("doctor"); doctor.add_argument("--probe", action="store_true")
    probe_parser = sub.add_parser("probe"); probe_parser.add_argument("--arm-id", required=True); probe_parser.add_argument("--timeout", type=float, default=60)
    dispatch_parser = sub.add_parser("dispatch"); dispatch_parser.add_argument("--arm-id", required=True); dispatch_parser.add_argument("--request-json"); dispatch_parser.add_argument("--request-file"); dispatch_parser.add_argument("--timeout", type=float, default=120)
    enable_parser = sub.add_parser("enable"); enable_parser.add_argument("--arm-id", action="append", required=True)
    disable_parser = sub.add_parser("disable"); disable_parser.add_argument("--arm-id", action="append", required=True)
    dossier_parser = sub.add_parser("dossier"); dossier_parser.add_argument("--arm-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "codex-config":
        _emit(codex_config(install=args.install, path=Path(args.path) if args.path else None))
        return 0
    if args.command == "litellm-config":
        _emit(litellm_config(
            install=args.install,
            path=Path(args.path) if args.path else None,
            service_path=Path(args.service_path) if args.service_path else None,
            generate_master_key=args.generate_master_key,
        ))
        return 0
    store = IntelligenceStore(root)
    if args.command == "sync":
        _emit(sync_registry(store))
    elif args.command == "list":
        _emit({"models": _models(root)})
    elif args.command == "secret-template":
        _emit(secret_template(root))
    elif args.command == "secret-status":
        _emit(secret_status(root))
    elif args.command == "doctor":
        sync_registry(store)
        models = _models(root)
        result = {"models": [{"arm_id": item.get("arm_id") or item.get("id"), "enabled": item.get("enabled"), "provider": item.get("provider"), "endpoint": item.get("endpoint_id") or item.get("base_url"), "credential_configured": bool(_secret(item.get("credential_env")) if item.get("credential_env") else True)} for item in models], "secrets": secret_status(root), "probes": []}
        if args.probe:
            result["probes"] = [probe(store, str(item.get("arm_id") or item.get("id"))) for item in models if item.get("enabled") and item.get("base_url")]
        _emit(result)
    elif args.command == "probe":
        _emit(probe(store, args.arm_id, timeout=args.timeout))
    elif args.command == "dispatch":
        if bool(args.request_json) == bool(args.request_file):
            raise ValueError("provide exactly one of --request-json or --request-file")
        request_data = json.loads(args.request_json) if args.request_json else json.loads(Path(args.request_file).read_text(encoding="utf-8"))
        _emit(dispatch(store, args.arm_id, request_data, timeout=args.timeout))
    elif args.command == "enable":
        _emit(set_enabled(store, args.arm_id, True))
    elif args.command == "disable":
        _emit(set_enabled(store, args.arm_id, False))
    elif args.command == "dossier":
        _emit(dossier(root, args.arm_id))
    return 0
