from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(*values: object) -> object | None:
    return next((value for value in values if value is not None), None)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def normalize_provider_usage(result: Mapping[str, Any]) -> dict[str, object]:
    """Preserve cache/reasoning telemetry without inventing missing zeroes."""

    usage = _mapping(result.get("usage"))
    input_details = _mapping(
        _first(
            usage.get("input_tokens_details"),
            usage.get("prompt_tokens_details"),
        )
    )
    output_details = _mapping(
        _first(
            usage.get("output_tokens_details"),
            usage.get("completion_tokens_details"),
        )
    )
    input_tokens = _optional_int(
        _first(
            usage.get("input_tokens"),
            usage.get("prompt_tokens"),
            result.get("input_tokens"),
        )
    )
    output_tokens = _optional_int(
        _first(
            usage.get("output_tokens"),
            usage.get("completion_tokens"),
            result.get("output_tokens"),
        )
    )
    cached = _optional_int(input_details.get("cached_tokens"))
    reasoning = _optional_int(output_details.get("reasoning_tokens"))
    ttft = _optional_float(_first(result.get("ttft_seconds"), usage.get("ttft_seconds")))
    uncached = None if cached is None or input_tokens is None else max(0, input_tokens - cached)
    explicit_cache_hit = _first(result.get("cache_hit"), usage.get("cache_hit"))
    cache_hit = (
        explicit_cache_hit
        if isinstance(explicit_cache_hit, bool)
        else True if cached is not None and cached > 0 else None
    )
    measured = (cached, reasoning, ttft)
    return {
        "input_tokens": input_tokens or 0,
        "input_tokens_cached": cached,
        "input_tokens_uncached": uncached,
        "output_tokens": output_tokens or 0,
        "reasoning_tokens": reasoning,
        "cache_hit": cache_hit,
        "cache_source": "provider" if cached is not None else None,
        "ttft_seconds": ttft,
        "measurement_status": "complete" if all(value is not None for value in measured) else "partial",
    }


__all__ = ["normalize_provider_usage"]
