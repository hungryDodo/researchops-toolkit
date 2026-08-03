#!/usr/bin/env python3
"""Interpretable task-to-model registry and adaptive routing.

This module records verified dispatch outcomes and ranks eligible models with
hard constraints, empirical task-specific quality, and bounded low-risk
exploration. It deliberately avoids opaque online self-training.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import tempfile
import sys
from pathlib import Path
from typing import Any

UTC = dt.timezone.utc
RISK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
MUTABILITY = {"read-only": 0, "workspace-write": 1, "external-write": 2, "hardware-write": 3, "destructive": 4}


def iso() -> str:
    return dt.datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def read_json_arg(raw: str | None, path: str | None) -> dict[str, Any]:
    if bool(raw) == bool(path):
        raise SystemExit("provide exactly one of --json or --file")
    return json.loads(raw) if raw else load(Path(path), {})


def paths(root: Path) -> dict[str, Path]:
    d = root / ".research/agents"
    return {
        "dir": d,
        "models": d / "models.json",
        "agents": d / "agents.json",
        "policy": d / "routing-policy.json",
        "history": d / "task-history.jsonl",
        "profiles": d / "profiles.json",
        "decisions": d / "routing-decisions.jsonl",
        "providers": d / "providers.json",
        "model_profiles": d / "model-profiles",
        "onboarding": d / "onboarding",
        "smoke": d / "smoke",
    }


def init_project(root: Path, assets: Path, force: bool = False) -> None:
    ps = paths(root)
    ps["dir"].mkdir(parents=True, exist_ok=True)
    for src_name, dst_key in [
        ("models.example.json", "models"),
        ("agents.example.json", "agents"),
        ("routing-policy.example.json", "policy"),
    ]:
        dst = ps[dst_key]
        if force or not dst.exists():
            atomic(dst, load(assets / src_name, {}))
    if force or not ps["profiles"].exists():
        atomic(ps["profiles"], {"schema_version": 1, "generated_at": iso(), "profiles": {}})
    if force or not ps["providers"].exists():
        atomic(ps["providers"], {"schema_version": 1, "providers": []})
    for key in ("model_profiles", "onboarding", "smoke"):
        ps[key].mkdir(parents=True, exist_ok=True)
    for key in ("history", "decisions"):
        if force or not ps[key].exists():
            ps[key].touch()
    print(ps["dir"])


def key_for(model_id: str, task: dict[str, Any]) -> str:
    return "|".join([
        model_id,
        str(task.get("stage", "unknown")),
        str(task.get("type", "unknown")),
        str(task.get("risk", "low")),
    ])


def read_events(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not path.exists(): return out
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if not line.strip(): continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict): out.append(obj)
        except json.JSONDecodeError:
            raise SystemExit(f"invalid JSONL at {path}:{i}")
    return out


def aggregate(events: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    for e in events:
        model_id = str(e.get("model_id", ""))
        task = e.get("task") or {}
        if not model_id or not isinstance(task, dict): continue
        k = key_for(model_id, task)
        b = buckets.setdefault(k, {
            "model_id": model_id,
            "stage": task.get("stage", "unknown"),
            "task_type": task.get("type", "unknown"),
            "risk": task.get("risk", "low"),
            "observations": 0,
            "accepted": 0,
            "quality_sum": 0.0,
            "cost_sum": 0.0,
            "latency_sum": 0.0,
            "correction_sum": 0.0,
            "disagreement_sum": 0.0,
        })
        b["observations"] += 1
        accepted = bool(e.get("accepted", False))
        b["accepted"] += int(accepted)
        b["quality_sum"] += float(e.get("quality", 1.0 if accepted else 0.0) or 0.0)
        b["cost_sum"] += float(e.get("cost", 0.0) or 0.0)
        b["latency_sum"] += float(e.get("latency_seconds", 0.0) or 0.0)
        b["correction_sum"] += float(e.get("human_correction", 0.0) or 0.0)
        b["disagreement_sum"] += float(e.get("verifier_disagreement", 0.0) or 0.0)
    profiles: dict[str, Any] = {}
    for k, b in buckets.items():
        n = b.pop("observations")
        accepted = b.pop("accepted")
        profiles[k] = {
            **b,
            "observations": n,
            "accepted": accepted,
            "success_rate_beta": (accepted + 1.0) / (n + 2.0),
            "mean_quality": b.pop("quality_sum") / n,
            "mean_cost": b.pop("cost_sum") / n,
            "mean_latency_seconds": b.pop("latency_sum") / n,
            "mean_human_correction": b.pop("correction_sum") / n,
            "mean_verifier_disagreement": b.pop("disagreement_sum") / n,
        }
    return {"schema_version": 1, "generated_at": iso(), "profiles": profiles}


def rebuild(root: Path) -> dict[str, Any]:
    ps = paths(root)
    data = aggregate(read_events(ps["history"]))
    atomic(ps["profiles"], data)
    return data


def provider_allowed(model: dict[str, Any], privacy: str, policy: dict[str, Any]) -> bool:
    allow = policy.get("privacy_provider_allowlist", {}).get(privacy, [])
    if "*" in allow: return True
    provider = str(model.get("provider", ""))
    if provider in allow: return True
    # Treat localhost gateways as local only when explicitly tagged.
    return provider == "openai-compatible" and "local-openai-compatible" in allow and str(model.get("trust_zone", "")).startswith("local")


def eligible(model: dict[str, Any], task: dict[str, Any], agent: dict[str, Any] | None, policy: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not model.get("enabled", False): reasons.append("disabled")
    risk = str(task.get("risk", "low"))
    ceiling = str(model.get("risk_ceiling", "low"))
    if RISK.get(risk, 99) > RISK.get(ceiling, -1): reasons.append("risk_ceiling")
    privacy = str(task.get("privacy", "internal"))
    if not provider_allowed(model, privacy, policy): reasons.append("privacy_provider")
    required = set(task.get("required_capabilities", []) or [])
    if agent: required.update(agent.get("required_capabilities", []) or [])
    have = set(model.get("capabilities", []) or [])
    missing = sorted(required - have)
    if missing: reasons.append("missing:" + ",".join(missing))
    mut = str(task.get("mutability", "read-only"))
    if agent:
        allowed = str(agent.get("allowed_mutability", "read-only"))
        if MUTABILITY.get(mut, 99) > MUTABILITY.get(allowed, -1): reasons.append("agent_mutability")
    candidates = set(agent.get("candidate_models", []) or []) if agent else set()
    if candidates and model.get("id") not in candidates: reasons.append("not_in_agent_candidates")
    return not reasons, reasons


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def normalize_hint(value: Any, default: float = 0.5) -> float:
    try: return clamp01(float(value))
    except (TypeError, ValueError): return default


def score_model(model: dict[str, Any], task: dict[str, Any], profile: dict[str, Any] | None, total_obs: int, policy: dict[str, Any]) -> tuple[float, dict[str, float]]:
    task_type = str(task.get("type", "unknown"))
    prior = normalize_hint((model.get("task_affinity") or {}).get(task_type, 0.5))
    min_obs = int(policy.get("minimum_observations_for_empirical_routing", 5))
    n = int((profile or {}).get("observations", 0))
    empirical_weight = min(0.8, n / max(1.0, float(min_obs)) * 0.5)
    quality_emp = normalize_hint((profile or {}).get("mean_quality", prior), prior)
    success_emp = normalize_hint((profile or {}).get("success_rate_beta", 0.5), 0.5)
    quality = (1.0 - empirical_weight) * prior + empirical_weight * quality_emp
    cost = normalize_hint((profile or {}).get("mean_cost", model.get("cost_hint", 0.5)))
    latency = normalize_hint((profile or {}).get("mean_latency_seconds", model.get("latency_hint", 0.5)))
    correction = normalize_hint((profile or {}).get("mean_human_correction", 0.0), 0.0)
    disagreement = normalize_hint((profile or {}).get("mean_verifier_disagreement", 0.0), 0.0)
    weights = policy.get("weights", {})
    parts = {
        "quality": quality,
        "success": success_emp,
        "cost_penalty": cost,
        "latency_penalty": latency,
        "correction_penalty": correction,
        "verifier_disagreement_penalty": disagreement,
        "exploration_bonus": 0.0,
    }
    exp = policy.get("exploration", {})
    risk = str(task.get("risk", "low"))
    if exp.get("enabled", False) and RISK.get(risk, 99) <= RISK.get(str(exp.get("max_risk", "medium")), 1):
        bonus = float(exp.get("ucb_coefficient", 0.08)) * math.sqrt(math.log(total_obs + 2.0) / (n + 1.0))
        parts["exploration_bonus"] = min(float(exp.get("max_bonus", 0.12)), bonus)
    score = (
        float(weights.get("quality", 0.55)) * quality
        + float(weights.get("success", 0.20)) * success_emp
        - float(weights.get("cost", 0.08)) * cost
        - float(weights.get("latency", 0.07)) * latency
        - float(weights.get("correction", 0.05)) * correction
        - float(weights.get("verifier_disagreement", 0.05)) * disagreement
        + parts["exploration_bonus"]
    )
    return score, parts


def recommend(root: Path, task: dict[str, Any], agent_name: str | None = None, write: bool = True) -> dict[str, Any]:
    ps = paths(root)
    models = load(ps["models"], {"models": []}).get("models", [])
    agents = load(ps["agents"], {"agents": []}).get("agents", [])
    policy = load(ps["policy"], {})
    profile_data = rebuild(root)
    profile_map = profile_data.get("profiles", {})
    agent = next((a for a in agents if a.get("name") == agent_name), None) if agent_name else None
    if agent_name and not agent: raise SystemExit(f"unknown agent: {agent_name}")
    total_obs = sum(int(x.get("observations", 0)) for x in profile_map.values())
    ranked: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for model in models:
        ok, reasons = eligible(model, task, agent, policy)
        if not ok:
            rejected.append({"model_id": model.get("id"), "reasons": reasons})
            continue
        profile = profile_map.get(key_for(str(model.get("id")), task))
        score, components = score_model(model, task, profile, total_obs, policy)
        ranked.append({
            "model_id": model.get("id"),
            "provider": model.get("provider"),
            "model": model.get("model"),
            "score": round(score, 6),
            "components": {k: round(v, 6) for k, v in components.items()},
            "observations": int((profile or {}).get("observations", 0)),
            "uncertainty": "high" if int((profile or {}).get("observations", 0)) < int(policy.get("minimum_observations_for_empirical_routing", 5)) else "lower",
        })
    ranked.sort(key=lambda x: (-x["score"], str(x["model_id"])))
    if not ranked: raise SystemExit("no eligible model; inspect rejected candidates")
    strong_markers = set(policy.get("strong_verification_required_for", []))
    require_verifier = (
        str(task.get("risk", "low")) in {"high", "critical"}
        or str(task.get("mutability", "read-only")) in {"hardware-write", "destructive"}
        or bool(strong_markers.intersection(set(task.get("tags", []) or [])))
    )
    primary = ranked[0]
    verifier = None
    if require_verifier:
        verifier = next((r for r in ranked[1:] if r["model_id"] != primary["model_id"]), None)
        if verifier is None:
            verifier = {"required": True, "status": "human_or_external_verifier_required"}
    decision = {
        "schema_version": 1,
        "decision_id": f"route-{dt.datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')}",
        "created_at": iso(),
        "task": task,
        "agent": agent_name,
        "primary": primary,
        "verifier": verifier,
        "ranked": ranked,
        "rejected": rejected,
        "policy_note": "Constrained, task-specific ranking with bounded exploration only for safe tasks.",
    }
    if write: append_jsonl(ps["decisions"], decision)
    return decision


def record(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    required = ["task", "model_id", "accepted"]
    missing = [k for k in required if k not in event]
    if missing: raise SystemExit("missing event fields: " + ", ".join(missing))
    if not isinstance(event.get("task"), dict): raise SystemExit("event.task must be an object")
    if event.get("registry_eligible") is not True:
        raise SystemExit("event is not registry-eligible; record only evaluated real-task outcomes")
    if int(event.get("deterministic_checks_count", 0)) < 1:
        raise SystemExit("registry-eligible event must include at least one deterministic acceptance check")
    event = {"schema_version": 1, "recorded_at": iso(), **event}
    append_jsonl(paths(root)["history"], event)
    profiles = rebuild(root)
    dossier = None
    dossier_error = None
    try:
        toolkit_root = Path(__file__).resolve().parents[3]
        if str(toolkit_root) not in sys.path:
            sys.path.insert(0, str(toolkit_root))
        from rops.models import rebuild_dossier
        dossier = rebuild_dossier(root, str(event["model_id"]))
    except Exception as exc:  # copy-only Skill installs may not include the ROPS runtime
        dossier_error = str(exc)
    return {
        "recorded": event,
        "profile": profiles.get("profiles", {}).get(key_for(str(event["model_id"]), event["task"])),
        "model_dossier_updated": dossier is not None,
        "model_dossier": dossier,
        "model_dossier_error": dossier_error,
    }


def summary(root: Path) -> dict[str, Any]:
    ps = paths(root)
    prof = rebuild(root)
    return {
        "schema_version": 1,
        "generated_at": iso(),
        "model_count": len(load(ps["models"], {"models": []}).get("models", [])),
        "agent_count": len(load(ps["agents"], {"agents": []}).get("agents", [])),
        "event_count": len(read_events(ps["history"])),
        "profile_count": len(prof.get("profiles", {})),
        "profiles": prof.get("profiles", {}),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=Path.cwd())
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--force", action="store_true"); p.add_argument("--assets", type=Path)
    p = sub.add_parser("recommend"); p.add_argument("--task-json"); p.add_argument("--task-file"); p.add_argument("--agent"); p.add_argument("--no-write", action="store_true")
    p = sub.add_parser("record"); p.add_argument("--event-json"); p.add_argument("--event-file")
    sub.add_parser("rebuild")
    sub.add_parser("summary")
    args = ap.parse_args(); root = args.root.resolve()
    if args.cmd == "init":
        assets = args.assets or Path(__file__).resolve().parent.parent / "assets"
        init_project(root, assets, args.force); return
    if args.cmd == "recommend":
        task = read_json_arg(args.task_json, args.task_file)
        print(json.dumps(recommend(root, task, args.agent, not args.no_write), ensure_ascii=False, indent=2)); return
    if args.cmd == "record":
        event = read_json_arg(args.event_json, args.event_file)
        print(json.dumps(record(root, event), ensure_ascii=False, indent=2)); return
    if args.cmd == "rebuild": print(json.dumps(rebuild(root), ensure_ascii=False, indent=2)); return
    if args.cmd == "summary": print(json.dumps(summary(root), ensure_ascii=False, indent=2)); return


if __name__ == "__main__": main()
