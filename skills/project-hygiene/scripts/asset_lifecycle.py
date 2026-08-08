#!/usr/bin/env python3
"""Research asset lifecycle inventory and two-phase cleanup.

The tool is intentionally conservative. `scan` and `plan` are read-only. `apply`
quarantines approved files or removes clean, expired registered worktrees. `purge`
permanently deletes expired quarantine entries with a second approval token.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

UTC = dt.timezone.utc
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}
DEFAULT_POLICY = {
    "schema_version": 1,
    "large_file_threshold_bytes": 100 * 1024 * 1024,
    "hash_files_below_bytes": 256 * 1024 * 1024,
    "quarantine_grace_days": 7,
    "default_retention_days": {
        "intermediate": 14,
        "run-log": 14,
        "raw-reproducible": 60,
        "unknown": 30,
    },
    "canonical_globs": [
        ".researchops/state/evidence/**",
        ".researchops/state/designs/**",
        "paper/**",
        "figures/source/**",
        "src/**",
    ],
    "candidate_globs": [
        "**/.cache/**",
        "**/tmp/**",
        "**/logs/**",
        "**/runs/**",
        "**/outputs/**",
        "**/checkpoints/**",
        "**/*.trace",
        "**/*.prof",
    ],
    "exclude_globs": [
        ".git/**",
        ".researchops/state/trash/**",
        ".researchops/state/archive/**",
        ".venv/**",
        "node_modules/**",
    ],
    "base_branch": "main",
}


def now() -> dt.datetime:
    return dt.datetime.now(UTC)


def iso(value: dt.datetime | None = None) -> str:
    return (value or now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def append_jsonl(path: Path, obj: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, sort_keys=True) + "\n")


def rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def matches(path: str, patterns: Iterable[str]) -> bool:
    path = path.replace(os.sep, "/")
    if path.startswith("./"):
        path = path[2:]
    for pattern in patterns:
        variants = [pattern]
        if pattern.startswith("**/"):
            variants.append(pattern[3:])
        if any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch("/" + path, p) for p in variants):
            return True
    return False


def safe_under(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve())
        return True
    except ValueError:
        return False


def sha256_file(path: Path, chunk: int = 8 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def canonical_hash(obj: Any) -> str:
    payload = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def run(cmd: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=check)


def git_root(root: Path) -> Path | None:
    p = run(["git", "rev-parse", "--show-toplevel"], root)
    return Path(p.stdout.strip()) if p.returncode == 0 and p.stdout.strip() else None


def git_tracked(root: Path, relative: str) -> bool:
    p = run(["git", "ls-files", "--error-unmatch", "--", relative], root)
    return p.returncode == 0


def ledger_text(root: Path) -> str:
    candidates = [
        root / ".researchops/state/evidence/ledger.json",
        root / ".researchops/state/dashboard/project.json",
        root / ".researchops/state/PROJECT.md",
    ]
    chunks: list[str] = []
    for p in candidates:
        if p.exists() and p.is_file():
            try:
                chunks.append(p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    return "\n".join(chunks)


def classify(path: str, policy: dict[str, Any]) -> str:
    p = path.lower()
    if matches(path, policy.get("canonical_globs", [])):
        return "canonical"
    if "/raw/" in "/" + p or p.startswith("data/raw/"):
        return "raw-reproducible"
    if any(x in p for x in ("checkpoint", "tensor", "intermediate", "/cache/", ".cache/")):
        return "intermediate"
    if any(x in p for x in ("/logs/", ".log", ".trace", ".prof", "stdout", "stderr")):
        return "run-log"
    if matches(path, policy.get("candidate_globs", [])):
        return "intermediate"
    return "unknown"


def list_files(root: Path, policy: dict[str, Any], include_small: bool) -> list[dict[str, Any]]:
    threshold = int(policy.get("large_file_threshold_bytes", 100 * 1024 * 1024))
    hash_limit = int(policy.get("hash_files_below_bytes", 256 * 1024 * 1024))
    refs = ledger_text(root)
    rows: list[dict[str, Any]] = []
    for base, dirs, files in os.walk(root, followlinks=False):
        base_path = Path(base)
        kept_dirs = []
        for d in dirs:
            child = base_path / d
            try:
                rp = rel(root, child)
            except ValueError:
                continue
            if child.is_symlink() or matches(rp + "/", policy.get("exclude_globs", [])):
                continue
            kept_dirs.append(d)
        dirs[:] = kept_dirs
        for name in files:
            path = base_path / name
            if path.is_symlink() or not path.is_file():
                continue
            try:
                rp = rel(root, path)
            except ValueError:
                continue
            if matches(rp, policy.get("exclude_globs", [])):
                continue
            try:
                st = path.stat()
            except OSError:
                continue
            likely = classify(rp, policy)
            candidate_pattern = matches(rp, policy.get("candidate_globs", []))
            if not include_small and st.st_size < threshold and not candidate_pattern:
                continue
            age_days = max(0.0, (now().timestamp() - st.st_mtime) / 86400)
            row: dict[str, Any] = {
                "path": rp,
                "size_bytes": st.st_size,
                "modified_at": iso(dt.datetime.fromtimestamp(st.st_mtime, UTC)),
                "age_days": round(age_days, 2),
                "classification": likely,
                "candidate_pattern": candidate_pattern,
                "tracked_by_git": git_tracked(root, rp) if (root / ".git").exists() else False,
                "referenced_by_research_state": rp in refs or str(path) in refs,
                "symlink": False,
            }
            if st.st_size <= hash_limit:
                try:
                    row["sha256"] = sha256_file(path)
                except OSError as e:
                    row["hash_error"] = str(e)
            else:
                row["sha256"] = None
                row["hash_note"] = "skipped_above_hash_limit"
            rows.append(row)
    rows.sort(key=lambda x: x["size_bytes"], reverse=True)
    return rows


def parse_git_worktrees(root: Path, registry: dict[str, Any], policy: dict[str, Any]) -> list[dict[str, Any]]:
    g = git_root(root)
    if not g:
        return []
    p = run(["git", "worktree", "list", "--porcelain"], g)
    if p.returncode != 0:
        return [{"error": p.stderr.strip()}]
    registry_map = {str(Path(x.get("path", "")).resolve()): x for x in registry.get("worktrees", [])}
    blocks = [b for b in p.stdout.strip().split("\n\n") if b.strip()]
    out: list[dict[str, Any]] = []
    for block in blocks:
        item: dict[str, Any] = {}
        for line in block.splitlines():
            k, _, v = line.partition(" ")
            if k in {"worktree", "HEAD", "branch", "detached", "locked", "prunable", "bare"}:
                item[k] = v if v else True
        wt = Path(str(item.get("worktree", "")))
        if not wt:
            continue
        reg = registry_map.get(str(wt.resolve()), {})
        item["registered"] = bool(reg)
        item["registry"] = reg
        item["is_main"] = wt.resolve() == g.resolve()
        item["exists"] = wt.exists()
        if wt.exists():
            s = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], wt)
            item["clean"] = s.returncode == 0 and not s.stdout.strip()
            item["status_lines"] = [x for x in s.stdout.splitlines()[:50]]
            lease = wt / ".researchops/state/lease.json"
            item["lease_file"] = str(lease) if lease.exists() else None
            item["active_process_hint"] = (wt / ".researchops/state/ACTIVE").exists()
        else:
            item["clean"] = None
        lease_expired = False
        lease_value = reg.get("lease_expires_at")
        if lease_value:
            try:
                lease_dt = dt.datetime.fromisoformat(lease_value.replace("Z", "+00:00"))
                lease_expired = lease_dt <= now()
            except ValueError:
                item["lease_parse_error"] = lease_value
        item["lease_expired"] = lease_expired
        head = item.get("HEAD")
        base = str(policy.get("base_branch", "main"))
        merged = False
        if head and not item.get("is_main"):
            check = run(["git", "merge-base", "--is-ancestor", str(head), base], g)
            if check.returncode != 0:
                check = run(["git", "merge-base", "--is-ancestor", str(head), f"origin/{base}"], g)
            merged = check.returncode == 0
        item["merged_into_base"] = merged
        out.append(item)
    return out


def init_project(root: Path, force: bool) -> None:
    h = root / ".researchops/state/hygiene"
    h.mkdir(parents=True, exist_ok=True)
    files = {
        h / "asset-policy.json": DEFAULT_POLICY,
        h / "worktree-registry.json": {"schema_version": 1, "worktrees": []},
        h / "asset-registry.json": {"schema_version": 1, "assets": []},
    }
    for path, data in files.items():
        if force or not path.exists():
            atomic_json(path, data)
    (root / ".researchops/state/trash").mkdir(parents=True, exist_ok=True)
    (root / ".researchops/state/archive").mkdir(parents=True, exist_ok=True)
    print(h)


def scan(root: Path, include_small: bool, out: Path | None) -> dict[str, Any]:
    policy_path = root / ".researchops/state/hygiene/asset-policy.json"
    policy = load_json(policy_path, DEFAULT_POLICY)
    registry = load_json(root / ".researchops/state/hygiene/worktree-registry.json", {"worktrees": []})
    asset_registry = load_json(root / ".researchops/state/hygiene/asset-registry.json", {"assets": []})
    asset_map = {str(x.get("path", "")): x for x in asset_registry.get("assets", []) if x.get("path")}
    files = list_files(root, policy, include_small)
    for item in files:
        item["registry"] = asset_map.get(item.get("path"))
    data = {
        "schema_version": 1,
        "generated_at": iso(),
        "root": str(root),
        "policy_sha256": canonical_hash(policy),
        "asset_registry_sha256": canonical_hash(asset_registry),
        "files": files,
        "worktrees": parse_git_worktrees(root, registry, policy),
    }
    data["summary"] = {
        "file_count": len(data["files"]),
        "bytes": sum(x.get("size_bytes", 0) for x in data["files"]),
        "worktree_count": len(data["worktrees"]),
    }
    out = out or root / ".researchops/state/hygiene/asset-inventory.json"
    atomic_json(out, data)
    return data


def action_for_file(item: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    cls = item.get("classification", "unknown")
    retention = int(policy.get("default_retention_days", {}).get(cls, 30))
    checks: list[str] = []
    safe = True
    action = "review"
    reason = "requires classification"
    if cls == "canonical":
        safe = False
        action = "keep"
        reason = "canonical path"
    elif item.get("tracked_by_git"):
        safe = False
        action = "review"
        reason = "tracked by Git; repository-hygiene review required"
    elif item.get("referenced_by_research_state"):
        safe = False
        action = "keep"
        reason = "referenced by research state or evidence"
    elif float(item.get("age_days", 0)) < retention:
        safe = False
        action = "keep"
        reason = f"younger than {retention}-day retention"
    elif cls in {"intermediate", "run-log"}:
        action = "quarantine_file"
        reason = f"expired {cls} candidate"
    elif cls == "raw-reproducible":
        reg = item.get("registry") or {}
        derived_ok = reg.get("derived_status") in {"accepted", "verified"} and bool(reg.get("derived_artifacts"))
        reproducibility_ok = bool(reg.get("regeneration_command") or reg.get("reproduction_waiver"))
        approved = bool(reg.get("cleanup_approved"))
        if derived_ok and reproducibility_ok and approved:
            action = "quarantine_file"
            reason = "raw data has accepted derived artifacts, a regeneration/waiver record, and explicit cleanup approval"
        else:
            safe = False
            action = "archive_or_review"
            reason = "raw data requires accepted derived artifacts, regeneration contract or waiver, and explicit cleanup approval"
    else:
        safe = False
        action = "review"
        reason = "unknown class"
    checks.extend([
        "path stays under project root",
        "path snapshot matches size/mtime/hash when available",
        "not referenced by active evidence",
    ])
    return {
        "kind": "file",
        "path": item.get("path"),
        "action": action,
        "safe_to_apply": safe,
        "approval_required": action not in {"keep", "review", "archive_or_review"},
        "reclaim_bytes": item.get("size_bytes", 0) if action == "quarantine_file" else 0,
        "reason": reason,
        "snapshot": {
            "size_bytes": item.get("size_bytes"),
            "modified_at": item.get("modified_at"),
            "sha256": item.get("sha256"),
        },
        "safety_checks": checks,
    }


def action_for_worktree(item: dict[str, Any]) -> dict[str, Any]:
    reg = item.get("registry") or {}
    blockers: list[str] = []
    if item.get("is_main"):
        blockers.append("main worktree")
    if not item.get("registered"):
        blockers.append("not in worktree registry")
    if item.get("locked"):
        blockers.append("locked")
    if item.get("active_process_hint"):
        blockers.append("ACTIVE marker present")
    if item.get("clean") is not True:
        blockers.append("dirty or unavailable")
    if not item.get("lease_expired"):
        blockers.append("lease not expired")
    if not item.get("merged_into_base") and reg.get("disposition") != "abandoned-approved":
        blockers.append("not merged into base")
    closed = reg.get("status") in {"closed", "merged", "abandoned"}
    if not closed:
        blockers.append("registered task still active")
    safe = not blockers
    return {
        "kind": "worktree",
        "path": item.get("worktree"),
        "branch": item.get("branch"),
        "action": "remove_worktree" if safe else "review",
        "safe_to_apply": safe,
        "approval_required": safe,
        "reclaim_bytes": 0,
        "reason": "eligible registered clean worktree" if safe else "; ".join(blockers),
        "safety_checks": ["clean", "lease expired", "task closed", "merged or approved abandonment", "not locked"],
    }


def build_plan(root: Path, inventory: dict[str, Any], out: Path | None) -> dict[str, Any]:
    policy = load_json(root / ".researchops/state/hygiene/asset-policy.json", DEFAULT_POLICY)
    actions = [action_for_file(x, policy) for x in inventory.get("files", [])]
    actions += [action_for_worktree(x) for x in inventory.get("worktrees", []) if not x.get("error")]
    plan_core = {
        "schema_version": 1,
        "generated_at": iso(),
        "root": str(root),
        "inventory_generated_at": inventory.get("generated_at"),
        "policy_sha256": canonical_hash(policy),
        "actions": actions,
    }
    token = canonical_hash(plan_core)
    plan = {**plan_core, "approval_token": token}
    plan["summary"] = {
        "safe_actions": sum(1 for x in actions if x.get("safe_to_apply")),
        "review_actions": sum(1 for x in actions if not x.get("safe_to_apply")),
        "reclaim_bytes": sum(int(x.get("reclaim_bytes", 0)) for x in actions if x.get("safe_to_apply")),
    }
    out = out or root / ".researchops/state/hygiene/cleanup-plan.json"
    atomic_json(out, plan)
    return plan


def verify_file_snapshot(root: Path, action: dict[str, Any]) -> tuple[bool, str]:
    path = root / str(action["path"])
    if not safe_under(root, path) or path.is_symlink() or not path.is_file():
        return False, "unsafe, missing, or non-file path"
    st = path.stat()
    snap = action.get("snapshot", {})
    if snap.get("size_bytes") is not None and st.st_size != snap["size_bytes"]:
        return False, "size changed since plan"
    if snap.get("sha256"):
        actual = sha256_file(path)
        if actual != snap["sha256"]:
            return False, "hash changed since plan"
    return True, "ok"


def apply_plan(root: Path, plan_path: Path, token: str) -> dict[str, Any]:
    plan = load_json(plan_path, None)
    if not plan:
        raise SystemExit(f"plan not found: {plan_path}")
    if token != plan.get("approval_token"):
        raise SystemExit("approval token mismatch")
    if Path(plan.get("root", "")).resolve() != root.resolve():
        raise SystemExit("plan root mismatch")
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    trash_root = root / ".researchops/state/trash" / stamp
    events: list[dict[str, Any]] = []
    for action in plan.get("actions", []):
        if not action.get("safe_to_apply"):
            continue
        kind = action.get("kind")
        if kind == "file" and action.get("action") == "quarantine_file":
            ok, reason = verify_file_snapshot(root, action)
            if not ok:
                events.append({"status": "blocked", "action": action, "reason": reason})
                continue
            src = root / action["path"]
            dst = trash_root / action["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.replace(src, dst)
            event = {
                "at": iso(),
                "status": "quarantined",
                "source": action["path"],
                "quarantine_path": rel(root, dst),
                "size_bytes": action.get("reclaim_bytes", 0),
                "plan_token": token,
            }
            append_jsonl(root / ".researchops/state/hygiene/deletion-log.jsonl", event)
            events.append(event)
        elif kind == "worktree" and action.get("action") == "remove_worktree":
            wt = Path(str(action["path"]))
            s = run(["git", "status", "--porcelain=v1", "--untracked-files=all"], wt) if wt.exists() else None
            if not wt.exists() or s is None or s.returncode != 0 or s.stdout.strip():
                events.append({"status": "blocked", "action": action, "reason": "worktree no longer clean/available"})
                continue
            g = git_root(root) or root
            p = run(["git", "worktree", "remove", str(wt)], g)
            status = "removed" if p.returncode == 0 else "blocked"
            event = {
                "at": iso(),
                "status": status,
                "worktree": str(wt),
                "stderr": p.stderr.strip(),
                "plan_token": token,
            }
            append_jsonl(root / ".researchops/state/hygiene/deletion-log.jsonl", event)
            events.append(event)
    result = {"schema_version": 1, "applied_at": iso(), "plan_token": token, "events": events}
    atomic_json(root / ".researchops/state/hygiene/last-apply.json", result)
    return result


def build_purge_plan(root: Path, days: int, out: Path | None) -> dict[str, Any]:
    trash = root / ".researchops/state/trash"
    cutoff = now() - dt.timedelta(days=days)
    entries: list[dict[str, Any]] = []
    if trash.exists():
        for p in sorted(trash.iterdir()):
            if not p.is_dir() or p.is_symlink():
                continue
            m = dt.datetime.fromtimestamp(p.stat().st_mtime, UTC)
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())
            entries.append({
                "path": rel(root, p),
                "modified_at": iso(m),
                "age_days": round((now() - m).total_seconds() / 86400, 2),
                "size_bytes": size,
                "eligible": m <= cutoff,
            })
    core = {"schema_version": 1, "generated_at": iso(), "root": str(root), "grace_days": days, "entries": entries}
    plan = {**core, "approval_token": canonical_hash(core)}
    out = out or root / ".researchops/state/hygiene/purge-plan.json"
    atomic_json(out, plan)
    return plan


def purge(root: Path, plan_path: Path, token: str) -> dict[str, Any]:
    plan = load_json(plan_path, None)
    if not plan or token != plan.get("approval_token"):
        raise SystemExit("purge approval token mismatch")
    if Path(plan.get("root", "")).resolve() != root.resolve():
        raise SystemExit("purge plan root mismatch")
    events: list[dict[str, Any]] = []
    for item in plan.get("entries", []):
        if not item.get("eligible"):
            continue
        p = root / item["path"]
        if not safe_under(root / ".researchops/state/trash", p) or p.is_symlink() or not p.is_dir():
            events.append({"status": "blocked", "path": item["path"]})
            continue
        shutil.rmtree(p)
        event = {"at": iso(), "status": "purged", "path": item["path"], "size_bytes": item.get("size_bytes", 0), "plan_token": token}
        append_jsonl(root / ".researchops/state/hygiene/deletion-log.jsonl", event)
        events.append(event)
    result = {"schema_version": 1, "purged_at": iso(), "events": events}
    atomic_json(root / ".researchops/state/hygiene/last-purge.json", result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("init"); p.add_argument("--force", action="store_true")
    p = sp.add_parser("scan"); p.add_argument("--include-small", action="store_true"); p.add_argument("--out")
    p = sp.add_parser("plan"); p.add_argument("--inventory"); p.add_argument("--out")
    p = sp.add_parser("apply"); p.add_argument("--plan"); p.add_argument("--approve-token", required=True)
    p = sp.add_parser("purge-plan"); p.add_argument("--grace-days", type=int); p.add_argument("--out")
    p = sp.add_parser("purge"); p.add_argument("--plan"); p.add_argument("--approve-token", required=True)
    args = ap.parse_args()
    root = Path(args.root).resolve()
    if args.cmd == "init":
        init_project(root, args.force); return 0
    if args.cmd == "scan":
        data = scan(root, args.include_small, Path(args.out) if args.out else None); print(json.dumps(data["summary"], indent=2)); return 0
    if args.cmd == "plan":
        inv_path = Path(args.inventory) if args.inventory else root / ".researchops/state/hygiene/asset-inventory.json"
        inv = load_json(inv_path, None) or scan(root, False, inv_path)
        plan = build_plan(root, inv, Path(args.out) if args.out else None)
        print(json.dumps({"summary": plan["summary"], "approval_token": plan["approval_token"]}, indent=2)); return 0
    if args.cmd == "apply":
        plan_path = Path(args.plan) if args.plan else root / ".researchops/state/hygiene/cleanup-plan.json"
        print(json.dumps(apply_plan(root, plan_path, args.approve_token), indent=2)); return 0
    if args.cmd == "purge-plan":
        policy = load_json(root / ".researchops/state/hygiene/asset-policy.json", DEFAULT_POLICY)
        days = args.grace_days if args.grace_days is not None else int(policy.get("quarantine_grace_days", 7))
        plan = build_purge_plan(root, days, Path(args.out) if args.out else None)
        print(json.dumps({"entries": len(plan["entries"]), "approval_token": plan["approval_token"]}, indent=2)); return 0
    if args.cmd == "purge":
        plan_path = Path(args.plan) if args.plan else root / ".researchops/state/hygiene/purge-plan.json"
        print(json.dumps(purge(root, plan_path, args.approve_token), indent=2)); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
