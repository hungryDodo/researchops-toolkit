#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.evaluation import run_benchmark


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="researchops-product-benchmark-smoke-") as temp:
        report = run_benchmark(candidate_root=ROOT, out=Path(temp) / "report")
        score = report["candidate"]["score"]
        assert score["covered"] == score["total"] == 19
        assert score["passed"] == 19 and score["rate"] == 1.0
        assert report["candidate"]["dashboard"]["quick_start"]["ready"] is True
        assert report["candidate"]["dashboard"]["quick_start"]["process_group_cleaned"] is True
        assert report["candidate"]["memory"]["layer_coverage"] >= 4
        assert Path(report["files"]["json"]).exists()
        assert Path(report["files"]["markdown"]).exists()
        print(json.dumps({
            "suite": report["benchmark_version"],
            "checks": f"{score['passed']}/{score['covered']}",
            "dashboard_http_ready": True,
            "dashboard_process_cleanup": True,
            "memory_lifecycle": True,
            "reports_written": True,
        }, indent=2))


if __name__ == "__main__":
    main()
