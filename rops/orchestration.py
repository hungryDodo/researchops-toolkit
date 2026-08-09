from __future__ import annotations

import json
import hashlib
import hmac
import http.client
import http.server
import math
import os
import re
import secrets
import signal
import shutil
import subprocess
import tempfile
import threading
import time
import tomllib
import urllib.parse
import uuid
from pathlib import Path
from typing import Any, Callable

from . import models
from .common import atomic_json, now
from .dispatch_evaluation import evaluate
from .intelligence.drift import record_endpoint_observation, record_identity_observation
from .intelligence.events import (
    ARTIFACTS,
    DECOMPOSABILITY,
    DEPENDENCY_STRUCTURE,
    MUTABILITY,
    OPERATION_MAP,
    OPERATIONS,
    ORIENTATIONS,
    PRIVACY,
    REASONING_EFFORTS,
    REASONING_DEMAND,
    RISK,
    TOOL_INTENSITY,
    normalize_task,
    record_event,
)
from .intelligence.patterns import rebuild_patterns
from .intelligence.projections import rebuild_projections
from .intelligence.routing import recommend
from .intelligence.store import IntelligenceStore


SAFE_MUTABILITY = {"read-only", "workspace-write"}
SAFE_BACKENDS = {"auto", "codex", "gateway"}
MAX_CHANGED_FILES = 256
MAX_CHANGED_FILE_BYTES = 16 * 1024 * 1024
MAX_PATCH_BYTES = 64 * 1024 * 1024
VERIFIER_DISPOSITIONS = {"accepted", "reject", "retry-same", "retry-stronger", "route-different"}
SECURITY_TASK_FIELDS = {
    "privacy",
    "mutability",
    "risk",
    "required_capabilities",
    "model_family_allowlist",
    "reasoning_effort",
    "min_reasoning_effort",
    "max_reasoning_effort",
    "operation",
    "shared_mutable_state",
}
SENSITIVE_ENV_NAME = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|secret|password|token|authorization|credential)"
)


class DispatchContractError(ValueError):
    """The Lead supplied a handoff that cannot be executed safely or evaluated."""


class WorkerTimeoutError(RuntimeError):
    pass


class WorkerRateLimitError(RuntimeError):
    pass


class ProviderResponseError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, failure_scope: str = "arm"):
        super().__init__(message)
        self.status = status
        self.failure_scope = failure_scope


class BrokerBudgetError(RuntimeError):
    pass


class WorkerCancelledError(BaseException):
    pass


def _arm_id(item: dict[str, Any]) -> str:
    return str(item.get("arm_id") or item.get("id") or item.get("model_id") or "")


def _response_model_values(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if isinstance(value.get("model"), str) and value["model"].strip():
            found.add(value["model"].strip())
        if "response" in value:
            found.update(_response_model_values(value["response"]))
    return found


def _models(root: Path) -> dict[str, dict[str, Any]]:
    return {_arm_id(item): item for item in models._models(root) if _arm_id(item)}


def _preflight_execution_arms(root: Path, task: dict[str, Any]) -> dict[str, Any]:
    """Fail on tampered enabled arms and exclude external arms not approved for this project."""
    denied = set(map(str, task.get("execution_arm_denylist") or []))
    for arm_id, model in _models(root).items():
        if not model.get("enabled", False):
            continue
        try:
            models.validate_execution_arm_identity(model)
        except ValueError as exc:
            raise DispatchContractError(str(exc)) from exc
        if str(model.get("provider") or "") == "codex-native":
            continue
        try:
            models.validate_external_arm_approval(model, root)
        except ValueError:
            denied.add(arm_id)
    return {**task, "execution_arm_denylist": sorted(denied)}


def _safe_slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-.")
    return cleaned[:96] or "work-unit"


def _relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _private_json(path: Path, value: Any) -> None:
    atomic_json(path, value)
    path.chmod(0o600)


def _private_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)


def _git_environment() -> dict[str, str]:
    allowed = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ"}
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update(
        {
            "HOME": "/nonexistent-researchops-git-home",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return environment


def _git_command(*arguments: str) -> list[str]:
    return [
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "diff.external=",
        *arguments,
    ]


def _git_metadata_fingerprint(root: Path) -> str:
    git_dir = root / ".git"
    digest = hashlib.sha256()
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise DispatchContractError("isolated Git clone has no .git directory")
    for directory, names, files in os.walk(git_dir, topdown=True, followlinks=False):
        names.sort()
        files.sort()
        base = Path(directory)
        for name in [*names, *files]:
            path = base / name
            relative = str(path.relative_to(git_dir)).replace("\\", "/")
            metadata = path.lstat()
            digest.update(relative.encode("utf-8", errors="surrogateescape"))
            digest.update(f"\0{metadata.st_mode:o}\0{metadata.st_size}\0".encode())
            if path.is_symlink():
                digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
            elif path.is_file():
                with path.open("rb") as handle:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(block)
    return digest.hexdigest()


def _git_head(root: Path) -> str:
    return subprocess.run(
        _git_command("rev-parse", "HEAD"),
        cwd=root,
        env=_git_environment(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _validate_tracked_inputs(root: Path, inputs: list[str], revision: str) -> None:
    for relative in inputs:
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise DispatchContractError(f"contract input escapes the project root: {relative}") from exc
        if not path.is_file():
            raise DispatchContractError(f"private-clone contract input is missing or not a file: {relative}")
        tracked = subprocess.run(
            _git_command("ls-files", "--error-unmatch", "--", relative),
            cwd=root,
            env=_git_environment(),
            capture_output=True,
            check=False,
        )
        in_revision = subprocess.run(
            _git_command("cat-file", "-e", f"{revision}:{relative}"),
            cwd=root,
            env=_git_environment(),
            capture_output=True,
            check=False,
        )
        if tracked.returncode or in_revision.returncode:
            raise DispatchContractError(
                f"private-clone contract input must be Git-tracked in frozen revision {revision}: {relative}"
            )


def _safe_write_scope(values: Any) -> list[str]:
    if not isinstance(values, list):
        raise DispatchContractError("contract.write_scope must be an array")
    scopes: list[str] = []
    for value in values:
        text = str(value).strip().replace("\\", "/").rstrip("/")
        path = Path(text)
        if not text or text == "." or path.is_absolute() or ".." in path.parts:
            raise DispatchContractError(f"unsafe write_scope entry: {value!r}")
        if path.parts[0] in {".git", ".researchops"}:
            raise DispatchContractError(f"dispatcher control paths cannot be delegated in write_scope: {value!r}")
        scopes.append(text)
    return sorted(set(scopes))


def _validate_raw_task_fields(raw: dict[str, Any], label: str) -> None:
    choices = {
        "orientation": ORIENTATIONS,
        "operation": OPERATIONS | set(OPERATION_MAP),
        "primary_artifact": ARTIFACTS,
        "artifact": ARTIFACTS,
        "risk": RISK,
        "privacy": PRIVACY,
        "mutability": MUTABILITY,
        "reasoning_demand": REASONING_DEMAND,
        "decomposability": DECOMPOSABILITY,
        "dependency_structure": DEPENDENCY_STRUCTURE,
        "tool_intensity": TOOL_INTENSITY,
    }
    for field, allowed in choices.items():
        if field not in raw:
            continue
        value = str(raw.get(field) or "").strip().lower()
        if value not in allowed:
            raise DispatchContractError(f"{label}.{field} has unsupported value: {raw.get(field)!r}")
    for field in (
        "required_capabilities",
        "uncertain_fields",
        "tags",
        "model_family_allowlist",
        "execution_arm_denylist",
    ):
        if field in raw and (
            not isinstance(raw[field], list) or not all(isinstance(value, str) for value in raw[field])
        ):
            raise DispatchContractError(f"{label}.{field} must be an array of strings")
    for field in ("reasoning_effort", "min_reasoning_effort", "max_reasoning_effort"):
        if field in raw and raw[field] is not None:
            value = str(raw[field]).strip().lower()
            if value not in REASONING_EFFORTS:
                raise DispatchContractError(f"{label}.{field} has unsupported value: {raw[field]!r}")
    if "shared_mutable_state" in raw and not isinstance(raw["shared_mutable_state"], bool):
        raise DispatchContractError(f"{label}.shared_mutable_state must be a JSON boolean")


def validate_contract(task: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(task, dict) or not isinstance(contract, dict):
        raise DispatchContractError("task and contract must be JSON objects")
    _validate_raw_task_fields(task, "task")
    objective = str(contract.get("objective") or task.get("objective") or "").strip()
    task_id = str(contract.get("task_id") or task.get("task_id") or "").strip()
    if not task_id:
        raise DispatchContractError("contract.task_id is required")
    if not objective:
        raise DispatchContractError("contract.objective or task.objective is required")
    tests = contract.get("acceptance_tests")
    if not isinstance(tests, list) or not tests or not all(isinstance(item, dict) for item in tests):
        raise DispatchContractError("contract.acceptance_tests must contain at least one structured check")
    for index, test in enumerate(tests):
        test_type = test.get("type")
        allowed_test_types = {
            "file_exists",
            "file_sha256",
            "regex_present",
            "regex_absent",
            "json_path_equals",
            "command_exit_zero",
        }
        if test_type not in allowed_test_types:
            raise DispatchContractError(f"acceptance_tests[{index}].type is unsupported: {test_type!r}")
        if "required" in test and not isinstance(test["required"], bool):
            raise DispatchContractError(f"acceptance_tests[{index}].required must be a JSON boolean")
        weight = test.get("weight", 1.0)
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise DispatchContractError(f"acceptance_tests[{index}].weight must be numeric")
        if not math.isfinite(float(weight)) or float(weight) < 0.0 or float(weight) > 1.0:
            raise DispatchContractError(f"acceptance_tests[{index}].weight must be finite and between 0 and 1")
        if test_type in {"file_exists", "file_sha256", "regex_present", "regex_absent"} or (
            test_type == "json_path_equals" and test.get("source", "result") == "file"
        ):
            path_value = test.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise DispatchContractError(f"acceptance_tests[{index}].path must be a non-empty relative path")
            check_path = Path(path_value)
            if check_path.is_absolute() or ".." in check_path.parts:
                raise DispatchContractError(f"acceptance_tests[{index}].path is unsafe")
        if test_type == "file_sha256" and (
            not isinstance(test.get("sha256"), str) or re.fullmatch(r"[0-9a-fA-F]{64}", test["sha256"]) is None
        ):
            raise DispatchContractError(f"acceptance_tests[{index}].sha256 must be a 64-character hexadecimal digest")
        if test_type in {"regex_present", "regex_absent"}:
            if not isinstance(test.get("pattern"), str):
                raise DispatchContractError(f"acceptance_tests[{index}].pattern must be a string")
            if len(test["pattern"]) > 4096:
                raise DispatchContractError(f"acceptance_tests[{index}].pattern exceeds 4096 characters")
            try:
                re.compile(test["pattern"], re.MULTILINE)
            except re.error as exc:
                raise DispatchContractError(f"acceptance_tests[{index}].pattern is invalid: {exc}") from exc
        if test_type == "json_path_equals":
            if test.get("source", "result") not in {"result", "file"}:
                raise DispatchContractError(f"acceptance_tests[{index}].source must be result or file")
            if not isinstance(test.get("json_path"), str) or not test["json_path"].strip():
                raise DispatchContractError(f"acceptance_tests[{index}].json_path must be a non-empty string")
            if "expected" not in test:
                raise DispatchContractError(f"acceptance_tests[{index}].expected is required")
        if test_type == "command_exit_zero":
            command = test.get("command")
            if not isinstance(command, list) or not command or not all(isinstance(value, str) for value in command):
                raise DispatchContractError(
                    f"acceptance_tests[{index}].command must be a non-empty argv array; shell strings are forbidden"
                )
            command_timeout = test.get("timeout", 120)
            if isinstance(command_timeout, bool) or not isinstance(command_timeout, (int, float)):
                raise DispatchContractError(f"acceptance_tests[{index}].timeout must be numeric")
            if not math.isfinite(float(command_timeout)) or float(command_timeout) <= 0:
                raise DispatchContractError(f"acceptance_tests[{index}].timeout must be finite and positive")
    minimum_quality = contract.get("minimum_verified_quality", 0.8)
    if isinstance(minimum_quality, bool) or not isinstance(minimum_quality, (int, float)):
        raise DispatchContractError("contract.minimum_verified_quality must be numeric")
    if not math.isfinite(float(minimum_quality)) or float(minimum_quality) < 0.0 or float(minimum_quality) > 1.0:
        raise DispatchContractError("contract.minimum_verified_quality must be finite and between 0 and 1")
    inputs = contract.get("inputs", [])
    if not isinstance(inputs, list) or not all(isinstance(value, str) and value.strip() for value in inputs):
        raise DispatchContractError("contract.inputs must be an array of non-empty project-relative paths")
    for value in inputs:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts:
            raise DispatchContractError(f"unsafe contract input path: {value!r}")
    task_normalized = normalize_task(task)
    contract_task = dict(contract.get("task") or {})
    _validate_raw_task_fields(contract_task, "contract.task")
    combined_task = normalize_task({**task_normalized, **contract_task, "objective": objective, "task_id": task_id})
    for field in SECURITY_TASK_FIELDS:
        if field in contract_task and combined_task.get(field) != task_normalized.get(field):
            raise DispatchContractError(
                f"contract.task.{field} conflicts with the routed task; freeze one canonical task before dispatch"
            )
    mutability = str(combined_task.get("mutability") or "read-only")
    if mutability not in SAFE_MUTABILITY:
        raise DispatchContractError(
            f"automatic worker dispatch does not authorize mutability={mutability}; use an explicit specialist approval path"
        )
    delegation = contract.get("delegation") or {"may_spawn_descendants": False, "remaining_depth": 0}
    if not isinstance(delegation, dict):
        raise DispatchContractError("contract.delegation must be an object")
    if "may_spawn_descendants" in delegation and not isinstance(delegation["may_spawn_descendants"], bool):
        raise DispatchContractError("delegation.may_spawn_descendants must be a JSON boolean")
    raw_remaining_depth = delegation.get("remaining_depth", 0)
    if isinstance(raw_remaining_depth, bool) or not isinstance(raw_remaining_depth, int):
        raise DispatchContractError("delegation.remaining_depth must be an integer")
    remaining_depth = raw_remaining_depth
    if remaining_depth < 0 or remaining_depth > 2:
        raise DispatchContractError("delegation.remaining_depth must be between 0 and 2")
    if delegation.get("may_spawn_descendants") or remaining_depth:
        raise DispatchContractError(
            "worker-to-worker descendant dispatch is not supported; the authoritative Lead must route every work unit"
        )
    write_scope = _safe_write_scope(contract.get("write_scope", []))
    if mutability == "workspace-write":
        if not write_scope:
            raise DispatchContractError("workspace-write dispatch requires a non-empty bounded write_scope")
        if combined_task.get("shared_mutable_state"):
            raise DispatchContractError("workspace-write dispatch cannot operate on shared mutable state")
    normalized = dict(contract)
    normalized.update({"task_id": task_id, "objective": objective})
    normalized["task"] = combined_task
    normalized["write_scope"] = write_scope
    normalized["inputs"] = [str(value).strip().replace("\\", "/") for value in inputs]
    normalized["delegation"] = {"may_spawn_descendants": False, "remaining_depth": 0}
    normalized.setdefault("project_id", str(task.get("project_id") or ""))
    normalized["minimum_verified_quality"] = float(minimum_quality)
    for field in ("requires_independent_verifier", "gateway_self_contained"):
        if field in contract and not isinstance(contract[field], bool):
            raise DispatchContractError(f"contract.{field} must be a JSON boolean")
    normalized["requires_independent_verifier"] = contract.get("requires_independent_verifier", False)
    normalized["gateway_self_contained"] = contract.get("gateway_self_contained", False)
    budget = contract.get("budget") or {}
    if not isinstance(budget, dict):
        raise DispatchContractError("contract.budget must be an object")
    if "max_cost_usd" in budget:
        raise DispatchContractError(
            "contract.budget.max_cost_usd is not enforceable by the runner; constrain provider arms in Lead governance"
        )
    if "max_minutes" in budget:
        max_minutes = budget["max_minutes"]
        if isinstance(max_minutes, bool) or not isinstance(max_minutes, (int, float)):
            raise DispatchContractError("contract.budget.max_minutes must be numeric")
        if not math.isfinite(float(max_minutes)) or float(max_minutes) <= 0:
            raise DispatchContractError("contract.budget.max_minutes must be finite and positive")
        budget = {"max_minutes": float(max_minutes)}
    normalized["budget"] = budget
    return normalized


def _handoff_prompt(contract: dict[str, Any]) -> str:
    delegation = contract["delegation"]
    descendant_rule = (
        f"Descendant delegation is permitted with remaining depth {delegation['remaining_depth']}; preserve all bounds."
        if delegation["may_spawn_descendants"] and delegation["remaining_depth"] > 0
        else "Do not delegate or invoke another route-and-dispatch worker."
    )
    return (
        "You are an isolated ResearchOps worker executing one already-routed work unit.\n"
        "Do not redefine the session objective, change the selected model, or approve your own work.\n"
        f"{descendant_rule}\n"
        "Respect the task mutability and write_scope exactly. Run the frozen acceptance checks when safe.\n"
        "Return a concise completion report with artifact paths, checks run, uncertainty, and blockers.\n\n"
        "Frozen handoff contract:\n"
        + json.dumps(contract, ensure_ascii=False, indent=2)
    )


def _verifier_prompt(contract_path: Path, result_path: Path, root: Path, patch_path: str | None = None) -> str:
    patch_instruction = f" Inspect the proposed patch at {patch_path}." if patch_path else ""
    return (
        "You are a fresh-context independent verifier. Do not preserve the worker's conclusion and do not modify files.\n"
        f"Read the frozen contract at {_relative(root, contract_path)} and worker result at {_relative(root, result_path)}."
        + patch_instruction
        + "\n"
        "Inspect the referenced artifacts and deterministic evidence. Return JSON only with this shape:\n"
        '{"confidence":0.0,"disposition":"accepted|reject|retry-same|retry-stronger|route-different",'
        '"dimensions":{"correctness":0.0,"evidence_quality":0.0,"scope_discipline":0.0},'
        '"failure_modes":[],"verifier_disagreement":0.0,"notes":"..."}\n'
        "Every numeric value must be between 0 and 1. Do not include markdown fences."
    )


def _parse_json_lines(text: str) -> tuple[str | None, dict[str, int], str | None]:
    thread_id: str | None = None
    usage: dict[str, int] = {}
    last_error: str | None = None
    for line in text.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict):
            continue
        thread_id = str(item.get("thread_id") or item.get("thread", {}).get("id") or thread_id or "") or None
        raw_usage = item.get("usage") or (item.get("turn") or {}).get("usage") or {}
        if isinstance(raw_usage, dict):
            for source, target in (
                ("input_tokens", "prompt_tokens"),
                ("prompt_tokens", "prompt_tokens"),
                ("output_tokens", "completion_tokens"),
                ("completion_tokens", "completion_tokens"),
            ):
                if source in raw_usage:
                    usage[target] = max(usage.get(target, 0), int(raw_usage.get(source) or 0))
        if item.get("type") in {"error", "turn.failed"}:
            raw_error = item.get("error") or item.get("message")
            if isinstance(raw_error, dict):
                raw_error = raw_error.get("message") or raw_error.get("type")
            if raw_error:
                last_error = str(raw_error)
    return thread_id, usage, last_error


def _selected_environment(
    root: Path,
    model: dict[str, Any],
    *,
    worker_depth: int,
    dispatch_id: str,
    delegation: dict[str, Any],
    selected_credential: str | None = None,
) -> dict[str, str]:
    external_profile = str(model.get("provider") or "") != "codex-native"
    if external_profile:
        allowed = {"PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "COLORTERM", "NO_COLOR"}
        environment = {key: value for key, value in os.environ.items() if key in allowed}
    else:
        environment = dict(os.environ)
    native_openai_key = environment.get("OPENAI_API_KEY") if not external_profile else None
    credential = str(model.get("credential_env") or "").strip()
    governed_credentials = models.governed_credential_names() | {
        str(item.get("credential_env") or "").strip()
        for item in _models(root).values()
        if item.get("credential_env")
    }
    for name in governed_credentials:
        environment.pop(name, None)
    for name in list(environment):
        if SENSITIVE_ENV_NAME.search(name):
            environment.pop(name, None)
    if native_openai_key:
        environment["OPENAI_API_KEY"] = native_openai_key
    if credential:
        value = selected_credential or models._secret(credential)
        if not value:
            raise RuntimeError(f"missing credential environment variable: {credential}")
        environment[credential] = value
    environment["ROPS_WORKER_DEPTH"] = str(worker_depth)
    environment["ROPS_PARENT_DISPATCH_ID"] = dispatch_id
    granted = bool(delegation.get("may_spawn_descendants") and int(delegation.get("remaining_depth", 0)) > 0)
    environment["ROPS_DESCENDANT_GRANT"] = "1" if granted else "0"
    environment["ROPS_DELEGATION_REMAINING"] = str(int(delegation.get("remaining_depth", 0)) if granted else 0)
    return environment


def _start_credential_broker(
    model: dict[str, Any],
    deadline: float,
) -> tuple[http.server.ThreadingHTTPServer, threading.Thread, str, str]:
    """Expose one pinned upstream through a process-local, one-dispatch bearer token."""
    upstream_base = str(model.get("base_url") or "").rstrip("/")
    if not upstream_base:
        raise DispatchContractError("external Codex arm has no pinned upstream base_url")
    allowed_path = models._request_path(model)
    upstream_headers = models._headers(model)
    credential_name = str(model.get("credential_env") or "")
    if credential_name and not models._secret(credential_name):
        raise RuntimeError(f"missing credential environment variable: {credential_name}")
    worker_token = "rops-dispatch-" + secrets.token_urlsafe(32)
    upstream = urllib.parse.urlsplit(upstream_base)
    if upstream.scheme not in {"http", "https"} or not upstream.hostname:
        raise DispatchContractError("external Codex arm has an unsupported upstream URL")
    upstream_target = (upstream.path.rstrip("/") + allowed_path) or "/"
    max_requests = 8
    max_request_bytes = 64 * 1024 * 1024
    max_response_bytes = 64 * 1024 * 1024
    max_output_tokens = 16_384
    total_output_tokens = 65_536

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            authorization = self.headers.get("Authorization", "")
            if not hmac.compare_digest(authorization, f"Bearer {worker_token}"):
                self.send_error(401)
                return
            request_path = self.path.split("?", 1)[0]
            if request_path != allowed_path:
                self.send_error(404)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_error(400)
                return
            if length < 0 or length > 32 * 1024 * 1024:
                self.send_error(413)
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(400)
                return
            if not isinstance(payload, dict):
                self.send_error(400)
                return
            payload["model"] = str(model.get("model") or "")
            effort = str(model.get("api_reasoning_effort") or model.get("reasoning_effort") or "")
            reasoning = payload.get("reasoning") if isinstance(payload.get("reasoning"), dict) else {}
            if effort:
                reasoning = {**reasoning, "effort": effort}
                payload["reasoning"] = reasoning
            payload.pop("reasoning_effort", None)
            payload.pop("thinking", None)
            requested_output = payload.get("max_output_tokens", max_output_tokens)
            if isinstance(requested_output, bool) or not isinstance(requested_output, int) or requested_output <= 0:
                self.send_error(400)
                return
            requested_output = min(requested_output, max_output_tokens)
            server = self.server
            assert isinstance(server, http.server.ThreadingHTTPServer)
            remaining = deadline - time.monotonic()
            with server._rops_lock:  # type: ignore[attr-defined]
                if remaining <= 0:
                    status = 504
                    local_reason = "deadline"
                elif server._rops_closing:  # type: ignore[attr-defined]
                    status = 503
                    local_reason = "closing"
                elif server._rops_request_count >= max_requests:  # type: ignore[attr-defined]
                    status = 429
                    local_reason = "request-budget"
                elif server._rops_active_slot:  # type: ignore[attr-defined]
                    status = 429
                    local_reason = "concurrency"
                elif server._rops_output_tokens >= total_output_tokens:  # type: ignore[attr-defined]
                    status = 429
                    local_reason = "output-token-budget"
                else:
                    status = 0
                    local_reason = ""
                    requested_output = min(
                        requested_output,
                        total_output_tokens - server._rops_output_tokens,  # type: ignore[attr-defined]
                    )
                    payload["max_output_tokens"] = requested_output
                    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    if server._rops_request_bytes + len(body) > max_request_bytes:  # type: ignore[attr-defined]
                        status = 413
                        local_reason = "request-byte-budget"
                    else:
                        server._rops_local_rejection = None  # type: ignore[attr-defined]
                        server._rops_active_slot = True  # type: ignore[attr-defined]
                        server._rops_active_zero.clear()  # type: ignore[attr-defined]
                        server._rops_request_count += 1  # type: ignore[attr-defined]
                        server._rops_request_bytes += len(body)  # type: ignore[attr-defined]
                        server._rops_output_tokens += requested_output  # type: ignore[attr-defined]
            if status:
                with server._rops_lock:  # type: ignore[attr-defined]
                    server._rops_local_rejection = {"status": status, "kind": local_reason}  # type: ignore[attr-defined]
                self.send_error(status)
                return
            assert "body" in locals()
            connection_class = http.client.HTTPSConnection if upstream.scheme == "https" else http.client.HTTPConnection
            connection = connection_class(
                upstream.hostname,
                upstream.port,
                timeout=max(0.1, remaining),
            )
            with server._rops_lock:  # type: ignore[attr-defined]
                server._rops_active_connections.add(connection)  # type: ignore[attr-defined]
            try:
                headers = {**upstream_headers, "Content-Length": str(len(body))}
                connection.request("POST", upstream_target, body=body, headers=headers)
                upstream_socket = connection.sock
                if upstream_socket is not None:
                    with server._rops_lock:  # type: ignore[attr-defined]
                        server._rops_active_sockets.add(upstream_socket)  # type: ignore[attr-defined]
                response = connection.getresponse()
                with server._rops_lock:  # type: ignore[attr-defined]
                    server._rops_active_responses.add(response)  # type: ignore[attr-defined]
                    server._rops_upstream_failure = (  # type: ignore[attr-defined]
                        {"status": int(response.status), "kind": "http"}
                        if int(response.status) >= 400
                        else None
                    )
                self.send_response(int(response.status))
                for name in ("Content-Type", "OpenAI-Version", "X-Request-Id"):
                    value = response.getheader(name)
                    if value:
                        self.send_header(name, value)
                self.send_header("Connection", "close")
                self.end_headers()
                transferred = 0
                identity_capture = bytearray()
                while True:
                    with server._rops_lock:  # type: ignore[attr-defined]
                        if server._rops_closing:  # type: ignore[attr-defined]
                            raise RuntimeError("credential broker is closing")
                    if time.monotonic() >= deadline:
                        raise RuntimeError("credential broker deadline exhausted")
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    transferred += len(chunk)
                    if len(identity_capture) < 2 * 1024 * 1024:
                        identity_capture.extend(chunk[: 2 * 1024 * 1024 - len(identity_capture)])
                    with server._rops_lock:  # type: ignore[attr-defined]
                        if server._rops_response_bytes + transferred > max_response_bytes:  # type: ignore[attr-defined]
                            raise RuntimeError("credential broker response byte budget exceeded")
                    self.wfile.write(chunk)
                    self.wfile.flush()
                with server._rops_lock:  # type: ignore[attr-defined]
                    server._rops_response_bytes += transferred  # type: ignore[attr-defined]
                returned_models: set[str] = set()
                response_text = identity_capture.decode("utf-8", errors="replace")
                candidates = [response_text]
                candidates.extend(
                    line[5:].strip()
                    for line in response_text.splitlines()
                    if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}
                )
                for candidate_text in candidates:
                    try:
                        returned_models.update(_response_model_values(json.loads(candidate_text)))
                    except json.JSONDecodeError:
                        continue
                with server._rops_lock:  # type: ignore[attr-defined]
                    server._rops_returned_models.update(returned_models)  # type: ignore[attr-defined]
            except (OSError, http.client.HTTPException, RuntimeError) as exc:
                with server._rops_lock:  # type: ignore[attr-defined]
                    if isinstance(exc, RuntimeError) or server._rops_closing:  # type: ignore[attr-defined]
                        server._rops_local_rejection = {  # type: ignore[attr-defined]
                            "status": None,
                            "kind": "stream-budget-or-cancellation",
                            "error_class": type(exc).__name__,
                        }
                    else:
                        server._rops_upstream_failure = {  # type: ignore[attr-defined]
                            "status": None,
                            "kind": "network",
                            "error_class": type(exc).__name__,
                        }
                self.close_connection = True
            finally:
                try:
                    response.close()
                except (NameError, OSError):
                    pass
                connection.close()
                with server._rops_lock:  # type: ignore[attr-defined]
                    if "response" in locals():
                        server._rops_active_responses.discard(response)  # type: ignore[attr-defined]
                    if "upstream_socket" in locals() and upstream_socket is not None:
                        server._rops_active_sockets.discard(upstream_socket)  # type: ignore[attr-defined]
                    server._rops_active_connections.discard(connection)  # type: ignore[attr-defined]
                    server._rops_active_slot = False  # type: ignore[attr-defined]
                    if not server._rops_active_connections and not server._rops_active_slot:  # type: ignore[attr-defined]
                        server._rops_active_zero.set()  # type: ignore[attr-defined]
                self.close_connection = True

        def log_message(self, _format: str, *_args: Any) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server._rops_lock = threading.Lock()  # type: ignore[attr-defined]
    server._rops_active_connections = set()  # type: ignore[attr-defined]
    server._rops_active_responses = set()  # type: ignore[attr-defined]
    server._rops_active_sockets = set()  # type: ignore[attr-defined]
    server._rops_active_slot = False  # type: ignore[attr-defined]
    server._rops_closing = False  # type: ignore[attr-defined]
    server._rops_active_zero = threading.Event()  # type: ignore[attr-defined]
    server._rops_active_zero.set()  # type: ignore[attr-defined]
    server._rops_request_count = 0  # type: ignore[attr-defined]
    server._rops_request_bytes = 0  # type: ignore[attr-defined]
    server._rops_response_bytes = 0  # type: ignore[attr-defined]
    server._rops_output_tokens = 0  # type: ignore[attr-defined]
    server._rops_shutdown_clean = False  # type: ignore[attr-defined]
    server._rops_upstream_failure = None  # type: ignore[attr-defined]
    server._rops_local_rejection = None  # type: ignore[attr-defined]
    server._rops_returned_models = set()  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, name="rops-credential-broker", daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return server, thread, worker_token, f"http://{host}:{port}"


def _stop_credential_broker(
    server: http.server.ThreadingHTTPServer | None,
    thread: threading.Thread | None,
) -> bool:
    if server is None:
        return True
    with server._rops_lock:  # type: ignore[attr-defined]
        server._rops_closing = True  # type: ignore[attr-defined]
        connections = list(server._rops_active_connections)  # type: ignore[attr-defined]
        responses = list(server._rops_active_responses)  # type: ignore[attr-defined]
        sockets = list(server._rops_active_sockets)  # type: ignore[attr-defined]
    server.shutdown()
    for upstream_socket in sockets:
        try:
            upstream_socket.shutdown(2)
        except OSError:
            pass
    for response in responses:
        response.close()
    for connection in connections:
        connection.close()
    server._rops_shutdown_clean = server._rops_active_zero.wait(timeout=5.0)  # type: ignore[attr-defined]
    server.server_close()
    if thread is not None:
        thread.join(timeout=3.0)
    return bool(server._rops_shutdown_clean and (thread is None or not thread.is_alive()))  # type: ignore[attr-defined]


def _validate_managed_profile(profile: str, model: dict[str, Any]) -> None:
    specifications = {str(item["profile"]): item for item in models._codex_profile_specs()}
    specification = specifications.get(profile)
    if not specification:
        raise DispatchContractError(f"unmanaged Codex profile is not executable: {profile}")
    if str(model.get("codex_profile") or "") != profile:
        raise DispatchContractError(f"arm/profile mismatch for {_arm_id(model)}")
    comparisons = (
        ("base_url", str(model.get("base_url") or "").rstrip("/"), str(specification.get("base_url") or "").rstrip("/")),
        ("credential_env", str(model.get("credential_env") or ""), str(specification.get("env_key") or "")),
        ("model", str(model.get("model") or ""), str(specification.get("model") or "")),
    )
    for field, actual, expected in comparisons:
        if actual != expected:
            raise DispatchContractError(f"managed profile {profile} does not match arm {field}")
    if str(model.get("reasoning_effort") or "") not in set(specification.get("efforts") or []):
        raise DispatchContractError(f"managed profile {profile} does not support the arm effort")
    codex_home = Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()
    profile_path = codex_home / f"{profile}.config.toml"
    if not profile_path.is_file():
        raise RuntimeError(f"managed Codex profile is not installed: {profile_path}")
    text = profile_path.read_text(encoding="utf-8")
    if models.CODEX_PROFILE_MARKER not in text:
        raise DispatchContractError(f"Codex profile is not ResearchOps-managed: {profile_path}")
    parsed = tomllib.loads(text)
    if parsed.get("model_provider") != specification.get("id") or parsed.get("model") != specification.get("model"):
        raise DispatchContractError(f"installed Codex profile does not match its managed specification: {profile}")
    if specification.get("model_catalog"):
        expected_effort = str(specification.get("default_effort") or "high")
        if str(model.get("reasoning_effort") or "") != expected_effort:
            raise DispatchContractError(f"managed fixed-alias profile {profile} does not match arm effort")
        if str(parsed.get("model_reasoning_effort") or "") != expected_effort:
            raise DispatchContractError(f"installed fixed-alias profile {profile} has drifted reasoning effort")
    config_path = codex_home / "config.toml"
    if not config_path.is_file():
        raise RuntimeError(f"managed Codex provider configuration is not installed: {config_path}")
    config_text = config_path.read_text(encoding="utf-8")
    if models.CODEX_CONFIG_BEGIN not in config_text or models.CODEX_CONFIG_END not in config_text:
        raise DispatchContractError("Codex provider configuration is not ResearchOps-managed")
    config = tomllib.loads(config_text)
    provider = ((config.get("model_providers") or {}).get(str(specification.get("id"))) or {})
    expected_provider = {
        "base_url": str(specification.get("base_url") or "").rstrip("/"),
        "env_key": str(specification.get("env_key") or ""),
        "wire_api": "responses",
    }
    actual_provider = {
        "base_url": str(provider.get("base_url") or "").rstrip("/"),
        "env_key": str(provider.get("env_key") or ""),
        "wire_api": str(provider.get("wire_api") or ""),
    }
    if actual_provider != expected_provider:
        raise DispatchContractError(f"managed Codex provider {specification.get('id')} endpoint/env/protocol has drifted")


def _external_codex_sandbox_command(
    command: list[str],
    execution_root: Path,
    run_dir: Path,
    model: dict[str, Any],
    mutability: str,
    proxy_base_url: str,
) -> list[str]:
    if shutil.which("bwrap") is None:
        raise DispatchContractError("profiled third-party Codex workers require bubblewrap read isolation")
    profile = str(model.get("codex_profile") or "")
    specifications = {str(item["profile"]): item for item in models._codex_profile_specs()}
    specification = specifications.get(profile)
    if not specification:
        raise DispatchContractError(f"cannot materialize unmanaged external Codex profile: {profile}")
    sandbox_home = run_dir / "codex-home"
    sandbox_home.mkdir(parents=True, exist_ok=True)
    sandbox_home.chmod(0o700)
    provider_config = "\n".join(
        [
            models.CODEX_CONFIG_BEGIN,
            "# One-dispatch local credential broker; the upstream credential is not present in this sandbox.",
            f"[model_providers.{specification['id']}]",
            f"name = {json.dumps(str(specification['name']) + ' (ResearchOps broker)')}",
            f"base_url = {json.dumps(proxy_base_url)}",
            f"env_key = {json.dumps(specification['env_key'])}",
            f"env_key_instructions = {json.dumps('Ephemeral ResearchOps dispatch credential.')}",
            'wire_api = "responses"',
            models.CODEX_CONFIG_END,
            "",
        ]
    )
    _private_text(sandbox_home / "config.toml", provider_config)
    _private_text(
        sandbox_home / f"{profile}.config.toml",
        models._codex_profile_text(specification, config_dir=Path("/codex-home")),
    )
    if specification.get("model_catalog"):
        _private_text(
            sandbox_home / models.CODEX_GLM_MODEL_CATALOG,
            models._codex_glm_model_catalog_text(),
        )
    executable = Path(shutil.which(command[0]) or command[0]).resolve()
    if not executable.is_file():
        raise DispatchContractError(f"Codex executable is not a file: {executable}")

    sandbox: list[str] = [
        "bwrap",
        "--die-with-parent",
        "--new-session",
        "--unshare-pid",
        "--tmpfs",
        "/",
    ]
    created: set[str] = set()

    def ensure_parents(path: Path) -> None:
        for parent in reversed(path.parents):
            text = str(parent)
            if text == "/" or text in created:
                continue
            sandbox.extend(["--dir", text])
            created.add(text)

    ensure_parents(Path("/usr"))
    sandbox.extend(["--ro-bind", "/usr", "/usr"])
    for source in (
        Path("/etc/ssl"),
        Path("/etc/ca-certificates"),
        Path("/etc/pki"),
        Path("/etc/resolv.conf"),
        Path("/etc/hosts"),
        Path("/etc/nsswitch.conf"),
        Path("/etc/passwd"),
        Path("/etc/group"),
    ):
        if source.exists():
            ensure_parents(source)
            sandbox.extend(["--ro-bind", str(source), str(source)])
    for destination, target in (("usr/bin", "/bin"), ("usr/lib", "/lib"), ("usr/lib64", "/lib64")):
        sandbox.extend(["--symlink", destination, target])
    sandbox.extend(["--dev", "/dev", "--proc", "/proc", "--dir", "/tmp"])
    output_dir = run_dir / "worker-output"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_dir.chmod(0o700)
    for path in (execution_root, output_dir, Path("/codex-home"), Path("/worker-bin/codex"), Path("/worker-home")):
        ensure_parents(path)
    root_binding = "--bind" if mutability == "workspace-write" else "--ro-bind"
    sandbox.extend(
        [
            root_binding,
            str(execution_root),
            str(execution_root),
            "--ro-bind",
            str(execution_root / ".git"),
            str(execution_root / ".git"),
            "--bind",
            str(output_dir),
            str(output_dir),
            "--bind",
            str(sandbox_home),
            "/codex-home",
            "--ro-bind",
            str(executable),
            "/worker-bin/codex",
            "--setenv",
            "HOME",
            "/worker-home",
            "--setenv",
            "CODEX_HOME",
            "/codex-home",
            "--chdir",
            str(execution_root),
            "--",
            "/worker-bin/codex",
            *command[1:],
        ]
    )
    return sandbox


def build_codex_command(
    root: Path,
    candidate: dict[str, Any],
    model: dict[str, Any],
    output_file: Path,
    *,
    codex_bin: str = "codex",
    persist_session: bool = False,
    worker_controls: dict[str, str] | None = None,
) -> list[str]:
    execution = dict(candidate.get("execution") or {})
    mutability = str(candidate.get("mutability") or "read-only")
    command = [
        codex_bin,
        "exec",
        "--json",
        "--color",
        "never",
        "--skip-git-repo-check",
        "-C",
        str(root),
        "-s",
        mutability,
        "-o",
        str(output_file),
        "-c",
        "mcp_servers={}",
        "-c",
        'shell_environment_policy.inherit="core"',
    ]
    controls = worker_controls or {}
    if controls:
        inline = ", ".join(f"{key} = {json.dumps(str(value))}" for key, value in sorted(controls.items()))
        command.extend(["-c", f"shell_environment_policy.set={{ {inline} }}"])
    if not persist_session:
        command.append("--ephemeral")
    # Descendants must re-enter this audited dispatcher. Native multi-agent
    # spawning would bypass route decisions, lifecycle rows, and depth limits.
    command.extend(["--disable", "multi_agent"])
    profile = str(execution.get("codex_profile") or model.get("codex_profile") or "").strip()
    if profile:
        _validate_managed_profile(profile, model)
        command.extend(["-p", profile])
    else:
        if str(model.get("provider") or "") != "codex-native":
            raise DispatchContractError(
                f"provider {model.get('provider')} has no managed Codex profile; use the read-only gateway backend"
            )
        command.extend(["-m", str(execution.get("model") or model.get("model"))])
    effort = execution.get("reasoning_effort", model.get("reasoning_effort"))
    if effort:
        command.extend(["-c", f"model_reasoning_effort={json.dumps(str(effort))}"])
    return command


def _redact_error(text: str, model: dict[str, Any]) -> str:
    redacted = str(text)
    credential = str(model.get("credential_env") or "")
    secret = models._secret(credential) if credential else None
    if secret:
        redacted = redacted.replace(secret, "[REDACTED]")
    redacted = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", redacted)
    redacted = re.sub(r"\bsk-[A-Za-z0-9_.-]{12,}\b", "[REDACTED]", redacted)
    return redacted[-2000:]


def _drain_stream(stream: Any, path: Path, limit: int, state: dict[str, Any], key: str) -> None:
    kept = 0
    truncated = False
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                remaining = max(0, limit - kept)
                if remaining:
                    handle.write(chunk[:remaining])
                    kept += min(len(chunk), remaining)
                if len(chunk) > remaining:
                    truncated = True
    finally:
        stream.close()
        state[key] = {"bytes_kept": kept, "truncated": truncated}


def _feed_stdin(stream: Any, payload: bytes) -> None:
    try:
        stream.write(payload)
        stream.flush()
    except BrokenPipeError:
        pass
    finally:
        stream.close()


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    group_id = process.pid
    try:
        os.killpg(group_id, signal.SIGTERM)
    except ProcessLookupError:
        if process.poll() is None:
            process.wait(timeout=2.0)
        return
    if process.poll() is None:
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        try:
            os.killpg(group_id, 0)
        except ProcessLookupError:
            return
        time.sleep(0.02)
    try:
        os.killpg(group_id, signal.SIGKILL)
    except ProcessLookupError:
        return
    if process.poll() is None:
        process.wait(timeout=2.0)


def _codex_dispatch(
    execution_root: Path,
    store: IntelligenceStore,
    candidate: dict[str, Any],
    model: dict[str, Any],
    contract: dict[str, Any],
    prompt: str,
    run_dir: Path,
    *,
    timeout: float,
    codex_bin: str,
    persist_session: bool,
    dispatch_id: str,
    worker_depth: int,
) -> dict[str, Any]:
    external_profile = str(model.get("provider") or "") != "codex-native"
    output_file = run_dir / ("worker-output/last-message.txt" if external_profile else "last-message.txt")
    raw_file = run_dir / "events.jsonl"
    stderr_file = run_dir / "stderr.txt"
    run_dir.mkdir(parents=True, exist_ok=True)
    run_dir.chmod(0o700)
    command_candidate = {**candidate, "mutability": str(candidate.get("mutability") or "read-only")}
    delegation = dict(contract.get("delegation") or {})
    granted = bool(delegation.get("may_spawn_descendants") and int(delegation.get("remaining_depth", 0)) > 0)
    command = build_codex_command(
        execution_root,
        command_candidate,
        model,
        output_file,
        codex_bin=codex_bin,
        persist_session=persist_session,
        worker_controls={
            "ROPS_WORKER_DEPTH": str(worker_depth),
            "ROPS_PARENT_DISPATCH_ID": dispatch_id,
            "ROPS_DESCENDANT_GRANT": "1" if granted else "0",
            "ROPS_DELEGATION_REMAINING": str(int(delegation.get("remaining_depth", 0)) if granted else 0),
        },
    )
    if shutil.which(codex_bin) is None and not Path(codex_bin).exists():
        raise RuntimeError(f"Codex executable not found: {codex_bin}")
    broker_server: http.server.ThreadingHTTPServer | None = None
    broker_thread: threading.Thread | None = None
    broker_token: str | None = None
    proxy_base_url: str | None = None
    try:
        if external_profile:
            broker_server, broker_thread, broker_token, proxy_base_url = _start_credential_broker(
                model,
                time.monotonic() + timeout,
            )
        environment = _selected_environment(
            store.layout.root,
            model,
            worker_depth=worker_depth,
            dispatch_id=dispatch_id,
            delegation=dict(contract.get("delegation") or {}),
            selected_credential=broker_token,
        )
        if external_profile:
            assert proxy_base_url is not None
            command = _external_codex_sandbox_command(
                command,
                execution_root,
                run_dir,
                model,
                str(candidate.get("mutability") or "read-only"),
                proxy_base_url,
            )
        prlimit = shutil.which("prlimit")
        if str(candidate.get("mutability") or "read-only") == "workspace-write" and not prlimit:
            raise DispatchContractError("workspace-write workers require prlimit for file-size enforcement")
        if prlimit:
            command = [prlimit, f"--fsize={MAX_CHANGED_FILE_BYTES}", "--", *command]
    except BaseException:
        _stop_credential_broker(broker_server, broker_thread)
        raise
    started = time.monotonic()
    stream_state: dict[str, Any] = {}
    process: subprocess.Popen[bytes] | None = None
    previous_sigterm: Any = None
    signal_handler_installed = threading.current_thread() is threading.main_thread()
    broker_shutdown_clean = True
    if signal_handler_installed:
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def cancel_worker(_signum: int, _frame: Any) -> None:
            raise WorkerCancelledError("worker dispatch received SIGTERM")

        signal.signal(signal.SIGTERM, cancel_worker)
    try:
        process = subprocess.Popen(
            command,
            cwd=execution_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        threads = [
            threading.Thread(target=_feed_stdin, args=(process.stdin, prompt.encode("utf-8")), daemon=True),
            threading.Thread(target=_drain_stream, args=(process.stdout, raw_file, 8 * 1024 * 1024, stream_state, "stdout"), daemon=True),
            threading.Thread(target=_drain_stream, args=(process.stderr, stderr_file, 128 * 1024, stream_state, "stderr"), daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_group(process)
            raise WorkerTimeoutError(f"Codex worker timed out after {timeout:.1f}s") from exc
        except BaseException:
            _terminate_process_group(process)
            raise
        finally:
            _terminate_process_group(process)
            for thread in threads:
                thread.join(timeout=3.0)
    except OSError as exc:
        raise RuntimeError(f"failed to start Codex worker: {exc}") from exc
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_group(process)
        if signal_handler_installed:
            signal.signal(signal.SIGTERM, previous_sigterm)
        broker_shutdown_clean = _stop_credential_broker(broker_server, broker_thread)
    if not broker_shutdown_clean:
        raise RuntimeError("credential broker did not terminate all active upstream requests")
    latency = time.monotonic() - started
    stdout = raw_file.read_text(encoding="utf-8", errors="replace") if raw_file.exists() else ""
    stderr = stderr_file.read_text(encoding="utf-8", errors="replace") if stderr_file.exists() else ""
    thread_id, usage, event_error = _parse_json_lines(stdout)
    if return_code:
        detail = _redact_error(event_error or stderr.strip(), model) or "Codex worker returned a non-zero exit code"
        upstream_failure = getattr(broker_server, "_rops_upstream_failure", None) if broker_server else None
        if upstream_failure:
            status = upstream_failure.get("status")
            if status == 429:
                raise WorkerRateLimitError(detail)
            label = f"HTTP {status}" if status else str(upstream_failure.get("kind") or "network")
            endpoint_scope = bool(status is None or status in {401, 403, 408} or int(status) >= 500)
            raise ProviderResponseError(
                f"provider request failed ({label}): {detail}",
                status=status,
                failure_scope="endpoint" if endpoint_scope else "arm",
            )
        local_rejection = getattr(broker_server, "_rops_local_rejection", None) if broker_server else None
        if local_rejection:
            raise BrokerBudgetError(
                f"credential broker rejected the worker request ({local_rejection.get('kind')}): {detail}"
            )
        if "429" in detail or "too many requests" in detail.lower():
            if external_profile:
                raise BrokerBudgetError(f"external worker received an unattributed local 429: {detail}")
            raise WorkerRateLimitError(detail)
        raise RuntimeError(f"Codex worker failed ({return_code}): {detail}")
    local_rejection = getattr(broker_server, "_rops_local_rejection", None) if broker_server else None
    if local_rejection:
        raise BrokerBudgetError(
            f"credential broker rejected or cancelled a worker request ({local_rejection.get('kind')})"
        )
    output = output_file.read_text(encoding="utf-8") if output_file.exists() else ""
    if not output.strip():
        raise RuntimeError("Codex worker completed without a final message")
    output_file.chmod(0o600)
    returned_models = sorted(getattr(broker_server, "_rops_returned_models", set())) if broker_server else []
    identity_mismatch = any(_returned_model_mismatch(model, value) for value in returned_models)
    endpoint = str(model.get("endpoint_id") or model.get("base_url") or "")
    if returned_models:
        record_identity_observation(
            store,
            arm_id=_arm_id(model),
            endpoint_id=endpoint or _arm_id(model),
            declared_identity={"requested_model": model.get("model"), "returned_models": returned_models},
            fingerprint={"api_protocol": models._protocol(model), "transport": "codex-credential-broker"},
        )
    if endpoint:
        record_endpoint_observation(
            store,
            endpoint_id=endpoint,
            arm_id=_arm_id(model),
            success=True,
            latency_seconds=latency,
            metadata={"kind": "codex-worker", "usage": usage},
        )
    return {
        "status": "complete",
        "backend": "codex",
        "worker_session_id": thread_id,
        "persisted_session": persist_session,
        "latency_seconds": round(latency, 6),
        "usage": usage,
        "requested_model": model.get("model"),
        "returned_model": returned_models[-1] if returned_models else None,
        "returned_models": returned_models,
        "identity_mismatch": identity_mismatch,
        "output_text": output,
        "stream_capture": stream_state,
        "artifacts": [
            _relative(store.layout.root, output_file),
            _relative(store.layout.root, raw_file),
            _relative(store.layout.root, stderr_file),
        ],
    }


def _response_text(response: dict[str, Any]) -> str:
    if response.get("output_text") is not None:
        return str(response.get("output_text") or "")
    parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                parts.append(str(content.get("text") or ""))
    if parts:
        return "".join(parts)
    choices = response.get("choices") or []
    return str(((choices[0].get("message") or {}).get("content") or "")) if choices else ""


def _returned_model_mismatch(model: dict[str, Any], returned_model: Any) -> bool:
    returned = str(returned_model or "").strip().lower()
    if not returned:
        return False
    requested = str(model.get("model") or "").strip().lower()
    allowed = {requested, *[str(value).strip().lower() for value in model.get("returned_model_aliases") or []]}
    return returned not in allowed


def _gateway_dispatch(
    store: IntelligenceStore,
    candidate: dict[str, Any],
    model: dict[str, Any],
    prompt: str,
    run_dir: Path,
    *,
    timeout: float,
) -> dict[str, Any]:
    if str(candidate.get("mutability") or "read-only") != "read-only":
        raise RuntimeError("text gateway workers cannot execute workspace-write contracts")
    try:
        dispatched = models.dispatch(
            store,
            _arm_id(model),
            {"messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 4096},
            timeout=timeout,
        )
    except Exception as exc:
        detail = _redact_error(str(exc), model)
        declared_status = getattr(exc, "status", None)
        if declared_status == 429 or "429" in detail or "too many requests" in detail.lower():
            raise WorkerRateLimitError(detail) from exc
        status_match = re.search(r"\bHTTP\s+(\d{3})\b", detail, re.I)
        status = declared_status if isinstance(declared_status, int) else (
            int(status_match.group(1)) if status_match else None
        )
        failure_scope = getattr(exc, "failure_scope", None)
        endpoint_scope = (
            failure_scope == "endpoint"
            if failure_scope in {"arm", "endpoint"}
            else bool(status is None or status in {401, 403, 408} or status >= 500)
        )
        raise ProviderResponseError(
            detail or "gateway provider request failed",
            status=status,
            failure_scope="endpoint" if endpoint_scope else "arm",
        ) from exc
    response = dict(dispatched.get("response") or {})
    returned_model = dispatched.get("returned_model") or response.get("model")
    identity_mismatch = _returned_model_mismatch(model, returned_model)
    if returned_model:
        record_identity_observation(
            store,
            arm_id=_arm_id(model),
            endpoint_id=str(model.get("endpoint_id") or model.get("base_url") or _arm_id(model)),
            declared_identity={"requested_model": model.get("model"), "returned_model": returned_model},
            fingerprint={"api_protocol": models._protocol(model), "response_shape": sorted(response)},
        )
    output = _response_text(response)
    if not output.strip():
        raise RuntimeError("gateway worker completed without output text")
    output_file = run_dir / "last-message.txt"
    _private_text(output_file, output)
    return {
        "status": "complete",
        "backend": "gateway",
        "worker_session_id": None,
        "persisted_session": False,
        "latency_seconds": float(dispatched.get("latency_seconds") or 0.0),
        "usage": response.get("usage") or {},
        "requested_model": model.get("model"),
        "returned_model": returned_model,
        "identity_mismatch": identity_mismatch,
        "output_text": output,
        "artifacts": [_relative(store.layout.root, output_file)],
    }


def _backend(candidate: dict[str, Any], model: dict[str, Any], requested: str) -> str:
    if requested not in SAFE_BACKENDS:
        raise DispatchContractError(f"unknown backend: {requested}")
    execution = candidate.get("execution") or {}
    provider = str(model.get("provider") or "")
    codex_compatible = bool(provider == "codex-native" or (execution.get("codex_profile") or model.get("codex_profile")))
    if requested == "codex" and not codex_compatible:
        raise DispatchContractError(
            f"provider {model.get('provider')} is not approved for automatic profiled Codex execution"
        )
    if requested != "auto":
        return requested
    if codex_compatible:
        return "codex"
    return "gateway"


def _candidate_for_contract(candidate: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    return {**candidate, "mutability": contract["task"]["mutability"]}


def _git_changed_paths(root: Path, *, ignore_researchops_runtime: bool = False) -> set[str]:
    probe = subprocess.run(
        _git_command("rev-parse", "--is-inside-work-tree"),
        cwd=root,
        env=_git_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    if probe.returncode or probe.stdout.strip() != "true":
        raise DispatchContractError("isolated Codex workers require a Git worktree")
    paths: set[str] = set()
    for command in (
        _git_command("diff", "--no-textconv", "--no-ext-diff", "--name-only", "-z"),
        _git_command("diff", "--no-textconv", "--no-ext-diff", "--cached", "--name-only", "-z"),
        _git_command("ls-files", "--others", "--exclude-standard", "-z"),
    ):
        completed = subprocess.run(command, cwd=root, env=_git_environment(), capture_output=True, check=False)
        if completed.returncode:
            raise DispatchContractError("unable to inspect Git changes for workspace-write scope enforcement")
        for value in completed.stdout.split(b"\0"):
            if not value:
                continue
            path = value.decode("utf-8", errors="surrogateescape")
            generated_prefixes = (
                ".researchops/artifacts/",
                ".researchops/cache/",
                ".researchops/intelligence/",
                ".researchops/logs/",
                ".researchops/runtime/",
                ".researchops/secrets/",
                ".researchops/state/runs/",
            )
            if ignore_researchops_runtime and path.startswith(generated_prefixes):
                continue
            paths.add(path)
    return paths


def _outside_scope(paths: set[str], scopes: list[str]) -> list[str]:
    return sorted(
        path
        for path in paths
        if not any(path == scope or path.startswith(scope.rstrip("/") + "/") for scope in scopes)
    )


def _filesystem_paths(root: Path) -> set[str]:
    paths: set[str] = set()
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        names[:] = [name for name in names if name != ".git"]
        base = Path(directory)
        for name in files:
            paths.add(str((base / name).relative_to(root)).replace("\\", "/"))
        for name in names:
            path = base / name
            if path.is_symlink():
                paths.add(str(path.relative_to(root)).replace("\\", "/"))
    return paths


def _create_isolated_worktree(root: Path, revision: str | None = None) -> tuple[Path, Path]:
    parent = Path(tempfile.mkdtemp(prefix="researchops-worker-"))
    worktree = parent / "worktree"
    try:
        revision = revision or _git_head(root)
        completed = subprocess.run(
            _git_command("clone", "--quiet", "--no-local", "--no-hardlinks", str(root), str(worktree)),
            cwd=root,
            env=_git_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            raise DispatchContractError(f"unable to create isolated worker worktree: {completed.stderr[-1000:]}")
        checkout = subprocess.run(
            _git_command("checkout", "--quiet", "--detach", revision),
            cwd=worktree,
            env=_git_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        if checkout.returncode:
            raise DispatchContractError(f"unable to detach isolated worker checkout: {checkout.stderr[-1000:]}")
        return worktree, parent
    except BaseException:
        shutil.rmtree(parent, ignore_errors=True)
        raise


def _remove_isolated_worktree(root: Path, worktree: Path | None, parent: Path | None) -> None:
    if parent is not None:
        # Only this exact mkdtemp path and its private clone are owned by the dispatcher.
        shutil.rmtree(parent, ignore_errors=True)


def _capture_workspace_patch(
    root: Path,
    worktree: Path,
    before_files: set[str],
    run_dir: Path,
    write_scope: list[str],
    git_metadata_fingerprint: str,
    base_revision: str,
) -> dict[str, Any]:
    if _git_metadata_fingerprint(worktree) != git_metadata_fingerprint:
        return {
            "status": "failed",
            "scope_violation": True,
            "error_class": "GitMetadataViolation",
            "error": "worker modified private clone Git metadata",
            "changed_paths": [".git/"],
        }
    git_changes = _git_changed_paths(worktree)
    filesystem_additions = _filesystem_paths(worktree) - before_files
    changed = git_changes | filesystem_additions
    outside = _outside_scope(changed, write_scope)
    if outside:
        return {
            "status": "failed",
            "scope_violation": True,
            "error_class": "WriteScopeViolation",
            "error": "worker changed paths outside write_scope: " + ", ".join(outside[:20]),
            "changed_paths": sorted(changed),
        }
    if len(changed) > MAX_CHANGED_FILES:
        return {
            "status": "failed",
            "scope_violation": True,
            "error_class": "PatchResourceLimit",
            "error": f"worker changed {len(changed)} paths; limit is {MAX_CHANGED_FILES}",
            "changed_paths": sorted(changed),
        }
    changed_bytes = 0
    for relative in changed:
        path = worktree / relative
        if not path.exists() and not path.is_symlink():
            continue
        size = path.lstat().st_size
        if size > MAX_CHANGED_FILE_BYTES:
            return {
                "status": "failed",
                "scope_violation": True,
                "error_class": "PatchResourceLimit",
                "error": f"worker changed file exceeds {MAX_CHANGED_FILE_BYTES} bytes: {relative}",
                "changed_paths": sorted(changed),
            }
        changed_bytes += size
        if changed_bytes > MAX_PATCH_BYTES:
            return {
                "status": "failed",
                "scope_violation": True,
                "error_class": "PatchResourceLimit",
                "error": f"worker changed files exceed {MAX_PATCH_BYTES} total bytes",
                "changed_paths": sorted(changed),
            }
    untracked_probe = subprocess.run(
        _git_command("ls-files", "--others", "--exclude-standard", "-z"),
        cwd=worktree,
        env=_git_environment(),
        capture_output=True,
        check=True,
    )
    untracked = [
        value.decode("utf-8", errors="surrogateescape")
        for value in untracked_probe.stdout.split(b"\0")
        if value
    ]
    ignored_additions = filesystem_additions - set(untracked)
    if ignored_additions:
        return {
            "status": "failed",
            "scope_violation": True,
            "error_class": "IgnoredPathWriteViolation",
            "error": "worker created ignored/unpatchable paths: " + ", ".join(sorted(ignored_additions)[:20]),
            "changed_paths": sorted(changed),
        }
    if untracked:
        subprocess.run(
            _git_command("add", "-N", "--", *untracked),
            cwd=worktree,
            env=_git_environment(),
            check=True,
            capture_output=True,
        )
    patch_process = subprocess.Popen(
        _git_command("diff", "--binary", "--no-textconv", "--no-ext-diff", "HEAD", "--"),
        cwd=worktree,
        env=_git_environment(),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    patch_path = run_dir / "changes.patch"
    descriptor = os.open(patch_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    patch_bytes = 0
    exceeded = False
    with os.fdopen(descriptor, "wb") as handle:
        assert patch_process.stdout is not None
        for chunk in iter(lambda: patch_process.stdout.read(64 * 1024), b""):
            patch_bytes += len(chunk)
            if patch_bytes > MAX_PATCH_BYTES:
                exceeded = True
                patch_process.kill()
                break
            handle.write(chunk)
    return_code = patch_process.wait(timeout=5)
    if exceeded:
        patch_path.unlink(missing_ok=True)
        return {
            "status": "failed",
            "scope_violation": True,
            "error_class": "PatchResourceLimit",
            "error": f"binary patch exceeds {MAX_PATCH_BYTES} bytes",
            "changed_paths": sorted(changed),
        }
    if return_code:
        patch_path.unlink(missing_ok=True)
        raise DispatchContractError("unable to capture bounded worker patch")
    return {
        "workspace_isolated": True,
        "base_revision": base_revision,
        "patch_path": _relative(root, patch_path),
        "changed_paths": sorted(changed),
        "artifacts": [_relative(root, patch_path)],
    }


def _materialize_evaluation_worktree(root: Path, result: dict[str, Any]) -> tuple[Path, Path] | None:
    if not result.get("workspace_isolated"):
        return None
    worktree, parent = _create_isolated_worktree(root)
    patch_path = (root / str(result["patch_path"])).resolve()
    if patch_path.stat().st_size:
        completed = subprocess.run(
            _git_command("apply", "--binary", str(patch_path)),
            cwd=worktree,
            env=_git_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode:
            _remove_isolated_worktree(root, worktree, parent)
            raise RuntimeError(f"unable to materialize worker patch for evaluation: {completed.stderr[-1000:]}")
    return worktree, parent


def _apply_accepted_patch(root: Path, result: dict[str, Any]) -> None:
    if not result.get("workspace_isolated"):
        return
    dirty = _git_changed_paths(root, ignore_researchops_runtime=True)
    if dirty:
        raise RuntimeError("project changed during isolated evaluation; accepted patch was not applied")
    if str(result.get("base_revision") or "") != _git_head(root):
        raise RuntimeError("project HEAD changed during isolated evaluation; stale accepted patch was not applied")
    patch_path = (root / str(result["patch_path"])).resolve()
    if not patch_path.stat().st_size:
        return
    check = subprocess.run(
        _git_command("apply", "--check", "--binary", str(patch_path)),
        cwd=root,
        env=_git_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    if check.returncode:
        raise RuntimeError(f"accepted patch no longer applies cleanly: {check.stderr[-1000:]}")
    subprocess.run(
        _git_command("apply", "--binary", str(patch_path)),
        cwd=root,
        env=_git_environment(),
        check=True,
        capture_output=True,
    )


def _evaluation_state_matches_patch(
    root: Path,
    evaluation_root: Path,
    result: dict[str, Any],
    files_before_checks: set[str],
) -> bool:
    additions = _filesystem_paths(evaluation_root) - files_before_checks
    untracked_probe = subprocess.run(
        _git_command("ls-files", "--others", "--exclude-standard", "-z"),
        cwd=evaluation_root,
        env=_git_environment(),
        capture_output=True,
        check=True,
    )
    untracked = [
        value.decode("utf-8", errors="surrogateescape")
        for value in untracked_probe.stdout.split(b"\0")
        if value
    ]
    if additions - set(untracked):
        return False
    if untracked:
        subprocess.run(
            _git_command("add", "-N", "--", *untracked),
            cwd=evaluation_root,
            env=_git_environment(),
            check=True,
            capture_output=True,
        )
    actual = subprocess.run(
        _git_command("diff", "--binary", "--no-textconv", "--no-ext-diff", "HEAD", "--"),
        cwd=evaluation_root,
        env=_git_environment(),
        capture_output=True,
        check=True,
    ).stdout
    expected = (root / str(result["patch_path"])).resolve().read_bytes()
    return actual == expected


def _start_dispatch_lifecycle(
    store: IntelligenceStore,
    *,
    dispatch_id: str,
    parent_dispatch_id: str | None,
    route_decision_id: str,
    project_id: str,
    task_id: str,
    arm_id: str,
    backend: str,
    artifact_root: Path,
) -> None:
    with store.transaction() as connection:
        connection.execute(
            """
            INSERT INTO worker_dispatches(
                dispatch_id,parent_dispatch_id,route_decision_id,project_id,task_id,arm_id,
                backend,status,started_at,artifact_root,metadata_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                dispatch_id,
                parent_dispatch_id,
                route_decision_id,
                project_id,
                task_id,
                arm_id,
                backend,
                "running",
                now(),
                str(artifact_root),
                json.dumps({"runner": "researchops-worker-v1"}, sort_keys=True),
            ),
        )


def _finish_dispatch_lifecycle(store: IntelligenceStore, result: dict[str, Any]) -> None:
    if result.get("status") == "complete":
        status = "completed"
    elif result.get("error_class") == "WorkerTimeoutError":
        status = "timed_out"
    elif result.get("scope_violation"):
        status = "rejected"
    else:
        status = "failed"
    metadata = {
        "reasoning_effort": result.get("reasoning_effort"),
        "usage": result.get("usage") or {},
        "latency_seconds": result.get("latency_seconds", 0.0),
        "infrastructure_failure": bool(result.get("infrastructure_failure")),
    }
    with store.transaction() as connection:
        connection.execute(
            """
            UPDATE worker_dispatches
            SET status=?,finished_at=?,worker_session_id=?,error_class=?,metadata_json=?
            WHERE dispatch_id=?
            """,
            (
                status,
                now(),
                result.get("worker_session_id"),
                result.get("error_class"),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                result["dispatch_id"],
            ),
        )


def dispatch_candidate(
    root: Path,
    store: IntelligenceStore,
    candidate: dict[str, Any],
    contract: dict[str, Any],
    run_dir: Path,
    *,
    backend: str = "auto",
    timeout: float = 900.0,
    codex_bin: str = "codex",
    persist_session: bool = False,
    worker_depth: int = 1,
    dispatch_id: str | None = None,
    parent_dispatch_id: str | None = None,
) -> dict[str, Any]:
    dispatch_id = dispatch_id or "dispatch-" + uuid.uuid4().hex[:16]
    arm_id = str(candidate.get("model_id") or "")
    model = _models(root).get(arm_id)
    if not model:
        raise DispatchContractError(f"selected route references unknown arm: {arm_id}")
    if not model.get("enabled", False):
        raise DispatchContractError(f"selected route references disabled arm: {arm_id}")
    try:
        models.validate_execution_arm_identity(model)
    except ValueError as exc:
        raise DispatchContractError(str(exc)) from exc
    if str(model.get("provider") or "") != "codex-native":
        try:
            models.validate_external_arm_approval(model, root)
        except ValueError as exc:
            raise DispatchContractError(str(exc)) from exc
    execution_contract = dict(contract)
    execution_contract["selected_execution_arm"] = {
        "arm_id": arm_id,
        "provider": candidate.get("provider"),
        "model": candidate.get("model"),
        "reasoning_effort": candidate.get("reasoning_effort"),
        "codex_profile": (candidate.get("execution") or {}).get("codex_profile"),
    }
    contract_path = run_dir / "contract.json"
    _private_json(contract_path, execution_contract)
    prompt = _handoff_prompt(execution_contract)
    selected = _backend(candidate, model, backend)
    common = {
        "dispatch_id": dispatch_id,
        "route_decision_id": contract.get("route_decision_id"),
        "execution_arm_id": arm_id,
        "model_id": arm_id,
        "provider": candidate.get("provider"),
        "model": candidate.get("model"),
        "reasoning_effort": candidate.get("reasoning_effort"),
        "selection_probability": contract.get("selection_probability"),
        "agent_revision": "researchops-worker-v1",
    }
    worker_root = root
    isolated_worktree: Path | None = None
    isolated_parent: Path | None = None
    isolated_before_files: set[str] | None = None
    isolated_git_fingerprint: str | None = None
    isolated_base_revision: str | None = None
    try:
        requires_private_clone = bool(
            contract["task"]["mutability"] == "workspace-write"
            or (selected == "codex" and str(model.get("provider") or "") != "codex-native")
        )
        if requires_private_clone:
            before_changes = _git_changed_paths(root, ignore_researchops_runtime=True)
            if before_changes:
                raise DispatchContractError(
                    "isolated Codex dispatch requires a clean Git worktree; existing changes: "
                    + ", ".join(sorted(before_changes)[:20])
                )
            isolated_base_revision = _git_head(root)
            _validate_tracked_inputs(root, list(contract.get("inputs") or []), isolated_base_revision)
            isolated_worktree, isolated_parent = _create_isolated_worktree(root, isolated_base_revision)
            worker_root = isolated_worktree
            isolated_git_fingerprint = _git_metadata_fingerprint(worker_root)
            if contract["task"]["mutability"] == "workspace-write":
                isolated_before_files = _filesystem_paths(worker_root)
        _start_dispatch_lifecycle(
            store,
            dispatch_id=dispatch_id,
            parent_dispatch_id=parent_dispatch_id,
            route_decision_id=str(contract.get("route_decision_id") or ""),
            project_id=str(contract.get("project_id") or root.name),
            task_id=str(contract.get("task_id") or ""),
            arm_id=arm_id,
            backend=selected,
            artifact_root=run_dir,
        )
        routed = _candidate_for_contract(candidate, contract)
        if selected == "gateway":
            required = set(contract.get("task", {}).get("required_capabilities", []))
            operation = str(contract.get("task", {}).get("operation") or "")
            if required.intersection({"tool-use", "code", "shell", "filesystem-write"}) or operation in {"implement", "debug", "operate"}:
                raise DispatchContractError("text gateway backend cannot satisfy an agentic/tool-use contract")
            if (
                not contract.get("gateway_self_contained")
                or contract.get("inputs")
                or contract.get("artifact_verifier")
            ):
                raise DispatchContractError(
                    "text gateway backend has no filesystem access; set gateway_self_contained=true only for an input-free inline contract"
                )
        if selected == "codex":
            result = _codex_dispatch(
                worker_root,
                store,
                routed,
                model,
                execution_contract,
                prompt,
                run_dir,
                timeout=timeout,
                codex_bin=codex_bin,
                persist_session=persist_session,
                dispatch_id=dispatch_id,
                worker_depth=worker_depth,
            )
        else:
            result = _gateway_dispatch(store, routed, model, prompt, run_dir, timeout=timeout)
        completed = {**common, **result, "infrastructure_failure": False}
        if (
            isolated_worktree is not None
            and isolated_before_files is not None
            and isolated_git_fingerprint is not None
            and isolated_base_revision is not None
        ):
            patch_result = _capture_workspace_patch(
                root,
                isolated_worktree,
                isolated_before_files,
                run_dir,
                contract["write_scope"],
                isolated_git_fingerprint,
                isolated_base_revision,
            )
            completed.update({key: value for key, value in patch_result.items() if key != "artifacts"})
            completed["artifacts"] = [*completed.get("artifacts", []), *patch_result.get("artifacts", [])]
        _finish_dispatch_lifecycle(store, completed)
        return completed
    except Exception as exc:
        if isinstance(exc, DispatchContractError):
            rejected = {
                **common,
                "status": "failed",
                "backend": selected,
                "infrastructure_failure": True,
                "error_class": type(exc).__name__,
                "error": str(exc),
                "latency_seconds": 0.0,
                "usage": {},
                "scope_violation": False,
                "artifacts": [_relative(root, contract_path)],
            }
            _finish_dispatch_lifecycle(store, rejected)
            return rejected
        endpoint = str(model.get("endpoint_id") or model.get("base_url") or "")
        provider_failure = isinstance(exc, (WorkerRateLimitError, ProviderResponseError))
        provider_failure_scope = (
            "endpoint"
            if isinstance(exc, WorkerRateLimitError)
            else getattr(exc, "failure_scope", None)
        )
        if endpoint and selected == "codex" and provider_failure and provider_failure_scope == "endpoint":
            record_endpoint_observation(
                store,
                endpoint_id=endpoint,
                arm_id=arm_id,
                success=False,
                latency_seconds=timeout,
                error_class=type(exc).__name__,
                rate_limited=isinstance(exc, WorkerRateLimitError),
                metadata={"kind": "codex-worker"},
            )
        failed = {
            **common,
            "status": "failed",
            "backend": selected,
            "infrastructure_failure": True,
            "provider_failure": provider_failure,
            "provider_failure_scope": provider_failure_scope,
            "error_class": type(exc).__name__,
            "error": str(exc),
            "latency_seconds": 0.0,
            "usage": {},
            "artifacts": [_relative(root, contract_path)],
        }
        _finish_dispatch_lifecycle(store, failed)
        return failed
    except BaseException as exc:
        cancelled = {
            **common,
            "status": "failed",
            "backend": selected,
            "infrastructure_failure": True,
            "error_class": type(exc).__name__,
            "error": "dispatch cancelled by parent process",
            "latency_seconds": 0.0,
            "usage": {},
            "artifacts": [_relative(root, contract_path)],
        }
        _finish_dispatch_lifecycle(store, cancelled)
        raise
    finally:
        _remove_isolated_worktree(root, isolated_worktree, isolated_parent)


def _extract_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I | re.S)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("verifier did not return a JSON object")
        parsed = json.loads(value[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("verifier output must be a JSON object")
    return parsed


def _normalize_verifier(
    raw: dict[str, Any],
    candidate: dict[str, Any],
    minimum_quality: float = 0.8,
) -> dict[str, Any]:
    required_dimensions = {"correctness", "evidence_quality", "scope_discipline"}
    disposition = str(raw.get("disposition") or "")
    if disposition not in VERIFIER_DISPOSITIONS:
        raise ValueError("verifier disposition is missing or invalid")
    raw_dimensions = raw.get("dimensions")
    if not isinstance(raw_dimensions, dict) or set(raw_dimensions) != required_dimensions:
        raise ValueError("verifier dimensions must contain exactly correctness, evidence_quality, and scope_discipline")

    def finite_score(value: Any, name: str) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"verifier {name} must be numeric")
        score = float(value)
        if not math.isfinite(score) or score < 0.0 or score > 1.0:
            raise ValueError(f"verifier {name} must be finite and between 0 and 1")
        return score

    dimensions = {str(key): finite_score(value, f"dimensions.{key}") for key, value in raw_dimensions.items()}
    confidence = finite_score(raw.get("confidence"), "confidence")
    disagreement = finite_score(raw.get("verifier_disagreement"), "verifier_disagreement")
    failure_modes = raw.get("failure_modes")
    if not isinstance(failure_modes, list) or not all(isinstance(value, str) for value in failure_modes):
        raise ValueError("verifier failure_modes must be an array of strings")
    if not isinstance(raw.get("notes"), str):
        raise ValueError("verifier notes must be a string")
    if disposition == "accepted" and confidence < 0.5:
        raise ValueError("verifier cannot accept with confidence below 0.5")
    if disposition == "accepted" and min(dimensions.values()) < float(minimum_quality):
        raise ValueError("verifier accepted disposition does not meet the contract's minimum quality in every dimension")
    return {
        "verifier_id": "dispatch-verifier-v1",
        "model_id": candidate.get("model_id"),
        "independent": True,
        "confidence": confidence,
        "disposition": disposition,
        "dimensions": dimensions,
        "failure_modes": failure_modes,
        "verifier_disagreement": disagreement,
        "notes": raw["notes"],
    }


def _verifier_candidate(decision: dict[str, Any], worker: dict[str, Any]) -> dict[str, Any] | None:
    explicit = decision.get("verifier")
    if explicit and explicit.get("model_id") != worker.get("model_id"):
        return explicit
    for candidate in decision.get("ranked", []):
        if candidate.get("model_id") == worker.get("model_id"):
            continue
        if candidate.get("model_family") != worker.get("model_family"):
            return candidate
    return next(
        (candidate for candidate in decision.get("ranked", []) if candidate.get("model_id") != worker.get("model_id")),
        None,
    )


def _record_evaluation(store: IntelligenceStore, evaluation: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    event = record_event(store, evaluation["event_for_registry"], project_id=project_id)
    rebuild_patterns(store)
    rebuild_projections(store)
    return event


def route_and_dispatch(
    root: Path,
    task: dict[str, Any],
    contract: dict[str, Any],
    *,
    agent_name: str | None = None,
    backend: str = "auto",
    timeout: float = 900.0,
    max_attempts: int = 2,
    allow_commands: bool = False,
    codex_bin: str = "codex",
    persist_session: bool = False,
    human_feedback: dict[str, Any] | None = None,
    random_seed: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    if max_attempts < 1 or max_attempts > 4:
        raise DispatchContractError("max_attempts must be between 1 and 4")
    if timeout <= 0:
        raise DispatchContractError("timeout must be positive")
    contract = validate_contract(task, contract)
    max_minutes = (contract.get("budget") or {}).get("max_minutes")
    deadline = time.monotonic() + float(max_minutes) * 60.0 if max_minutes else None
    task = _preflight_execution_arms(root, dict(contract["task"]))
    contract["task"] = task
    parent_depth = int(os.environ.get("ROPS_WORKER_DEPTH", "0") or 0)
    if parent_depth > 0:
        raise DispatchContractError("worker sessions cannot start descendants; return a decomposition request to the Lead")
    store = IntelligenceStore(root, read_only=dry_run)
    if not dry_run:
        models.sync_registry(store)
    decision = recommend(store, task, agent_name=agent_name, write=not dry_run, random_seed=random_seed)
    contract["project_id"] = decision["project_id"]
    run_id = f"{_safe_slug(contract['task_id'])}-{uuid.uuid4().hex[:10]}"
    state_dir = store.layout.state / "runs" / run_id
    artifact_dir = store.layout.artifacts / "dispatches" / run_id
    if dry_run:
        registry = _models(root)
        candidate = decision["primary"]
        model = registry.get(str(candidate.get("model_id"))) or {}
        try:
            models.validate_execution_arm_identity(model)
        except ValueError as exc:
            raise DispatchContractError(str(exc)) from exc
        selected = _backend(candidate, model, backend)
        item = {
            "model_id": candidate.get("model_id"),
            "provider": candidate.get("provider"),
            "reasoning_effort": candidate.get("reasoning_effort"),
            "backend": selected,
        }
        if selected == "codex":
            item["command"] = build_codex_command(
                root,
                _candidate_for_contract(candidate, contract),
                model,
                artifact_dir / "attempt-1" / "last-message.txt",
                codex_bin=codex_bin,
                persist_session=persist_session,
                worker_controls={
                    "ROPS_WORKER_DEPTH": str(parent_depth + 1),
                    "ROPS_PARENT_DISPATCH_ID": "dry-run",
                    "ROPS_DESCENDANT_GRANT": "1"
                    if contract["delegation"].get("may_spawn_descendants")
                    and int(contract["delegation"].get("remaining_depth", 0)) > 0
                    else "0",
                    "ROPS_DELEGATION_REMAINING": str(contract["delegation"].get("remaining_depth", 0)),
                },
            )
        return {
            "schema_version": 1,
            "dry_run": True,
            "decision": decision,
            "planned_attempts": [item],
            "bounded_reroute_attempts": max_attempts,
            "secrets_exposed": False,
            "state_written": False,
        }

    state_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.chmod(0o700)
    atomic_json(state_dir / "route.json", decision)
    attempts: list[dict[str, Any]] = []
    attempt_evaluations: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = [decision]
    completed: dict[str, Any] | None = None
    completed_candidate: dict[str, Any] | None = None
    completed_decision: dict[str, Any] | None = None
    failed_arms: list[str] = []
    reroute_error: str | None = None
    current_decision = decision
    for index in range(1, max_attempts + 1):
        remaining_seconds = deadline - time.monotonic() if deadline is not None else timeout
        if remaining_seconds <= 0:
            reroute_error = "contract max_minutes budget exhausted before the next attempt"
            break
        candidate = current_decision["primary"]
        attempt_contract = {
            **contract,
            "route_decision_id": current_decision["decision_id"],
            "selection_probability": current_decision["selection_probability"],
        }
        attempt_dir = artifact_dir / f"attempt-{index}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        result = dispatch_candidate(
            root,
            store,
            candidate,
            attempt_contract,
            attempt_dir,
            backend=backend,
            timeout=min(timeout, remaining_seconds),
            codex_bin=codex_bin,
            persist_session=persist_session,
            worker_depth=parent_depth + 1,
            parent_dispatch_id=os.environ.get("ROPS_PARENT_DISPATCH_ID") or None,
        )
        result["fallback_attempt"] = index
        _private_json(attempt_dir / "result.json", result)
        attempts.append(result)
        if not result.get("infrastructure_failure"):
            completed, completed_candidate = result, candidate
            completed_decision = current_decision
            break
        failed_evaluation = evaluate(
            root,
            attempt_contract,
            result,
            None,
            human_feedback,
            allow_commands,
            deadline,
        )
        failed_event = _record_evaluation(store, failed_evaluation, project_id=current_decision["project_id"])
        failed_evaluation["recorded_event_id"] = failed_event["event_id"]
        atomic_json(state_dir / f"attempt-{index}-evaluation.json", failed_evaluation)
        attempt_evaluations.append(failed_evaluation)
        failed_arms.append(result["execution_arm_id"])
        if result.get("provider_failure_scope") == "endpoint":
            failed_model = _models(root).get(str(result.get("execution_arm_id"))) or {}
            failed_endpoint = str(failed_model.get("endpoint_id") or failed_model.get("base_url") or "")
            if failed_endpoint:
                failed_arms.extend(
                    arm_id
                    for arm_id, arm in _models(root).items()
                    if str(arm.get("endpoint_id") or arm.get("base_url") or "") == failed_endpoint
                )
                failed_arms = sorted(set(failed_arms))
        if index < max_attempts:
            if deadline is not None and time.monotonic() >= deadline:
                reroute_error = "contract max_minutes budget exhausted after infrastructure failure"
                break
            reroute_task = {
                **task,
                "execution_arm_denylist": sorted(set(task.get("execution_arm_denylist", [])) | set(failed_arms)),
                "parent_route_decision_id": current_decision["decision_id"],
                "fallback_reason": "infrastructure-failure",
            }
            try:
                current_decision = recommend(
                    store,
                    reroute_task,
                    agent_name=agent_name,
                    write=True,
                    random_seed=random_seed,
                )
                decisions.append(current_decision)
            except ValueError as exc:
                reroute_error = str(exc)
                break

    if completed is None or completed_candidate is None or completed_decision is None:
        summary = {
            "schema_version": 1,
            "status": "failed",
            "run_id": run_id,
            "route_decision_ids": [item["decision_id"] for item in decisions],
            "selected_arm": decision["primary"]["model_id"],
            "reroute_error": reroute_error,
            "attempts": [
                {
                    "arm_id": item["execution_arm_id"],
                    "backend": item["backend"],
                    "status": item["status"],
                    "error_class": item.get("error_class"),
                    "event_id": attempt_evaluations[index].get("recorded_event_id") if index < len(attempt_evaluations) else None,
                }
                for index, item in enumerate(attempts)
            ],
            "artifacts_root": _relative(root, artifact_dir),
            "secrets_exposed": False,
        }
        atomic_json(state_dir / "summary.json", summary)
        return summary

    final_attempt = len(attempts)
    final_dir = artifact_dir / f"attempt-{final_attempt}"
    requires_verifier = bool(
        contract.get("requires_independent_verifier")
        or completed_decision.get("verification_policy", {}).get("independent_required")
    )
    evaluation_contract = {
        **contract,
        "route_decision_id": completed_decision["decision_id"],
        "selection_probability": completed_decision["selection_probability"],
    }
    evaluation_contract["requires_independent_verifier"] = requires_verifier
    verifier_data: dict[str, Any] | None = None
    verifier_result: dict[str, Any] | None = None
    verifier_decision: dict[str, Any] | None = None
    if requires_verifier and backend != "gateway" and (deadline is None or time.monotonic() < deadline):
        verifier_task = {
            **task,
            "task_id": f"{contract['task_id']}-verify",
            "objective": f"Independently verify {contract['task_id']}",
            "operation": "validate",
            "mutability": "read-only",
            "shared_mutable_state": False,
            "model_family_allowlist": [],
            "reasoning_effort": None,
            "min_reasoning_effort": None,
            "max_reasoning_effort": None,
            "execution_arm_denylist": sorted(set(failed_arms + [completed["execution_arm_id"]])),
            "parent_route_decision_id": completed_decision["decision_id"],
        }
        try:
            verifier_decision = recommend(
                store,
                verifier_task,
                agent_name="independent_verifier",
                write=True,
                random_seed=random_seed,
            )
        except ValueError:
            verifier_decision = None
        # Artifact verification requires a real Codex/tool session. Direct text
        # gateways cannot read the contract, result, patch, or project files.
        while verifier_decision:
            verifier_candidate = verifier_decision["primary"]
            verifier_model = _models(root).get(str(verifier_candidate.get("model_id"))) or {}
            if (
                _backend(verifier_candidate, verifier_model, "auto") == "codex"
                and str(verifier_model.get("provider") or "") == "codex-native"
            ):
                break
            verifier_task["execution_arm_denylist"] = sorted(
                set(verifier_task.get("execution_arm_denylist", [])) | {str(verifier_candidate.get("model_id"))}
            )
            try:
                verifier_decision = recommend(
                    store,
                    verifier_task,
                    agent_name="independent_verifier",
                    write=True,
                    random_seed=random_seed,
                )
            except ValueError:
                verifier_decision = None
        if verifier_decision:
            verifier_candidate = verifier_decision["primary"]
            verifier_contract = {
                **contract,
                "task_id": f"{contract['task_id']}-verify",
                "objective": f"Independently verify {contract['task_id']}",
                "task": verifier_task,
                "delegation": {"may_spawn_descendants": False, "remaining_depth": 0},
                "route_decision_id": verifier_decision["decision_id"],
                "selection_probability": verifier_decision["selection_probability"],
                "artifact_verifier": True,
                "inputs": [],
            }
            verifier_dir = artifact_dir / "verifier"
            verifier_dir.mkdir(parents=True, exist_ok=True)
            verifier_prompt = _verifier_prompt(
                final_dir / "contract.json",
                final_dir / "result.json",
                root,
                str(completed.get("patch_path") or "") or None,
            )
            # The verifier dispatch gets a frozen prompt as its objective, while its own
            # synthetic completion check is not used to accept the primary worker.
            verifier_contract["objective"] = verifier_prompt
            verifier_contract["acceptance_tests"] = [
                {"name": "verifier completed", "type": "json_path_equals", "source": "result", "json_path": "status", "expected": "complete"}
            ]
            verifier_result = dispatch_candidate(
                root,
                store,
                verifier_candidate,
                verifier_contract,
                verifier_dir,
                backend="codex",
                timeout=min(timeout, max(0.1, deadline - time.monotonic())) if deadline is not None else timeout,
                codex_bin=codex_bin,
                persist_session=False,
                worker_depth=parent_depth + 1,
                parent_dispatch_id=completed["dispatch_id"],
            )
            _private_json(verifier_dir / "result.json", verifier_result)
            if not verifier_result.get("infrastructure_failure"):
                try:
                    verifier_data = _normalize_verifier(
                        _extract_json_object(str(verifier_result.get("output_text") or "")),
                        verifier_candidate,
                        float(contract.get("minimum_verified_quality", 0.8)),
                    )
                except Exception as exc:
                    verifier_result["verifier_parse_error"] = f"{type(exc).__name__}: {exc}"
            _private_json(verifier_dir / "verifier.json", verifier_data or {"independent": False})

    verification_failure = bool(requires_verifier and verifier_data is None)
    evaluation_result = {
        **completed,
        "verification_infrastructure_failure": verification_failure,
    }
    command_checks_requested = bool(
        allow_commands
        and any(test.get("type") == "command_exit_zero" for test in evaluation_contract.get("acceptance_tests", []))
    )
    evaluation_workspace = _materialize_evaluation_worktree(root, completed)
    if command_checks_requested and evaluation_workspace is None:
        try:
            evaluation_workspace = _create_isolated_worktree(root)
        except Exception as exc:
            evaluation_result["acceptance_harness_failure"] = True
            evaluation_result["acceptance_harness_error"] = f"{type(exc).__name__}: {exc}"
    evaluation_root = evaluation_workspace[0] if evaluation_workspace else root
    evaluation_files_before_checks = _filesystem_paths(evaluation_root) if evaluation_workspace else set()
    evaluation_git_before_checks = _git_metadata_fingerprint(evaluation_root) if evaluation_workspace else None
    evaluation_result["acceptance_command_sandboxed"] = bool(evaluation_workspace)
    try:
        final_evaluation = evaluate(
            evaluation_root,
            evaluation_contract,
            evaluation_result,
            verifier_data,
            human_feedback,
            allow_commands,
            deadline,
        )
        if (
            command_checks_requested
            and evaluation_workspace
            and evaluation_git_before_checks is not None
            and _git_metadata_fingerprint(evaluation_root) != evaluation_git_before_checks
        ):
            evaluation_result["acceptance_harness_failure"] = True
            evaluation_result["acceptance_harness_error"] = (
                "an acceptance command modified disposable-clone Git metadata"
            )
            final_evaluation = evaluate(
                evaluation_root,
                evaluation_contract,
                evaluation_result,
                verifier_data,
                human_feedback,
                False,
                deadline,
            )
        elif (
            command_checks_requested
            and evaluation_workspace
            and not completed.get("workspace_isolated")
            and (
                _git_changed_paths(evaluation_root)
                or _filesystem_paths(evaluation_root) != evaluation_files_before_checks
            )
        ):
            evaluation_result["acceptance_harness_failure"] = True
            evaluation_result["acceptance_harness_error"] = (
                "a read-only acceptance command modified its disposable snapshot"
            )
            final_evaluation = evaluate(
                evaluation_root,
                evaluation_contract,
                evaluation_result,
                verifier_data,
                human_feedback,
                False,
                deadline,
            )
        elif completed.get("workspace_isolated") and not _evaluation_state_matches_patch(
            root,
            evaluation_root,
            completed,
            evaluation_files_before_checks,
        ):
            evaluation_result["integration_infrastructure_failure"] = True
            evaluation_result["integration_error"] = (
                "acceptance checks modified the evaluated workspace; the tested state no longer equals the worker patch"
            )
            final_evaluation = evaluate(
                evaluation_root,
                evaluation_contract,
                evaluation_result,
                verifier_data,
                human_feedback,
                False,
                deadline,
            )
        elif final_evaluation["accepted"] and completed.get("workspace_isolated"):
            try:
                _apply_accepted_patch(root, completed)
            except Exception as exc:
                evaluation_result["integration_infrastructure_failure"] = True
                evaluation_result["integration_error"] = f"{type(exc).__name__}: {exc}"
                final_evaluation = evaluate(
                    evaluation_root,
                    evaluation_contract,
                    evaluation_result,
                    verifier_data,
                    human_feedback,
                    allow_commands,
                    deadline,
                )
    finally:
        if evaluation_workspace:
            _remove_isolated_worktree(root, evaluation_workspace[0], evaluation_workspace[1])
    final_event = _record_evaluation(store, final_evaluation, project_id=completed_decision["project_id"])
    final_evaluation["recorded_event_id"] = final_event["event_id"]
    atomic_json(state_dir / "evaluation.json", final_evaluation)
    summary = {
        "schema_version": 1,
        "status": "accepted" if final_evaluation["accepted"] else "rejected",
        "run_id": run_id,
        "route_decision_id": completed_decision["decision_id"],
        "route_decision_ids": [item["decision_id"] for item in decisions],
        "selected_arm": decision["primary"]["model_id"],
        "executed_arm": completed["execution_arm_id"],
        "fallback_used": completed["execution_arm_id"] != decision["primary"]["model_id"],
        "worker_session_id": completed.get("worker_session_id"),
        "worker_session_persisted": completed.get("persisted_session", False),
        "verifier_arm": (verifier_result or {}).get("execution_arm_id"),
        "verifier_route_decision_id": (verifier_decision or {}).get("decision_id"),
        "accepted": final_evaluation["accepted"],
        "disposition": final_evaluation["disposition"],
        "quality": final_evaluation["quality"],
        "event_id": final_event["event_id"],
        "attempts": [
            {
                "arm_id": item["execution_arm_id"],
                "backend": item["backend"],
                "status": item["status"],
                "infrastructure_failure": item["infrastructure_failure"],
                "worker_session_id": item.get("worker_session_id"),
            }
            for item in attempts
        ],
        "artifacts_root": _relative(root, artifact_dir),
        "secrets_exposed": False,
    }
    atomic_json(state_dir / "summary.json", summary)
    return summary
