from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CAPTURED: dict[str, Any] = {}


class MockGlmHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        size = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(size))
        CAPTURED.update({"path": self.path, "payload": payload})
        message: dict[str, Any] = {"role": "assistant", "content": "BRIDGE_OK"}
        finish_reason = "stop"
        if payload.get("tools"):
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "mock-custom-tool-call",
                        "type": "function",
                        "function": {
                            "name": "apply_patch",
                            "arguments": json.dumps({"content": "*** Begin Patch\n*** End Patch"}),
                        },
                    }
                ],
            }
            finish_reason = "tool_calls"
        response = {
            "id": "mock-glm-chat-completion",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "glm-5.2",
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": finish_reason,
                }
            ],
            "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
        }
        encoded = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        return


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data)
    if payload is not None:
        request.add_header("Content-Type", "application/json")
        request.add_header("Authorization", "Bearer local-integration-master-key")
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read())


def main() -> None:
    litellm = shutil.which("litellm")
    if not litellm:
        raise RuntimeError(
            "litellm is required; run: "
            "uv tool install --force 'litellm[proxy]==1.96.0' --with 'fastapi==0.136.3'"
        )

    mock_server = ThreadingHTTPServer(("127.0.0.1", 0), MockGlmHandler)
    mock_port = int(mock_server.server_address[1])
    proxy_port = free_port()
    thread = threading.Thread(target=mock_server.serve_forever, daemon=True)
    thread.start()
    process: subprocess.Popen[str] | None = None
    logs = ""
    try:
        with tempfile.TemporaryDirectory(prefix="researchops-litellm-bridge-") as temp:
            config_path = Path(temp) / "glm.yaml"
            source = (ROOT / "config/litellm-glm.yaml").read_text(encoding="utf-8")
            source = source.replace("https://api.z.ai/api/paas/v4", f"http://127.0.0.1:{mock_port}/v4")
            config_path.write_text(source, encoding="utf-8")
            env = dict(os.environ)
            env.update(
                {
                    "ZAI_API_KEY": "local-integration-upstream-key",
                    "LITELLM_MASTER_KEY": "local-integration-master-key",
                    "NO_PROXY": "127.0.0.1,localhost",
                    "no_proxy": "127.0.0.1,localhost",
                }
            )
            process = subprocess.Popen(
                [litellm, "--config", str(config_path), "--host", "127.0.0.1", "--port", str(proxy_port)],
                cwd=ROOT,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            deadline = time.monotonic() + 90
            health_error: Exception | None = None
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                try:
                    request_json(f"http://127.0.0.1:{proxy_port}/health/liveliness")
                    health_error = None
                    break
                except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    health_error = exc
                    time.sleep(0.25)
            else:
                health_error = TimeoutError("LiteLLM did not become ready within 90 seconds")
            if health_error is not None or process.poll() is not None:
                process.terminate()
                logs = process.communicate(timeout=10)[0]
                raise RuntimeError(f"LiteLLM startup failed: {health_error or process.returncode}\n{logs[-4000:]}")

            result = request_json(
                f"http://127.0.0.1:{proxy_port}/v1/responses",
                {"model": "glm-5.2-max", "input": "Return BRIDGE_OK", "max_output_tokens": 16},
            )
            upstream = CAPTURED["payload"]
            assert CAPTURED["path"].endswith("/chat/completions")
            assert upstream["model"] == "glm-5.2"
            assert upstream["messages"][-1]["content"] == "Return BRIDGE_OK"
            assert upstream["thinking"] == {"type": "enabled"}
            assert upstream["reasoning_effort"] == "max"
            assert result["object"] == "response"
            assert result["status"] == "completed"
            assert any(
                content.get("text") == "BRIDGE_OK"
                for output in result.get("output", [])
                for content in output.get("content", [])
            )

            CAPTURED.clear()
            tool_result = request_json(
                f"http://127.0.0.1:{proxy_port}/v1/responses",
                {
                    "model": "glm-5.2-max",
                    "input": "Patch one file",
                    "max_output_tokens": 32,
                    "tools": [
                        {
                            "type": "custom",
                            "name": "apply_patch",
                            "description": "Apply a patch",
                            "format": {
                                "type": "grammar",
                                "syntax": "lark",
                                "definition": "start: /[\\s\\S]+/",
                            },
                        }
                    ],
                },
            )
            converted_tool = CAPTURED["payload"]["tools"][0]
            assert converted_tool["type"] == "function"
            assert converted_tool["function"]["name"] == "apply_patch"
            assert converted_tool["function"]["parameters"]["required"] == ["content"]
            custom_call = next(output for output in tool_result["output"] if output["type"] == "custom_tool_call")
            assert custom_call["name"] == "apply_patch"
            assert custom_call["input"] == "*** Begin Patch\n*** End Patch"
            print(
                json.dumps(
                    {
                        "responses_endpoint": True,
                        "chat_completions_upstream": True,
                        "fixed_alias_effort_preserved": "max",
                        "response_transformed_back": True,
                        "codex_custom_tool_round_trip": "apply_patch",
                        "real_credentials_used": False,
                    },
                    indent=2,
                )
            )
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                logs = process.communicate(timeout=10)[0]
            except subprocess.TimeoutExpired:
                process.kill()
                logs = process.communicate(timeout=10)[0]
        mock_server.shutdown()
        mock_server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
