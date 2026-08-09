#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.release import package_release


def names(archive: Path) -> set[str]:
    with zipfile.ZipFile(archive) as handle:
        return set(handle.namelist())


def contains(paths: set[str], suffix: str) -> bool:
    return any(path.endswith(suffix) for path in paths)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="researchops-package-smoke-") as temp:
        out = Path(temp) / "dist"
        routing, routing_sum = package_release(out, skip_smoke=True, preset="routing-core", target="codex")
        routing_names = names(routing)
        assert contains(routing_names, "skills/adaptive-agent-orchestration/SKILL.md")
        assert not contains(routing_names, "skills/research-discovery/SKILL.md")
        assert contains(routing_names, "components/model-intelligence/component.json")
        assert contains(routing_names, "components/model-gateway/component.json")
        assert contains(routing_names, "components/model-control-plane/profile-schema.json")
        assert contains(routing_names, "behavior/packs/delegation-quality/pack.json")
        assert not contains(routing_names, "behavior/packs/research-integrity/pack.json")
        assert contains(routing_names, ".codex-plugin/plugin.json")
        assert contains(routing_names, "hooks/hooks.json")
        assert not contains(routing_names, ".claude-plugin/plugin.json")
        assert contains(routing_names, "PACKAGE.json")
        if (ROOT / "release/product-benchmark.json").exists():
            assert contains(routing_names, "release/product-benchmark.json")
            assert contains(routing_names, "release/product-benchmark.md")
        assert routing_sum.exists()

        full, full_sum = package_release(out, skip_smoke=True, preset="full", target="portable")
        full_names = names(full)
        assert contains(full_names, "skills/software-development/SKILL.md")
        assert contains(full_names, "skills/research-discovery/SKILL.md")
        assert contains(full_names, ".codex-plugin/plugin.json")
        assert contains(full_names, ".claude-plugin/plugin.json")
        assert contains(full_names, "gemini-extension.json")
        assert full_sum.exists()

        # A local project database may exist beside the source checkout during
        # development, but neither source manifests nor release artifacts may
        # include it.
        assert not any("/.researchops/" in f"/{name}" for name in routing_names)
        assert not any("/.researchops/" in f"/{name}" for name in full_names)

        extract = Path(temp) / "extract"
        with zipfile.ZipFile(routing) as handle:
            handle.extractall(extract)
        roots = [item for item in extract.iterdir() if item.is_dir()]
        assert len(roots) == 1
        check = subprocess.run(
            [sys.executable, "-m", "rops", "validate"],
            cwd=roots[0],
            text=True,
            capture_output=True,
        )
        assert check.returncode == 0, check.stdout + "\n" + check.stderr
        plugin_manifest = json.loads((roots[0] / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
        assert plugin_manifest["author"]["name"]
        assert "hooks" not in plugin_manifest

        print(
            json.dumps(
                {
                    "routing_artifact_filtered": True,
                    "target_native_manifest_filtered": True,
                    "codex_conventional_hooks": True,
                    "full_portable_artifact": True,
                    "package_local_validation": True,
                    "checksums": True,
                    "local_state_excluded": True,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
