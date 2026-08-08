from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterator

from ..layout import ProjectLayout, layout

SCHEMA_VERSION = 3

SCHEMA = r"""
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    root TEXT NOT NULL,
    title TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS project_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    adoption_mode TEXT NOT NULL,
    root_digest TEXT NOT NULL,
    assessment_json TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(project_id)
);
CREATE INDEX IF NOT EXISTS idx_project_snapshots ON project_snapshots(project_id, captured_at);
CREATE TABLE IF NOT EXISTS execution_arms (
    arm_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_family TEXT NOT NULL,
    model_revision TEXT,
    endpoint_id TEXT,
    deployment_epoch TEXT NOT NULL DEFAULT 'epoch-1',
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evaluation_events (
    event_id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_id TEXT,
    work_unit_id TEXT,
    route_decision_id TEXT,
    source TEXT NOT NULL CHECK(source IN ('live','shadow','anchor')),
    execution_arm_id TEXT NOT NULL,
    orientation TEXT NOT NULL,
    operation TEXT NOT NULL,
    primary_artifact TEXT NOT NULL,
    risk TEXT NOT NULL,
    privacy TEXT NOT NULL,
    mutability TEXT NOT NULL,
    accepted INTEGER NOT NULL,
    verified_progress REAL NOT NULL,
    quality REAL NOT NULL,
    human_correction REAL NOT NULL,
    verifier_disagreement REAL NOT NULL,
    cost_amount REAL NOT NULL,
    currency TEXT NOT NULL,
    latency_seconds REAL NOT NULL,
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    selection_probability REAL,
    registry_eligible INTEGER NOT NULL,
    task_json TEXT NOT NULL,
    outcome_json TEXT NOT NULL,
    usage_json TEXT NOT NULL,
    verification_json TEXT NOT NULL,
    versions_json TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    supersedes_event_id TEXT,
    FOREIGN KEY(supersedes_event_id) REFERENCES evaluation_events(event_id)
);
CREATE INDEX IF NOT EXISTS idx_eval_arm_time ON evaluation_events(execution_arm_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_eval_project_operation ON evaluation_events(project_id, operation, occurred_at);
CREATE INDEX IF NOT EXISTS idx_eval_eligible ON evaluation_events(registry_eligible, source);
CREATE TABLE IF NOT EXISTS route_decisions (
    decision_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    project_id TEXT NOT NULL,
    task_json TEXT NOT NULL,
    selected_arm_id TEXT,
    selected_endpoint_id TEXT,
    selection_probability REAL,
    policy_version TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS endpoint_observations (
    observation_id TEXT PRIMARY KEY,
    observed_at TEXT NOT NULL,
    endpoint_id TEXT NOT NULL,
    arm_id TEXT,
    success INTEGER NOT NULL,
    latency_seconds REAL NOT NULL,
    ttft_seconds REAL,
    error_class TEXT,
    rate_limited INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_endpoint_obs ON endpoint_observations(endpoint_id, observed_at);
CREATE TABLE IF NOT EXISTS pricing_rules (
    price_rule_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model_family TEXT NOT NULL,
    endpoint_id TEXT,
    valid_from TEXT NOT NULL,
    valid_to TEXT,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    rule_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profile_slices (
    scope_key TEXT PRIMARY KEY,
    arm_id TEXT NOT NULL,
    project_id TEXT,
    orientation TEXT,
    operation TEXT,
    generated_at TEXT NOT NULL,
    aggregator_version TEXT NOT NULL,
    event_count INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_profile_arm ON profile_slices(arm_id, project_id, operation);
CREATE TABLE IF NOT EXISTS failure_observations (
    observation_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    arm_id TEXT NOT NULL,
    code TEXT NOT NULL,
    attribution TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL,
    evidence_ref TEXT,
    observed_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES evaluation_events(event_id)
);
CREATE INDEX IF NOT EXISTS idx_failure_obs ON failure_observations(arm_id, code, observed_at);
CREATE TABLE IF NOT EXISTS failure_patterns (
    pattern_id TEXT PRIMARY KEY,
    arm_id TEXT NOT NULL,
    orientation TEXT,
    operation TEXT,
    code TEXT NOT NULL,
    attribution TEXT NOT NULL,
    status TEXT NOT NULL,
    occurrence_count INTEGER NOT NULL,
    recent_occurrence_count INTEGER NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    representative_json TEXT NOT NULL,
    UNIQUE(arm_id, orientation, operation, code, attribution)
);
CREATE TABLE IF NOT EXISTS mitigations (
    mitigation_id TEXT PRIMARY KEY,
    mitigation_type TEXT NOT NULL,
    status TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    content_json TEXT NOT NULL,
    revision INTEGER NOT NULL,
    proposed_at TEXT NOT NULL,
    approved_at TEXT,
    approved_by TEXT,
    expires_at TEXT,
    supersedes_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS mitigation_pattern_links (
    mitigation_id TEXT NOT NULL,
    pattern_id TEXT NOT NULL,
    PRIMARY KEY(mitigation_id, pattern_id),
    FOREIGN KEY(mitigation_id) REFERENCES mitigations(mitigation_id),
    FOREIGN KEY(pattern_id) REFERENCES failure_patterns(pattern_id)
);
CREATE TABLE IF NOT EXISTS mitigation_trials (
    trial_id TEXT PRIMARY KEY,
    mitigation_id TEXT NOT NULL,
    event_id TEXT,
    mode TEXT NOT NULL,
    applied INTEGER NOT NULL,
    outcome_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    approval_id TEXT PRIMARY KEY,
    approval_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    approved_by TEXT NOT NULL,
    approved_at TEXT NOT NULL,
    expires_at TEXT,
    one_use INTEGER NOT NULL DEFAULT 0,
    consumed_at TEXT,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS warmup_states (
    project_id TEXT NOT NULL,
    arm_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    initialization TEXT NOT NULL,
    inherited_equivalent_observations REAL NOT NULL,
    inherited_success_mean REAL,
    transfer_status TEXT NOT NULL,
    rationale_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(project_id, arm_id, operation)
);
CREATE TABLE IF NOT EXISTS identity_observations (
    observation_id TEXT PRIMARY KEY,
    arm_id TEXT NOT NULL,
    endpoint_id TEXT,
    observed_at TEXT NOT NULL,
    declared_identity_json TEXT NOT NULL,
    fingerprint_json TEXT NOT NULL,
    signal_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS deployment_epochs (
    epoch_id TEXT PRIMARY KEY,
    arm_base_id TEXT NOT NULL,
    endpoint_id TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    declared_identity_json TEXT NOT NULL,
    fingerprint_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS drift_events (
    drift_id TEXT PRIMARY KEY,
    arm_id TEXT NOT NULL,
    endpoint_id TEXT,
    detected_at TEXT NOT NULL,
    drift_type TEXT NOT NULL,
    status TEXT NOT NULL,
    signals_json TEXT NOT NULL,
    response_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS judge_observations (
    observation_id TEXT PRIMARY KEY,
    judge_arm_id TEXT NOT NULL,
    task_family TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    agrees_with_reference INTEGER,
    position_consistent INTEGER,
    abstained INTEGER NOT NULL,
    confidence REAL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS judge_pairwise_observations (
    pairwise_id TEXT PRIMARY KEY,
    judge_arm_id TEXT NOT NULL,
    task_family TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    item_a TEXT NOT NULL,
    item_b TEXT NOT NULL,
    first_result TEXT NOT NULL CHECK(first_result IN ('a','b','tie','abstain')),
    swapped_result TEXT CHECK(swapped_result IN ('a','b','tie','abstain')),
    position_consistent INTEGER,
    evidence_package_hash TEXT,
    rubric_revision TEXT,
    prompt_revision TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_judge_pairwise_family ON judge_pairwise_observations(task_family, observed_at);
CREATE TABLE IF NOT EXISTS memory_items (
    memory_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    layer TEXT NOT NULL DEFAULT 'semantic',
    kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    confidence REAL NOT NULL DEFAULT 1.0,
    salience REAL NOT NULL DEFAULT 0.5,
    access_count INTEGER NOT NULL DEFAULT 0,
    last_accessed_at TEXT,
    content_hash TEXT NOT NULL,
    source_type TEXT,
    source_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    provenance_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(scope, content_hash)
);
CREATE TABLE IF NOT EXISTS memory_relations (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    PRIMARY KEY(source_id, target_id, relation_type)
);
CREATE TABLE IF NOT EXISTS memory_sync_runs (
    sync_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    project_id TEXT NOT NULL,
    sources_json TEXT NOT NULL,
    summary_json TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    memory_id UNINDEXED,
    title,
    body,
    tokenize='unicode61'
);
"""


class IntelligenceStore:
    def __init__(self, root: str | Path):
        self.layout: ProjectLayout = layout(root).ensure()
        self.path = self.layout.database
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
                (SCHEMA_VERSION,),
            )

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})").fetchall()}

    def _migrate(self, connection: sqlite3.Connection) -> None:
        """Apply small, idempotent local migrations without a second authority.

        v2 databases only need additive memory columns. Existing rows are
        backfilled deterministically, then the FTS projection is rebuilt.
        """
        columns = self._columns(connection, "memory_items")
        additions = {
            "layer": "TEXT NOT NULL DEFAULT 'semantic'",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "updated_at": "TEXT",
            "salience": "REAL NOT NULL DEFAULT 0.5",
            "access_count": "INTEGER NOT NULL DEFAULT 0",
            "last_accessed_at": "TEXT",
            "content_hash": "TEXT",
            "source_type": "TEXT",
            "source_id": "TEXT",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for name, declaration in additions.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE memory_items ADD COLUMN {name} {declaration}")
        if "updated_at" not in columns:
            connection.execute("UPDATE memory_items SET updated_at=created_at WHERE updated_at IS NULL")
        if "content_hash" not in columns:
            rows = connection.execute("SELECT memory_id,scope,title,body FROM memory_items").fetchall()
            import hashlib
            for row in rows:
                digest = hashlib.sha256(
                    (str(row[1]) + "\0" + str(row[2]).strip() + "\0" + str(row[3]).strip()).encode("utf-8")
                ).hexdigest()
                connection.execute("UPDATE memory_items SET content_hash=? WHERE memory_id=?", (digest, row[0]))
        connection.execute("UPDATE memory_items SET updated_at=COALESCE(updated_at,created_at)")
        connection.execute("UPDATE memory_items SET content_hash=COALESCE(content_hash,memory_id)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_memory_scope_status ON memory_items(scope,status,layer,updated_at)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_memory_source ON memory_items(source_type,source_id)")
        # FTS is a derived index. Rebuild it from the authoritative table.
        connection.execute("DELETE FROM memory_fts")
        connection.execute("INSERT INTO memory_fts(memory_id,title,body) SELECT memory_id,title,body FROM memory_items")

    @contextlib.contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def query(self, sql: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, parameters).fetchall()]

    def one(self, sql: str, parameters: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(sql, parameters).fetchone()
            return dict(row) if row else None

    def scalar(self, sql: str, parameters: tuple[Any, ...] = (), default: Any = None) -> Any:
        row = self.one(sql, parameters)
        return next(iter(row.values())) if row else default

    def json_rows(self, sql: str, parameters: tuple[Any, ...] = (), json_columns: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        rows = self.query(sql, parameters)
        for row in rows:
            for column in json_columns:
                if row.get(column) is not None:
                    row[column] = json.loads(row[column])
        return rows
