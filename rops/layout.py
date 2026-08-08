from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .common import now, write_json


@dataclass(frozen=True)
class ProjectLayout:
    """Canonical project-local ResearchOps layout.

    A project gets one hidden root only.  Durable research artifacts live under
    ``state``; governance is human-editable policy; ``intelligence`` contains
    the SQLite authority and generated projections; ``runtime`` is replaceable.
    """

    root: Path

    @property
    def home(self) -> Path:
        override = os.environ.get("ROPS_STATE_DIR", "").strip()
        return Path(override).expanduser().resolve() if override else self.root / ".researchops"

    @property
    def state(self) -> Path:
        return self.home / "state"

    @property
    def governance(self) -> Path:
        return self.home / "governance"

    @property
    def intelligence(self) -> Path:
        return self.home / "intelligence"

    @property
    def database(self) -> Path:
        return self.intelligence / "state.sqlite"

    @property
    def exports(self) -> Path:
        return self.intelligence / "exports"

    @property
    def runtime(self) -> Path:
        return self.home / "runtime"

    @property
    def artifacts(self) -> Path:
        return self.home / "artifacts"

    @property
    def cache(self) -> Path:
        return self.home / "cache"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def legacy_state(self) -> Path:
        return self.root / ".research"

    def ensure(self) -> "ProjectLayout":
        for path in (
            self.home,
            self.state,
            self.governance,
            self.intelligence,
            self.exports,
            self.runtime,
            self.artifacts,
            self.cache,
            self.logs,
        ):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def describe(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "home": str(self.home),
            "state": str(self.state),
            "governance": str(self.governance),
            "intelligence": str(self.intelligence),
            "database": str(self.database),
            "exports": str(self.exports),
            "runtime": str(self.runtime),
        }


def layout(root: str | Path) -> ProjectLayout:
    return ProjectLayout(Path(root).resolve())


def migrate_legacy_layout(root: str | Path, *, move: bool = True) -> dict[str, Any]:
    """Migrate the old sibling ``.research``/``.researchops`` layout.

    The migration is conservative: existing canonical destinations are never
    overwritten.  A manifest records every moved/copied path.  The old runtime
    directory is handled before the canonical root is created.
    """

    project = Path(root).resolve()
    target = ProjectLayout(project)
    legacy_state = project / ".research"
    old_runtime = project / ".researchops"
    temp_runtime = project / ".researchops-runtime-migration"
    events: list[dict[str, str]] = []

    # Before v2, .researchops was replaceable runtime.  Temporarily move it out
    # of the way so the new single-root layout can be created safely.
    if old_runtime.exists() and not (old_runtime / "state").exists():
        if temp_runtime.exists():
            shutil.rmtree(temp_runtime)
        if move:
            old_runtime.rename(temp_runtime)
        else:
            shutil.copytree(old_runtime, temp_runtime)
        events.append({"source": ".researchops", "target": ".researchops/runtime", "kind": "legacy-runtime"})

    target.ensure()

    def transfer_tree(source: Path, destination: Path, kind: str) -> None:
        if not source.exists():
            return
        for child in source.iterdir():
            out = destination / child.name
            if out.exists():
                events.append({"source": str(child.relative_to(project)), "target": str(out.relative_to(project)), "kind": "preserved-existing"})
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            if move:
                shutil.move(str(child), str(out))
            elif child.is_dir():
                shutil.copytree(child, out)
            else:
                shutil.copy2(child, out)
            events.append({"source": str(child.relative_to(project)), "target": str(out.relative_to(project)), "kind": kind})

    transfer_tree(legacy_state, target.state, "legacy-state")
    transfer_tree(temp_runtime, target.runtime, "legacy-runtime")

    if move:
        for leftover in (legacy_state, temp_runtime):
            try:
                leftover.rmdir()
            except OSError:
                pass

    manifest = {
        "schema_version": 1,
        "migrated_at": now(),
        "move": move,
        "events": events,
        "layout": target.describe(),
    }
    write_json(target.home / "migration-v2.json", manifest)
    return manifest
