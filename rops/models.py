from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from . import ROOT

UTC = dt.timezone.utc
RISK_PROVIDER = {
    "openai-chat": "openai-compatible",
    "anthropic-messages": "anthropic-direct",
    "google-generate-content": "google-direct",
}


def iso() -> str:
    return dt.datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower()


def sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def agent_dir(root: Path) -> Path:
    return root / ".research" / "agents"


def provider_recipes() -> dict[str, Any]:
    return load_json(ROOT / "config" / "provider-recipes.json", {"providers": {}})


def recipe(provider: str) -> dict[str, Any]:
    item = provider_recipes().get("providers", {}).get(provider)
    if not isinstance(item, dict):
        raise ValueError(f"unknown provider recipe: {provider}")
    return {"id": provider, **item}


def list_recipes(provider: str | None = None) -> dict[str, Any]:
    recipes = provider_recipes().get("providers", {})
    if provider:
        return {"schema_version": 1, "provider": recipe(provider)}
    return {
        "schema_version": 1,
        "providers": [
            {
                "id": key,
                "display_name": value.get("display_name", key),
                "protocol": value.get("protocol"),
                "credential_env": value.get("credential_env", []),
                "base_url": value.get("base_url"),
                "docs": value.get("docs", []),
            }
            for key, value in sorted(recipes.items())
        ],
    }


def secrets_file() -> Path:
    configured = os.environ.get("ROPS_SECRETS_FILE", "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".config" / "rops" / "secrets.env"


def parse_secret_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line_no, raw in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            raise ValueError(f"invalid secret file line {line_no}: expected NAME=value")
        name, value = line.split("=", 1)
        name = name.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise ValueError(f"invalid secret variable name at line {line_no}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[name] = value
    return values


def resolve_secret(names: list[str], optional: bool = False) -> tuple[str, str | None]:
    for name in names:
        value = os.environ.get(name, "")
        if value:
            return value, f"environment:{name}"
    path = secrets_file()
    if path.exists() and os.name != "nt":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            raise ValueError(f"secret file permissions are too broad ({oct(mode)}); require 0600 or 0400: {path}")
    file_values = parse_secret_file(path)
    for name in names:
        value = file_values.get(name, "")
        if value:
            return value, f"secret-file:{name}"
    if optional:
        return "", None
    raise ValueError("credential not found; expected one of: " + ", ".join(names))


def secret_template(provider: str, write: bool = False) -> dict[str, Any]:
    item = recipe(provider)
    envs = list(item.get("credential_env", []))
    path = secrets_file()
    result: dict[str, Any] = {
        "schema_version": 1,
        "provider": provider,
        "path": str(path),
        "variables": envs,
        "written": False,
        "instructions": [
            f"Open {path} in a local editor outside the Agent conversation.",
            "Fill exactly one supported credential variable.",
            "Never paste the key into chat, Skill files, Git, .research, or a command-line argument.",
            f"Set permissions with: chmod 600 {path}",
        ],
    }
    if not write:
        return result
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    existing = path.read_text(encoding="utf-8") if path.exists() else "# ROPS user secrets. Never commit this file.\n"
    known = set(parse_secret_file(path)) if path.exists() else set()
    additions = [f"{name}=\n" for name in envs if name not in known]
    if additions:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        path.write_text(existing + "".join(additions), encoding="utf-8")
    path.chmod(0o600)
    result["written"] = True
    result["added_variables"] = [name for name in envs if name not in known]
    return result


def provider_config(provider: str, root: Path | None = None) -> dict[str, Any]:
    """Resolve a built-in recipe or an enrolled project provider without exposing secrets."""
    try:
        return recipe(provider)
    except ValueError:
        if root is None:
            raise
        providers = load_json(agent_dir(root) / "providers.json", {"providers": []}).get("providers", [])
        item = next((entry for entry in providers if entry.get("id") == provider), None)
        if isinstance(item, dict):
            return dict(item)
        # During onboarding the provider is intentionally not enrolled yet; resolve its
        # non-secret connection metadata from the newest matching content-bound plan.
        onboarding = agent_dir(root) / "onboarding"
        for plan_path in sorted(onboarding.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True) if onboarding.exists() else []:
            if plan_path.name.endswith(".probe.json"):
                continue
            plan = load_json(plan_path, {})
            candidate = plan.get("provider")
            if isinstance(candidate, dict) and candidate.get("id") == provider:
                return dict(candidate)
        raise ValueError(f"unknown provider recipe, onboarding plan, or enrolled provider: {provider}")


def secret_status(provider: str, root: Path | None = None) -> dict[str, Any]:
    item = provider_config(provider, root)
    envs = list(item.get("credential_env", []))
    path = secrets_file()
    file_values: dict[str, str] = {}
    file_error = None
    if path.exists():
        try:
            file_values = parse_secret_file(path)
        except Exception as exc:  # metadata only
            file_error = str(exc)
    found: list[dict[str, Any]] = []
    for name in envs:
        source = None
        if os.environ.get(name):
            source = "environment"
        elif file_values.get(name):
            source = "secret-file"
        found.append({"name": name, "present": source is not None, "source": source})
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    permissions_safe = mode in {0o600, 0o400} if mode is not None else None
    environment_ready = any(x["present"] and x["source"] == "environment" for x in found)
    file_ready = bool(permissions_safe) and not file_error and any(x["present"] and x["source"] == "secret-file" for x in found)
    return {
        "schema_version": 1,
        "provider": provider,
        "secret_file": str(path),
        "secret_file_exists": path.exists(),
        "secret_file_mode": oct(mode) if mode is not None else None,
        "secret_file_permissions_safe": permissions_safe,
        "file_parse_error": file_error,
        "credentials": found,
        "ready": bool(item.get("credential_optional")) or environment_ready or file_ready,
        "values_exposed": False,
    }


def create_plan(
    root: Path,
    provider: str,
    model: str,
    base_url: str | None = None,
    protocol: str | None = None,
    credential_env: str | None = None,
    capabilities: list[str] | None = None,
    risk_ceiling: str = "low",
    trust_zone: str | None = None,
    candidate_agents: list[str] | None = None,
) -> dict[str, Any]:
    try:
        item = recipe(provider)
    except ValueError:
        if not protocol or not base_url:
            raise ValueError("custom provider requires --protocol and --base-url")
        item = {
            "id": provider,
            "display_name": provider,
            "protocol": protocol,
            "base_url": base_url,
            "credential_env": [credential_env] if credential_env else [],
            "credential_optional": not bool(credential_env),
            "docs": [],
            "default_trust_zone": trust_zone or "external-unreviewed",
        }
    if base_url:
        item["base_url"] = base_url
    if protocol:
        item["protocol"] = protocol
    if credential_env:
        item["credential_env"] = [credential_env]
        item["credential_optional"] = False
    if trust_zone:
        item["default_trust_zone"] = trust_zone
    provider_id = slug(provider)
    model_id = f"{provider_id}/{model}"
    plan_id = f"onboard-{provider_id}-{slug(model)}-{dt.datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    plan = {
        "schema_version": 1,
        "plan_id": plan_id,
        "created_at": iso(),
        "status": "awaiting-secret",
        "provider": {
            "id": provider_id,
            "display_name": item.get("display_name", provider),
            "protocol": item.get("protocol"),
            "base_url": str(item.get("base_url", "")).rstrip("/"),
            "credential_env": list(item.get("credential_env", [])),
            "credential_optional": bool(item.get("credential_optional", False)),
            "api_version": item.get("api_version"),
            "model_list_path": item.get("model_list_path"),
            "default_headers_env": item.get("default_headers_env", {}),
            "trust_zone": item.get("default_trust_zone", "external-unreviewed"),
            "docs": item.get("docs", []),
        },
        "model": {
            "id": model_id,
            "model": model,
            "enabled_after_probe": True,
            "risk_ceiling": risk_ceiling,
            "capabilities": capabilities or ["text"],
            "task_affinity": {},
            "cost_hint": 0.5,
            "latency_hint": 0.5,
            "candidate_agents": sorted(set(candidate_agents or [])),
        },
        "human_steps": [
            "Review the linked official provider documentation and model identifier.",
            "Place the API key in an environment variable or the user secret file; do not give it to the Agent.",
            "Tell the Agent that the secret is ready, then run doctor and probe.",
            "Enroll the model only after a successful probe and privacy-policy review.",
        ],
    }
    plan["plan_sha256"] = canonical_sha({k: v for k, v in plan.items() if k != "plan_sha256"})
    path = agent_dir(root) / "onboarding" / f"{plan_id}.json"
    atomic_json(path, plan)
    secret_info = secret_template(provider, write=False) if provider in provider_recipes().get("providers", {}) else {
        "schema_version": 1,
        "provider": provider_id,
        "path": str(secrets_file()),
        "variables": list(plan["provider"].get("credential_env", [])),
        "written": False,
        "instructions": [
            "Set the named variable in the process environment or the user-level ROPS secret file.",
            "Never paste the value into chat, Git, Skills, .research, or command-line arguments.",
        ],
    }
    return {"plan": plan, "path": str(path), "secret": secret_info}


def plan_path(root: Path, plan_ref: str) -> Path:
    candidate = Path(plan_ref)
    if candidate.exists():
        return candidate.resolve()
    path = agent_dir(root) / "onboarding" / (plan_ref if plan_ref.endswith(".json") else plan_ref + ".json")
    if not path.exists():
        raise ValueError(f"onboarding plan not found: {plan_ref}")
    return path


def load_plan(root: Path, plan_ref: str) -> tuple[Path, dict[str, Any]]:
    path = plan_path(root, plan_ref)
    plan = load_json(path, {})
    expected = plan.get("plan_sha256")
    actual = canonical_sha({k: v for k, v in plan.items() if k != "plan_sha256"})
    if expected != actual:
        raise ValueError("onboarding plan hash mismatch")
    return path, plan


def default_headers(provider: dict[str, Any], key: str) -> dict[str, str]:
    protocol = provider.get("protocol")
    headers = {"Content-Type": "application/json", "User-Agent": "ResearchOps-Toolkit/1.7"}
    if protocol == "anthropic-messages":
        if key:
            headers["x-api-key"] = key
        headers["anthropic-version"] = str(provider.get("api_version") or "2023-06-01")
    elif protocol == "google-generate-content":
        if key:
            headers["x-goog-api-key"] = key
    else:
        if key:
            headers["Authorization"] = f"Bearer {key}"
    for header, env_name in (provider.get("default_headers_env") or {}).items():
        value = os.environ.get(str(env_name), "")
        if value:
            headers[str(header)] = value
    return headers


def http_json(url: str, headers: dict[str, str], payload: dict[str, Any] | None, timeout: float, method: str = "POST") -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1200]
        for value in headers.values():
            if value and len(value) >= 8:
                body = body.replace(value, "[REDACTED]")
                if value.lower().startswith("bearer "):
                    body = body.replace(value[7:], "[REDACTED]")
        raise RuntimeError(f"provider HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"provider connection error: {exc.reason}") from exc


def extract_text(protocol: str, response: dict[str, Any]) -> str:
    if protocol == "anthropic-messages":
        return "".join(str(x.get("text", "")) for x in response.get("content", []) if isinstance(x, dict) and x.get("type") == "text")
    if protocol == "google-generate-content":
        candidates = response.get("candidates", [])
        if not candidates:
            return ""
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        return "".join(str(x.get("text", "")) for x in parts if isinstance(x, dict))
    choices = response.get("choices", [])
    if not choices:
        return ""
    return str((choices[0].get("message") or {}).get("content", ""))


def usage_from_response(protocol: str, response: dict[str, Any]) -> Any:
    if protocol == "anthropic-messages":
        return response.get("usage")
    if protocol == "google-generate-content":
        return response.get("usageMetadata")
    return response.get("usage")


def call_provider(provider: dict[str, Any], model: str, prompt: str, system: str, max_tokens: int, temperature: float, timeout: float) -> dict[str, Any]:
    key, key_source = resolve_secret(list(provider.get("credential_env", [])), bool(provider.get("credential_optional")))
    protocol = str(provider.get("protocol"))
    base = str(provider.get("base_url", "")).rstrip("/")
    if not base:
        raise ValueError("provider base_url is empty")
    headers = default_headers(provider, key)
    if protocol == "anthropic-messages":
        url = base + "/v1/messages"
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
    elif protocol == "google-generate-content":
        quoted_model = urllib.parse.quote(model, safe="-._/")
        url = f"{base}/models/{quoted_model}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
    elif protocol == "openai-chat":
        url = base + "/chat/completions"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    else:
        raise ValueError(f"unsupported provider protocol: {protocol}")
    started = time.monotonic()
    response = http_json(url, headers, payload, timeout)
    elapsed = time.monotonic() - started
    text = extract_text(protocol, response)
    return {
        "protocol": protocol,
        "latency_seconds": round(elapsed, 6),
        "output_text": text,
        "usage": usage_from_response(protocol, response),
        "response_id": response.get("id") or response.get("responseId"),
        "credential_source": key_source,
    }


def probe(root: Path, plan_ref: str, timeout: float = 60.0, enroll_after: bool = False) -> dict[str, Any]:
    plan_file, plan = load_plan(root, plan_ref)
    provider = dict(plan["provider"])
    model = dict(plan["model"])
    prompt = "Reply with exactly ROPS_OK and nothing else."
    result: dict[str, Any] = {
        "schema_version": 1,
        "probe_id": f"probe-{dt.datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}",
        "created_at": iso(),
        "plan_id": plan["plan_id"],
        "plan_sha256": plan["plan_sha256"],
        "provider_id": provider["id"],
        "model_id": model["id"],
        "model": model["model"],
        "prompt_sha256": sha_text(prompt),
        "success": False,
        "secret_value_logged": False,
    }
    try:
        response = call_provider(provider, model["model"], prompt, "Follow output constraints exactly.", 32, 0.0, timeout)
        output = response.pop("output_text", "")
        result.update(response)
        result["output_sha256"] = sha_text(output)
        result["output_preview"] = output[:120]
        result["success"] = output.strip() == "ROPS_OK"
        result["connectivity_ok"] = True
        if not result["success"]:
            result["warning"] = "provider responded, but exact-format probe failed"
    except Exception as exc:
        result["connectivity_ok"] = False
        result["error"] = str(exc)
    probe_file = plan_file.with_name(plan_file.stem + ".probe.json")
    atomic_json(probe_file, result)
    plan["status"] = "probe-passed" if result["success"] else "probe-failed"
    plan["latest_probe"] = str(probe_file)
    plan["updated_at"] = iso()
    plan["plan_sha256"] = canonical_sha({k: v for k, v in plan.items() if k != "plan_sha256"})
    atomic_json(plan_file, plan)
    response: dict[str, Any] = {"probe": result, "path": str(probe_file), "enrolled": False}
    if enroll_after:
        if not result["success"]:
            raise ValueError("cannot enroll: probe did not pass")
        response["enrollment"] = enroll(root, str(plan_file), str(probe_file))
        response["enrolled"] = True
    return response


def upsert(items: list[dict[str, Any]], key: str, value: dict[str, Any]) -> list[dict[str, Any]]:
    out = [item for item in items if item.get(key) != value.get(key)]
    out.append(value)
    out.sort(key=lambda x: str(x.get(key, "")))
    return out


def attach_model_to_agents(root: Path, model_id: str, agent_names: list[str]) -> dict[str, Any]:
    path = agent_dir(root) / "agents.json"
    data = load_json(path, {"schema_version": 1, "agents": []})
    agents = list(data.get("agents", []))
    known = {str(item.get("name")) for item in agents}
    missing = sorted(set(agent_names) - known)
    if missing:
        raise ValueError("unknown candidate agent(s): " + ", ".join(missing))
    changed: list[str] = []
    for item in agents:
        if item.get("name") not in agent_names:
            continue
        candidates = list(item.get("candidate_models", []))
        if model_id not in candidates:
            candidates.append(model_id)
            item["candidate_models"] = candidates
            changed.append(str(item.get("name")))
    atomic_json(path, data)
    return {"path": str(path), "updated_agents": changed}


def find_agent(root: Path, agent_name: str) -> dict[str, Any]:
    agents = load_json(agent_dir(root) / "agents.json", {"agents": []}).get("agents", [])
    agent = next((item for item in agents if item.get("name") == agent_name), None)
    if not agent:
        raise ValueError(f"unknown agent: {agent_name}")
    return agent


def agent_instructions(root: Path, agent_name: str | None, model_id: str) -> tuple[str, dict[str, Any] | None]:
    if not agent_name:
        return "", None
    agent = find_agent(root, agent_name)
    candidates = list(agent.get("candidate_models", []))
    if candidates and model_id not in candidates:
        raise ValueError(f"model {model_id} is not an approved candidate for agent {agent_name}")
    return str(agent.get("instructions", "")).strip(), agent


def enroll(root: Path, plan_ref: str, probe_ref: str | None = None) -> dict[str, Any]:
    plan_file, plan = load_plan(root, plan_ref)
    probe_file = Path(probe_ref).resolve() if probe_ref else plan_file.with_name(plan_file.stem + ".probe.json")
    probe_data = load_json(probe_file, {})
    if not probe_data.get("success"):
        raise ValueError("successful probe record required before enrollment")
    if probe_data.get("plan_id") != plan.get("plan_id"):
        raise ValueError("probe does not belong to onboarding plan")
    provider_plan = dict(plan["provider"])
    model_plan = dict(plan["model"])
    directory = agent_dir(root)
    providers_path = directory / "providers.json"
    models_path = directory / "models.json"
    providers_data = load_json(providers_path, {"schema_version": 1, "providers": []})
    models_data = load_json(models_path, {"schema_version": 1, "models": []})
    provider_entry = {
        "id": provider_plan["id"],
        "display_name": provider_plan.get("display_name"),
        "protocol": provider_plan["protocol"],
        "base_url": provider_plan["base_url"],
        "credential_env": provider_plan.get("credential_env", []),
        "credential_optional": provider_plan.get("credential_optional", False),
        "api_version": provider_plan.get("api_version"),
        "model_list_path": provider_plan.get("model_list_path"),
        "default_headers_env": provider_plan.get("default_headers_env", {}),
        "trust_zone": provider_plan.get("trust_zone", "external-unreviewed"),
        "docs": provider_plan.get("docs", []),
        "approved_at": iso(),
    }
    model_entry = {
        "id": model_plan["id"],
        "provider": RISK_PROVIDER.get(provider_plan["protocol"], provider_plan["protocol"]),
        "provider_id": provider_plan["id"],
        "model": model_plan["model"],
        "enabled": bool(model_plan.get("enabled_after_probe", True)),
        "trust_zone": provider_plan.get("trust_zone", "external-unreviewed"),
        "risk_ceiling": model_plan.get("risk_ceiling", "low"),
        "capabilities": model_plan.get("capabilities", ["text"]),
        "task_affinity": model_plan.get("task_affinity", {}),
        "cost_hint": model_plan.get("cost_hint", 0.5),
        "latency_hint": model_plan.get("latency_hint", 0.5),
        "enrolled_at": iso(),
        "probe_id": probe_data.get("probe_id"),
    }
    providers_data["providers"] = upsert(list(providers_data.get("providers", [])), "id", provider_entry)
    models_data["models"] = upsert(list(models_data.get("models", [])), "id", model_entry)
    atomic_json(providers_path, providers_data)
    atomic_json(models_path, models_data)
    plan["status"] = "enrolled"
    plan["enrolled_at"] = iso()
    plan["plan_sha256"] = canonical_sha({k: v for k, v in plan.items() if k != "plan_sha256"})
    atomic_json(plan_file, plan)
    rebuild_dossier(root, model_entry["id"])
    agent_attachment = attach_model_to_agents(root, model_entry["id"], list(model_plan.get("candidate_agents", []))) if model_plan.get("candidate_agents") else {"updated_agents": []}
    return {
        "schema_version": 1,
        "provider": provider_entry,
        "model": model_entry,
        "agent_attachment": agent_attachment,
        "providers_path": str(providers_path),
        "models_path": str(models_path),
        "secret_stored_in_repository": False,
    }


def configured(root: Path) -> dict[str, Any]:
    directory = agent_dir(root)
    providers = load_json(directory / "providers.json", {"providers": []}).get("providers", [])
    models = load_json(directory / "models.json", {"models": []}).get("models", [])
    status_by_provider: dict[str, Any] = {}
    for provider in providers:
        names = list(provider.get("credential_env", []))
        present = False
        source = None
        try:
            _, source = resolve_secret(names, bool(provider.get("credential_optional")))
            present = source is not None or bool(provider.get("credential_optional"))
        except Exception:
            pass
        status_by_provider[str(provider.get("id"))] = {"credential_ready": present, "credential_source": source}
    return {
        "schema_version": 1,
        "providers": [{**item, **status_by_provider.get(str(item.get("id")), {})} for item in providers],
        "models": models,
        "secret_values_exposed": False,
    }


def find_model(root: Path, model_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = agent_dir(root)
    models = load_json(directory / "models.json", {"models": []}).get("models", [])
    model = next((item for item in models if item.get("id") == model_id), None)
    if not model:
        raise ValueError(f"unknown model id: {model_id}")
    providers = load_json(directory / "providers.json", {"providers": []}).get("providers", [])
    provider = next((item for item in providers if item.get("id") == model.get("provider_id")), None)
    if not provider:
        # Backward-compatible OpenAI-compatible registry entries.
        provider = {
            "id": model.get("provider_id") or model.get("provider"),
            "protocol": "openai-chat",
            "base_url": model.get("base_url"),
            "credential_env": [model.get("credential_env")] if model.get("credential_env") else [],
            "credential_optional": not bool(model.get("credential_env")),
            "trust_zone": model.get("trust_zone"),
        }
    return model, provider


def dossier_path(root: Path, model_id: str) -> Path:
    return agent_dir(root) / "model-profiles" / f"{slug(model_id)}.json"


def read_events(root: Path) -> list[dict[str, Any]]:
    path = agent_dir(root) / "task-history.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def rebuild_dossier(root: Path, model_id: str) -> dict[str, Any]:
    path = dossier_path(root, model_id)
    previous = load_json(path, {})
    events = [event for event in read_events(root) if event.get("model_id") == model_id]
    buckets: dict[str, dict[str, Any]] = {}
    failures: dict[str, int] = {}
    total_correction = total_disagreement = total_quality = 0.0
    accepted_total = 0
    for event in events:
        task = event.get("task") or {}
        task_type = str(task.get("type", "unknown"))
        bucket = buckets.setdefault(task_type, {"observations": 0, "accepted": 0, "quality": 0.0, "correction": 0.0, "disagreement": 0.0})
        bucket["observations"] += 1
        accepted = bool(event.get("accepted", False))
        bucket["accepted"] += int(accepted)
        accepted_total += int(accepted)
        quality = float(event.get("quality", 1.0 if accepted else 0.0) or 0.0)
        correction = float(event.get("human_correction", 0.0) or 0.0)
        disagreement = float(event.get("verifier_disagreement", 0.0) or 0.0)
        bucket["quality"] += quality
        bucket["correction"] += correction
        bucket["disagreement"] += disagreement
        total_quality += quality
        total_correction += correction
        total_disagreement += disagreement
        for failure in event.get("failure_modes", []) or []:
            failures[str(failure)] = failures.get(str(failure), 0) + 1
        if not accepted and event.get("disposition"):
            key = "disposition:" + str(event.get("disposition"))
            failures[key] = failures.get(key, 0) + 1
    strengths: list[dict[str, Any]] = []
    weaknesses: list[dict[str, Any]] = []
    for task_type, bucket in sorted(buckets.items()):
        n = bucket["observations"]
        success = bucket["accepted"] / n
        quality = bucket["quality"] / n
        correction = bucket["correction"] / n
        disagreement = bucket["disagreement"] / n
        summary = {
            "task_type": task_type,
            "observations": n,
            "success_rate": round(success, 4),
            "mean_quality": round(quality, 4),
            "mean_human_correction": round(correction, 4),
            "mean_verifier_disagreement": round(disagreement, 4),
        }
        if n >= 2 and success >= 0.75 and quality >= 0.75 and correction <= 0.15:
            strengths.append(summary)
        if n >= 2 and (success < 0.65 or quality < 0.7 or correction > 0.2 or disagreement > 0.25):
            weaknesses.append(summary)
    prompt_lines: list[str] = []
    if weaknesses or failures:
        prompt_lines.append("Model-specific operating notes derived from independently evaluated history:")
    for item in weaknesses[:5]:
        prompt_lines.append(
            f"- For {item['task_type']} tasks, use a completeness checklist, verify edge cases, and return explicit uncertainty; observed success={item['success_rate']}, correction={item['mean_human_correction']}."
        )
    for name, count in sorted(failures.items(), key=lambda x: (-x[1], x[0]))[:5]:
        prompt_lines.append(f"- Guard against recurring failure pattern `{name}` observed {count} time(s); run the assigned acceptance checks before handoff.")
    proposed = "\n".join(prompt_lines)
    active = str(((previous.get("prompt_overlay") or {}).get("active")) or "")
    active_revision = int(((previous.get("prompt_overlay") or {}).get("active_revision")) or 0)
    manual_notes = list(previous.get("manual_notes", []))
    count = len(events)
    model_metadata: dict[str, Any] = {}
    try:
        model_entry, provider_entry = find_model(root, model_id)
        model_metadata = {
            "provider_id": model_entry.get("provider_id"),
            "provider_protocol": provider_entry.get("protocol"),
            "model": model_entry.get("model"),
            "trust_zone": model_entry.get("trust_zone"),
            "risk_ceiling": model_entry.get("risk_ceiling"),
            "capabilities": list(model_entry.get("capabilities", [])),
        }
    except ValueError:
        # Historical events may outlive a removed registry entry; preserve the dossier.
        model_metadata = {}
    dossier = {
        "schema_version": 1,
        "generated_at": iso(),
        "model_id": model_id,
        **model_metadata,
        "observations": count,
        "accepted": accepted_total,
        "success_rate": round(accepted_total / count, 4) if count else None,
        "mean_quality": round(total_quality / count, 4) if count else None,
        "mean_human_correction": round(total_correction / count, 4) if count else None,
        "mean_verifier_disagreement": round(total_disagreement / count, 4) if count else None,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "failure_patterns": [{"name": key, "count": value} for key, value in sorted(failures.items(), key=lambda x: (-x[1], x[0]))],
        "manual_notes": manual_notes,
        "prompt_overlay": {
            "active": active,
            "active_revision": active_revision,
            "proposed": proposed if proposed != active else "",
            "proposal_basis": "verified task-history events only",
            "auto_activated": False,
        },
    }
    atomic_json(path, dossier)
    return dossier


def rebuild_all_dossiers(root: Path) -> dict[str, Any]:
    model_ids = [item.get("id") for item in load_json(agent_dir(root) / "models.json", {"models": []}).get("models", []) if item.get("id")]
    return {"schema_version": 1, "profiles": [rebuild_dossier(root, str(model_id)) for model_id in model_ids]}


def approve_prompt(root: Path, model_id: str) -> dict[str, Any]:
    dossier = rebuild_dossier(root, model_id)
    overlay = dossier["prompt_overlay"]
    proposed = str(overlay.get("proposed", "")).strip()
    proposed_notes = [
        item for item in dossier.get("manual_notes", [])
        if item.get("kind") == "prompt" and item.get("status") == "proposed" and item.get("text")
    ]
    if not proposed and not proposed_notes:
        raise ValueError("no proposed prompt overlay or prompt note to approve")
    # Automatic overlay text and human-authored prompt notes are stored separately so
    # prompt composition cannot inject an approved note twice.
    if proposed:
        overlay["active"] = proposed
        overlay["proposed"] = ""
    for item in proposed_notes:
        item["status"] = "active"
        item["approved_at"] = iso()
    overlay["active_revision"] = int(overlay.get("active_revision", 0)) + 1
    overlay["approved_at"] = iso()
    overlay["approved_by"] = "human-operator"
    atomic_json(dossier_path(root, model_id), dossier)
    return dossier


def add_profile_note(root: Path, model_id: str, kind: str, text: str) -> dict[str, Any]:
    dossier = rebuild_dossier(root, model_id)
    note = {
        "created_at": iso(), "kind": kind, "text": text, "source": "human-operator",
        "status": "proposed" if kind == "prompt" else "active",
    }
    dossier.setdefault("manual_notes", []).append(note)
    atomic_json(dossier_path(root, model_id), dossier)
    return {"model_id": model_id, "note": note, "path": str(dossier_path(root, model_id))}


def prompt_overlay(root: Path, model_id: str) -> str:
    dossier = rebuild_dossier(root, model_id)
    active = str((dossier.get("prompt_overlay") or {}).get("active", "")).strip()
    notes = [
        str(item.get("text")) for item in dossier.get("manual_notes", [])
        if item.get("kind") == "prompt" and item.get("status") == "active" and item.get("text")
    ]
    return "\n".join([part for part in [active, *notes] if part])


def assert_dispatch_allowed(root: Path, model: dict[str, Any], privacy: str, risk: str) -> None:
    risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if privacy not in {"public", "internal", "confidential", "restricted"}:
        raise ValueError(f"unsupported privacy classification: {privacy}")
    if risk not in risk_order:
        raise ValueError(f"unsupported risk level: {risk}")
    ceiling = str(model.get("risk_ceiling", "low"))
    if risk_order[risk] > risk_order.get(ceiling, -1):
        raise ValueError(f"task risk {risk} exceeds model ceiling {ceiling}")
    policy = load_json(agent_dir(root) / "routing-policy.json", {})
    allowed = list((policy.get("privacy_provider_allowlist") or {}).get(privacy, []))
    provider = str(model.get("provider", ""))
    trust = str(model.get("trust_zone", ""))
    local_alias = provider == "openai-compatible" and trust.startswith("local") and "local-openai-compatible" in allowed
    if "*" not in allowed and provider not in allowed and not local_alias:
        raise ValueError(f"provider {provider} is not approved for privacy={privacy}")


def dispatch(
    root: Path,
    model_id: str,
    prompt_file: Path,
    output: Path,
    system_file: Path | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    timeout: float = 120.0,
    dry_run: bool = False,
    agent_name: str | None = None,
    privacy: str = "public",
    risk: str = "low",
) -> dict[str, Any]:
    model, provider = find_model(root, model_id)
    if not model.get("enabled", False):
        raise ValueError("model is disabled")
    assert_dispatch_allowed(root, model, privacy, risk)
    prompt = prompt_file.read_text(encoding="utf-8")
    system = system_file.read_text(encoding="utf-8") if system_file else ""
    overlay = prompt_overlay(root, model_id)
    base_agent_instructions, agent = agent_instructions(root, agent_name, model_id)
    composed_system = "\n\n".join(
        part for part in [base_agent_instructions, overlay.strip(), system.strip()] if part
    )
    metadata: dict[str, Any] = {
        "schema_version": 2,
        "created_at": iso(),
        "model_id": model_id,
        "provider_id": provider.get("id"),
        "provider_protocol": provider.get("protocol"),
        "model": model.get("model"),
        "prompt_sha256": sha_text(prompt),
        "prompt_bytes": len(prompt.encode("utf-8")),
        "system_sha256": sha_text(composed_system) if composed_system else None,
        "agent": agent_name,
        "privacy": privacy,
        "risk": risk,
        "agent_revision": f"{agent_name}@registry" if agent_name else None,
        "agent_instructions_applied": bool(base_agent_instructions),
        "profile_overlay_applied": bool(overlay),
        "profile_overlay_revision": int((load_json(dossier_path(root, model_id), {}).get("prompt_overlay") or {}).get("active_revision", 0)),
        "dry_run": dry_run,
        "secret_value_logged": False,
    }
    if dry_run:
        result = {**metadata, "request": {"max_tokens": max_tokens, "temperature": temperature}}
    else:
        response = call_provider(provider, str(model.get("model")), prompt, composed_system, max_tokens, temperature, timeout)
        output_text = response.pop("output_text", "")
        result = {
            **metadata,
            **response,
            "output_text": output_text,
            "output_sha256": sha_text(output_text),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, result)
    return {"result": result, "path": str(output)}


def route_and_dispatch(
    root: Path,
    task_file: Path,
    prompt_file: Path,
    output_dir: Path,
    agent_name: str | None = None,
    system_file: Path | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    timeout: float = 120.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    import subprocess
    import sys

    task = load_json(task_file, {})
    if not isinstance(task, dict) or not task:
        raise ValueError("task file must contain a non-empty JSON object")
    registry = ROOT / "skills" / "adaptive-agent-orchestration" / "scripts" / "agent_registry.py"
    args = [
        sys.executable, str(registry), "--root", str(root), "recommend",
        "--task-json", json.dumps(task, ensure_ascii=False),
    ]
    if agent_name:
        args += ["--agent", agent_name]
    completed = subprocess.run(args, text=True, capture_output=True)
    if completed.returncode:
        raise RuntimeError(f"routing failed: {completed.stderr or completed.stdout}")
    decision = json.loads(completed.stdout)
    model_id = str((decision.get("primary") or {}).get("model_id", ""))
    if not model_id:
        raise RuntimeError("routing decision did not select a model")
    dispatch_id = f"dispatch-{dt.datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}"
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / f"{dispatch_id}.result.json"
    decision_path = output_dir / f"{dispatch_id}.routing.json"
    atomic_json(decision_path, decision)
    result = dispatch(
        root, model_id, prompt_file, result_path, system_file, max_tokens,
        temperature, timeout, dry_run, agent_name,
        str(task.get("privacy", "public")), str(task.get("risk", "low")),
    )
    handoff = {
        "schema_version": 1,
        "dispatch_id": dispatch_id,
        "created_at": iso(),
        "task": task,
        "agent": agent_name,
        "model_id": model_id,
        "routing_decision": str(decision_path),
        "result": str(result_path),
        "requires_evaluation": True,
        "profile_updated": False,
        "next": "Run deterministic acceptance checks and an independent verifier when required, then record event_for_registry.",
    }
    handoff_path = output_dir / f"{dispatch_id}.handoff.json"
    atomic_json(handoff_path, handoff)
    return {"handoff": handoff, "handoff_path": str(handoff_path), "routing": decision, "dispatch": result}


def smoke(root: Path, model_id: str, timeout: float = 60.0) -> dict[str, Any]:
    model, provider = find_model(root, model_id)
    suite = load_json(ROOT / "config" / "model-smoke-suite.json", {"tests": []})
    outcomes: list[dict[str, Any]] = []
    for test in suite.get("tests", []):
        started = time.monotonic()
        try:
            response = call_provider(provider, str(model.get("model")), str(test.get("prompt", "")), str(test.get("system", "")), int(test.get("max_tokens", 64)), 0.0, timeout)
            text = str(response.pop("output_text", ""))
            expectation = test.get("expect", {})
            passed = False
            if expectation.get("type") == "exact":
                passed = text.strip() == str(expectation.get("value"))
            elif expectation.get("type") == "json-path-equals":
                try:
                    parsed = json.loads(text)
                    passed = parsed.get(str(expectation.get("path"))) == expectation.get("value")
                except Exception:
                    passed = False
            outcomes.append({
                "id": test.get("id"),
                "passed": passed,
                "latency_seconds": round(time.monotonic() - started, 6),
                "output_sha256": sha_text(text),
                "output_preview": text[:120],
                "usage": response.get("usage"),
            })
        except Exception as exc:
            outcomes.append({"id": test.get("id"), "passed": False, "error": str(exc), "latency_seconds": round(time.monotonic() - started, 6)})
    report = {
        "schema_version": 1,
        "created_at": iso(),
        "model_id": model_id,
        "passed": bool(outcomes) and all(item.get("passed") for item in outcomes),
        "outcomes": outcomes,
        "profile_updated": False,
        "note": "Onboarding smoke results do not update task-performance profiles; only independently evaluated real dispatches do.",
    }
    path = agent_dir(root) / "smoke" / f"{slug(model_id)}-{dt.datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    atomic_json(path, report)
    return {"report": report, "path": str(path)}


def list_remote_models(root: Path, provider_id: str, timeout: float = 30.0) -> dict[str, Any]:
    providers = load_json(agent_dir(root) / "providers.json", {"providers": []}).get("providers", [])
    provider = next((item for item in providers if item.get("id") == provider_id), None)
    if not provider:
        # Permit recipe inspection before enrollment.
        provider = recipe(provider_id)
    path = provider.get("model_list_path")
    if not path:
        raise ValueError("provider has no model-list endpoint configured")
    key, source = resolve_secret(list(provider.get("credential_env", [])), bool(provider.get("credential_optional")))
    url = str(provider.get("base_url", "")).rstrip("/") + str(path)
    response = http_json(url, default_headers(provider, key), None, timeout, method="GET")
    if provider.get("protocol") == "google-generate-content":
        models = [item.get("name") for item in response.get("models", []) if item.get("name")]
    else:
        models = [item.get("id") for item in response.get("data", []) if isinstance(item, dict) and item.get("id")]
    return {
        "schema_version": 1,
        "provider_id": provider_id,
        "credential_source": source,
        "models": models,
        "count": len(models),
        "raw_response_logged": False,
    }
