from __future__ import annotations

import datetime as dt
import json
import math
import random
import uuid
from pathlib import Path
from typing import Any

from ..common import load_json, now
from ..layout import layout
from .events import normalize_task
from .profiles import best_profile, load_profiles, rebuild_profiles, scope_key
from .store import IntelligenceStore
from . import mitigations, warmup

RISK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
MUTABILITY = {"read-only": 0, "workspace-write": 1, "external-write": 2, "hardware-write": 3, "destructive": 4}
DEFAULT_EFFORT_ORDER = ["none", "low", "medium", "high", "xhigh", "max", "ultra"]


def governance_paths(root: Path) -> dict[str, Path]:
    base = layout(root).governance
    return {
        "models": base / "models.json",
        "agents": base / "agents.json",
        "policy": base / "routing-policy.json",
        "providers": base / "providers.json",
    }


def _provider_allowed(model: dict[str, Any], privacy: str, policy: dict[str, Any]) -> bool:
    allowed = policy.get("privacy_provider_allowlist", {}).get(privacy, [])
    provider = str(model.get("provider", ""))
    return "*" in allowed or provider in allowed or (
        provider == "openai-compatible"
        and "local-openai-compatible" in allowed
        and str(model.get("trust_zone", "")).startswith("local")
    )


def _arm_id(model: dict[str, Any]) -> str:
    return str(model.get("arm_id") or model.get("id") or "")


def _model_family(model: dict[str, Any]) -> str:
    return str(model.get("model_family") or model.get("model") or _arm_id(model))


def _reasoning_effort(model: dict[str, Any]) -> str | None:
    value = str(model.get("reasoning_effort") or "").strip().lower()
    return value or None


def _effort_order(policy: dict[str, Any]) -> list[str]:
    configured = policy.get("effort_routing", {}).get("order", DEFAULT_EFFORT_ORDER)
    order = [str(value).strip().lower() for value in configured if str(value).strip()]
    return order or list(DEFAULT_EFFORT_ORDER)


def _effort_rank(effort: str | None, policy: dict[str, Any]) -> int | None:
    if effort is None:
        return None
    order = _effort_order(policy)
    try:
        return order.index(effort)
    except ValueError:
        return None


def _effort_fit(model: dict[str, Any], task: dict[str, Any], policy: dict[str, Any]) -> float:
    """Score a model-effort arm against task demand without assuming more is always better."""

    effort = _reasoning_effort(model)
    rank = _effort_rank(effort, policy)
    if rank is None:
        return 0.5
    settings = policy.get("effort_routing", {})
    demand = str(task.get("reasoning_demand") or "medium")
    target_effort = str((settings.get("target_by_reasoning_demand") or {}).get(demand, demand))
    target = _effort_rank(target_effort, policy)
    if target is None:
        return 0.5
    distance = rank - target
    per_level = float(settings.get("overprovision_penalty_per_level", 0.10)) if distance > 0 else float(settings.get("underprovision_penalty_per_level", 0.22))
    return max(0.0, min(1.0, 1.0 - abs(distance) * per_level))


def recommend_topology(task: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Choose a coordination shape from task properties, not organizational personas."""

    configured = policy.get("orchestration", {})
    if task.get("shared_mutable_state"):
        return {"topology": "single-agent", "reason": "shared-mutable-state", "max_concurrent_workers": 1}
    if task.get("dependency_structure") == "sequential":
        return {"topology": "single-agent", "reason": "sequential-dependencies", "max_concurrent_workers": 1}
    if task.get("tool_intensity") == "high" and task.get("decomposability") != "high":
        return {"topology": "single-agent", "reason": "tool-coordination-overhead", "max_concurrent_workers": 1}
    if task.get("decomposability") == "high" and task.get("dependency_structure") == "independent":
        return {
            "topology": "centralized-fanout",
            "reason": "independent-bounded-workstreams",
            "max_concurrent_workers": int(configured.get("max_concurrent_workers", 3)),
        }
    if task.get("decomposability") == "medium" and task.get("dependency_structure") in {"independent", "mixed"}:
        return {
            "topology": "lead-worker",
            "reason": "partially-decomposable",
            "max_concurrent_workers": min(2, int(configured.get("max_concurrent_workers", 3))),
        }
    return {"topology": "single-agent", "reason": "coordination-not-justified", "max_concurrent_workers": 1}


def eligible(model: dict[str, Any], task: dict[str, Any], agent: dict[str, Any] | None, policy: dict[str, Any], endpoint_health: dict[str, Any] | None = None) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if not model.get("enabled", False):
        reasons.append("disabled")
    if RISK.get(task["risk"], 99) > RISK.get(str(model.get("risk_ceiling", "low")), -1):
        reasons.append("risk-ceiling")
    if not _provider_allowed(model, task["privacy"], policy):
        reasons.append("privacy-provider")
    allowed_operations = {str(value) for value in model.get("allowed_operations", [])}
    if allowed_operations and task["operation"] not in allowed_operations:
        reasons.append("operation-scope")
    required = set(task.get("required_capabilities", []))
    if agent:
        required.update(agent.get("required_capabilities", []))
    missing = sorted(required - set(model.get("capabilities", [])))
    if missing:
        reasons.append("missing:" + ",".join(missing))
    if agent and MUTABILITY.get(task["mutability"], 99) > MUTABILITY.get(str(agent.get("allowed_mutability", "read-only")), -1):
        reasons.append("agent-mutability")
    candidates = set(agent.get("candidate_arms") or agent.get("candidate_models") or []) if agent else set()
    if candidates and _arm_id(model) not in candidates:
        reasons.append("not-in-agent-candidates")
    allowed_families = {str(value) for value in task.get("model_family_allowlist", [])}
    if allowed_families and _model_family(model) not in allowed_families:
        reasons.append("model-family")
    effort = _reasoning_effort(model)
    exact_effort = task.get("reasoning_effort")
    min_rank = _effort_rank(task.get("min_reasoning_effort"), policy)
    max_rank = _effort_rank(task.get("max_reasoning_effort"), policy)
    effort_rank = _effort_rank(effort, policy)
    if exact_effort and effort != exact_effort:
        reasons.append("reasoning-effort")
    if min_rank is not None and (effort_rank is None or effort_rank < min_rank):
        reasons.append("reasoning-effort-below-minimum")
    if max_rank is not None and (effort_rank is None or effort_rank > max_rank):
        reasons.append("reasoning-effort-above-maximum")
    if endpoint_health and endpoint_health.get("state") == "open-circuit":
        reasons.append("endpoint-open-circuit")
    return not reasons, reasons


def endpoint_health(store: IntelligenceStore, endpoint_id: str | None) -> dict[str, Any]:
    if not endpoint_id:
        return {"state": "unknown", "observations": 0, "success_rate": None}
    rows = store.query(
        "SELECT success,latency_seconds,rate_limited,observed_at FROM endpoint_observations WHERE endpoint_id=? ORDER BY observed_at DESC LIMIT 20",
        (endpoint_id,),
    )
    if not rows:
        return {"state": "unknown", "observations": 0, "success_rate": None}
    success_rate = sum(int(row["success"]) for row in rows) / len(rows)
    state = "healthy" if success_rate >= 0.85 else "degraded" if success_rate >= 0.55 else "open-circuit"
    return {
        "state": state,
        "observations": len(rows),
        "success_rate": round(success_rate, 6),
        "latency_mean": round(sum(float(row["latency_seconds"]) for row in rows) / len(rows), 6),
        "rate_limited": sum(int(row["rate_limited"]) for row in rows),
        "last_seen": rows[0]["observed_at"],
    }


def current_price(store: IntelligenceStore, model: dict[str, Any], at: str | None = None) -> dict[str, Any]:
    instant = at or now().replace("+00:00", "Z")
    row = store.one(
        """
        SELECT * FROM pricing_rules
        WHERE provider=? AND model_family=?
          AND (endpoint_id IS NULL OR endpoint_id=?)
          AND valid_from<=? AND (valid_to IS NULL OR valid_to>?)
        ORDER BY endpoint_id IS NOT NULL DESC, valid_from DESC LIMIT 1
        """,
        (str(model.get("provider", "")), str(model.get("model_family") or model.get("model", "")), model.get("endpoint_id"), instant, instant),
    )
    if not row:
        return {"price_rule_id": None, "cost_index": float(model.get("cost_hint", 0.5)), "source": "model-hint"}
    rule = json.loads(row["rule_json"])
    return {
        "price_rule_id": row["price_rule_id"],
        "cost_index": float(rule.get("cost_index", model.get("cost_hint", 0.5))),
        "input_per_million": rule.get("input_per_million"),
        "output_per_million": rule.get("output_per_million"),
        "currency": rule.get("currency", "USD"),
        "source": "effective-dated-rule",
    }


def _clamp(value: Any, default: float = 0.5) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _effective_profile(
    local: dict[str, Any] | None,
    fallback: dict[str, Any] | None,
    warm: dict[str, Any],
) -> dict[str, Any] | None:
    """Combine project evidence with a bounded inherited prior.

    Cross-project slices are never consumed at their full sample size.  They
    provide metric values only; ``warmup_states`` controls the equivalent
    evidence mass that is allowed to influence a new project.
    """

    inherited_n = max(0.0, float(warm.get("inherited_equivalent_observations", 0.0)))
    inherited_mean = warm.get("inherited_success_mean")
    if not local and (not fallback or inherited_n <= 0 or inherited_mean is None):
        return None

    local_n = float((local or {}).get("observations", 0.0))
    result = dict(local or fallback or {})
    result["observations"] = local_n + inherited_n
    result["local_observations"] = local_n
    result["inherited_equivalent_observations"] = inherited_n

    if inherited_n > 0 and inherited_mean is not None:
        success = dict((local or {}).get("success") or {})
        local_successes = max(0.0, float(success.get("alpha", 1.0)) - 1.0) if local else 0.0
        combined_success = (1.0 + local_successes + inherited_n * float(inherited_mean)) / (2.0 + local_n + inherited_n)
        result["success"] = {**success, "posterior_mean": round(combined_success, 6)}

        for field in ("quality", "verified_progress"):
            local_value = (((local or {}).get(field) or {}).get("mean"))
            fallback_value = (((fallback or {}).get(field) or {}).get("mean"))
            if local_value is None:
                combined = fallback_value
            elif fallback_value is None or inherited_n == 0:
                combined = local_value
            else:
                combined = (float(local_value) * local_n + float(fallback_value) * inherited_n) / (local_n + inherited_n)
            if combined is not None:
                result[field] = {**((local or {}).get(field) or {}), "mean": round(float(combined), 6)}
    return result


def _score(model: dict[str, Any], task: dict[str, Any], profile: dict[str, Any] | None, source: str, total_obs: int, policy: dict[str, Any], health: dict[str, Any], price: dict[str, Any]) -> tuple[float, dict[str, float]]:
    operation = task["operation"]
    affinity = model.get("task_affinity", {})
    prior = _clamp(affinity.get(operation, affinity.get(task.get("type"), 0.5)))
    observations = float((profile or {}).get("observations", 0.0))
    minimum = max(1, int(policy.get("minimum_observations_for_empirical_routing", 5)))
    empirical_weight = min(0.85, observations / minimum * 0.55)
    empirical_quality = _clamp(((profile or {}).get("quality") or {}).get("mean", prior), prior)
    empirical_success = _clamp(((profile or {}).get("success") or {}).get("posterior_mean", 0.5), 0.5)
    progress = _clamp(((profile or {}).get("verified_progress") or {}).get("mean", empirical_success), empirical_success)
    quality = (1.0 - empirical_weight) * prior + empirical_weight * empirical_quality
    success = (1.0 - empirical_weight) * 0.5 + empirical_weight * empirical_success
    progress_value = (1.0 - empirical_weight) * prior + empirical_weight * progress
    cost = _clamp(price.get("cost_index", model.get("cost_hint", 0.5)))
    latency = _clamp(model.get("latency_hint", 0.5))
    if profile:
        median_latency = float((profile.get("latency_seconds") or {}).get("median", 0.0))
        latency = min(1.0, median_latency / max(1.0, float(policy.get("latency_reference_seconds", 300.0))))
    correction = _clamp((profile or {}).get("human_correction_mean", 0.0), 0.0)
    disagreement = _clamp((profile or {}).get("verifier_disagreement_mean", 0.0), 0.0)
    operational_risk = 0.0 if health["state"] in {"healthy", "unknown"} else 0.2 if health["state"] == "degraded" else 1.0
    reasoning_fit = _effort_fit(model, task, policy)
    exploration = 0.0
    exploration_policy = policy.get("exploration", {})
    if exploration_policy.get("enabled", True) and RISK[task["risk"]] <= RISK.get(str(exploration_policy.get("max_risk", "medium")), 1):
        coefficient = float(exploration_policy.get("ucb_coefficient", 0.08))
        exploration = min(float(exploration_policy.get("max_bonus", 0.12)), coefficient * math.sqrt(math.log(total_obs + 2.0) / (observations + 1.0)))
    weights = policy.get("weights", {})
    components = {
        "verified_progress": progress_value,
        "quality": quality,
        "success": success,
        "cost_penalty": cost,
        "latency_penalty": latency,
        "correction_penalty": correction,
        "verifier_disagreement_penalty": disagreement,
        "operational_risk_penalty": operational_risk,
        "reasoning_fit": reasoning_fit,
        "exploration_bonus": exploration,
    }
    score = (
        float(weights.get("verified_progress", 0.25)) * progress_value
        + float(weights.get("quality", 0.35)) * quality
        + float(weights.get("success", 0.18)) * success
        + float(weights.get("reasoning_fit", 0.12)) * reasoning_fit
        - float(weights.get("cost", 0.07)) * cost
        - float(weights.get("latency", 0.05)) * latency
        - float(weights.get("correction", 0.04)) * correction
        - float(weights.get("verifier_disagreement", 0.03)) * disagreement
        - float(weights.get("operational_risk", 0.12)) * operational_risk
        + exploration
    )
    return score, components


def recommend(store: IntelligenceStore, task_raw: dict[str, Any], *, agent_name: str | None = None, write: bool = True, random_seed: int | None = None) -> dict[str, Any]:
    task = normalize_task(task_raw)
    root = store.layout.root
    paths = governance_paths(root)
    models = (load_json(paths["models"], {"models": []}) or {}).get("models", [])
    agents = (load_json(paths["agents"], {"agents": []}) or {}).get("agents", [])
    policy = load_json(paths["policy"], {}) or {}
    agent = next((entry for entry in agents if entry.get("name") == agent_name), None) if agent_name else None
    if agent_name and not agent:
        raise ValueError(f"unknown agent: {agent_name}")
    if write and not store.query("SELECT 1 FROM profile_slices LIMIT 1"):
        rebuild_profiles(store)
    profiles = load_profiles(store)
    total_obs = int(store.scalar(
        """
        SELECT COUNT(*) n FROM evaluation_events e
        WHERE registry_eligible=1
          AND NOT EXISTS (
            SELECT 1 FROM evaluation_events replacement
            WHERE replacement.supersedes_event_id=e.event_id
          )
        """,
        default=0,
    ))
    ranked: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    project_id = str(task_raw.get("project_id") or root.name or "default")
    for model in models:
        arm_id = _arm_id(model)
        endpoint_id = model.get("endpoint_id") or model.get("base_url")
        health = endpoint_health(store, str(endpoint_id) if endpoint_id else None)
        ok, reasons = eligible(model, task, agent, policy, health)
        if not ok:
            rejected.append({"model_id": arm_id, "reasons": reasons})
            continue
        local_profile = profiles.get(scope_key(arm_id, project_id, None, task["operation"]))
        fallback_profile, fallback_source = best_profile(profiles, arm_id, task, project_id)
        prior_row = store.one(
            "SELECT 1 FROM warmup_states WHERE project_id=? AND arm_id=? AND operation=?",
            (project_id, arm_id, task["operation"]),
        )
        if prior_row:
            warm = warmup.warmup_state(store, project_id, arm_id, task["operation"], persist=write)
        else:
            warm = warmup.initialize_transfer(
                store,
                project_id=project_id,
                arm_id=arm_id,
                operation=task["operation"],
                primary_artifact=task.get("primary_artifact", "unknown"),
                acceptance_profile=task.get("acceptance_profile"),
                mode=str(policy.get("warmup_mode", "conservative")),
                persist=write,
            )
            warm = {
                **warm,
                "local_observations": int((local_profile or {}).get("observations", 0)),
                "calibration_progress": min(
                    1.0,
                    (int((local_profile or {}).get("observations", 0)) + min(float(warm.get("inherited_equivalent_observations", 0)), 2.0)) / 5.0,
                ),
            }
        profile = _effective_profile(local_profile, fallback_profile, warm)
        if local_profile:
            profile_source = "project-operation"
        elif float(warm.get("inherited_equivalent_observations", 0.0)) > 0:
            profile_source = f"soft-transfer:{fallback_source}"
        else:
            profile_source = "prior-only"
        price = current_price(store, model)
        score, components = _score(model, task, profile, profile_source, total_obs, policy, health, price)
        ranked.append({
            "model_id": arm_id,
            "provider": model.get("provider"),
            "model": model.get("model"),
            "model_family": _model_family(model),
            "reasoning_effort": _reasoning_effort(model),
            "reasoning_mode": model.get("reasoning_mode", "standard"),
            "execution": {
                "provider": model.get("provider"),
                "model": model.get("model"),
                "reasoning_effort": _reasoning_effort(model),
                "reasoning_mode": model.get("reasoning_mode", "standard"),
            },
            "endpoint_id": endpoint_id,
            "score": round(score, 6),
            "profile_source": profile_source,
            "observations": round(float((profile or {}).get("observations", 0.0)), 3),
            "local_observations": int(warm.get("local_observations", 0)),
            "inherited_equivalent_observations": round(float(warm.get("inherited_equivalent_observations", 0.0)), 3),
            "warmup": warm,
            "success_posterior": ((profile or {}).get("success") or {}).get("posterior_mean"),
            "uncertainty": "high" if float((profile or {}).get("observations", 0)) < int(policy.get("minimum_observations_for_empirical_routing", 5)) else "lower",
            "endpoint_health": health,
            "price": price,
            "components": {key: round(value, 6) for key, value in components.items()},
        })
    ranked.sort(key=lambda item: (-item["score"], str(item["model_id"])))
    if not ranked:
        raise ValueError("no eligible model; inspect rejected candidates")

    rng = random.Random(random_seed)
    top = ranked[0]
    exploration_probability = float(policy.get("exploration", {}).get("selection_probability", 0.0))
    selected = top
    selection_probability = 1.0
    if len(ranked) > 1 and exploration_probability > 0 and RISK[task["risk"]] <= RISK.get(str(policy.get("exploration", {}).get("max_risk", "medium")), 1):
        if rng.random() < exploration_probability:
            selected = rng.choice(ranked[1:min(4, len(ranked))])
            selection_probability = exploration_probability / min(3, len(ranked) - 1)
        else:
            selection_probability = 1.0 - exploration_probability

    strong_markers = set(policy.get("strong_verification_required_for", []))
    require_verifier = task["risk"] in {"high", "critical"} or task["mutability"] in {"hardware-write", "destructive"} or bool(strong_markers.intersection(set(task.get("tags", []))))
    verifier = None
    if require_verifier:
        verifier = next(
            (item for item in ranked if item["model_id"] != selected["model_id"] and item.get("model_family") != selected.get("model_family")),
            None,
        )
        verifier = verifier or next((item for item in ranked if item["model_id"] != selected["model_id"]), None)
    applicable_mitigations = [
        {
            "mitigation_id": item["mitigation_id"],
            "type": item["mitigation_type"],
            "status": item["status"],
            "revision": item["revision"],
        }
        for item in mitigations.applicable(
            store,
            arm_id=selected["model_id"],
            project_id=project_id,
            operation=task["operation"],
            task_id=task_raw.get("task_id"),
        )
    ]
    decision_id = f"route-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:6]}"
    orchestration = recommend_topology(task, policy)
    orchestration.update({
        "lead_required": orchestration["topology"] != "single-agent",
        "max_delegation_depth": int(policy.get("orchestration", {}).get("max_delegation_depth", 2)),
        "task_partitioning": "work-unit" if orchestration["topology"] != "single-agent" else "none",
    })
    visible_reason = [
        f"best available evidence for {task['operation']}",
        f"model={selected['model_family']}",
        f"effort={selected['reasoning_effort'] or 'provider-default'}",
        f"profile={selected['profile_source']}",
        f"endpoint={selected['endpoint_health']['state']}",
        f"uncertainty={selected['uncertainty']}",
        f"topology={orchestration['topology']}",
    ]
    decision = {
        "schema_version": 4,
        "decision_id": decision_id,
        "created_at": now(),
        "project_id": project_id,
        "task": task,
        "agent": agent_name,
        "primary": selected,
        "verifier": verifier,
        "orchestration": orchestration,
        "verification_policy": {
            "independent_required": require_verifier,
            "acceptance_profile": task.get("acceptance_profile"),
            "recommended_verifier_arm": (verifier or {}).get("model_id"),
        },
        "applicable_mitigations": applicable_mitigations,
        "ranked": ranked,
        "rejected": rejected,
        "selection_probability": round(selection_probability, 6),
        "visible_reason": visible_reason,
        "internal_score_factors_hidden_by_default": True,
        "policy_version": str(policy.get("schema_version", 2)),
    }
    if write:
        with store.transaction() as connection:
            connection.execute(
                "INSERT INTO route_decisions(decision_id,created_at,project_id,task_json,selected_arm_id,selected_endpoint_id,selection_probability,policy_version,summary_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    decision_id, decision["created_at"], project_id,
                    json.dumps(task, ensure_ascii=False, sort_keys=True), selected["model_id"],
                    selected.get("endpoint_id"), selection_probability, decision["policy_version"],
                    json.dumps(decision, ensure_ascii=False, sort_keys=True),
                ),
            )
            for rank, candidate in enumerate(ranked, start=1):
                connection.execute(
                    """
                    INSERT INTO route_candidate_scores(
                        decision_id,arm_id,rank,selected,score,reasoning_effort,reasoning_mode,
                        profile_source,observations,uncertainty,components_json,endpoint_health_json,
                        price_json,execution_json,created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        decision_id,
                        candidate["model_id"],
                        rank,
                        int(candidate["model_id"] == selected["model_id"]),
                        candidate["score"],
                        candidate.get("reasoning_effort"),
                        candidate.get("reasoning_mode", "standard"),
                        candidate["profile_source"],
                        candidate["observations"],
                        candidate["uncertainty"],
                        json.dumps(candidate["components"], ensure_ascii=False, sort_keys=True),
                        json.dumps(candidate["endpoint_health"], ensure_ascii=False, sort_keys=True),
                        json.dumps(candidate["price"], ensure_ascii=False, sort_keys=True),
                        json.dumps(candidate["execution"], ensure_ascii=False, sort_keys=True),
                        decision["created_at"],
                    ),
                )
    return decision
