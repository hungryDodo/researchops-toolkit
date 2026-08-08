from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
import uuid
from pathlib import Path
from typing import Any, Protocol

from ..common import now
from .store import IntelligenceStore

MEMORY_VERSION = "memory-v2.1"
LAYERS = {"episodic", "semantic", "procedural", "preference"}
STATUSES = {"active", "candidate", "superseded", "retired"}
RELATIONS = {"supersedes", "derived_from", "supports", "contradicts", "mitigates", "related_to"}


class RecallAdapter(Protocol):
    """Optional recall adapter.

    An adapter may improve recall, but it never becomes an authority for model
    profiles, approvals, pricing, or risk decisions.
    """

    def search(self, query: str, scope: str, as_of: str | None, limit: int) -> list[dict[str, Any]]: ...
    def publish(self, items: list[dict[str, Any]]) -> dict[str, Any]: ...


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash(scope: str, layer: str, kind: str, title: str, body: str) -> str:
    payload = "\0".join((scope.strip(), layer.strip(), kind.strip(), title.strip(), body.strip()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _scope_match(requested: str, candidate: str) -> float:
    if requested == "*":
        return 0.75
    if requested == candidate:
        return 1.0
    # Hierarchical scopes use slash-separated segments, for example
    # project/edgeweaver/task/debug. Parent memories remain useful, but weaker.
    req = requested.rstrip("/")
    cand = candidate.rstrip("/")
    if req.startswith(cand + "/"):
        return 0.88
    if cand.startswith(req + "/"):
        return 0.82
    if req.split("/")[0:2] == cand.split("/")[0:2] and len(req.split("/")) >= 2:
        return 0.55
    if candidate in {"global", "user"}:
        return 0.45
    return 0.0


def add(
    store: IntelligenceStore,
    *,
    scope: str,
    kind: str,
    title: str,
    body: str,
    layer: str = "semantic",
    status: str = "active",
    confidence: float = 1.0,
    salience: float = 0.5,
    provenance: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    merge_duplicate: bool = True,
) -> dict[str, Any]:
    """Write one memory item, idempotently by scoped content hash.

    Duplicate observations enrich provenance/confidence/salience rather than
    creating an unbounded pile of near-identical rows.
    """

    if layer not in LAYERS:
        raise ValueError(f"unsupported memory layer: {layer}")
    if status not in STATUSES:
        raise ValueError(f"unsupported memory status: {status}")
    if not scope.strip() or not title.strip() or not body.strip():
        raise ValueError("scope, title, and body must be non-empty")
    created_at = now()
    digest = _content_hash(scope, layer, kind, title, body)
    clean_provenance = provenance or {}
    clean_metadata = metadata or {}
    with store.transaction() as connection:
        existing = connection.execute(
            "SELECT * FROM memory_items WHERE scope=? AND content_hash=?",
            (scope, digest),
        ).fetchone()
        if existing and merge_duplicate:
            old_provenance = json.loads(existing["provenance_json"] or "{}")
            observations = list(old_provenance.get("observations", []))
            incoming = clean_provenance.get("observations")
            if isinstance(incoming, list):
                observations.extend(incoming)
            elif clean_provenance:
                observations.append(clean_provenance)
            # Keep a bounded representative history.
            merged_provenance = {**old_provenance, **clean_provenance}
            if observations:
                unique: list[Any] = []
                seen: set[str] = set()
                for item in observations[-25:]:
                    marker = _json(item)
                    if marker not in seen:
                        seen.add(marker)
                        unique.append(item)
                merged_provenance["observations"] = unique
            merged_metadata = {**json.loads(existing["metadata_json"] or "{}"), **clean_metadata}
            new_confidence = max(float(existing["confidence"]), _clamp(confidence))
            new_salience = max(float(existing["salience"]), _clamp(salience))
            connection.execute(
                """
                UPDATE memory_items
                SET updated_at=?,confidence=?,salience=?,status=?,valid_from=COALESCE(?,valid_from),
                    valid_to=?,source_type=COALESCE(?,source_type),source_id=COALESCE(?,source_id),
                    metadata_json=?,provenance_json=?
                WHERE memory_id=?
                """,
                (
                    created_at,
                    new_confidence,
                    new_salience,
                    status if existing["status"] != "superseded" else existing["status"],
                    valid_from,
                    valid_to,
                    source_type,
                    source_id,
                    _json(merged_metadata),
                    _json(merged_provenance),
                    existing["memory_id"],
                ),
            )
            return {
                "memory_id": existing["memory_id"],
                "scope": scope,
                "layer": layer,
                "kind": kind,
                "created": False,
                "deduplicated": True,
                "updated_at": created_at,
            }

        memory_id = f"mem-{uuid.uuid4().hex[:16]}"
        connection.execute(
            """
            INSERT INTO memory_items(
                memory_id,scope,layer,kind,status,title,body,created_at,updated_at,
                valid_from,valid_to,confidence,salience,access_count,last_accessed_at,
                content_hash,source_type,source_id,metadata_json,provenance_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0,NULL,?,?,?,?,?)
            """,
            (
                memory_id,
                scope,
                layer,
                kind,
                status,
                title.strip(),
                body.strip(),
                created_at,
                created_at,
                valid_from,
                valid_to,
                _clamp(confidence),
                _clamp(salience),
                digest,
                source_type,
                source_id,
                _json(clean_metadata),
                _json(clean_provenance),
            ),
        )
        connection.execute("INSERT INTO memory_fts(memory_id,title,body) VALUES (?,?,?)", (memory_id, title.strip(), body.strip()))
    return {
        "memory_id": memory_id,
        "scope": scope,
        "layer": layer,
        "kind": kind,
        "created": True,
        "deduplicated": False,
        "created_at": created_at,
    }


def get(store: IntelligenceStore, memory_id: str) -> dict[str, Any] | None:
    row = store.one("SELECT * FROM memory_items WHERE memory_id=?", (memory_id,))
    if not row:
        return None
    row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
    row["provenance"] = json.loads(row.pop("provenance_json") or "{}")
    row["relations_out"] = store.query(
        "SELECT target_id,relation_type FROM memory_relations WHERE source_id=? ORDER BY relation_type,target_id",
        (memory_id,),
    )
    row["relations_in"] = store.query(
        "SELECT source_id,relation_type FROM memory_relations WHERE target_id=? ORDER BY relation_type,source_id",
        (memory_id,),
    )
    row["authoritative"] = False
    return row


def relate(store: IntelligenceStore, source_id: str, target_id: str, relation_type: str) -> dict[str, str]:
    if relation_type not in RELATIONS:
        raise ValueError("unsupported memory relation")
    if not store.one("SELECT memory_id FROM memory_items WHERE memory_id=?", (source_id,)):
        raise ValueError(f"unknown source memory: {source_id}")
    if not store.one("SELECT memory_id FROM memory_items WHERE memory_id=?", (target_id,)):
        raise ValueError(f"unknown target memory: {target_id}")
    with store.transaction() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO memory_relations(source_id,target_id,relation_type) VALUES (?,?,?)",
            (source_id, target_id, relation_type),
        )
    return {"source_id": source_id, "target_id": target_id, "relation_type": relation_type}


def retire(store: IntelligenceStore, memory_id: str, *, reason: str = "", status: str = "retired") -> dict[str, Any]:
    if status not in {"retired", "superseded"}:
        raise ValueError("retire status must be retired or superseded")
    timestamp = now()
    with store.transaction() as connection:
        row = connection.execute("SELECT metadata_json FROM memory_items WHERE memory_id=?", (memory_id,)).fetchone()
        if not row:
            raise ValueError(f"unknown memory: {memory_id}")
        metadata = json.loads(row["metadata_json"] or "{}")
        if reason:
            metadata["retirement_reason"] = reason
        connection.execute(
            "UPDATE memory_items SET status=?,valid_to=COALESCE(valid_to,?),updated_at=?,metadata_json=? WHERE memory_id=?",
            (status, timestamp, timestamp, _json(metadata), memory_id),
        )
    return {"memory_id": memory_id, "status": status, "valid_to": timestamp, "reason": reason}


def supersede(store: IntelligenceStore, old_id: str, new_id: str, *, reason: str = "") -> dict[str, Any]:
    relate(store, new_id, old_id, "supersedes")
    retired = retire(store, old_id, reason=reason or f"superseded by {new_id}", status="superseded")
    return {"old": retired, "new_id": new_id, "relation": "supersedes"}


def _fts_query(query: str) -> str:
    tokens = [token for token in re.findall(r"[\w-]+", query, flags=re.UNICODE) if len(token) > 1]
    if not tokens:
        return '"' + query.replace('"', ' ') + '"'
    return " OR ".join('"' + token.replace('"', '') + '"' for token in tokens[:20])


def search(
    store: IntelligenceStore,
    query: str,
    *,
    scope: str = "*",
    limit: int = 10,
    as_of: str | None = None,
    layers: list[str] | None = None,
    include_candidates: bool = False,
) -> list[dict[str, Any]]:
    """Hybrid local recall with provenance, lifecycle and scope controls."""

    if not query.strip():
        return []
    selected_layers = [layer for layer in (layers or []) if layer in LAYERS]
    statuses = ["active"] + (["candidate"] if include_candidates else [])
    as_of_value = as_of or now()
    clauses = ["memory_fts MATCH ?", "m.status IN (" + ",".join("?" for _ in statuses) + ")"]
    params: list[Any] = [_fts_query(query), *statuses]
    if selected_layers:
        clauses.append("m.layer IN (" + ",".join("?" for _ in selected_layers) + ")")
        params.extend(selected_layers)
    clauses.extend([
        "(m.valid_from IS NULL OR m.valid_from<=?)",
        "(m.valid_to IS NULL OR m.valid_to>?)",
    ])
    params.extend([as_of_value, as_of_value])
    candidate_limit = max(limit * 8, 40)
    params.append(candidate_limit)
    rows = store.query(
        f"""
        SELECT m.*,bm25(memory_fts) bm25_rank
        FROM memory_fts JOIN memory_items m USING(memory_id)
        WHERE {' AND '.join(clauses)}
        ORDER BY bm25_rank LIMIT ?
        """,
        tuple(params),
    )
    instant = _parse_time(as_of_value) or dt.datetime.now(dt.timezone.utc)
    hits: list[dict[str, Any]] = []
    for row in rows:
        scope_score = _scope_match(scope, str(row["scope"]))
        if scope_score <= 0:
            continue
        age = max(0.0, (instant - (_parse_time(row.get("updated_at")) or instant)).total_seconds())
        recency = math.exp(-age / (120.0 * 86400.0))
        # FTS5 bm25 is lower/better and commonly negative. Convert it to a
        # bounded relevance term without pretending it is a calibrated score.
        rank = float(row.pop("bm25_rank", 0.0))
        lexical = 1.0 / (1.0 + abs(rank))
        confidence = _clamp(float(row.get("confidence", 0.5)))
        salience = _clamp(float(row.get("salience", 0.5)))
        score = (
            0.45 * lexical
            + 0.20 * scope_score
            + 0.13 * confidence
            + 0.12 * salience
            + 0.10 * recency
        )
        row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
        row["provenance"] = json.loads(row.pop("provenance_json") or "{}")
        row["recall"] = {
            "score": round(score, 6),
            "lexical": round(lexical, 6),
            "scope": round(scope_score, 6),
            "recency": round(recency, 6),
            "memory_version": MEMORY_VERSION,
        }
        row["authoritative"] = False
        hits.append(row)
    hits.sort(key=lambda item: (-item["recall"]["score"], -float(item["confidence"]), item["memory_id"]))
    hits = hits[:limit]
    if hits:
        timestamp = now()
        with store.transaction() as connection:
            connection.executemany(
                "UPDATE memory_items SET access_count=access_count+1,last_accessed_at=? WHERE memory_id=?",
                [(timestamp, hit["memory_id"]) for hit in hits],
            )
    for hit in hits:
        hit["relations"] = store.query(
            """
            SELECT source_id,target_id,relation_type FROM memory_relations
            WHERE source_id=? OR target_id=? ORDER BY relation_type,source_id,target_id
            """,
            (hit["memory_id"], hit["memory_id"]),
        )
    return hits


def context_bundle(
    store: IntelligenceStore,
    query: str,
    *,
    scope: str = "*",
    max_items: int = 8,
    max_chars: int = 6000,
    as_of: str | None = None,
) -> dict[str, Any]:
    hits = search(store, query, scope=scope, limit=max_items, as_of=as_of)
    items: list[dict[str, Any]] = []
    used = 0
    for hit in hits:
        body = str(hit["body"])
        allowance = max(0, max_chars - used)
        if allowance <= 80:
            break
        clipped = body if len(body) <= allowance else body[: max(0, allowance - 1)] + "…"
        item = {
            "memory_id": hit["memory_id"],
            "scope": hit["scope"],
            "layer": hit["layer"],
            "kind": hit["kind"],
            "title": hit["title"],
            "body": clipped,
            "confidence": hit["confidence"],
            "valid_from": hit["valid_from"],
            "valid_to": hit["valid_to"],
            "provenance": hit["provenance"],
            "recall_score": hit["recall"]["score"],
        }
        items.append(item)
        used += len(clipped)
    return {
        "schema_version": 1,
        "generated_at": now(),
        "query": query,
        "scope": scope,
        "items": items,
        "characters": used,
        "authoritative": False,
        "instruction": "Treat these as recalled context. Verify consequential claims against authoritative project state or evidence.",
    }


def _project_id(store: IntelligenceStore) -> str:
    row = store.one("SELECT project_id FROM projects ORDER BY updated_at DESC LIMIT 1")
    return str(row["project_id"]) if row else store.layout.root.name or "default"


def _remember_source(
    store: IntelligenceStore,
    *,
    scope: str,
    layer: str,
    kind: str,
    title: str,
    body: str,
    source_type: str,
    source_id: str,
    confidence: float,
    salience: float,
    provenance: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    previous = store.one(
        """
        SELECT memory_id,content_hash FROM memory_items
        WHERE source_type=? AND source_id=? AND status IN ('active','candidate')
        ORDER BY updated_at DESC LIMIT 1
        """,
        (source_type, source_id),
    )
    result = add(
        store,
        scope=scope,
        layer=layer,
        kind=kind,
        title=title,
        body=body,
        source_type=source_type,
        source_id=source_id,
        confidence=confidence,
        salience=salience,
        provenance=provenance,
        metadata=metadata,
    )
    if previous and previous["memory_id"] != result["memory_id"]:
        supersede(store, previous["memory_id"], result["memory_id"], reason=f"{source_type}:{source_id} was updated")
        result["superseded_memory_id"] = previous["memory_id"]
    return result


def sync_from_project(store: IntelligenceStore) -> dict[str, Any]:
    """Idempotently derive useful recall items from authoritative local state."""

    started_at = now()
    project_id = _project_id(store)
    project_scope = f"project/{project_id}"
    results: list[dict[str, Any]] = []
    sources: dict[str, int] = {}

    intake_path = store.layout.state / "onboarding" / "current.json"
    if intake_path.exists():
        try:
            assessment = json.loads(intake_path.read_text(encoding="utf-8"))
            inference = assessment.get("inference", {})
            inventory = assessment.get("inventory", {})
            categories = inventory.get("categories", {})
            body = (
                f"Adoption mode: {assessment.get('adoption_mode')}. "
                f"Inferred phase: {inference.get('phase')} ({inference.get('confidence')} confidence). "
                f"Focus: {inference.get('focus')} "
                f"Inventory: {inventory.get('file_count', 0)} files; categories={categories}. "
                f"Blocking uncertainty: {inference.get('blocking_uncertainty')}"
            )
            results.append(_remember_source(
                store,
                scope=project_scope,
                layer="semantic",
                kind="project-intake",
                title="Current project intake assessment",
                body=body,
                source_type="project_snapshot",
                source_id="current",
                confidence=float(inference.get("confidence", 0.5)),
                salience=0.9,
                provenance={"path": str(intake_path), "generated_at": assessment.get("generated_at")},
                metadata={"adoption_mode": assessment.get("adoption_mode"), "phase": inference.get("phase")},
            ))
            sources["project_snapshot"] = 1
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            sources["project_snapshot_error"] = 1

    decisions_path = store.layout.state / "decisions.md"
    if decisions_path.exists():
        text = decisions_path.read_text(encoding="utf-8", errors="ignore")
        chunks = [chunk.strip() for chunk in re.split(r"(?m)^##+\s+", text) if chunk.strip()]
        for index, chunk in enumerate(chunks[:50]):
            lines = [line.strip() for line in chunk.splitlines() if line.strip()]
            if not lines:
                continue
            first = re.sub(r"^#+\s*", "", lines[0]).strip()
            if first.lower() == "decisions" and len(lines) == 1:
                continue
            if first.lower() == "decisions":
                lines = lines[1:]
                if not lines:
                    continue
                first = re.sub(r"^#+\s*", "", lines[0]).strip()
            title = first[:180]
            body = "\n".join(lines[1:] or [first])[:4000]
            results.append(_remember_source(
                store,
                scope=project_scope,
                layer="semantic",
                kind="project-decision",
                title=title,
                body=body,
                source_type="decision_log",
                source_id=f"{decisions_path}:{index}",
                confidence=0.9,
                salience=0.85,
                provenance={"path": str(decisions_path), "section": index},
            ))
        sources["decision_log"] = max(0, len(chunks) - 1)

    events = store.json_rows(
        """
        SELECT event_id,occurred_at,project_id,task_id,work_unit_id,execution_arm_id,
               operation,primary_artifact,accepted,verified_progress,quality,task_json,
               verification_json
        FROM evaluation_events
        WHERE registry_eligible=1 AND accepted=1
        ORDER BY occurred_at DESC LIMIT 250
        """,
        json_columns=("task_json", "verification_json"),
    )
    for event in events:
        task = event.get("task_json") or {}
        objective = task.get("objective") or event.get("task_id") or event["event_id"]
        body = (
            f"{objective}. Executed by {event['execution_arm_id']} as {event['operation']} / "
            f"{event['primary_artifact']}; verified progress={float(event['verified_progress']):.3f}, "
            f"quality={float(event['quality']):.3f}."
        )
        results.append(_remember_source(
            store,
            scope=f"project/{event['project_id']}/task/{event['operation']}",
            layer="episodic",
            kind="accepted-work-unit",
            title=f"Accepted {event['operation']} work: {str(objective)[:140]}",
            body=body,
            source_type="evaluation_event",
            source_id=event["event_id"],
            confidence=max(0.5, min(1.0, (float(event["quality"]) + float(event["verified_progress"])) / 2.0)),
            salience=max(0.5, float(event["verified_progress"])),
            provenance={
                "event_id": event["event_id"],
                "verification": event.get("verification_json") or {},
                "occurred_at": event["occurred_at"],
            },
            metadata={"arm_id": event["execution_arm_id"], "operation": event["operation"]},
        ))
    sources["evaluation_event"] = len(events)

    patterns = store.json_rows(
        "SELECT * FROM failure_patterns WHERE status IN ('active','candidate') ORDER BY last_seen DESC",
        json_columns=("representative_json",),
    )
    for pattern in patterns:
        body = (
            f"Failure pattern {pattern['code']} attributed to {pattern['attribution']} for "
            f"{pattern.get('operation') or 'general work'}. Occurrences={pattern['occurrence_count']}; "
            f"severity={pattern['severity']}; confidence={pattern['confidence']}."
        )
        results.append(_remember_source(
            store,
            scope=f"project/{project_id}/task/{pattern.get('operation') or 'general'}",
            layer="procedural",
            kind="failure-pattern",
            title=f"Watch for: {pattern['code']}",
            body=body,
            source_type="failure_pattern",
            source_id=pattern["pattern_id"],
            confidence=float(pattern["confidence"]),
            salience=0.9 if pattern["severity"] in {"high", "critical"} else 0.7,
            provenance={"pattern_id": pattern["pattern_id"], "representative": pattern["representative_json"]},
            metadata={"arm_id": pattern["arm_id"], "status": pattern["status"]},
        ))
    sources["failure_pattern"] = len(patterns)

    mitigations = store.json_rows(
        "SELECT * FROM mitigations WHERE status IN ('approved','canary','active') ORDER BY proposed_at DESC",
        json_columns=("scope_json", "content_json", "metadata_json"),
    )
    for mitigation in mitigations:
        content = mitigation.get("content_json") or {}
        text = content.get("instruction") or content.get("text") or _json(content)
        scope_json = mitigation.get("scope_json") or {}
        operation = scope_json.get("operation") or "general"
        results.append(_remember_source(
            store,
            scope=f"project/{project_id}/task/{operation}",
            layer="procedural",
            kind="approved-mitigation",
            title=f"Mitigation: {mitigation['mitigation_type']}",
            body=str(text),
            source_type="mitigation",
            source_id=mitigation["mitigation_id"],
            confidence=0.95,
            salience=0.95 if mitigation["status"] == "active" else 0.75,
            provenance={"mitigation_id": mitigation["mitigation_id"], "status": mitigation["status"]},
            metadata={"revision": mitigation["revision"], "scope": scope_json},
        ))
    sources["mitigation"] = len(mitigations)

    completed_at = now()
    summary = {
        "created": sum(1 for item in results if item.get("created")),
        "deduplicated": sum(1 for item in results if item.get("deduplicated")),
        "processed": len(results),
        "sources": sources,
    }
    sync_id = f"msync-{uuid.uuid4().hex[:16]}"
    with store.transaction() as connection:
        connection.execute(
            "INSERT INTO memory_sync_runs(sync_id,started_at,completed_at,project_id,sources_json,summary_json) VALUES (?,?,?,?,?,?)",
            (sync_id, started_at, completed_at, project_id, _json(sources), _json(summary)),
        )
    return {"sync_id": sync_id, "started_at": started_at, "completed_at": completed_at, **summary}


def status(store: IntelligenceStore) -> dict[str, Any]:
    counts = store.query(
        "SELECT layer,status,COUNT(*) count FROM memory_items GROUP BY layer,status ORDER BY layer,status"
    )
    latest = store.one(
        "SELECT sync_id,started_at,completed_at,project_id,sources_json,summary_json FROM memory_sync_runs ORDER BY completed_at DESC LIMIT 1"
    )
    if latest:
        latest["sources"] = json.loads(latest.pop("sources_json") or "{}")
        latest["summary"] = json.loads(latest.pop("summary_json") or "{}")
    return {
        "memory_version": MEMORY_VERSION,
        "total": int(store.scalar("SELECT COUNT(*) n FROM memory_items", default=0)),
        "active": int(store.scalar("SELECT COUNT(*) n FROM memory_items WHERE status='active'", default=0)),
        "by_layer_status": counts,
        "relations": int(store.scalar("SELECT COUNT(*) n FROM memory_relations", default=0)),
        "last_sync": latest,
        "authority": False,
        "backend": "sqlite-fts5",
    }
