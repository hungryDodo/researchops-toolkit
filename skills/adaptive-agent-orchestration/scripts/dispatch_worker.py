#!/usr/bin/env python3
"""Route, launch, verify, and record one bounded ResearchOps worker session."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve()
IMPORT_ROOTS = (
    SCRIPT.parents[3],
    SCRIPT.parents[4] / ".researchops/runtime",
    Path.cwd().resolve() / ".researchops/runtime",
)
for import_root in IMPORT_ROOTS:
    if (import_root / "rops").is_dir() and str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from rops.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["route-run", *sys.argv[1:]]))
