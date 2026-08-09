from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .common import load_json, now
from .intelligence.drift import record_endpoint_observation, record_identity_observation
from .intelligence.projections import rebuild_projections
from .intelligence.store import IntelligenceStore
from .layout import layout

SECRET_FILE = Path.home() / ".config" / "rops" / "secrets.env"
CODEX_CONFIG_FILE = Path.home() / ".codex" / "config.toml"
CODEX_CONFIG_BEGIN = "# >>> ResearchOps managed model providers >>>"
CODEX_CONFIG_END = "# <<< ResearchOps managed model providers <<<"

CODEX_PROVIDER_SPECS: tuple[dict[str, Any], ...] = (
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "env_key": "DEEPSEEK_API_KEY",
        "model": "deepseek-v4-flash",
        "efforts": ["none", "high", "max"],
    },
    {
        "id": "mimo_paygo",
        "name": "Xiaomi MiMo pay-as-you-go",
        "base_url": "https://api.xiaomimimo.com/v1",
        "env_key": "MIMO_API_KEY",
        "model": "mimo-v2.5-pro",
        "efforts": ["none", "high"],
    },
    {
        "id": "mimo_token_plan",
        "name": "Xiaomi MiMo Token Plan",
        "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
        "env_key": "MIMO_API_KEY",
        "model": "mimo-v2.5-pro",
        "efforts": ["none", "high"],
    },
    {
        "id": "minimax_cn",
        "name": "MiniMax China",
        "base_url": "https://api.minimaxi.com/v1",
        "env_key": "MINIMAX_API_KEY",
        "model": "MiniMax-M3",
        "efforts": ["none", "high"],
    },
    {
        "id": "minimax_global",
        "name": "MiniMax Global",
        "base_url": "https://api.minimax.io/v1",
        "env_key": "MINIMAX_API_KEY",
        "model": "MiniMax-M3",
        "efforts": ["none", "high"],
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
        raise RuntimeError(f"HTTP {exc.code}: {body[:800]}") from exc
    latency = time.monotonic() - started
    data = json.loads(body)
    if not isinstance(data, dict):
        raise RuntimeError("provider returned a non-object response")
    return data, latency, headers


def probe(store: IntelligenceStore, arm_id: str, *, timeout: float = 60.0) -> dict[str, Any]:
    model = _find(store.layout.root, arm_id)
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
        endpoint_obs = record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=False, latency_seconds=timeout, error_class=type(exc).__name__, metadata={"kind": "probe"})
        return {"status": "failed", "arm_id": arm_id, "error": str(exc), "endpoint_observation": endpoint_obs, "competence_updated": False}


def dispatch(store: IntelligenceStore, arm_id: str, request_data: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    model = _find(store.layout.root, arm_id)
    if not _direct_gateway_allowed(model):
        raise ValueError("this execution arm is restricted to an approved coding client; direct gateway dispatch is disabled")
    endpoint = str(model.get("endpoint_id") or model.get("base_url") or arm_id)
    payload = _prepare_payload(model, request_data)
    try:
        response, latency, headers = _request(model, payload, timeout=timeout)
        record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=True, latency_seconds=latency, metadata={"kind": "dispatch", "usage": response.get("usage")})
        return {"dispatch_id": "dispatch-" + uuid.uuid4().hex[:16], "arm_id": arm_id, "model": model.get("model"), "reasoning_effort": model.get("reasoning_effort"), "api_protocol": _protocol(model), "latency_seconds": round(latency, 6), "response": response, "returned_model": response.get("model"), "evaluation_pending": True}
    except Exception as exc:
        record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=False, latency_seconds=timeout, error_class=type(exc).__name__, metadata={"kind": "dispatch"})
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
        fd, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(updated)
            if target.exists():
                os.chmod(temporary, target.stat().st_mode & 0o777)
            else:
                os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        installed = True
    providers = [
        {
            "id": spec["id"],
            "model": spec["model"],
            "reasoning_efforts": spec["efforts"],
            "base_url": spec["base_url"],
            "credential_env": spec["env_key"],
        }
        for spec in CODEX_PROVIDER_SPECS
    ]
    return {
        "path": str(target),
        "installed": installed,
        "default_model_changed": False,
        "providers": providers,
        "glm_codex_native": False,
        "glm_reason": "official GLM API documentation exposes Chat Completions, while Codex custom providers require Responses",
        "secret_values_written": False,
        "launch_examples": [
            "codex -c model_provider=deepseek -m deepseek-v4-flash -c model_supports_reasoning_summaries=true -c model_reasoning_summary=none -c model_reasoning_effort=high",
            "codex -c model_provider=mimo_paygo -m mimo-v2.5-pro -c model_supports_reasoning_summaries=true -c model_reasoning_summary=none -c model_reasoning_effort=high",
            "codex -c model_provider=minimax_cn -m MiniMax-M3 -c model_supports_reasoning_summaries=true -c model_reasoning_summary=none -c model_reasoning_effort=high",
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
    doctor = sub.add_parser("doctor"); doctor.add_argument("--probe", action="store_true")
    probe_parser = sub.add_parser("probe"); probe_parser.add_argument("--arm-id", required=True); probe_parser.add_argument("--timeout", type=float, default=60)
    dispatch_parser = sub.add_parser("dispatch"); dispatch_parser.add_argument("--arm-id", required=True); dispatch_parser.add_argument("--request-json"); dispatch_parser.add_argument("--request-file"); dispatch_parser.add_argument("--timeout", type=float, default=120)
    dossier_parser = sub.add_parser("dossier"); dossier_parser.add_argument("--arm-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "codex-config":
        _emit(codex_config(install=args.install, path=Path(args.path) if args.path else None))
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
    elif args.command == "dossier":
        _emit(dossier(root, args.arm_id))
    return 0
