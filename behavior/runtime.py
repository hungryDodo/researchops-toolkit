from __future__ import annotations

"""Portable lifecycle behavior runtime.

This module is intentionally thin.  Workflow ownership stays in Skills;
canonical project/model state stays in ``.researchops`` and SQLite; this hook
runtime only classifies applicable cross-cutting packs and evaluates exposed
operations before a Harness executes them.
"""

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

MODES = {"off", "observe", "guide", "enforce"}
TASK_SIGNALS: dict[str, tuple[str, ...]] = {
    "coding": (
        "implement", "code", "coding", "bug", "fix", "refactor", "script", "api", "test", "compile",
        "实现", "代码", "修复", "重构", "脚本", "测试", "编译",
    ),
    "research": (
        "research", "survey", "paper", "experiment", "hypothesis", "related work", "novelty", "ablation",
        "研究", "调研", "论文", "实验", "假设", "相关工作", "创新", "消融",
    ),
    "writing": (
        "write", "manuscript", "latex", "abstract", "introduction", "reviewer", "rebuttal", "caption",
        "写作", "撰写", "摘要", "引言", "审稿", "回复", "图注",
    ),
    "hardware": (
        "hardware", "firmware", "flash", "jlink", "openocd", "nrfjprog", "power", "ppk", "gpio",
        "硬件", "固件", "烧录", "供电", "开发板", "功耗",
    ),
    "hygiene": (
        "cleanup", "archive", "delete", "purge", "obsolete", "worktree", "large log", "repository hygiene",
        "清理", "归档", "删除", "过时", "大日志", "仓库整理",
    ),
    "delegation": (
        "subagent", "sub-agent", "delegate", "worker", "agent routing", "model routing", "multi-agent",
        "子代理", "委派", "模型路由", "多智能体",
    ),
    "visual": (
        "dashboard", "figure", "slide", "visual", "layout", "design", "plot", "chart",
        "看板", "图表", "幻灯片", "视觉", "布局", "设计",
    ),
}
DOMAIN_PACKS = {
    "coding": ("coding-minimal-change", "coding-evidence"),
    "research": ("research-integrity",),
    "writing": ("writing-claim-discipline",),
    "hardware": ("hardware-safety",),
    "hygiene": ("archive-first-hygiene",),
    "delegation": ("delegation-quality",),
    "visual": ("visual-consistency",),
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def behavior_root(runtime_root: Path | None = None) -> Path:
    return runtime_root.resolve() if runtime_root else Path(__file__).resolve().parent


def _project_root(payload: dict[str, Any], explicit: Path | None = None) -> Path:
    if explicit:
        return explicit.resolve()
    cwd = Path(
        payload.get("cwd")
        or os.environ.get("GEMINI_PROJECT_DIR")
        or os.environ.get("CLAUDE_PROJECT_DIR")
        or os.getcwd()
    ).resolve()
    for candidate in (cwd, *cwd.parents):
        if (candidate / ".researchops").exists() or (candidate / ".git").exists():
            return candidate
    return cwd


def _config_path(project_root: Path) -> Path:
    return project_root / ".researchops" / "runtime" / "behavior" / "config.json"


def current_mode(project_root: Path, payload: dict[str, Any] | None = None) -> str:
    requested = (payload or {}).get("behavior_mode") or os.environ.get("ROPS_BEHAVIOR_MODE")
    if requested in MODES:
        return str(requested)
    config = _read_json(_config_path(project_root), {})
    mode = config.get("mode", "guide")
    return mode if mode in MODES else "guide"


def set_mode(project_root: Path, mode: str) -> dict[str, Any]:
    if mode not in MODES:
        raise ValueError(f"invalid behavior mode: {mode}")
    state = _read_json(_config_path(project_root), {})
    state.update({"schema_version": 1, "mode": mode, "updated_at": utc_now()})
    _atomic_json(_config_path(project_root), state)
    return state


def load_packs(runtime_root: Path | None = None) -> dict[str, dict[str, Any]]:
    packs: dict[str, dict[str, Any]] = {}
    for path in sorted((behavior_root(runtime_root) / "packs").glob("*/pack.json")):
        data = _read_json(path, {})
        if data.get("id"):
            packs[str(data["id"])] = data
    return packs


def _extract_text(payload: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("prompt", "user_prompt", "message", "task", "query"):
        if isinstance(payload.get(key), str):
            values.append(payload[key])
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("description", "content", "patch"):
            if isinstance(tool_input.get(key), str):
                values.append(tool_input[key])
    return "\n".join(values)


def _command(payload: dict[str, Any]) -> str:
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict) and isinstance(tool_input.get("command"), str):
        return tool_input["command"]
    tool_name = str(payload.get("tool_name") or "").lower()
    if isinstance(tool_input, str) and tool_name in {"bash", "shell", "run_shell_command", "execute", "terminal"}:
        return tool_input
    return ""


def classify(text: str, *, active_skill: str | None = None, runtime_root: Path | None = None) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text.lower())
    domains = [name for name, signals in TASK_SIGNALS.items() if any(signal.lower() in normalized for signal in signals)]
    if active_skill:
        name = active_skill.lower()
        if name.startswith("research-") or name in {"experimental-research", "research-program-orchestrator"}:
            domains.append("research")
        if name in {"research-engineering", "software-development"}:
            domains.append("coding")
        if name == "research-communication":
            domains.extend(("writing", "visual"))
        if name == "hardware-experiment-loop":
            domains.append("hardware")
        if name == "project-hygiene":
            domains.append("hygiene")
        if name == "adaptive-agent-orchestration":
            domains.append("delegation")
    domains = sorted(set(domains))
    available = load_packs(runtime_root)
    pack_ids = []
    for domain in domains:
        for pack_id in DOMAIN_PACKS.get(domain, ()):
            if pack_id in available and pack_id not in pack_ids:
                pack_ids.append(pack_id)
    return {"domains": domains, "pack_ids": pack_ids, "packs": [available[pack_id] for pack_id in pack_ids]}


def _audit(project_root: Path, data: dict[str, Any]) -> None:
    """Append metadata only; never persist raw prompts or commands."""
    path = project_root / ".researchops" / "logs" / "behavior-events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")


def evaluate(
    payload: dict[str, Any],
    *,
    framework: str = "portable",
    runtime_root: Path | None = None,
    project_root: Path | None = None,
) -> dict[str, Any]:
    root = _project_root(payload, project_root)
    mode = current_mode(root, payload)
    event = str(payload.get("hook_event_name") or "")
    text = _extract_text(payload)
    classification = classify(text, active_skill=payload.get("active_skill"), runtime_root=runtime_root)
    command = _command(payload)
    risk: dict[str, Any] = {"disposition": "allow", "findings": [], "approved": True}
    if command:
        # Import lazily so the portable hook remains cheap at session start.
        from rops.behavior import analyze, check
        from rops.intelligence.store import IntelligenceStore

        risk = analyze(command)
        if risk["disposition"] == "approval-required":
            risk = check(IntelligenceStore(root), command)
    denied = mode == "enforce" and (risk.get("disposition") == "block" or not risk.get("approved", True))
    guidance = [str(pack.get("description", "")) for pack in classification["packs"] if pack.get("description")]
    result = {
        "schema_version": 1,
        "evaluated_at": utc_now(),
        "framework": framework,
        "event": event,
        "mode": mode,
        "domains": classification["domains"],
        "pack_ids": classification["pack_ids"],
        "guidance": guidance,
        "risk": risk,
        "decision": "deny" if denied else "allow",
        "raw_content_persisted": False,
    }
    _audit(
        root,
        {
            "at": result["evaluated_at"],
            "framework": framework,
            "event": event,
            "mode": mode,
            "pack_ids": result["pack_ids"],
            "decision": result["decision"],
            "risk_categories": [item.get("category") for item in risk.get("findings", [])],
            "text_hash": _hash(text) if text else None,
            "command_hash": _hash(command) if command else None,
        },
    )
    return result


def _context(result: dict[str, Any]) -> str:
    if result["mode"] in {"off", "observe"} or not result["guidance"]:
        return ""
    lines = ["ResearchOps behavior guidance:"]
    lines.extend(f"- {item}" for item in result["guidance"])
    if result["risk"].get("disposition") == "approval-required":
        lines.append("- This operation requires a separate short-lived, content-bound human approval.")
    return "\n".join(lines)


def render_hook_output(result: dict[str, Any], framework: str, event: str) -> dict[str, Any]:
    context = _context(result)
    denied = result["decision"] == "deny"
    reason = "ResearchOps blocked this exposed operation because required approval is absent or the action is non-approvable."
    if framework == "gemini":
        output: dict[str, Any] = {}
        if denied:
            output.update({"decision": "deny", "reason": reason})
        if context:
            output["additionalContext"] = context
        return output
    specific: dict[str, Any] = {"hookEventName": event}
    if denied:
        specific.update({"permissionDecision": "deny", "permissionDecisionReason": reason})
    if context:
        specific["additionalContext"] = context
    return {"hookSpecificOutput": specific} if specific else {}
