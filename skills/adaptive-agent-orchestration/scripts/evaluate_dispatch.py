#!/usr/bin/env python3
"""Independently evaluate a delegated task result against a bounded contract."""
from __future__ import annotations

import argparse
import datetime as dt
import json
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

from rops.dispatch_evaluation import evaluate, load


def iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--verifier", type=Path, help="Independent verifier JSON; required when the contract says so.")
    parser.add_argument("--human-feedback", type=Path, help="Optional calibrated human correction/override JSON.")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-commands", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    data = evaluate(
        root,
        load(args.contract),
        load(args.result),
        load(args.verifier),
        load(args.human_feedback),
        args.allow_commands,
    )
    data["evaluated_at"] = iso()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output.chmod(0o600)
    print(args.output)


if __name__ == "__main__":
    main()
