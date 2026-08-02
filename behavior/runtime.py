from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MODES = {"off", "observe", "guide", "enforce"}

TASK_SIGNALS: dict[str, tuple[str, ...]] = {
    "coding": (
        "implement", "code", "coding", "bug", "fix", "refactor", "function", "class", "module",
        "script", "api", "feature", "dependency", "test", "benchmark", "parser", "compile",
        "实现", "代码", "修复", "重构", "函数", "脚本", "测试", "编译", "依赖",
    ),
    "research": (
        "research", "survey", "paper", "experiment", "hypothesis", "related work", "novelty",
        "route", "evaluation", "result", "baseline", "ablation", "literature", "method",
        "研究", "调研", "论文", "实验", "假设", "相关工作", "创新", "路线", "评估", "结果", "消融",
    ),
    "writing": (
        "write", "writing", "manuscript", "paper section", "latex", "abstract", "introduction",
        "revision", "reviewer", "rebuttal", "caption", "draft", "polish",
        "写作", "撰写", "论文修改", "摘要", "引言", "审稿", "回复", "润色", "图注",
    ),
    "hardware": (
        "hardware", "device", "firmware", "flash", "serial", "jlink", "openocd", "nrfjprog",
        "power", "ppk", "instrument", "relay", "board", "usb", "gpio",
        "硬件", "设备", "固件", "烧录", "串口", "供电", "仪器", "开发板",
    ),
    "hygiene": (
        "cleanup", "clean up", "archive", "delete", "purge", "obsolete", "stale", "worktree",
        "large log", "raw data", "temporary test", "remove old", "repository hygiene",
        "清理", "归档", "删除", "过时", "旧文件", "临时测试", "大日志", "原始数据", "精简",
    ),
    "delegation": (
        "subagent", "sub-agent", "delegate", "worker", "parallel agent", "agent routing",
        "model routing", "weak model", "third-party model", "multi-agent",
        "子代理", "子 agent", "委派", "并行 agent", "模型路由", "弱模型", "第三方模型", "多智能体",
    ),
}

DESTRUCTIVE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("destructive-delete", r"(?:^|[;&|\s])rm\s+(?:-[A-Za-z]*r[A-Za-z]*f|-[A-Za-z]*f[A-Za-z]*r)\b"),
    ("destructive-delete", r"\bfind\b[^\n]*(?:-delete|\bxargs\s+rm\b)"),
    ("destructive-delete", r"\b(?:del|erase)\s+/[sq]\b"),
    ("destructive-delete", r"\bRemove-Item\b[^\n]*-(?:Recurse|Force)"),
    ("git-destructive", r"\bgit\s+reset\s+--hard\b"),
    ("git-destructive", r"\bgit\s+clean\s+-[A-Za-z]*[fdx][A-Za-z]*\b"),
    ("git-destructive", r"\bgit\s+branch\s+-D\b"),
    ("worktree-remove", r"\bgit\s+worktree\s+remove\b"),
    ("hardware-write", r"\b(?:nrfjprog|JLinkExe|JLinkCommander|openocd|pyocd|dfu-util|esptool(?:\.py)?|west)\b[^\n]*(?:flash|program|erase|reset|recover|write|load)"),
    ("hardware-write", r"\badb\b[^\n]*(?:reboot\s+bootloader|sideload|push\s+[^\n]+/(?:sys|system|vendor))"),
)

DEPENDENCY_PATTERN = re.compile(
    r"\b(?:pip(?:3)?\s+install|uv\s+add|poetry\s+add|npm\s+(?:install|i)|pnpm\s+add|yarn\s+add|cargo\s+add|go\s+get)\b",
    re.I,
)

EXTERNAL_SEND_PATTERN = re.compile(
    r"\b(?:curl|wget|httpie|requests\.(?:post|put)|openai|anthropic|litellm)\b", re.I
)
SENSITIVE_PATTERN = re.compile(
    r"(?:\.env\b|id_rsa|credentials|secret|api[_-]?key|token\b|private[_-]?key|\.pem\b|\.research/(?:raw|evidence|runs))",
    re.I,
)

POLICY_BYPASS_PATTERN = re.compile(
    r"(?:\b(?:rwt|rops)\b[^\n]*\bbehavior\b[^\n]*\bapprove\b|"
    r"\bcreate_approval\b|\.research[\\/]+runtime[\\/]+approvals\.json)",
    re.I,
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: float = 3.0, stale_seconds: float = 30.0):
    """Small cross-platform lock for approval state transitions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, f"{os.getpid()} {utc_now()}\n".encode("utf-8"))
            os.close(descriptor)
        except FileExistsError:
            try:
                if time.time() - path.stat().st_mtime > stale_seconds:
                    path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError(f"timed out waiting for runtime lock: {path}")
            time.sleep(0.025)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def behavior_root(runtime_root: Path | None = None) -> Path:
    if runtime_root:
        return runtime_root.resolve()
    return Path(__file__).resolve().parent


def load_registry(runtime_root: Path | None = None) -> dict[str, Any]:
    root = behavior_root(runtime_root)
    return _read_json(root / "registry.json", {})


def load_packs(runtime_root: Path | None = None) -> dict[str, dict[str, Any]]:
    root = behavior_root(runtime_root)
    packs: dict[str, dict[str, Any]] = {}
    for path in sorted((root / "packs").glob("*.json")):
        data = _read_json(path, {})
        if data.get("id"):
            packs[data["id"]] = data
    return packs


def _project_root(payload: dict[str, Any], explicit_root: Path | None = None) -> Path:
    if explicit_root:
        return explicit_root.resolve()
    cwd = Path(payload.get("cwd") or os.environ.get("GEMINI_PROJECT_DIR") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).resolve()
    current = cwd
    for candidate in (current, *current.parents):
        if (candidate / ".research").exists() or (candidate / ".git").exists():
            return candidate
    return cwd


def _runtime_dir(project_root: Path) -> Path:
    return project_root / ".research" / "runtime"


def current_mode(project_root: Path, payload: dict[str, Any], registry: dict[str, Any]) -> str:
    requested = payload.get("behavior_mode") or os.environ.get("RESEARCHOPS_BEHAVIOR_MODE")
    if requested in MODES:
        return str(requested)
    state = _read_json(_runtime_dir(project_root) / "config.json", {})
    mode = state.get("mode") or registry.get("default_mode", "guide")
    return mode if mode in MODES else "guide"


def set_mode(project_root: Path, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"invalid mode: {mode}")
    path = _runtime_dir(project_root) / "config.json"
    state = _read_json(path, {})
    state.update({"schema_version": 1, "mode": mode, "updated_at": utc_now()})
    _write_json(path, state)
    return state


def _extract_text(payload: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("prompt", "user_prompt", "message", "task", "query"):
        value = payload.get(key)
        if isinstance(value, str):
            values.append(value)
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("command", "patch", "content", "path", "file_path", "description"):
            value = tool_input.get(key)
            if isinstance(value, str):
                values.append(value)
    elif isinstance(tool_input, str):
        values.append(tool_input)
    return "\n".join(values)


def classify(payload: dict[str, Any]) -> list[str]:
    explicit = payload.get("task_class")
    if isinstance(explicit, str) and explicit in TASK_SIGNALS:
        return [explicit]
    if isinstance(explicit, list):
        selected = [str(item) for item in explicit if str(item) in TASK_SIGNALS]
        if selected:
            return sorted(set(selected))
    text = _extract_text(payload).lower()
    event = str(payload.get("hook_event_name") or "")
    tool_name = str(payload.get("tool_name") or "").lower()
    agent_type = str(payload.get("agent_type") or payload.get("agent_name") or "").lower()
    scores: dict[str, int] = {}
    for task_class, terms in TASK_SIGNALS.items():
        score = sum(1 for term in terms if term.lower() in text)
        if score:
            scores[task_class] = score
    if tool_name in {"bash", "apply_patch", "edit", "write", "run_shell_command", "write_file", "replace"}:
        scores["coding"] = scores.get("coding", 0) + 1
    if event.lower() in {"subagentstart", "subagent_start"} or "agent" in agent_type:
        scores["delegation"] = scores.get("delegation", 0) + 2
    for kind, pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, text, re.I):
            scores["hardware" if kind == "hardware-write" else "hygiene"] = scores.get("hardware" if kind == "hardware-write" else "hygiene", 0) + 3
    if not scores:
        return ["general"]
    maximum = max(scores.values())
    threshold = max(1, maximum - 1)
    return sorted(task_class for task_class, score in scores.items() if score >= threshold)


def _active_packs(task_classes: list[str], payload: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    result: list[str] = []
    mapping = registry.get("task_pack_map", {})
    for task_class in task_classes:
        result.extend(mapping.get(task_class, []))
    active_skill = payload.get("active_skill")
    if isinstance(active_skill, str):
        result.extend(registry.get("skill_pack_map", {}).get(active_skill, []))
    return list(dict.fromkeys(result))


def _command(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("command", "patch", "content"):
            if isinstance(tool_input.get(key), str):
                return tool_input[key]
    return tool_input if isinstance(tool_input, str) else ""


def risk_findings(payload: dict[str, Any]) -> list[dict[str, str]]:
    event = str(payload.get("hook_event_name") or "").lower()
    if event not in {"pretooluse", "beforetool", "permissionrequest"}:
        return []
    command = _command(payload)
    findings: list[dict[str, str]] = []
    if POLICY_BYPASS_PATTERN.search(command):
        findings.append({"kind": "policy-bypass", "reason": "an Agent tool attempted to create or modify its own runtime approval"})
    for kind, pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, command, re.I):
            findings.append({"kind": kind, "reason": f"deterministic high-risk pattern matched: {kind}"})
    if EXTERNAL_SEND_PATTERN.search(command) and SENSITIVE_PATTERN.search(command):
        findings.append({"kind": "external-sensitive-transfer", "reason": "external transfer appears to reference sensitive or research-state material"})
    dedup: dict[str, dict[str, str]] = {item["kind"]: item for item in findings}
    return list(dedup.values())


def _approval_fingerprint(kind: str, command: str) -> str:
    return _hash_text(kind + "\n" + _normalize(command))


def _parse_time(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def create_approval(project_root: Path, kind: str, command: str, reason: str, ttl_minutes: int = 30) -> dict[str, Any]:
    registry = load_registry()
    if kind == "policy-bypass" or kind not in registry.get("hard_risk_kinds", []):
        raise ValueError(f"unsupported approval kind: {kind}")
    if not command.strip():
        raise ValueError("approval must bind to a non-empty exact command")
    if not reason.strip():
        raise ValueError("approval requires a human-readable reason")
    if ttl_minutes < 1 or ttl_minutes > 1440:
        raise ValueError("approval TTL must be between 1 and 1440 minutes")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    item = {
        "id": "apv-" + _hash_text(f"{kind}|{command}|{now.isoformat()}")[:12],
        "kind": kind,
        "command_sha256": _hash_text(_normalize(command)),
        "fingerprint": _approval_fingerprint(kind, command),
        "reason": reason,
        "created_at": now.isoformat(),
        "expires_at": (now + dt.timedelta(minutes=ttl_minutes)).isoformat(),
        "status": "approved",
        "consumed_at": None,
    }
    path = _runtime_dir(project_root) / "approvals.json"
    with _exclusive_lock(path.with_suffix(".lock")):
        state = _read_json(path, {"schema_version": 1, "approvals": []})
        state.setdefault("approvals", []).append(item)
        _write_json(path, state)
    return item


def _consume_approval(project_root: Path, kind: str, command: str) -> dict[str, Any] | None:
    if kind == "policy-bypass":
        return None
    path = _runtime_dir(project_root) / "approvals.json"
    expected = _approval_fingerprint(kind, command)
    now = dt.datetime.now(dt.timezone.utc)
    consumed: dict[str, Any] | None = None
    with _exclusive_lock(path.with_suffix(".lock")):
        state = _read_json(path, {"schema_version": 1, "approvals": []})
        for item in state.get("approvals", []):
            if item.get("status") != "approved" or item.get("fingerprint") != expected:
                continue
            expires = _parse_time(item.get("expires_at", ""))
            if not expires or expires < now:
                item["status"] = "expired"
                continue
            item["status"] = "consumed"
            item["consumed_at"] = utc_now()
            consumed = item
            break
        _write_json(path, state)
    return consumed


def _session_key(payload: dict[str, Any]) -> str:
    for name in ("session_id", "thread_id", "conversation_id"):
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return _hash_text(name + ":" + value)[:20]
    return "project-default"


def _remember_active_context(project_root: Path, payload: dict[str, Any], task_classes: list[str], active_packs: list[str]) -> None:
    path = _runtime_dir(project_root) / "active-context.json"
    key = _session_key(payload)
    with _exclusive_lock(path.with_suffix(".lock")):
        state = _read_json(path, {"schema_version": 1, "sessions": {}})
        sessions = state.setdefault("sessions", {})
        sessions[key] = {
            "task_classes": [item for item in task_classes if item != "general"],
            "active_packs": active_packs,
            "updated_at": utc_now(),
        }
        # Bound state growth without persisting any prompt text.
        if len(sessions) > 64:
            ordered = sorted(sessions.items(), key=lambda item: item[1].get("updated_at", ""), reverse=True)[:64]
            state["sessions"] = dict(ordered)
        _write_json(path, state)


def _inherited_active_context(project_root: Path, payload: dict[str, Any], max_age_minutes: int = 30) -> tuple[list[str], list[str]]:
    path = _runtime_dir(project_root) / "active-context.json"
    state = _read_json(path, {"sessions": {}})
    item = state.get("sessions", {}).get(_session_key(payload), {})
    updated = _parse_time(item.get("updated_at", ""))
    if not updated or dt.datetime.now(dt.timezone.utc) - updated > dt.timedelta(minutes=max_age_minutes):
        return [], []
    return list(item.get("task_classes", [])), list(item.get("active_packs", []))


def _context(registry: dict[str, Any], packs: dict[str, dict[str, Any]], active: list[str], mode: str, findings: list[dict[str, str]], dependency_change: bool) -> str:
    if mode not in {"guide", "enforce"}:
        return ""
    lines = ["[ResearchOps Behavior Runtime]", "Kernel:"]
    lines.extend(f"- {item}" for item in registry.get("kernel", []))
    if active:
        lines.append("Active task behavior:")
        for pack_id in active:
            pack = packs.get(pack_id, {})
            if pack.get("summary"):
                lines.append(f"- {pack_id}: {pack['summary']}")
            for instruction in pack.get("instructions", [])[:4]:
                lines.append(f"  - {instruction}")
    if dependency_change:
        lines.append("- Dependency change detected: first show why existing code, stdlib, platform, or installed dependencies are insufficient.")
    if findings:
        kinds = ", ".join(item["kind"] for item in findings)
        lines.append(f"- Consequential action detected ({kinds}). Propose the specialist workflow and obtain its operational approval before retrying.")
    text = "\n".join(lines)
    return text[:3800]


def evaluate(payload: dict[str, Any], framework: str = "portable", runtime_root: Path | None = None, explicit_project_root: Path | None = None, record: bool = True) -> dict[str, Any]:
    registry = load_registry(runtime_root)
    packs = load_packs(runtime_root)
    project_root = _project_root(payload, explicit_project_root)
    mode = current_mode(project_root, payload, registry)
    task_classes = classify(payload)
    active = _active_packs(task_classes, payload, registry)
    event = str(payload.get("hook_event_name") or "")
    event_lower = event.lower()
    if event_lower in {"subagentstart", "subagent_start"}:
        inherited_classes, inherited_packs = _inherited_active_context(project_root, payload)
        task_classes = list(dict.fromkeys([*inherited_classes, *task_classes]))
        active = list(dict.fromkeys([*inherited_packs, *active]))
    elif event_lower in {"userpromptsubmit", "beforeagent"}:
        _remember_active_context(project_root, payload, task_classes, active)
    findings = risk_findings(payload)
    command = _command(payload)
    approved: list[str] = []
    remaining: list[dict[str, str]] = []
    for finding in findings:
        item = _consume_approval(project_root, finding["kind"], command) if mode == "enforce" else None
        if item:
            approved.append(finding["kind"])
        else:
            remaining.append(finding)
    dependency_change = bool(event_lower in {"pretooluse", "beforetool"} and DEPENDENCY_PATTERN.search(command))
    decision = "allow"
    reason = ""
    if mode == "enforce" and remaining:
        decision = "deny"
        reason = "Blocked by ResearchOps Behavior Runtime: " + "; ".join(item["reason"] for item in remaining) + ". Create a content-bound approval or use the specialist workflow."
    context = _context(registry, packs, active, mode, remaining, dependency_change)
    proposals = [
        {
            "kind": item["kind"],
            "proposal_only": True,
            "executed": False,
            "reason": item["reason"],
        }
        for item in remaining
    ]
    result = {
        "schema_version": 1,
        "framework": framework,
        "event": event,
        "mode": mode,
        "decision": decision,
        "reason": reason,
        "task_classes": task_classes,
        "active_packs": active,
        "additional_context": context,
        "proposals": proposals,
        "approvals_consumed": approved,
        "project_root": str(project_root),
    }
    if record and mode != "off":
        text = _extract_text(payload)
        event_record = {
            "timestamp": utc_now(),
            "framework": framework,
            "event": event,
            "mode": mode,
            "decision": decision,
            "task_classes": task_classes,
            "active_packs": active,
            "risk_kinds": [item["kind"] for item in remaining],
            "approvals_consumed": approved,
            "input_sha256": _hash_text(text) if text else None,
            "input_chars": len(text),
            "raw_input_logged": False,
        }
        _append_jsonl(_runtime_dir(project_root) / "events.jsonl", event_record)
    return result


def render_hook_output(result: dict[str, Any], framework: str, event: str) -> dict[str, Any]:
    decision = result.get("decision")
    context = result.get("additional_context") or ""
    reason = result.get("reason") or ""
    event_lower = event.lower()
    if framework == "gemini":
        output: dict[str, Any] = {}
        if decision == "deny":
            output.update({"decision": "deny", "reason": reason})
        elif context and event_lower in {"beforeagent", "sessionstart", "aftertool"}:
            output["hookSpecificOutput"] = {"additionalContext": context}
        elif context and event_lower == "beforetool":
            output["systemMessage"] = context[:1200]
        return output
    if decision == "deny" and event_lower in {"pretooluse", "permissionrequest"}:
        return {
            "hookSpecificOutput": {
                "hookEventName": event,
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    if context and event_lower in {"userpromptsubmit", "sessionstart", "subagentstart", "pretooluse"}:
        return {"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}
    return {}
