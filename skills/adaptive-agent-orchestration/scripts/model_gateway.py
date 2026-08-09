#!/usr/bin/env python3
"""Bounded OpenAI-compatible text worker for third-party/local models.

This is intentionally not a general autonomous agent. It sends one request,
records metadata without secrets or full prompts, and writes a structured result.
Use a gateway such as LiteLLM for provider routing, budgets, and fallbacks.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as f: return json.load(f)


def iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def find_model(registry: dict[str, Any], model_id: str) -> dict[str, Any]:
    for m in registry.get("models", []):
        if (m.get("arm_id") or m.get("id")) == model_id: return m
    raise SystemExit(f"unknown model id: {model_id}")


def protocol(model: dict[str, Any]) -> str:
    raw = str(model.get("api_protocol") or "chat_completions").strip().lower().replace("-", "_")
    aliases = {"openai_chat_compatible": "chat_completions", "openai_responses": "responses"}
    value = aliases.get(raw, raw)
    if value not in {"chat_completions", "responses"}:
        raise SystemExit(f"unsupported API protocol: {raw}")
    return value


def prepare_payload(model: dict[str, Any], messages: list[dict[str, str]], max_tokens: int, temperature: float) -> dict[str, Any]:
    effort = model.get("api_reasoning_effort", model.get("reasoning_effort"))
    if protocol(model) == "responses":
        payload: dict[str, Any] = {"model": model.get("model"), "input": messages, "max_output_tokens": max_tokens}
        if effort is not None:
            payload["reasoning"] = {"effort": effort}
    else:
        payload = {"model": model.get("model"), "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if effort is not None:
            payload["reasoning_effort"] = effort
        if model.get("thinking_type"):
            payload["thinking"] = {"type": model["thinking_type"]}
    return payload


def output_text(response: dict[str, Any], api_protocol: str) -> tuple[str, str | None]:
    if api_protocol == "responses":
        if response.get("output_text") is not None:
            return str(response.get("output_text") or ""), str(response.get("status") or "") or None
        parts = []
        for item in response.get("output", []):
            if item.get("type") != "message":
                continue
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    parts.append(str(content.get("text") or ""))
        return "".join(parts), str(response.get("status") or "") or None
    choices = response.get("choices", [])
    text = str((choices[0].get("message") or {}).get("content", "")) if choices else ""
    return text, choices[0].get("finish_reason") if choices else None


def request_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:1000]
        raise SystemExit(f"gateway HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        raise SystemExit(f"gateway error: {e.reason}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", type=Path, default=Path(".researchops/governance/models.json"))
    ap.add_argument("--model-id", required=True)
    ap.add_argument("--prompt-file", type=Path, required=True)
    ap.add_argument("--system-file", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    model = find_model(load(args.registry), args.model_id)
    if not model.get("base_url"):
        raise SystemExit("model_gateway only handles entries with an OpenAI-compatible base_url")
    if not model.get("enabled", False): raise SystemExit("model is disabled")
    if not model.get("direct_gateway_allowed", True):
        raise SystemExit("model plan is restricted to an approved coding client; direct gateway dispatch is disabled")
    base = str(model.get("base_url", "")).rstrip("/")
    if not base: raise SystemExit("model entry has no base_url")
    prompt = args.prompt_file.read_text(encoding="utf-8")
    messages: list[dict[str, str]] = []
    if args.system_file: messages.append({"role": "system", "content": args.system_file.read_text(encoding="utf-8")})
    messages.append({"role": "user", "content": prompt})
    api_protocol = protocol(model)
    payload = prepare_payload(model, messages, args.max_tokens, args.temperature)
    metadata = {
        "schema_version": 1,
        "created_at": iso(),
        "model_id": args.model_id,
        "provider": model.get("provider"),
        "model": model.get("model"),
        "reasoning_effort": model.get("reasoning_effort"),
        "api_protocol": api_protocol,
        "base_url_host": base.split("//", 1)[-1].split("/", 1)[0],
        "prompt_sha256": sha(prompt),
        "prompt_bytes": len(prompt.encode("utf-8")),
        "dry_run": args.dry_run,
    }
    if args.dry_run:
        result = {**metadata, "request": {"model": payload["model"], "reasoning": payload.get("reasoning") or payload.get("reasoning_effort"), "message_count": len(messages), "max_tokens": args.max_tokens}}
    else:
        env = str(model.get("credential_env", ""))
        key = os.environ.get(env, "") if env else ""
        headers = {"Content-Type": "application/json"}
        if key: headers["Authorization"] = f"Bearer {key}"
        path = str(model.get("request_path") or ("/responses" if api_protocol == "responses" else "/chat/completions"))
        if not path.startswith("/"): path = "/" + path
        start = time.monotonic(); response = request_json(base + path, headers, payload, args.timeout); elapsed = time.monotonic() - start
        text, finish_reason = output_text(response, api_protocol)
        result = {
            **metadata,
            "latency_seconds": round(elapsed, 6),
            "response_id": response.get("id"),
            "usage": response.get("usage"),
            "output_text": text,
            "output_sha256": sha(text),
            "finish_reason": finish_reason,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__": main()
