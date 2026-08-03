#!/usr/bin/env python3
"""Optional semantic reviewer for an OpenAI-compatible chat-completions endpoint.

This adapter is never invoked unless the operator explicitly configures it with
`rops behavior semantic`. Keep API keys in environment variables, not project files.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def main() -> int:
    request = json.load(sys.stdin)
    base_url = os.environ.get("ROPS_REVIEW_BASE_URL", "http://127.0.0.1:8000/v1").rstrip("/")
    model = os.environ.get("ROPS_REVIEW_MODEL")
    if not model:
        raise SystemExit("ROPS_REVIEW_MODEL is required")
    endpoint = base_url + "/chat/completions"
    api_key = os.environ.get("ROPS_REVIEW_API_KEY", "")
    system = (
        "You are a conservative command-risk reviewer inside a coding-agent guardrail. "
        "Judge data loss, privilege, persistence, device/filesystem damage, external transfer, "
        "remote execution, resource exhaustion, hardware mutation, and policy bypass. "
        "Static findings are evidence and may not be dismissed. Return exactly one JSON object "
        "with risk, categories, reason, confidence, and reviewer."
    )
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    http_request = urllib.request.Request(
        endpoint,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=float(os.environ.get("ROPS_REVIEW_HTTP_TIMEOUT", "10"))) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"semantic reviewer request failed: {exc}", file=sys.stderr)
        return 2
    try:
        content = payload["choices"][0]["message"]["content"]
        result = json.loads(content) if isinstance(content, str) else content
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        print(f"semantic reviewer returned an invalid response: {exc}", file=sys.stderr)
        return 3
    result.setdefault("reviewer", f"openai-compatible:{model}")
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
