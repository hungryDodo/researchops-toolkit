#!/usr/bin/env python3
"""End-to-end smoke test for the task-aware Behavior Runtime."""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PYTHON = os.environ.get("PYTHON", "python3")


def run(*args: str, cwd: Path | None = None, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(list(args), cwd=cwd or ROOT, text=True, capture_output=True)
    if result.returncode != expect:
        raise RuntimeError(
            f"command failed ({result.returncode}, expected {expect}): {' '.join(args)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def read_stdout_json(result: subprocess.CompletedProcess[str]) -> Any:
    positions = [index for index, char in enumerate(result.stdout) if char == "{"]
    for position in reversed(positions):
        try:
            return json.loads(result.stdout[position:])
        except json.JSONDecodeError:
            pass
    raise ValueError(result.stdout)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="researchops-behavior-smoke-") as temp:
        project = Path(temp) / "project"
        project.mkdir()
        run("git", "init", "-q", "-b", "main", cwd=project)
        run(PYTHON, "-m", "rops", "bootstrap", str(project), "--title", "Behavior Test", "--upgrade")

        installed = read_stdout_json(run(
            PYTHON, "-m", "rops", "behavior", "--root", str(project), "install",
            "--target", "all", "--mode", "enforce",
        ))
        assert set(installed["hook_configs"]) == {"codex", "claude", "gemini"}
        assert (project / ".researchops/behavior/runtime.py").exists()
        assert (project / ".codex/hooks.json").exists()
        assert (project / ".claude/settings.json").exists()
        assert (project / ".gemini/settings.json").exists()

        classified = read_stdout_json(run(
            PYTHON, "-m", "rops", "behavior", "--root", str(project), "classify",
            "--text", "Refactor this parser and add tests without a new dependency.",
        ))
        assert "coding" in classified["task_classes"]
        assert {"coding-minimal-change", "coding-evidence"}.issubset(classified["active_packs"])

        command = "rm -rf raw_traces"
        denied = read_stdout_json(run(
            PYTHON, "-m", "rops", "behavior", "--root", str(project), "evaluate",
            "--framework", "codex", "--event", "PreToolUse", "--tool-name", "Bash",
            "--command", command, "--record",
        ))
        assert denied["decision"] == "deny"
        assert any(item["kind"] == "destructive-delete" for item in denied["proposals"])

        approval_env = dict(os.environ)
        approval_env["RESEARCHOPS_ALLOW_NONINTERACTIVE_APPROVAL"] = "1"
        approval_process = subprocess.run(
            [PYTHON, "-m", "rops", "behavior", "--root", str(project), "approve",
             "--kind", "destructive-delete", "--command", command,
             "--reason", "isolated behavior-runtime smoke test", "--ttl", "5"],
            cwd=ROOT, text=True, capture_output=True, env=approval_env,
        )
        if approval_process.returncode:
            raise RuntimeError(approval_process.stderr)
        approval = read_stdout_json(approval_process)
        assert approval["status"] == "approved"

        allowed_once = read_stdout_json(run(
            PYTHON, "-m", "rops", "behavior", "--root", str(project), "evaluate",
            "--framework", "codex", "--event", "PreToolUse", "--tool-name", "Bash",
            "--command", command, "--record",
        ))
        assert allowed_once["decision"] == "allow"
        assert allowed_once["approvals_consumed"] == ["destructive-delete"]

        denied_again = read_stdout_json(run(
            PYTHON, "-m", "rops", "behavior", "--root", str(project), "evaluate",
            "--framework", "codex", "--event", "PreToolUse", "--tool-name", "Bash",
            "--command", command, "--record",
        ))
        assert denied_again["decision"] == "deny"


        # The main task context is remembered without raw prompt text and
        # propagated into a subagent that reports the same session id.
        from rops import behavior as behavior_api
        session_id = "behavior-smoke-session"
        behavior_api.evaluate(project, {
            "hook_event_name": "UserPromptSubmit",
            "session_id": session_id,
            "cwd": str(project),
            "prompt": "Refactor this parser and add regression tests.",
        }, "portable", True)
        inherited = behavior_api.evaluate(project, {
            "hook_event_name": "SubagentStart",
            "session_id": session_id,
            "cwd": str(project),
            "agent_type": "worker",
        }, "portable", False)
        assert "coding-minimal-change" in inherited["active_packs"]
        assert "delegation-quality" in inherited["active_packs"]

        events_path = project / ".research/runtime/events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        assert events and all(item["raw_input_logged"] is False for item in events)
        assert command not in events_path.read_text(encoding="utf-8")
        assert all(item.get("input_sha256") for item in events)

        hook = project / ".researchops/hooks/researchops_hook.py"
        payload = json.dumps({
            "hook_event_name": "UserPromptSubmit",
            "cwd": str(project),
            "prompt": "Design a reproducible experiment and preserve negative results.",
        })
        hook_result = subprocess.run(
            [PYTHON, str(hook), "--framework", "codex"],
            cwd=project,
            input=payload,
            text=True,
            capture_output=True,
        )
        if hook_result.returncode:
            raise RuntimeError(hook_result.stderr)
        hook_output = json.loads(hook_result.stdout)
        assert "additionalContext" in hook_output["hookSpecificOutput"]

        gemini_payload = json.dumps({
            "hook_event_name": "BeforeAgent",
            "session_id": "gemini-extension-smoke",
            "cwd": str(project),
            "prompt": "Survey the literature and preserve negative evidence.",
        })
        gemini_result = subprocess.run(
            [PYTHON, str(ROOT / "hooks/researchops_hook.py"), "--framework", "gemini"],
            cwd=project, input=gemini_payload, text=True, capture_output=True,
        )
        if gemini_result.returncode:
            raise RuntimeError(gemini_result.stderr)
        gemini_output = json.loads(gemini_result.stdout)
        assert "additionalContext" in gemini_output["hookSpecificOutput"]
        assert (ROOT / "hooks/hooks.json").exists()

        print(json.dumps({
            "behavior_packs": 7,
            "framework_hook_configs": 3,
            "coding_classification": True,
            "guide_context": True,
            "enforce_block": True,
            "content_bound_one_use_approval": True,
            "metadata_only_logging": True,
            "hook_adapter": True,
            "subagent_context_inheritance": True,
            "operator_only_approval": True,
            "gemini_extension_hook": True,
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
