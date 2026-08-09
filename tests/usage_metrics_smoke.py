from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rops.intelligence.events import EvaluationEvent
from rops.usage_metrics import normalize_provider_usage


def main() -> None:
    usage = normalize_provider_usage(
        {
            "usage": {
                "input_tokens": 120,
                "input_tokens_details": {"cached_tokens": 80},
                "output_tokens": 50,
                "output_tokens_details": {"reasoning_tokens": 30},
            },
            "ttft_seconds": 0.4,
        }
    )
    assert usage == {
        "input_tokens": 120,
        "input_tokens_cached": 80,
        "input_tokens_uncached": 40,
        "output_tokens": 50,
        "reasoning_tokens": 30,
        "cache_hit": True,
        "cache_source": "provider",
        "ttft_seconds": 0.4,
        "measurement_status": "complete",
    }
    unknown = normalize_provider_usage({"usage": {"prompt_tokens": 7}})
    assert unknown["input_tokens_cached"] is None
    assert unknown["reasoning_tokens"] is None
    assert unknown["ttft_seconds"] is None
    assert unknown["measurement_status"] == "partial"

    event = EvaluationEvent.normalize(
        {
            "project_id": "usage-smoke",
            "execution_arm_id": "provider/model@effort",
            "execution_identity": {"provider": "provider", "model": "model"},
            "task": {"operation": "validate"},
            "usage": unknown,
        }
    ).data
    assert event["usage"]["input_tokens_cached"] is None
    assert event["usage"]["reasoning_tokens"] is None
    assert event["usage"]["ttft_seconds"] is None
    assert event["execution_identity"] == {"provider": "provider", "model": "model"}


if __name__ == "__main__":
    main()
