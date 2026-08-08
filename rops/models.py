from __future__ import annotations

import argparse
import json
import os
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


def _emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _parse_env(path: Path = SECRET_FILE) -> dict[str, str]:
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
    if not SECRET_FILE.exists():
        lines = ["# ResearchOps secrets. Never commit this file."] + [f"{name}=" for name in names]
        SECRET_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            SECRET_FILE.chmod(0o600)
        except OSError:
            pass
    return {"path": str(SECRET_FILE), "variables": names, "values_exposed": False}


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


def _request(model: dict[str, Any], payload: dict[str, Any], *, timeout: float = 120.0) -> tuple[dict[str, Any], float, dict[str, str]]:
    base = str(model.get("base_url") or model.get("endpoint_id") or "").rstrip("/")
    if not base:
        raise ValueError("execution arm has no OpenAI-compatible base_url")
    path = str(model.get("chat_path") or "/chat/completions")
    if not path.startswith("/"):
        path = "/" + path
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
    endpoint = str(model.get("endpoint_id") or model.get("base_url") or arm_id)
    payload = {
        "model": model.get("model"),
        "messages": [{"role": "user", "content": "Return exactly the JSON object {\"status\":\"ok\"}."}],
        "temperature": 0,
        "max_tokens": 32,
    }
    try:
        response, latency, headers = _request(model, payload, timeout=timeout)
        declared = {"requested_model": model.get("model"), "returned_model": response.get("model"), "api_version": headers.get("openai-version")}
        fingerprint = {"system_fingerprint": response.get("system_fingerprint"), "response_shape": sorted(response), "finish_reason": (((response.get("choices") or [{}])[0] or {}).get("finish_reason"))}
        endpoint_obs = record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=True, latency_seconds=latency, metadata={"kind": "probe", "usage": response.get("usage")})
        identity_obs = record_identity_observation(store, arm_id=arm_id, endpoint_id=endpoint, declared_identity=declared, fingerprint=fingerprint)
        return {"status": "healthy", "arm_id": arm_id, "latency_seconds": round(latency, 6), "endpoint_observation": endpoint_obs, "identity_observation": identity_obs, "competence_updated": False}
    except Exception as exc:
        endpoint_obs = record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=False, latency_seconds=timeout, error_class=type(exc).__name__, metadata={"kind": "probe"})
        return {"status": "failed", "arm_id": arm_id, "error": str(exc), "endpoint_observation": endpoint_obs, "competence_updated": False}


def dispatch(store: IntelligenceStore, arm_id: str, request_data: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any]:
    model = _find(store.layout.root, arm_id)
    endpoint = str(model.get("endpoint_id") or model.get("base_url") or arm_id)
    payload = dict(request_data)
    payload.setdefault("model", model.get("model"))
    try:
        response, latency, headers = _request(model, payload, timeout=timeout)
        record_endpoint_observation(store, endpoint_id=endpoint, arm_id=arm_id, success=True, latency_seconds=latency, metadata={"kind": "dispatch", "usage": response.get("usage")})
        return {"dispatch_id": "dispatch-" + uuid.uuid4().hex[:16], "arm_id": arm_id, "latency_seconds": round(latency, 6), "response": response, "returned_model": response.get("model"), "evaluation_pending": True}
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rops models")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sync")
    sub.add_parser("list")
    sub.add_parser("secret-template")
    sub.add_parser("secret-status")
    doctor = sub.add_parser("doctor"); doctor.add_argument("--probe", action="store_true")
    probe_parser = sub.add_parser("probe"); probe_parser.add_argument("--arm-id", required=True); probe_parser.add_argument("--timeout", type=float, default=60)
    dispatch_parser = sub.add_parser("dispatch"); dispatch_parser.add_argument("--arm-id", required=True); dispatch_parser.add_argument("--request-json"); dispatch_parser.add_argument("--request-file"); dispatch_parser.add_argument("--timeout", type=float, default=120)
    dossier_parser = sub.add_parser("dossier"); dossier_parser.add_argument("--arm-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
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
