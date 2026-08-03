from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from pathlib import Path
from typing import Any, Iterable

SEVERITY_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}

SAFE_COMMAND_SUBSTITUTIONS = (
    re.compile(r"\$\(\s*(?:which|command\s+-v|type\s+-P)\s+([A-Za-z0-9_.+:-]+)\s*\)"),
    re.compile(r"`\s*(?:which|command\s+-v|type\s+-P)\s+([A-Za-z0-9_.+:-]+)\s*`"),
)

ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=.*$", re.S)
DYNAMIC_COMMAND_RE = re.compile(r"(?:^|[;&|]\s*)(?:\$\(|`|\$\{|\$[A-Za-z_])", re.M)
DYNAMIC_ANY_RE = re.compile(r"\$\(|`[^`]+`|\beval\b|\b(?:bash|sh|zsh|dash|ksh)\s+-c\b", re.I)
FORK_BOMB_RE = re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")
POLICY_BYPASS_RE = re.compile(
    r"(?:\b(?:python(?:3(?:\.\d+)?)?\s+-m\s+)?rops\s+behavior\b[^\n]*(?:\bapprove\b|\bmode\s+off\b|\bsemantic\b[^\n]*--mode\s+off|\binstall\b[^\n]*--mode\s+off)|"
    r"\bcreate_approval\b|"
    r"\.research[\\/]+runtime[\\/]+(?:approvals|config)\.json|"
    r"\.researchops[\\/]+(?:behavior|hooks)|"
    r"ROPS_(?:BEHAVIOR_MODE\s*=\s*off|ALLOW_NONINTERACTIVE_APPROVAL\s*=))",
    re.I,
)


NETWORK_SEND_COMMANDS = {
    "curl", "http", "httpie", "wget", "nc", "netcat", "ncat", "socat", "scp", "sftp",
    "rsync", "rclone", "ftp", "lftp", "aws", "gsutil", "gcloud", "az", "kubectl",
}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd", "cmd.exe"}
WRAPPERS = {"command", "builtin", "exec", "nohup"}
HARDWARE_TOOLS = {
    "nrfjprog", "jlinkexe", "jlinkcommander", "openocd", "pyocd", "dfu-util", "esptool",
    "esptool.py", "west", "avrdude", "bossac", "stm32flash", "flashrom", "fastboot",
}
FILESYSTEM_ADMIN = {
    "wipefs", "fdisk", "sfdisk", "cfdisk", "gdisk", "sgdisk", "parted", "diskpart",
    "format", "format.com", "cryptsetup", "zpool", "zfs",
}
POWER_COMMANDS = {"shutdown", "reboot", "poweroff", "halt", "init"}
DANGEROUS_KEYWORDS = re.compile(
    r"(?:\brm\b|--recursive|--force|\bmkfs|\bdd\b|/dev/|\bshred\b|\bchmod\b|\bchown\b|"
    r"\bgit\b.*(?:--force|reset|clean)|\bdocker\b|\bmount\b|\bcrontab\b|systemd|\bnc\b|\bsocat\b|"
    r"\bshutdown\b|\breboot\b|\bflash\b|\bprogram\b)",
    re.I | re.S,
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _basename(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1].lower()


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _safe_substitutions(command: str) -> tuple[str, list[str]]:
    transformed = command
    resolved: list[str] = []
    for pattern in SAFE_COMMAND_SUBSTITUTIONS:
        while True:
            match = pattern.search(transformed)
            if not match:
                break
            executable = match.group(1)
            resolved.append(executable)
            transformed = transformed[: match.start()] + executable + transformed[match.end() :]
    return transformed, resolved


def _lex(command: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer), warnings
    except ValueError as exc:
        warnings.append(f"shell parse error: {exc}")
        # A conservative fallback preserves enough structure for regex and semantic review.
        return command.split(), warnings


def _split_segments(tokens: list[str]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current: list[str] = []
    leading_operator = ""
    for token in tokens:
        if token in {";", "&&", "||", "|", "&"}:
            if current:
                segments.append({"tokens": current, "operator_before": leading_operator, "operator_after": token})
                current = []
            leading_operator = token
            continue
        if token in {"(", ")"}:
            # Parentheses are retained for uncertainty metadata but do not become executables.
            continue
        current.append(token)
    if current:
        segments.append({"tokens": current, "operator_before": leading_operator, "operator_after": ""})
    return segments


def _skip_options(tokens: list[str], index: int, options_with_value: set[str] | None = None) -> int:
    value_options = options_with_value or set()
    while index < len(tokens):
        token = tokens[index]
        if token == "--":
            return index + 1
        if token in value_options:
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        break
    return index


def _unwrap(tokens: list[str]) -> tuple[str, list[str], list[str]]:
    work = list(tokens)
    wrappers: list[str] = []
    while work and ASSIGNMENT_RE.match(work[0]):
        wrappers.append("assignment")
        work.pop(0)
    while work:
        executable = _basename(work[0])
        if executable == "sudo":
            wrappers.append("sudo")
            index = _skip_options(work, 1, {"-u", "--user", "-g", "--group", "-h", "--host", "-p", "--prompt", "-C", "--close-from", "-T", "--command-timeout", "-R", "--chroot", "-D", "--chdir"})
            work = work[index:]
        elif executable == "env":
            wrappers.append("env")
            index = 1
            while index < len(work) and (work[index].startswith("-") or ASSIGNMENT_RE.match(work[index])):
                if work[index] in {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}:
                    index += 2
                else:
                    index += 1
            work = work[index:]
        elif executable in WRAPPERS:
            wrappers.append(executable)
            work = work[1:]
            while work and work[0].startswith("-"):
                work.pop(0)
        elif executable == "nice":
            wrappers.append("nice")
            index = _skip_options(work, 1, {"-n", "--adjustment"})
            work = work[index:]
        elif executable in {"time", "stdbuf", "setsid"}:
            wrappers.append(executable)
            work = work[_skip_options(work, 1):]
        elif executable == "timeout":
            wrappers.append("timeout")
            index = _skip_options(work, 1, {"-k", "--kill-after", "-s", "--signal"})
            if index < len(work):
                index += 1  # duration
            work = work[index:]
        elif executable in {"busybox", "toybox"} and len(work) > 1:
            wrappers.append(executable)
            work = work[1:]
        else:
            break
        while work and ASSIGNMENT_RE.match(work[0]):
            wrappers.append("assignment")
            work.pop(0)
    if not work:
        return "", [], wrappers
    return _basename(work[0]), work[1:], wrappers


def _short_flags(args: Iterable[str]) -> set[str]:
    result: set[str] = set()
    for value in args:
        if value.startswith("--") or not value.startswith("-") or value == "-":
            continue
        result.update(value[1:])
    return result


def _has_option(args: list[str], *names: str) -> bool:
    lowered = {item.lower() for item in args}
    return any(name.lower() in lowered for name in names)


def _targets(args: list[str]) -> list[str]:
    return [item for item in args if item and not item.startswith("-") and not ASSIGNMENT_RE.match(item)]


def _is_block_device(path: str) -> bool:
    normalized = _strip_quotes(path).replace("\\", "/").lower()
    return normalized.startswith("/dev/") or bool(re.match(r"^(?:\\\\\.\\)?physicaldrive\d+$", normalized)) or normalized.startswith("/dev/disk")


def _is_absolute_or_sensitive(path: str, project_root: Path | None, policy: dict[str, Any]) -> bool:
    raw = _strip_quotes(path).strip()
    if not raw:
        return False
    normalized = raw.replace("\\", "/")
    lowered = normalized.lower()
    if lowered in {"/", "~", "$home", "${home}"}:
        return True
    for prefix in policy.get("sensitive_path_prefixes", []):
        p = str(prefix).replace("\\", "/").lower().rstrip("/")
        if lowered == p or lowered.startswith(p + "/"):
            return True
    for pattern in policy.get("sensitive_name_patterns", []):
        if re.search(pattern, normalized, re.I):
            return True
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        return True
    if project_root:
        try:
            candidate = (project_root / raw).resolve(strict=False)
            protected = [
                project_root.resolve(),
                (project_root / ".git").resolve(strict=False),
                (project_root / ".research").resolve(strict=False),
                (project_root / ".researchops").resolve(strict=False),
            ]
            if candidate in protected:
                return True
        except (OSError, RuntimeError):
            pass
    return False


def _finding(policy: dict[str, Any], rule_id: str, kind: str, reason: str, evidence: str, *, confidence: str = "deterministic", severity: str | None = None, approvable: bool | None = None) -> dict[str, Any]:
    category = policy.get("categories", {}).get(kind, {})
    return {
        "rule_id": rule_id,
        "kind": kind,
        "severity": severity or category.get("severity", "high"),
        "confidence": confidence,
        "reason": reason,
        "evidence": evidence[:600],
        "approvable": category.get("approvable", True) if approvable is None else approvable,
        "specialist": category.get("specialist", "research-engineering"),
    }


def _invocation(tokens: list[str], raw: str, depth: int = 0) -> dict[str, Any]:
    executable, args, wrappers = _unwrap(tokens)
    return {"executable": executable, "args": args, "wrappers": wrappers, "tokens": tokens, "raw": raw, "depth": depth}


def _nested_invocations(invocation: dict[str, Any], depth: int = 0) -> list[dict[str, Any]]:
    if depth >= 4:
        return []
    executable = invocation["executable"]
    args = invocation["args"]
    nested: list[dict[str, Any]] = []
    if executable in SHELLS:
        for index, value in enumerate(args[:-1]):
            if value.lower() in {"-c", "--command", "/c", "/k"}:
                nested_analysis = parse_shell(args[index + 1], depth=depth + 1)
                nested.extend(nested_analysis["invocations"])
                break
    if executable == "xargs":
        index = _skip_options(args, 0, {"-a", "--arg-file", "-d", "--delimiter", "-E", "--eof", "-I", "--replace", "-L", "--max-lines", "-n", "--max-args", "-P", "--max-procs", "-s", "--max-chars"})
        if index < len(args):
            nested_item = _invocation(args[index:], " ".join(args[index:]), depth + 1)
            nested.append(nested_item)
            nested.extend(_nested_invocations(nested_item, depth + 1))
    if executable == "find":
        for marker in ("-exec", "-execdir"):
            if marker in args:
                index = args.index(marker) + 1
                end = len(args)
                for terminator in (";", "+"):
                    if terminator in args[index:]:
                        end = min(end, index + args[index:].index(terminator))
                if index < end:
                    nested_item = _invocation(args[index:end], " ".join(args[index:end]), depth + 1)
                    nested.append(nested_item)
                    nested.extend(_nested_invocations(nested_item, depth + 1))
    return nested


def parse_shell(command: str, depth: int = 0) -> dict[str, Any]:
    transformed, resolved = _safe_substitutions(command)
    tokens, warnings = _lex(transformed)
    segments = _split_segments(tokens)
    invocations: list[dict[str, Any]] = []
    for segment in segments:
        item = _invocation(segment["tokens"], " ".join(segment["tokens"]), depth)
        item["operator_before"] = segment["operator_before"]
        item["operator_after"] = segment["operator_after"]
        if item["executable"]:
            invocations.append(item)
            invocations.extend(_nested_invocations(item, depth))
    canonical_parts = []
    for item in invocations:
        prefix = ">" * int(item.get("depth", 0))
        canonical_parts.append(prefix + " ".join([item["executable"], *item["args"]]).strip())
    dynamic_constructs: list[str] = []
    if DYNAMIC_COMMAND_RE.search(transformed):
        dynamic_constructs.append("dynamic-command-position")
    if "$ (" in " ".join(tokens) or "$(`" in transformed:
        dynamic_constructs.append("command-substitution")
    if re.search(r"\$\(|`[^`]+`", transformed):
        dynamic_constructs.append("command-substitution")
    if re.search(r"\beval\b", transformed):
        dynamic_constructs.append("eval")
    for item in invocations:
        if item.get("executable") in {"python", "python3", "perl", "ruby", "node", "php", "lua", "pwsh", "powershell"} and any(
            str(arg).lower() in {"-c", "-e", "--eval", "--command", "-command"} for arg in item.get("args", [])
        ):
            dynamic_constructs.append("inline-interpreter")
    if re.search(r"(?:^|[;&|]\s*)\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", transformed):
        dynamic_constructs.append("variable-command")
    return {
        "raw": command,
        "transformed": transformed,
        "resolved_safe_substitutions": resolved,
        "tokens": tokens,
        "invocations": invocations,
        "canonical": " ; ".join(canonical_parts) or re.sub(r"\s+", " ", transformed.strip()),
        "parse_warnings": warnings,
        "dynamic_constructs": sorted(set(dynamic_constructs)),
    }


def _detect_redirections(command: str, project_root: Path | None, policy: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    # This intentionally handles ordinary shell redirection syntax without expanding variables.
    pattern = re.compile(r"(?<!<)(?:^|\s)(?:\d*)?(>>?|>\|)\s*([^\s;&|]+)")
    for match in pattern.finditer(command):
        operator, target = match.group(1), _strip_quotes(match.group(2))
        if _is_block_device(target):
            findings.append(_finding(policy, "shell.redirect.block-device", "block-device-write", "shell redirection writes directly to a block or device path", f"{operator} {target}"))
        elif _is_absolute_or_sensitive(target, project_root, policy):
            findings.append(_finding(policy, "shell.redirect.sensitive", "destructive-overwrite", "shell redirection can truncate or overwrite a sensitive/absolute path", f"{operator} {target}"))
    return findings


def _detect_invocation(item: dict[str, Any], command: str, project_root: Path | None, policy: dict[str, Any]) -> list[dict[str, Any]]:
    exe = item["executable"]
    args = item["args"]
    raw = item["raw"]
    lowered_args = [value.lower() for value in args]
    flags = _short_flags(args)
    targets = _targets(args)
    findings: list[dict[str, Any]] = []

    if exe == "rm":
        recursive = "r" in flags or "R" in flags or _has_option(args, "--recursive")
        force = "f" in flags or _has_option(args, "--force")
        if recursive and force:
            findings.append(_finding(policy, "shell.rm.recursive-force", "destructive-delete", "recursive forced deletion", raw))
        elif recursive and any(_is_absolute_or_sensitive(target, project_root, policy) for target in targets):
            findings.append(_finding(policy, "shell.rm.recursive-sensitive", "destructive-delete", "recursive deletion targets a sensitive or absolute path", raw))

    if exe == "find" and ("-delete" in lowered_args or "-exec" in lowered_args or "-execdir" in lowered_args):
        if "-delete" in lowered_args:
            findings.append(_finding(policy, "shell.find.delete", "destructive-delete", "find -delete recursively removes matched paths", raw))

    if exe in {"del", "erase"} and ({"s", "q"} & flags or any(value in {"/s", "/q"} for value in lowered_args)):
        findings.append(_finding(policy, "windows.del.recursive", "destructive-delete", "recursive or quiet Windows deletion", raw))

    if exe in {"remove-item", "ri"} and any(value in {"-recurse", "-force"} for value in lowered_args):
        findings.append(_finding(policy, "powershell.remove-item", "destructive-delete", "PowerShell recursive/forced removal", raw))

    if exe == "shred":
        kind = "block-device-write" if any(_is_block_device(target) for target in targets) else "destructive-overwrite"
        findings.append(_finding(policy, "shell.shred", kind, "shred irreversibly overwrites file contents", raw))

    if exe == "truncate" and any(value in {"-s", "--size"} or value.startswith("--size=") for value in lowered_args):
        findings.append(_finding(policy, "shell.truncate", "destructive-overwrite", "truncate changes file length and can destroy contents", raw))

    if exe == "dd":
        outputs = [value.split("=", 1)[1] for value in args if value.lower().startswith("of=")]
        for target in outputs:
            kind = "block-device-write" if _is_block_device(target) else "destructive-overwrite"
            findings.append(_finding(policy, "shell.dd.output", kind, "dd writes raw bytes to its output target", f"of={target}"))

    if exe in {"cp", "mv", "install", "tee"} and any(_is_block_device(target) for target in targets):
        findings.append(_finding(policy, "shell.device-copy", "block-device-write", "file-copy/write command targets a block or device path", raw))
    if exe in {"cp", "mv", "install"} and targets:
        destination = targets[-1]
        if _is_absolute_or_sensitive(destination, project_root, policy) and not _is_block_device(destination):
            findings.append(_finding(policy, "shell.copy-sensitive", "destructive-overwrite", "copy/move/install command writes a sensitive or absolute destination", raw))
    if exe in {"rsync"} and any(value == "--delete" or value.startswith("--delete-") for value in lowered_args) and targets:
        destination = targets[-1]
        if _is_absolute_or_sensitive(destination, project_root, policy):
            findings.append(_finding(policy, "shell.rsync-delete-sensitive", "destructive-delete", "rsync --delete can remove content from a sensitive destination", raw))
    if exe == "tee" and any(_is_absolute_or_sensitive(target, project_root, policy) for target in targets):
        findings.append(_finding(policy, "shell.tee-sensitive", "destructive-overwrite", "tee writes a sensitive or absolute path", raw))
    if exe == "sed" and any(value == "-i" or value.startswith("-i") or value.startswith("--in-place") for value in args) and any(_is_absolute_or_sensitive(target, project_root, policy) for target in targets):
        findings.append(_finding(policy, "shell.sed-in-place-sensitive", "destructive-overwrite", "in-place edit targets a sensitive or absolute path", raw))

    if exe in FILESYSTEM_ADMIN or exe.startswith("mkfs"):
        read_only_fs = (
            (exe in {"fdisk", "sfdisk", "cfdisk", "gdisk", "sgdisk", "parted"} and any(value in {"-l", "--list", "--dump", "-p", "print"} for value in lowered_args))
            or (exe == "wipefs" and any(value in {"-n", "--no-act"} for value in lowered_args))
            or (exe == "cryptsetup" and bool(lowered_args) and lowered_args[0] in {"status", "isLuks".lower(), "luksdump"})
            or (exe == "zfs" and (not args or args[0].lower() not in {"destroy", "create", "set", "mount", "unmount", "rename", "rollback"}))
            or (exe == "zpool" and (not args or args[0].lower() not in {"destroy", "create", "attach", "detach", "replace", "remove", "export", "import"}))
        )
        if not read_only_fs:
            findings.append(_finding(policy, "system.filesystem-admin", "filesystem-admin", "filesystem or partition administration can irreversibly alter storage", raw))

    if exe in {"mount", "umount", "mount.cifs", "mount.nfs"} and (exe != "mount" or args):
        findings.append(_finding(policy, "system.mount", "filesystem-admin", "mount namespace or filesystem state modification", raw, severity="high"))

    if exe in {"chmod", "chown", "chgrp", "icacls", "takeown"}:
        recursive = "r" in flags or "R" in flags or _has_option(args, "--recursive", "/t")
        bad_mode = any(re.fullmatch(r"0?[0-7]*[2367]{2,3}", value) for value in args) or any("everyone:f" in value.lower() for value in args)
        sensitive = any(_is_absolute_or_sensitive(target, project_root, policy) for target in targets)
        if recursive and (exe in {"chown", "chgrp", "takeown"} or bad_mode or sensitive):
            findings.append(_finding(policy, "system.permissions.recursive", "permission-recursive", "recursive ownership/permission change affects a broad or sensitive target", raw))

    if exe == "git":
        if len(args) >= 2 and args[0].lower() == "reset" and "--hard" in lowered_args:
            findings.append(_finding(policy, "git.reset-hard", "git-history-rewrite", "git reset --hard discards tracked worktree changes", raw))
        if args and args[0].lower() == "clean" and "f" in flags and ({"d", "x", "X"} & flags or any(v in {"-d", "-x", "-X"} for v in args)):
            findings.append(_finding(policy, "git.clean-force", "destructive-delete", "git clean forcefully deletes untracked or ignored content", raw))
        if len(args) >= 2 and args[0].lower() == "branch" and "-D" in args:
            findings.append(_finding(policy, "git.branch-force-delete", "git-history-rewrite", "force-deletes a Git branch", raw))
        if len(args) >= 2 and args[0].lower() == "worktree" and args[1].lower() in {"remove", "prune"}:
            findings.append(_finding(policy, "git.worktree.remove", "worktree-remove", "removes or prunes Git worktrees", raw))
        if args and args[0].lower() == "push":
            dry_run = any(value in {"-n", "--dry-run"} for value in lowered_args)
            force = any(value in {"-f", "--force", "--mirror"} or value.startswith("--force=") for value in lowered_args)
            force_refspec = any(value.startswith("+") and len(value) > 1 for value in args[1:])
            force_with_lease = any(value.startswith("--force-with-lease") for value in lowered_args)
            delete_ref = "--delete" in lowered_args or any(value.startswith(":") and len(value) > 1 for value in args[1:])
            if not dry_run and (force or force_refspec):
                findings.append(_finding(policy, "git.push.force", "git-force-push", "unconditional force or mirror refspec rewrites remote history", raw))
            elif not dry_run and force_with_lease:
                findings.append(_finding(policy, "git.push.force-with-lease", "git-history-rewrite", "force-with-lease can still rewrite remote history", raw, severity="high"))
            if not dry_run and delete_ref:
                findings.append(_finding(policy, "git.push.delete-ref", "git-history-rewrite", "push deletes a remote ref", raw, severity="high"))
        if args and args[0].lower() in {"filter-branch", "filter-repo"}:
            findings.append(_finding(policy, "git.history-filter", "git-history-rewrite", "rewrites repository history", raw))

    if exe in {"docker", "podman"}:
        sub = lowered_args[0] if lowered_args else ""
        joined = " ".join(lowered_args)
        if sub in {"run", "create"} and (
            any(value == "--privileged" or value.startswith("--privileged=") for value in lowered_args)
            or "--pid=host" in joined or "--network=host" in joined or "--net=host" in joined
            or "--ipc=host" in joined or "--uts=host" in joined
            or "--cap-add=sys_admin" in joined or "--cap-add=all" in joined
            or "seccomp=unconfined" in joined or "apparmor=unconfined" in joined
            or re.search(r"(?:^|\s)(?:-v|--volume)(?:=|\s)*/\s*:/", " " + joined)
            or re.search(r"(?:source|src)=/(?:,|\s|$)", joined)
            or "/var/run/docker.sock" in joined or "/run/docker.sock" in joined
            or any(value == "--device" or value.startswith("--device=") for value in lowered_args)
        ):
            findings.append(_finding(policy, "container.host-access", "container-host-access", "container receives privileged host access or a host-root/control-socket mount", raw))
        if sub == "system" and any(value == "prune" for value in lowered_args[1:]):
            findings.append(_finding(policy, "container.system-prune", "container-destructive", "container system prune removes shared resources", raw))
        if sub in {"volume", "image", "network", "builder"} and "prune" in lowered_args:
            findings.append(_finding(policy, "container.resource-prune", "container-destructive", "container resource prune removes shared resources", raw))
        if sub == "rm" and ("f" in flags or "--force" in lowered_args):
            findings.append(_finding(policy, "container.force-remove", "container-destructive", "force-removes containers", raw))
        if exe == "docker" and sub == "compose" and "down" in lowered_args and any(value in {"-v", "--volumes"} for value in lowered_args):
            findings.append(_finding(policy, "container.compose-down-volumes", "container-destructive", "compose down with volumes deletes persistent data", raw))

    if exe == "kubectl" and args:
        verb = lowered_args[0]
        if verb in {"delete", "drain", "replace"}:
            findings.append(_finding(policy, "cluster.kubectl-destructive", "cluster-cloud-destructive", f"kubectl {verb} mutates or deletes cluster resources", raw))
    if exe in {"terraform", "tofu"} and args and lowered_args[0] in {"destroy", "state"}:
        if lowered_args[0] == "destroy" or (len(lowered_args) > 1 and lowered_args[1] in {"rm", "mv"}):
            findings.append(_finding(policy, "iac.terraform-destructive", "cluster-cloud-destructive", "infrastructure command destroys resources or rewrites state", raw))
    if exe == "helm" and args and lowered_args[0] in {"uninstall", "delete"}:
        findings.append(_finding(policy, "cluster.helm-uninstall", "cluster-cloud-destructive", "removes a Helm release", raw))

    if exe == "aws" and any(value in {"rm", "delete-stack", "terminate-instances", "delete-db-instance", "delete-cluster", "delete-bucket"} or value.startswith("delete-") for value in lowered_args):
        findings.append(_finding(policy, "cloud.aws-destructive", "cluster-cloud-destructive", "AWS command deletes or terminates cloud resources", raw))
    if exe in {"gcloud", "az"} and any(value in {"delete", "remove", "destroy"} for value in lowered_args):
        findings.append(_finding(policy, "cloud.cli-destructive", "cluster-cloud-destructive", "cloud CLI deletes or destroys resources", raw))

    if exe == "crontab" and not (len(args) == 1 and lowered_args[0] == "-l"):
        findings.append(_finding(policy, "persistence.crontab", "persistence-modification", "modifies scheduled persistent execution", raw))
    if exe == "systemctl" and any(value in {"enable", "disable", "mask", "unmask", "daemon-reload", "edit", "link"} for value in lowered_args):
        findings.append(_finding(policy, "persistence.systemd", "persistence-modification", "modifies system service persistence or unit loading", raw))
    if exe in {"launchctl", "schtasks", "at"}:
        if exe != "schtasks" or any(value in {"/create", "/change", "/delete", "/run"} for value in lowered_args):
            findings.append(_finding(policy, "persistence.scheduler", "persistence-modification", "modifies persistent or scheduled execution", raw))

    if exe in POWER_COMMANDS or (exe == "systemctl" and any(value in {"reboot", "poweroff", "halt", "suspend", "hibernate"} for value in lowered_args)):
        findings.append(_finding(policy, "system.power", "system-power-control", "changes host power or boot state", raw))
    if exe in {"kill", "pkill", "killall"} and any(value in {"-9", "-kill", "--signal=kill"} for value in lowered_args) and any(value in {"-1", "1", "all"} for value in lowered_args):
        findings.append(_finding(policy, "system.kill-all", "resource-exhaustion", "attempts to terminate a broad set of processes", raw))

    if exe in HARDWARE_TOOLS:
        joined = " ".join(lowered_args)
        write_flag = exe == "flashrom" and any(value in {"-w", "--write"} for value in lowered_args)
        if write_flag or re.search(r"\b(?:flash|program|erase|reset|recover|write|load|burn|sideload|update)\b", joined):
            findings.append(_finding(policy, "hardware.programming", "hardware-write", "programs, erases, resets, or writes hardware/firmware state", raw))
    if exe == "adb" and any(value in {"sideload", "root", "remount", "reboot"} for value in lowered_args):
        findings.append(_finding(policy, "hardware.adb-write", "hardware-write", "ADB command changes device boot or protected state", raw))

    if exe in {"python", "python3", "perl", "ruby", "node", "php", "lua", "pwsh", "powershell"} and any(
        value in {"-c", "-e", "--eval", "--command", "-command"} for value in lowered_args
    ):
        code = " ".join(args)
        if re.search(r"(?:os\.(?:remove|unlink|rmdir|chmod|chown|system)|shutil\.rmtree|subprocess\.|socket\.|requests\.|urllib\.|open\s*\([^)]*[, ]\s*['\"](?:w|a|x)|child_process|(?:fs|require\(['\"]fs['\"]\))\.(?:rm(?:sync)?|unlink(?:sync)?|write(?:filesync)?|chmod(?:sync)?|chown(?:sync)?)|Remove-Item|Invoke-WebRequest|Start-Process|/dev/)", code, re.I):
            findings.append(_finding(policy, "interpreter.inline-side-effect", "dynamic-shell-review", "inline general-purpose code contains file, process, network, or device side-effect primitives", raw, confidence="heuristic"))

    if exe in {"nc", "netcat", "ncat", "socat"}:
        joined = " ".join(lowered_args)
        if "l" in flags or "listen" in joined or "tcp-listen" in joined or "udp-listen" in joined or "exec:" in joined:
            findings.append(_finding(policy, "network.listener", "network-listener-or-tunnel", "opens a listener, tunnel, or process-connected socket", raw))
        if any(value in {"-e", "--exec", "-c"} for value in lowered_args) or "exec:/" in joined:
            findings.append(_finding(policy, "network.process-socket", "remote-code-execution", "connects a network socket directly to a local process", raw))
    if exe == "ssh" and any(value in {"-r", "-l", "-d", "-w"} for value in lowered_args):
        findings.append(_finding(policy, "network.ssh-tunnel", "network-listener-or-tunnel", "creates an SSH tunnel or forwarding path", raw))

    if exe in NETWORK_SEND_COMMANDS:
        sensitive = any(_is_absolute_or_sensitive(value, project_root, policy) for value in args) or any(re.search(pattern, command, re.I) for pattern in policy.get("sensitive_name_patterns", []))
        upload_signal = any(
            value in {"-t", "--upload-file", "--data-binary", "--data", "-d", "--form", "-f", "cp", "sync", "copy", "put", "post"}
            or value.startswith(("--upload-file=", "--data-binary=", "--data=", "--form=", "--post-file="))
            for value in lowered_args
        )
        remote_target = any(re.search(r"(?:^[A-Za-z0-9_.-]+@[^:]+:|^[^/\s]+::|^rsync://|^s3://|^gs://)", value, re.I) for value in args)
        pipe_input = item.get("operator_before") == "|"
        raw_transport = exe in {"nc", "netcat", "ncat", "socat", "scp", "sftp", "rsync", "rclone"}
        listener = exe in {"nc", "netcat", "ncat", "socat"} and ("l" in flags or "listen" in " ".join(lowered_args))
        scan_only = exe in {"nc", "netcat", "ncat"} and ("z" in flags or "--zero" in lowered_args)
        rclone_remote = exe == "rclone" and any(re.match(r"^[A-Za-z0-9_.-]+:[^/\\]", value) for value in args)
        interactive_raw_egress = exe in {"nc", "netcat", "ncat", "socat"} and not listener and not scan_only and len(args) >= 1
        outbound = upload_signal or (remote_target and raw_transport) or rclone_remote or (raw_transport and pipe_input) or interactive_raw_egress
        if sensitive and (outbound or raw_transport):
            findings.append(_finding(policy, "network.sensitive-egress", "external-sensitive-transfer", "network transfer references sensitive, credential, or research-state material", raw))
        elif outbound:
            findings.append(_finding(policy, "network.data-egress", "external-data-transfer", "command sends local data to a remote endpoint", raw))

    return findings


def analyze_command(command: str, project_root: Path | None, policy: dict[str, Any]) -> dict[str, Any]:
    parsed = parse_shell(command)
    findings: list[dict[str, Any]] = []

    if POLICY_BYPASS_RE.search(command):
        findings.append(_finding(policy, "policy.self-authorization", "policy-bypass", "tool execution attempts to alter, disable, or self-authorize the ROPS policy runtime", command, approvable=False))
    if FORK_BOMB_RE.search(command):
        findings.append(_finding(policy, "system.fork-bomb", "resource-exhaustion", "classic recursive fork bomb", command, approvable=False))

    findings.extend(_detect_redirections(command, project_root, policy))
    for invocation in parsed["invocations"]:
        findings.extend(_detect_invocation(invocation, command, project_root, policy))

    # Remote content piped into an interpreter is materially different from an ordinary download.
    if re.search(r"\b(?:curl|wget|http|httpie)\b[^|;&]*(?:\||\|&)\s*(?:sudo\s+)?(?:sh|bash|zsh|python|perl|ruby|node)\b", command, re.I):
        findings.append(_finding(policy, "network.download-execute", "remote-code-execution", "downloads remote content and pipes it directly into an interpreter", command))
    if re.search(r"\b(?:base64\s+(?:-d|--decode)|openssl\s+enc\s+-d)[^|;&]*(?:\||\|&)\s*(?:sh|bash|zsh|python|perl)\b", command, re.I):
        findings.append(_finding(policy, "shell.decode-execute", "remote-code-execution", "decodes opaque content and executes it immediately", command))
    if re.search(r"(?:/etc/systemd/system|/usr/lib/systemd/system|/etc/crontab|/etc/cron\.|/var/spool/cron|\.config/systemd/user|\.bashrc|\.zshrc|\.profile|authorized_keys)", command, re.I) and re.search(r"(?:>|tee\b|cp\b|install\b|sed\s+-i|echo\b)", command, re.I):
        findings.append(_finding(policy, "persistence.file-write", "persistence-modification", "writes a service, scheduler, shell-startup, or authorization persistence file", command))

    variable_target = bool(re.search(r"(?:>>?|>\|)\s*[\"']?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", command))
    dynamic_risky = bool(parsed["dynamic_constructs"] and (DYNAMIC_COMMAND_RE.search(parsed["transformed"]) or DANGEROUS_KEYWORDS.search(command))) or variable_target
    if dynamic_risky:
        findings.append(_finding(policy, "shell.dynamic-command", "dynamic-shell-review", "dynamic shell construction prevents reliable static resolution of a potentially consequential command", ", ".join(parsed["dynamic_constructs"]), confidence="heuristic"))

    # Conservative Windows/PowerShell fallbacks for syntax shlex does not model well.
    windows_fallbacks = (
        ("powershell.remove-item", "destructive-delete", r"\bRemove-Item\b[^\n]*(?:-Recurse[^\n]*-Force|-Force[^\n]*-Recurse)"),
        ("powershell.disk", "filesystem-admin", r"\b(?:Clear-Disk|Initialize-Disk|Format-Volume|Remove-Partition)\b"),
        ("windows.permissions", "permission-recursive", r"\bicacls\b[^\n]*/grant[^\n]*(?:Everyone|Users):F[^\n]*/T"),
    )
    for rule_id, kind, pattern in windows_fallbacks:
        if re.search(pattern, command, re.I):
            findings.append(_finding(policy, rule_id, kind, "Windows/PowerShell high-risk operation", command))

    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for item in findings:
        key = (item["kind"], item["rule_id"])
        existing = dedup.get(key)
        if not existing or SEVERITY_ORDER.get(item["severity"], 0) > SEVERITY_ORDER.get(existing["severity"], 0):
            dedup[key] = item
    ordered = sorted(dedup.values(), key=lambda item: (-SEVERITY_ORDER.get(item["severity"], 0), item["kind"], item["rule_id"]))
    uncertain = bool(parsed["parse_warnings"] or parsed["dynamic_constructs"])
    return {
        "schema_version": 2,
        "raw_sha256": _sha256(command),
        "canonical": parsed["canonical"],
        "canonical_sha256": _sha256(parsed["canonical"]),
        "parse_warnings": parsed["parse_warnings"],
        "dynamic_constructs": parsed["dynamic_constructs"],
        "safe_substitutions_resolved": parsed["resolved_safe_substitutions"],
        "invocations": [
            {"executable": item["executable"], "args": item["args"], "wrappers": item["wrappers"], "depth": item["depth"]}
            for item in parsed["invocations"]
        ],
        "findings": ordered,
        "uncertain": uncertain,
        "needs_semantic_review": uncertain or bool(DYNAMIC_ANY_RE.search(command)),
    }


def load_policy(root: Path) -> dict[str, Any]:
    path = root / "policies" / "risk-policy.json"
    return json.loads(path.read_text(encoding="utf-8"))
