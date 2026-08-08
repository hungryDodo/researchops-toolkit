#!/usr/bin/env python3
"""Conservative archive-first repository hygiene scanner and internal-ID normalizer."""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

UTC = dt.timezone.utc
TEXT_EXTS = {
    ".md", ".rst", ".txt", ".tex", ".py", ".sh", ".bash", ".zsh", ".json", ".jsonl",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".csv", ".tsv", ".js", ".ts", ".tsx",
    ".jsx", ".c", ".cc", ".cpp", ".h", ".hpp", ".java", ".go", ".rs", ".html", ".css",
}
DEFAULT_POLICY = {
    "schema_version": 1,
    "exclude_globs": [".git/**", ".venv/**", "node_modules/**", ".researchops/state/trash/**", ".researchops/state/archive/**"],
    "candidate_name_patterns": [
        "*~", "*.bak", "*.backup", "*.orig", "*.rej", "*.old", "*_old.*", "*_copy.*",
        "*final_v*.?*", "*scratch*", "*debug*", "*temporary*", "*deprecated*",
    ],
    "test_globs": ["tests/**", "test/**", "**/test_*.py", "**/*_test.py", "**/*smoke*"],
    "public_surface_globs": ["README*.md", "docs/**", "paper/**", "figures/**", ".researchops/state/dashboard/**"],
    "internal_id_patterns": {
        "baseline": "\\bB[-_ ]?\\d{1,4}\\b",
        "experiment": "\\bE[-_ ]?\\d{1,4}\\b",
        "ablation": "\\bA[-_ ]?\\d{1,4}\\b"
    },
    "semantic_context_window_chars": 160,
    "minimum_unused_age_days": 30,
}


def now() -> dt.datetime:
    return dt.datetime.now(UTC)


def iso(v: dt.datetime | None = None) -> str:
    return (v or now()).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def canonical_hash(obj: Any) -> str:
    b = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(b).hexdigest()


def matches(path: str, patterns: Iterable[str]) -> bool:
    p = path.replace(os.sep, "/")
    if p.startswith("./"):
        p = p[2:]
    for pat in patterns:
        variants = [pat]
        if pat.startswith("**/"):
            variants.append(pat[3:])
        if any(fnmatch.fnmatch(p, x) for x in variants):
            return True
    return False


def safe_under(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve())
        return True
    except ValueError:
        return False


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True)


def git_last_change(root: Path, rp: str) -> str | None:
    p = run(["git", "log", "-1", "--format=%cI", "--", rp], root)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


def git_tracked(root: Path, rp: str) -> bool:
    p = run(["git", "ls-files", "--error-unmatch", "--", rp], root)
    return p.returncode == 0


def text_files(root: Path, policy: dict[str, Any]) -> list[Path]:
    result: list[Path] = []
    for base, dirs, files in os.walk(root, followlinks=False):
        bp = Path(base)
        kept = []
        for d in dirs:
            p = bp / d
            try: rp = p.resolve().relative_to(root.resolve()).as_posix()
            except ValueError: continue
            if p.is_symlink() or matches(rp + "/", policy.get("exclude_globs", [])): continue
            kept.append(d)
        dirs[:] = kept
        for name in files:
            p = bp / name
            if p.is_symlink() or p.suffix.lower() not in TEXT_EXTS: continue
            try: rp = p.resolve().relative_to(root.resolve()).as_posix()
            except ValueError: continue
            if matches(rp, policy.get("exclude_globs", [])): continue
            result.append(p)
    return result


def all_file_inventory(root: Path, policy: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    for base, dirs, files in os.walk(root, followlinks=False):
        bp = Path(base)
        kept_dirs: list[str] = []
        for directory in dirs:
            child = bp / directory
            if child.is_symlink():
                continue
            try:
                relative = child.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
            if matches(relative + "/", policy.get("exclude_globs", [])):
                continue
            kept_dirs.append(directory)
        dirs[:] = kept_dirs
        for name in files:
            p = bp / name
            if p.is_symlink() or not p.is_file(): continue
            try: rp = p.resolve().relative_to(root.resolve()).as_posix()
            except ValueError: continue
            if matches(rp, policy.get("exclude_globs", [])): continue
            st = p.stat()
            age = max(0.0, (now().timestamp() - st.st_mtime) / 86400)
            row = {
                "path": rp,
                "size_bytes": st.st_size,
                "modified_at": iso(dt.datetime.fromtimestamp(st.st_mtime, UTC)),
                "age_days": round(age, 2),
                "tracked_by_git": git_tracked(root, rp),
                "last_git_change": git_last_change(root, rp),
            }
            if matches(Path(rp).name, policy.get("candidate_name_patterns", [])) or matches(rp, policy.get("candidate_name_patterns", [])):
                row["candidate_reasons"] = ["candidate filename pattern"]
                candidates.append(row)
            if matches(rp, policy.get("test_globs", [])):
                row = dict(row)
                lower = rp.lower()
                row["kind"] = "smoke" if "smoke" in lower else "test"
                tests.append(row)
    return candidates, tests


def reference_counts(root: Path, text_paths: list[Path], target_paths: list[str]) -> dict[str, int]:
    basenames = {t: Path(t).name for t in target_paths}
    counts = {t: 0 for t in target_paths}
    for p in text_paths:
        try: text = p.read_text(encoding="utf-8", errors="replace")
        except OSError: continue
        try: source = p.resolve().relative_to(root.resolve()).as_posix()
        except ValueError: source = str(p)
        for t, base in basenames.items():
            if source == t: continue
            if t in text or (base and base in text): counts[t] += 1
    return counts


def normalize_id(token: str) -> str:
    return re.sub(r"[-_ ]", "", token).upper()


def id_occurrences(root: Path, policy: dict[str, Any], registry: dict[str, Any]) -> list[dict[str, Any]]:
    mapping = {normalize_id(x.get("internal_id", "")): x for x in registry.get("identifiers", []) if x.get("internal_id")}
    patterns = [(kind, re.compile(pat)) for kind, pat in policy.get("internal_id_patterns", {}).items()]
    window = int(policy.get("semantic_context_window_chars", 160))
    rows: list[dict[str, Any]] = []
    for path in text_files(root, policy):
        try: text = path.read_text(encoding="utf-8", errors="replace")
        except OSError: continue
        rp = path.resolve().relative_to(root.resolve()).as_posix()
        public = matches(rp, policy.get("public_surface_globs", []))
        for kind, pattern in patterns:
            for m in pattern.finditer(text):
                raw = m.group(0)
                key = normalize_id(raw)
                entry = mapping.get(key)
                start = max(0, m.start() - window // 2); end = min(len(text), m.end() + window // 2)
                context = re.sub(r"\s+", " ", text[start:end]).strip()
                semantic = False
                if entry:
                    label = str(entry.get("public_label", "")); slug = str(entry.get("semantic_slug", ""))
                    semantic = bool((label and label.lower() in context.lower()) or (slug and slug.lower() in context.lower()))
                line = text.count("\n", 0, m.start()) + 1
                rows.append({
                    "path": rp,
                    "line": line,
                    "token": raw,
                    "normalized_id": key,
                    "kind": kind,
                    "public_surface": public,
                    "mapped": bool(entry),
                    "public_label": entry.get("public_label") if entry else None,
                    "semantic_label_nearby": semantic,
                    "bare_public_id": public and (not entry or not semantic),
                    "context": context[:320],
                })
    return rows


def init_project(root: Path, force: bool) -> None:
    h = root / ".researchops/state/hygiene"; h.mkdir(parents=True, exist_ok=True)
    items = {
        h / "repository-policy.json": DEFAULT_POLICY,
        h / "naming-registry.json": {"schema_version": 1, "identifiers": [], "public_surface_globs": DEFAULT_POLICY["public_surface_globs"]},
        h / "test-inventory.json": {"schema_version": 1, "tests": []},
    }
    for p, data in items.items():
        if force or not p.exists(): atomic_json(p, data)
    (root / ".researchops/state/archive/repository-hygiene").mkdir(parents=True, exist_ok=True)
    print(h)


def scan(root: Path, out: Path | None = None) -> dict[str, Any]:
    policy = load_json(root / ".researchops/state/hygiene/repository-policy.json", DEFAULT_POLICY)
    registry = load_json(root / ".researchops/state/hygiene/naming-registry.json", {"identifiers": []})
    candidates, tests = all_file_inventory(root, policy)
    texts = text_files(root, policy)
    refs = reference_counts(root, texts, [x["path"] for x in candidates + tests])
    for x in candidates: x["text_reference_count"] = refs.get(x["path"], 0)
    test_manifest = load_json(root / ".researchops/state/hygiene/test-inventory.json", {"tests": []})
    manifest_map = {x.get("path"): x for x in test_manifest.get("tests", [])}
    for x in tests:
        x["text_reference_count"] = refs.get(x["path"], 0)
        x["lifecycle"] = manifest_map.get(x["path"])
    ids = id_occurrences(root, policy, registry)
    data = {
        "schema_version": 1,
        "generated_at": iso(),
        "root": str(root),
        "policy_sha256": canonical_hash(policy),
        "candidate_files": sorted(candidates, key=lambda x: (-x["age_days"], x["path"])),
        "tests": sorted(tests, key=lambda x: x["path"]),
        "identifier_occurrences": ids,
        "summary": {
            "candidate_file_count": len(candidates),
            "test_count": len(tests),
            "temporary_or_unregistered_tests": sum(1 for x in tests if not x.get("lifecycle") or x.get("lifecycle", {}).get("status") == "temporary"),
            "identifier_occurrences": len(ids),
            "bare_public_ids": sum(1 for x in ids if x.get("bare_public_id")),
            "unmapped_ids": len({x["normalized_id"] for x in ids if not x.get("mapped")}),
        },
    }
    out = out or root / ".researchops/state/hygiene/repository-inventory.json"
    atomic_json(out, data)
    return data


def plan(root: Path, inventory: dict[str, Any], out: Path | None = None) -> dict[str, Any]:
    policy = load_json(root / ".researchops/state/hygiene/repository-policy.json", DEFAULT_POLICY)
    age_min = float(policy.get("minimum_unused_age_days", 30))
    actions: list[dict[str, Any]] = []
    for x in inventory.get("candidate_files", []):
        safe = not x.get("tracked_by_git") and x.get("text_reference_count", 0) == 0 and x.get("age_days", 0) >= age_min
        actions.append({
            "kind": "file",
            "path": x["path"],
            "action": "archive" if safe else "review",
            "safe_to_apply": safe,
            "reason": "untracked, unreferenced, aged candidate" if safe else "tracked, referenced, or too recent",
            "snapshot": {"size_bytes": x["size_bytes"], "modified_at": x["modified_at"]},
        })
    for x in inventory.get("tests", []):
        life = x.get("lifecycle") or {}
        status = life.get("status")
        replacement = life.get("replacement")
        validation = life.get("validation_command")
        if status == "superseded" and replacement and validation:
            action, reason = "retire_after_validation", "manifest marks superseded with replacement and validation"
        elif not life:
            action, reason = "register", "test/smoke lacks lifecycle metadata"
        elif status == "temporary":
            action, reason = "review_expiry", "temporary test requires scheduled review"
        else:
            action, reason = "keep", f"status={status or 'unknown'}"
        actions.append({"kind": "test", "path": x["path"], "action": action, "safe_to_apply": False, "reason": reason, "replacement": replacement, "validation_command": validation})
    unmapped = sorted({x["normalized_id"] for x in inventory.get("identifier_occurrences", []) if not x.get("mapped")})
    bare = [x for x in inventory.get("identifier_occurrences", []) if x.get("bare_public_id")]
    for key in unmapped:
        actions.append({"kind": "identifier", "id": key, "action": "define_mapping", "safe_to_apply": False, "reason": "internal ID has no semantic/public mapping"})
    for x in bare:
        actions.append({"kind": "identifier_occurrence", "path": x["path"], "line": x["line"], "id": x["normalized_id"], "action": "add_semantic_label", "safe_to_apply": False, "reason": "bare internal ID on public surface"})
    core = {"schema_version": 1, "generated_at": iso(), "root": str(root), "inventory_generated_at": inventory.get("generated_at"), "actions": actions}
    result = {**core, "approval_token": canonical_hash(core), "summary": {
        "actions": len(actions),
        "auto_archive_candidates": sum(1 for x in actions if x.get("safe_to_apply")),
        "bare_public_ids": len(bare),
        "unmapped_ids": len(unmapped),
    }}
    out = out or root / ".researchops/state/hygiene/repository-cleanup-plan.json"
    atomic_json(out, result)
    return result


def registry_mapping(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {normalize_id(x.get("internal_id", "")): x for x in registry.get("identifiers", []) if x.get("internal_id")}


def normalize_public_ids(root: Path, check_only: bool, token: str | None, out: Path | None) -> dict[str, Any]:
    policy = load_json(root / ".researchops/state/hygiene/repository-policy.json", DEFAULT_POLICY)
    registry_path = root / ".researchops/state/hygiene/naming-registry.json"
    registry = load_json(registry_path, {"identifiers": []})
    mapping = registry_mapping(registry)
    planned: list[dict[str, Any]] = []
    patterns = [re.compile(p) for p in policy.get("internal_id_patterns", {}).values()]
    for path in text_files(root, policy):
        rp = path.resolve().relative_to(root.resolve()).as_posix()
        if not matches(rp, policy.get("public_surface_globs", [])): continue
        try: text = path.read_text(encoding="utf-8", errors="strict")
        except (OSError, UnicodeError): continue
        changes: list[dict[str, Any]] = []
        new = text
        # Replace only a bare token when its semantic label is not already in a local line.
        for pat in patterns:
            def repl(m: re.Match[str]) -> str:
                key = normalize_id(m.group(0)); entry = mapping.get(key)
                if not entry or not entry.get("public_label"): return m.group(0)
                line_start = new.rfind("\n", 0, m.start()) + 1
                line_end = new.find("\n", m.end()); line_end = len(new) if line_end < 0 else line_end
                line = new[line_start:line_end]
                label = str(entry["public_label"])
                if label.lower() in line.lower(): return m.group(0)
                changes.append({"id": key, "from": m.group(0), "to": label})
                return label
            new = pat.sub(repl, new)
        if new != text:
            planned.append({"path": rp, "changes": changes, "before_sha256": hashlib.sha256(text.encode()).hexdigest(), "after_sha256": hashlib.sha256(new.encode()).hexdigest(), "content": new})
    public_files = [{k: v for k, v in x.items() if k != "content"} for x in planned]
    approval_payload = {"schema_version": 1, "root": str(root), "files": public_files}
    approval = canonical_hash(approval_payload)
    core = {**approval_payload, "generated_at": iso()}
    result = {**core, "approval_token": approval, "applied": False}
    if not check_only:
        if token != approval: raise SystemExit("approval token mismatch for normalization plan")
        for x in planned:
            p = root / x["path"]
            if not safe_under(root, p): raise SystemExit(f"unsafe path: {p}")
            current = p.read_text(encoding="utf-8")
            if hashlib.sha256(current.encode()).hexdigest() != x["before_sha256"]: raise SystemExit(f"file changed: {p}")
            p.write_text(x["content"], encoding="utf-8")
        result["applied"] = True
    for x in planned: x.pop("content", None)
    out = out or root / ".researchops/state/hygiene/naming-normalization-plan.json"
    atomic_json(out, result)
    return result


def archive_candidates(root: Path, plan_path: Path, token: str) -> dict[str, Any]:
    plan_data = load_json(plan_path, None)
    if not plan_data or token != plan_data.get("approval_token"): raise SystemExit("approval token mismatch")
    if Path(plan_data.get("root", "")).resolve() != root.resolve(): raise SystemExit("plan root mismatch")
    stamp = now().strftime("%Y%m%dT%H%M%SZ")
    qroot = root / ".researchops/state/archive/repository-hygiene" / stamp
    events = []
    for action in plan_data.get("actions", []):
        if not action.get("safe_to_apply") or action.get("kind") != "file" or action.get("action") != "archive": continue
        p = root / action["path"]
        if not safe_under(root, p) or p.is_symlink() or not p.is_file():
            events.append({"path": action["path"], "status": "blocked"}); continue
        st = p.stat(); snap = action.get("snapshot", {})
        if st.st_size != snap.get("size_bytes"):
            events.append({"path": action["path"], "status": "blocked", "reason": "size changed"}); continue
        dst = qroot / action["path"]; dst.parent.mkdir(parents=True, exist_ok=True); os.replace(p, dst)
        events.append({"path": action["path"], "status": "archived", "archive_path": dst.resolve().relative_to(root.resolve()).as_posix()})
    result = {"schema_version": 1, "operation": "archive", "applied_at": iso(), "archive_root": qroot.resolve().relative_to(root.resolve()).as_posix(), "plan_token": token, "events": events}
    if events:
        atomic_json(qroot / "manifest.json", result)
    atomic_json(root / ".researchops/state/hygiene/repository-last-apply.json", result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=".")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("init"); p.add_argument("--force", action="store_true")
    p = sp.add_parser("scan"); p.add_argument("--out")
    p = sp.add_parser("plan"); p.add_argument("--inventory"); p.add_argument("--out")
    p = sp.add_parser("normalize-ids"); p.add_argument("--apply", action="store_true"); p.add_argument("--approve-token"); p.add_argument("--out")
    p = sp.add_parser("apply"); p.add_argument("--plan"); p.add_argument("--approve-token", required=True)
    a = ap.parse_args(); root = Path(a.root).resolve()
    if a.cmd == "init": init_project(root, a.force); return 0
    if a.cmd == "scan":
        data = scan(root, Path(a.out) if a.out else None); print(json.dumps(data["summary"], indent=2)); return 0
    if a.cmd == "plan":
        ip = Path(a.inventory) if a.inventory else root / ".researchops/state/hygiene/repository-inventory.json"
        inv = load_json(ip, None) or scan(root, ip)
        data = plan(root, inv, Path(a.out) if a.out else None); print(json.dumps({"summary": data["summary"], "approval_token": data["approval_token"]}, indent=2)); return 0
    if a.cmd == "normalize-ids":
        data = normalize_public_ids(root, not a.apply, a.approve_token, Path(a.out) if a.out else None)
        print(json.dumps({"file_count": len(data["files"]), "approval_token": data["approval_token"], "applied": data["applied"]}, indent=2)); return 0
    if a.cmd == "apply":
        pp = Path(a.plan) if a.plan else root / ".researchops/state/hygiene/repository-cleanup-plan.json"
        print(json.dumps(archive_candidates(root, pp, a.approve_token), indent=2)); return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
