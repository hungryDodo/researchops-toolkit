from __future__ import annotations

import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

MODES = {"off", "observe", "guide", "enforce"}
SEMANTIC_MODES = {"off", "advisory", "required"}
SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}

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

DEPENDENCY_PATTERN = re.compile(
    r"\b(?:pip(?:3)?\s+install|uv\s+add|poetry\s+add|npm\s+(?:install|i)|pnpm\s+add|yarn\s+add|cargo\s+add|go\s+get)\b",
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
    return runtime_root.resolve() if runtime_root else Path(__file__).resolve().parent


def _load_local_module(filename: str, runtime_root: Path | None = None):
    root = behavior_root(runtime_root)
    path = root / filename
    module_name = "_rops_" + path.stem + "_" + _hash_text(str(path))[:12]
    existing = sys.modules.get(module_name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(module_name, path)
    if not spec or not spec.loader:
        raise RuntimeError(f"cannot load behavior module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_registry(runtime_root: Path | None = None) -> dict[str, Any]:
    return _read_json(behavior_root(runtime_root) / "registry.json", {})


def load_policy(runtime_root: Path | None = None) -> dict[str, Any]:
    return _read_json(behavior_root(runtime_root) / "policies" / "risk-policy.json", {})


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
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".research").exists() or (candidate / ".git").exists():
            return candidate
    return cwd


def _runtime_dir(project_root: Path) -> Path:
    return project_root / ".research" / "runtime"


def current_mode(project_root: Path, payload: dict[str, Any], registry: dict[str, Any]) -> str:
    requested = payload.get("behavior_mode") or os.environ.get("ROPS_BEHAVIOR_MODE")
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
    state.update({"schema_version": 2, "mode": mode, "updated_at": utc_now()})
    _write_json(path, state)
    return state


def set_semantic_review(project_root: Path, mode: str, command: str | None = None, timeout_seconds: int | None = None, scope: str | None = None) -> dict[str, Any]:
    if mode not in SEMANTIC_MODES:
        raise ValueError(f"invalid semantic review mode: {mode}")
    path = _runtime_dir(project_root) / "config.json"
    state = _read_json(path, {})
    semantic = dict(state.get("semantic_review", {}))
    semantic["mode"] = mode
    if command is not None:
        semantic["command"] = command
    if timeout_seconds is not None:
        if timeout_seconds < 1 or timeout_seconds > 120:
            raise ValueError("semantic review timeout must be between 1 and 120 seconds")
        semantic["timeout_seconds"] = timeout_seconds
    if scope is not None:
        if scope not in {"uncertain", "all"}:
            raise ValueError("semantic review scope must be uncertain or all")
        semantic["review_uncertain_only"] = scope == "uncertain"
    state.update({"schema_version": 2, "semantic_review": semantic, "updated_at": utc_now()})
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


def _command(payload: dict[str, Any]) -> str:
    """Return only an actual shell command, never a patch or file body."""
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    if isinstance(tool_input, str) and str(payload.get("tool_name") or "").lower() in {"bash", "shell", "run_shell_command", "execute", "terminal"}:
        return tool_input
    return ""


def _tool_input_text(payload: dict[str, Any]) -> str:
    value = payload.get("tool_input")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            return str(value)
    return ""


def _non_shell_findings(payload: dict[str, Any], project_root: Path, policy: dict[str, Any]) -> list[dict[str, Any]]:
    event = str(payload.get("hook_event_name") or "").lower()
    if event not in {"pretooluse", "beforetool", "permissionrequest"}:
        return []
    tool_name = str(payload.get("tool_name") or "").lower()
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or _command(payload):
        return []
    category = policy.get("categories", {})
    findings: list[dict[str, Any]] = []
    paths = [str(tool_input.get(key) or "") for key in ("path", "file_path", "target", "destination") if tool_input.get(key)]
    normalized = [value.replace("\\", "/").lower() for value in paths]
    protected_runtime = any(
        value.endswith("/.research/runtime/approvals.json")
        or value.endswith("/.research/runtime/config.json")
        or "/.researchops/behavior/" in value
        or value.endswith("/.researchops/hooks/researchops_hook.py")
        for value in normalized
    )
    if protected_runtime:
        meta = category.get("policy-bypass", {})
        findings.append({
            "rule_id": "policy.runtime-file-write", "kind": "policy-bypass",
            "severity": meta.get("severity", "critical"), "confidence": "deterministic",
            "reason": "tool write targets the installed ROPS policy runtime or approval state",
            "evidence": ", ".join(paths)[:600], "approvable": False,
            "specialist": meta.get("specialist", "skill-system-engineering"),
        })
    if tool_name in {"write", "write_file", "edit", "replace"} and any(
        value.startswith("/dev/") or value.startswith("/etc/") or value.startswith("/boot/")
        for value in normalized
    ):
        kind = "block-device-write" if any(value.startswith("/dev/") for value in normalized) else "destructive-overwrite"
        meta = category.get(kind, {})
        findings.append({
            "rule_id": "tool.structured-sensitive-write", "kind": kind,
            "severity": meta.get("severity", "high"), "confidence": "deterministic",
            "reason": "structured file tool writes a device or sensitive absolute path",
            "evidence": ", ".join(paths)[:600], "approvable": meta.get("approvable", True),
            "specialist": meta.get("specialist", "research-engineering"),
        })
    # Generic tools are only escalated when both the tool verb and structured arguments indicate consequence.
    if re.search(r"(?:delete|destroy|purge|drop|force_remove|wipe)", tool_name) and tool_input:
        meta = category.get("destructive-delete", {})
        findings.append({
            "rule_id": "tool.structured-destructive-verb", "kind": "destructive-delete",
            "severity": meta.get("severity", "high"), "confidence": "heuristic",
            "reason": "structured tool name expresses a destructive operation",
            "evidence": tool_name[:200], "approvable": meta.get("approvable", True),
            "specialist": meta.get("specialist", "project-hygiene"),
        })
    return findings


def command_analysis(command: str, project_root: Path, runtime_root: Path | None = None) -> dict[str, Any]:
    analyzer = _load_local_module("shell_analyzer.py", runtime_root)
    return analyzer.analyze_command(command, project_root, load_policy(runtime_root))


def classify(payload: dict[str, Any], runtime_root: Path | None = None, explicit_project_root: Path | None = None) -> list[str]:
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
    command = _command(payload)
    if command and event.lower() in {"pretooluse", "beforetool", "permissionrequest"}:
        analysis = command_analysis(command, _project_root(payload, explicit_project_root), runtime_root)
        for finding in analysis.get("findings", []):
            kind = finding.get("kind")
            if kind in {"hardware-write", "block-device-write", "filesystem-admin", "system-power-control"}:
                scores["hardware"] = scores.get("hardware", 0) + 3
            elif kind in {"destructive-delete", "destructive-overwrite", "worktree-remove", "permission-recursive", "container-destructive"}:
                scores["hygiene"] = scores.get("hygiene", 0) + 3
            else:
                scores["coding"] = scores.get("coding", 0) + 2
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


def risk_findings(payload: dict[str, Any], runtime_root: Path | None = None, explicit_project_root: Path | None = None) -> list[dict[str, Any]]:
    event = str(payload.get("hook_event_name") or "").lower()
    if event not in {"pretooluse", "beforetool", "permissionrequest"}:
        return []
    command = _command(payload)
    if not command.strip():
        return []
    return command_analysis(command, _project_root(payload, explicit_project_root), runtime_root).get("findings", [])


def _approval_fingerprint(kind: str, raw_sha256: str, canonical_sha256: str, rule_ids: list[str]) -> str:
    return _hash_text("\n".join([kind, raw_sha256, canonical_sha256, ",".join(sorted(rule_ids))]))


def _parse_time(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def create_approval(project_root: Path, kind: str, command: str, reason: str, ttl_minutes: int = 30, runtime_root: Path | None = None) -> dict[str, Any]:
    policy = load_policy(runtime_root)
    category = policy.get("categories", {}).get(kind)
    if not category or not category.get("approvable", False):
        raise ValueError(f"unsupported or non-approvable risk kind: {kind}")
    if not command.strip():
        raise ValueError("approval must bind to a non-empty exact command")
    if not reason.strip():
        raise ValueError("approval requires a human-readable reason")
    if ttl_minutes < 1 or ttl_minutes > 1440:
        raise ValueError("approval TTL must be between 1 and 1440 minutes")
    analysis = command_analysis(command, project_root, runtime_root)
    if kind == "semantic-risk":
        reviewer = _load_local_module("semantic_reviewer.py", runtime_root)
        semantic = reviewer.review(command, analysis, project_root, policy)
        semantic_item = _semantic_finding(semantic, policy)
        if semantic_item:
            analysis["findings"] = [*analysis.get("findings", []), semantic_item]
    rule_ids = sorted(item["rule_id"] for item in analysis.get("findings", []) if item.get("kind") == kind)
    if not rule_ids:
        raise ValueError(f"command does not currently produce the requested risk kind: {kind}")
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    item = {
        "id": "apv-" + _hash_text(f"{kind}|{command}|{now.isoformat()}")[:12],
        "kind": kind,
        "raw_command_sha256": analysis["raw_sha256"],
        "canonical_command_sha256": analysis["canonical_sha256"],
        "rule_ids": rule_ids,
        "fingerprint": _approval_fingerprint(kind, analysis["raw_sha256"], analysis["canonical_sha256"], rule_ids),
        "reason": reason,
        "created_at": now.isoformat(),
        "expires_at": (now + dt.timedelta(minutes=ttl_minutes)).isoformat(),
        "status": "approved",
        "consumed_at": None,
    }
    path = _runtime_dir(project_root) / "approvals.json"
    with _exclusive_lock(path.with_suffix(".lock")):
        state = _read_json(path, {"schema_version": 2, "approvals": []})
        state["schema_version"] = 2
        state.setdefault("approvals", []).append(item)
        _write_json(path, state)
    return item


def _consume_approval(project_root: Path, kind: str, analysis: dict[str, Any]) -> dict[str, Any] | None:
    rule_ids = sorted(item["rule_id"] for item in analysis.get("findings", []) if item.get("kind") == kind)
    if not rule_ids:
        return None
    path = _runtime_dir(project_root) / "approvals.json"
    expected = _approval_fingerprint(kind, analysis["raw_sha256"], analysis["canonical_sha256"], rule_ids)
    now = dt.datetime.now(dt.timezone.utc)
    consumed: dict[str, Any] | None = None
    with _exclusive_lock(path.with_suffix(".lock")):
        state = _read_json(path, {"schema_version": 2, "approvals": []})
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
        state = _read_json(path, {"schema_version": 2, "sessions": {}})
        sessions = state.setdefault("sessions", {})
        sessions[key] = {
            "task_classes": [item for item in task_classes if item != "general"],
            "active_packs": active_packs,
            "updated_at": utc_now(),
        }
        if len(sessions) > 64:
            ordered = sorted(sessions.items(), key=lambda item: item[1].get("updated_at", ""), reverse=True)[:64]
            state["sessions"] = dict(ordered)
        _write_json(path, state)


def _inherited_active_context(project_root: Path, payload: dict[str, Any], max_age_minutes: int = 30) -> tuple[list[str], list[str]]:
    state = _read_json(_runtime_dir(project_root) / "active-context.json", {"sessions": {}})
    item = state.get("sessions", {}).get(_session_key(payload), {})
    updated = _parse_time(item.get("updated_at", ""))
    if not updated or dt.datetime.now(dt.timezone.utc) - updated > dt.timedelta(minutes=max_age_minutes):
        return [], []
    return list(item.get("task_classes", [])), list(item.get("active_packs", []))


def _context(registry: dict[str, Any], packs: dict[str, dict[str, Any]], active: list[str], mode: str, findings: list[dict[str, Any]], dependency_change: bool, semantic: dict[str, Any]) -> str:
    if mode not in {"guide", "enforce"}:
        return ""
    lines = ["[ROPS Behavior Runtime]", "Kernel:"]
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
        labels = ", ".join(f"{item['kind']}:{item['severity']}" for item in findings)
        lines.append(f"- Consequential action detected ({labels}). Propose the specialist workflow and obtain its operational approval before retrying.")
    if semantic.get("status") in {"unavailable", "error"} and semantic.get("mode") == "required":
        lines.append("- Required semantic risk review was unavailable; do not infer safety from that failure.")
    return "\n".join(lines)[:4200]


def _semantic_finding(semantic: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
    if semantic.get("status") != "completed" or not isinstance(semantic.get("response"), dict):
        return None
    response = semantic["response"]
    risk = response.get("risk", "none")
    if risk == "none":
        return None
    category = policy.get("categories", {}).get("semantic-risk", {})
    return {
        "rule_id": "semantic.external-review",
        "kind": "semantic-risk",
        "severity": risk,
        "confidence": "semantic",
        "reason": response.get("reason", "semantic reviewer identified consequential risk"),
        "evidence": ", ".join(response.get("categories", []))[:600],
        "approvable": category.get("approvable", True),
        "specialist": category.get("specialist", "research-engineering"),
        "reviewer_confidence": response.get("confidence"),
        "reviewer": response.get("reviewer"),
    }


def _required_semantic_failure(semantic: dict[str, Any], analysis: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any] | None:
    if semantic.get("mode") != "required" or semantic.get("status") not in {"unavailable", "error"}:
        return None
    category = policy.get("categories", {}).get("semantic-review-unavailable", {})
    return {
        "rule_id": "semantic.required-unavailable",
        "kind": "semantic-review-unavailable",
        "severity": category.get("severity", "high"),
        "confidence": "deterministic",
        "reason": "required semantic review did not complete; safety cannot be inferred",
        "evidence": str(semantic.get("error") or semantic.get("status"))[:600],
        "approvable": False,
        "specialist": category.get("specialist", "skill-system-engineering"),
    }


def evaluate(payload: dict[str, Any], framework: str = "portable", runtime_root: Path | None = None, explicit_project_root: Path | None = None, record: bool = True) -> dict[str, Any]:
    registry = load_registry(runtime_root)
    policy = load_policy(runtime_root)
    packs = load_packs(runtime_root)
    project_root = _project_root(payload, explicit_project_root)
    mode = current_mode(project_root, payload, registry)
    task_classes = classify(payload, runtime_root, project_root)
    active = _active_packs(task_classes, payload, registry)
    event = str(payload.get("hook_event_name") or "")
    event_lower = event.lower()
    if event_lower in {"subagentstart", "subagent_start"}:
        inherited_classes, inherited_packs = _inherited_active_context(project_root, payload)
        task_classes = list(dict.fromkeys([*inherited_classes, *task_classes]))
        active = list(dict.fromkeys([*inherited_packs, *active]))
    elif event_lower in {"userpromptsubmit", "beforeagent"}:
        _remember_active_context(project_root, payload, task_classes, active)

    command = _command(payload)
    structured_findings = _non_shell_findings(payload, project_root, policy)
    review_text = command or _tool_input_text(payload)
    if command and event_lower in {"pretooluse", "beforetool", "permissionrequest"}:
        analysis = command_analysis(command, project_root, runtime_root)
    elif structured_findings:
        analysis = {
            "raw_sha256": _hash_text(review_text), "canonical_sha256": _hash_text(review_text),
            "canonical": f"{payload.get('tool_name')}:structured-input", "findings": structured_findings,
            "uncertain": any(item.get("confidence") != "deterministic" for item in structured_findings),
            "needs_semantic_review": any(item.get("confidence") != "deterministic" for item in structured_findings),
            "dynamic_constructs": [], "parse_warnings": [], "invocations": [],
        }
    else:
        analysis = {"raw_sha256": None, "canonical_sha256": None, "canonical": "", "findings": [], "uncertain": False, "needs_semantic_review": False, "dynamic_constructs": [], "parse_warnings": [], "invocations": []}
    if review_text and event_lower in {"pretooluse", "beforetool", "permissionrequest"}:
        reviewer = _load_local_module("semantic_reviewer.py", runtime_root)
        semantic = reviewer.review(review_text, analysis, project_root, policy)
    else:
        semantic = {"mode": "off", "status": "not-applicable", "response": None, "error": None}

    all_findings = list(analysis.get("findings", []))
    semantic_item = _semantic_finding(semantic, policy)
    if semantic_item:
        all_findings.append(semantic_item)
    failure_item = _required_semantic_failure(semantic, analysis, policy)
    if failure_item:
        all_findings.append(failure_item)

    approved: list[str] = []
    remaining: list[dict[str, Any]] = []
    kinds = sorted(set(item["kind"] for item in all_findings))
    consumed_by_kind: dict[str, dict[str, Any] | None] = {}
    if mode == "enforce" and command:
        for kind in kinds:
            category = policy.get("categories", {}).get(kind, {})
            consumed_by_kind[kind] = _consume_approval(project_root, kind, {**analysis, "findings": all_findings}) if category.get("approvable", False) else None
    for finding in all_findings:
        if consumed_by_kind.get(finding["kind"]):
            if finding["kind"] not in approved:
                approved.append(finding["kind"])
        else:
            remaining.append(finding)

    blocking = [item for item in remaining if SEVERITY_ORDER.get(item.get("severity", "high"), 3) >= SEVERITY_ORDER["high"]]
    dependency_change = bool(event_lower in {"pretooluse", "beforetool"} and DEPENDENCY_PATTERN.search(command))
    decision = "allow"
    reason = ""
    if mode == "enforce" and blocking:
        decision = "deny"
        reason = "Blocked by ROPS Behavior Runtime: " + "; ".join(f"{item['rule_id']}: {item['reason']}" for item in blocking) + ". Use the named specialist workflow and an operator-created content-bound approval where allowed."
    context = _context(registry, packs, active, mode, remaining, dependency_change, semantic)
    proposals = [
        {
            "kind": item["kind"],
            "rule_id": item["rule_id"],
            "severity": item["severity"],
            "specialist": item.get("specialist"),
            "approvable": item.get("approvable", False),
            "proposal_only": True,
            "executed": False,
            "reason": item["reason"],
        }
        for item in remaining
    ]
    event_id = "evt-" + _hash_text(f"{utc_now()}|{framework}|{event}|{analysis.get('raw_sha256')}|{os.getpid()}")[:16]
    result = {
        "schema_version": 2,
        "event_id": event_id,
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
        "risk_analysis": {
            "canonical": analysis.get("canonical"),
            "raw_sha256": analysis.get("raw_sha256"),
            "canonical_sha256": analysis.get("canonical_sha256"),
            "invocations": analysis.get("invocations", []),
            "dynamic_constructs": analysis.get("dynamic_constructs", []),
            "parse_warnings": analysis.get("parse_warnings", []),
            "uncertain": analysis.get("uncertain", False),
            "findings": all_findings,
        },
        "semantic_review": semantic,
    }
    if record and mode != "off":
        text = _extract_text(payload)
        event_record = {
            "event_id": event_id,
            "timestamp": utc_now(),
            "framework": framework,
            "event": event,
            "mode": mode,
            "decision": decision,
            "task_classes": task_classes,
            "active_packs": active,
            "risk_kinds": [item["kind"] for item in remaining],
            "risk_rule_ids": [item["rule_id"] for item in remaining],
            "risk_severities": [item["severity"] for item in remaining],
            "approvals_consumed": approved,
            "semantic_status": semantic.get("status"),
            "semantic_risk": (semantic.get("response") or {}).get("risk") if isinstance(semantic.get("response"), dict) else None,
            "input_sha256": _hash_text(text) if text else None,
            "input_chars": len(text),
            "raw_input_logged": False,
        }
        _append_jsonl(_runtime_dir(project_root) / "events.jsonl", event_record)
    return result


def record_feedback(project_root: Path, event_id: str, label: str, note: str = "") -> dict[str, Any]:
    allowed = {"true-positive", "false-positive", "missed-risk", "acceptable-risk", "needs-policy-update"}
    if label not in allowed:
        raise ValueError(f"invalid feedback label: {label}")
    if not event_id.strip():
        raise ValueError("event_id is required")
    item = {"timestamp": utc_now(), "event_id": event_id, "label": label, "note": note[:1200]}
    _append_jsonl(_runtime_dir(project_root) / "feedback.jsonl", item)
    return item


def feedback_report(project_root: Path) -> dict[str, Any]:
    path = _runtime_dir(project_root) / "feedback.jsonl"
    labels: dict[str, int] = {}
    count = 0
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            label = str(item.get("label", "unknown"))
            labels[label] = labels.get(label, 0) + 1
            count += 1
    return {
        "schema_version": 1,
        "feedback_items": count,
        "labels": dict(sorted(labels.items())),
        "policy_learning": "human feedback is recorded for review; runtime rules are never weakened automatically",
        "path": str(path),
    }


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
