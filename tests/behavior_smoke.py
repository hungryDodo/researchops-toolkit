#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.behavior import analyze, approve, check
from rops.intelligence.store import IntelligenceStore


def hook(payload: dict, *, framework: str = "claude") -> dict:
    process = subprocess.run(
        [sys.executable, str(ROOT / "hooks/researchops_hook.py"), "--framework", framework],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=True,
    )
    return json.loads(process.stdout or "{}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rops-behavior-smoke-") as temp:
        project = Path(temp) / "project"
        project.mkdir()
        store = IntelligenceStore(project)

        assert analyze("python -m pytest")["disposition"] == "allow"
        assert analyze("git reset --hard HEAD~1")["disposition"] == "approval-required"
        assert analyze("cat ~/.config/rops/secrets.env")["disposition"] == "block"
        assert analyze("docker run --privileged image")["disposition"] == "approval-required"

        command = "git reset --hard HEAD~1"
        assert check(store, command)["approved"] is False
        approval = approve(store, command, "history-rewrite", "human")
        assert approval["one_use"] is True
        assert check(store, command, consume=True)["approved"] is True
        assert check(store, command)["approved"] is False

        # Guide mode injects only selected compact pack guidance.
        guide = hook(
            {
                "hook_event_name": "UserPromptSubmit",
                "cwd": str(project),
                "prompt": "Please debug this implementation and run fresh tests.",
                "active_skill": "software-development",
            }
        )
        context = guide.get("hookSpecificOutput", {}).get("additionalContext", "")
        assert "smallest sufficient change" in context
        assert "fresh tests" in context

        # Enforce mode denies an exposed, unapproved consequential operation.
        config = project / ".researchops/runtime/behavior/config.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"mode": "enforce"}), encoding="utf-8")
        denied = hook(
            {
                "hook_event_name": "PreToolUse",
                "cwd": str(project),
                "tool_name": "Bash",
                "tool_input": {"command": command},
            }
        )
        assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

        # Hooks persist hashes/metadata, not raw prompts or commands.
        audit = project / ".researchops/logs/behavior-events.jsonl"
        text = audit.read_text(encoding="utf-8")
        assert "Please debug this implementation" not in text
        assert command not in text
        assert "text_hash" in text and "command_hash" in text

        print(json.dumps({
            "risk_analysis": True,
            "one_use_approval": True,
            "guide_injection": True,
            "enforce_denial": True,
            "metadata_only_audit": True,
        }, indent=2))


if __name__ == "__main__":
    main()
