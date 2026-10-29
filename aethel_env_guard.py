#!/usr/bin/env python3
"""AETHEL environment-file and credential guard.

The guard reports file paths, rule IDs, and line numbers only. It never prints
matched text, credential values, or source snippets.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

MAX_SCAN_BYTES = 2 * 1024 * 1024
MAX_HISTORY_COMMITS_PER_PATH = 250

TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
SENSITIVE_ENV_NAMES = {".envrc", ".envrc.local", ".envrc.private"}

SECRET_NAME = re.compile(
    r"""^\s*(?:export\s+)?["']?(?P<name>[A-Z][A-Z0-9_]*(?:API[_-]?KEY|ADMIN[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|PRIVATE[_-]?KEY|ACCESS[_-]?KEY|AUTHORIZATION|AUTH[_-]?TOKEN|BEARER|WEBHOOK[_-]?SECRET)[A-Z0-9_.-]*)["']?\s*[:=]\s*["']?(?P<value>[^"'#,;\r\n]*?)["']?\s*,?\s*(?:#.*)?$"""
)
HIGH_CONFIDENCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("PRIVATE_KEY_BLOCK", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("AWS_ACCESS_KEY_ID", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")),
    ("STRIPE_LIVE_KEY", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("BEARER_TOKEN", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~-]{20,}")),
)
PLACEHOLDER_EXACT = {
    "", "none", "null", "undefined", "nil", "n/a", "na", "false", "true",
    "changeme", "change-me", "change_me", "replace-me", "replace_me",
    "placeholder", "example", "sample", "dummy", "redacted", "not-a-secret",
    "notasecret", "your-secret-here", "your_api_key", "your-api-key",
}
PLACEHOLDER_PREFIXES = (
    "ci-test-", "test-", "dummy-", "fake-", "example-", "sample-",
    "placeholder-", "replace-me-", "your-", "your_", "redacted-",
)
REFERENCE_VALUE = re.compile(
    r"^(?:\$\{?[A-Z_][A-Z0-9_]*\}?|%[A-Z_][A-Z0-9_]*%|"
    r"[A-Z][A-Z0-9_]*(?:_API_KEY|_SECRET|_TOKEN|_KEY|_PASSWORD))$"
)


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    path: str
    line_numbers: tuple[int, ...]
    source: str
    message: str


class GuardReport:
    """Redacted finding aggregate. It intentionally has no source/value field."""

    def __init__(self) -> None:
        self._findings: dict[tuple[str, str, str], Finding] = {}

    def add(self, finding: Finding) -> None:
        key = (finding.rule_id, finding.path, finding.source)
        prior = self._findings.get(key)
        if prior is None:
            self._findings[key] = finding
            return
        lines = tuple(sorted(set(prior.line_numbers) | set(finding.line_numbers)))
        self._findings[key] = Finding(
            prior.rule_id, prior.severity, prior.path, lines, prior.source, prior.message
        )

    @property
    def findings(self) -> list[Finding]:
        return sorted(
            self._findings.values(),
            key=lambda item: (item.severity, item.path.casefold(), item.rule_id, item.source),
        )

    def has_current_blockers(self) -> bool:
        return any(item.source in {"tracked", "staged"} for item in self.findings)

    def has_history_findings(self) -> bool:
        return any(item.source == "history" for item in self.findings)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": "aethel-env-guard-report/v1",
            "finding_count": len(self.findings),
            "findings": [
                {
                    **asdict(item),
                    "line_numbers": list(item.line_numbers),
                }
                for item in self.findings
            ],
        }


def is_template_env_path(path: str) -> bool:
    name = PurePosixPath(path.replace("\\", "/")).name.casefold()
    return any(name.endswith(suffix) for suffix in TEMPLATE_SUFFIXES)


def is_sensitive_env_path(path: str) -> bool:
    """True for environment files that should never be checked into Git."""
    name = PurePosixPath(path.replace("\\", "/")).name.casefold()
    if is_template_env_path(name):
        return False
    if name in SENSITIVE_ENV_NAMES or name == ".env":
        return True
    if name.startswith(".env.") or name.endswith(".env"):
        return True
    return False


def _clean_candidate_value(raw: str) -> str:
    value = raw.strip().strip(chr(34) + chr(39) + " ").strip()
    if " #" in value:
        value = value.split(" #", 1)[0].rstrip()
    return value


def _is_placeholder(raw: str) -> bool:
    value = _clean_candidate_value(raw)
    normalized = value.casefold()
    if normalized in PLACEHOLDER_EXACT:
        return True
    if any(normalized.startswith(prefix) for prefix in PLACEHOLDER_PREFIXES):
        return True
    if normalized.startswith(("os.getenv(", "os.environ", "process.env.", "getenv(", "re.compile(", "re.pattern(")):
        return True
    if re.fullmatch(r"\{[A-Za-z_][A-Za-z0-9_]*\}", value):
        return True
    if REFERENCE_VALUE.fullmatch(value):
        return True
    if "..." in value or ("<" in value and ">" in value):
        return True
    if value and set(value) <= {"x", "X", "*", ".", "_", "-"}:
        return True
    return False


class EnvFileScanner:
    def scan_paths(self, paths: Iterable[str], *, source: str) -> list[Finding]:
        findings = []
        for raw_path in paths:
            path = raw_path.replace("\\", "/")
            if is_sensitive_env_path(path):
                findings.append(Finding(
                    "ENV_FILE_TRACKED",
                    "critical",
                    path,
                    (),
                    source,
                    "Environment-like file is present in the Git index/history; remove it from tracking.",
                ))
        return findings


def _supports_assignment_scan(path: str) -> bool:
    """Only parse key/value assignments in configuration-like files, not source code."""
    normalized = path.replace("\\", "/")
    name = PurePosixPath(normalized).name.casefold()
    suffix = PurePosixPath(name).suffix
    return (
        name.startswith(".env")
        or name.endswith(".env")
        or suffix in {".ini", ".yaml", ".yml", ".toml", ".cfg", ".conf", ".properties"}
    )


class CredentialPatternScanner:
    """Find likely credential material without retaining or displaying values."""

    def scan_text(self, path: str, text: str, *, source: str) -> list[Finding]:
        findings: dict[tuple[str, int], Finding] = {}
        for line_number, line in enumerate(text.splitlines(), start=1):
            for rule_id, pattern in HIGH_CONFIDENCE_PATTERNS:
                if pattern.search(line):
                    findings[(rule_id, line_number)] = Finding(
                        rule_id,
                        "critical" if rule_id in {"PRIVATE_KEY_BLOCK", "STRIPE_LIVE_KEY"} else "high",
                        path,
                        (line_number,),
                        source,
                        "Credential-like material detected; value intentionally redacted.",
                    )
            assignment = SECRET_NAME.search(line) if _supports_assignment_scan(path) else None
            if assignment:
                name = assignment.group("name").strip(chr(34) + chr(39)).casefold()
                value = assignment.group("value")
                if not _is_placeholder(value):
                    rule_id = "CREDENTIAL_ASSIGNMENT"
                    findings[(rule_id, line_number)] = Finding(
                        rule_id,
                        "high",
                        path,
                        (line_number,),
                        source,
                        f"Non-placeholder value assigned to a sensitive variable ({name}); value redacted.",
                    )
        return list(findings.values())


class GitHistoryScanner:
    """Inspect historical env-file names and their blobs without emitting content."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.env_scanner = EnvFileScanner()
        self.credential_scanner = CredentialPatternScanner()

    def _git(self, *args: str, check: bool = True) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and result.returncode:
            raise RuntimeError("Git history scan failed; command output suppressed.")
        return result.stdout

    def scan(self) -> list[Finding]:
        names = self._git("log", "--all", "--full-history", "--format=", "--name-only", "-z")
        paths = sorted({
            entry.decode("utf-8", "surrogateescape").replace("\\", "/")
            for entry in names.split(b"\0")
            if entry and is_sensitive_env_path(entry.decode("utf-8", "surrogateescape"))
        })
        findings: list[Finding] = []
        for path in paths:
            findings.extend(self.env_scanner.scan_paths([path], source="history"))
            commits = self._git(
                "log", "--all", "--format=%H", "--", f":(literal){path}"
            ).decode("ascii", "ignore").splitlines()
            for commit in commits[:MAX_HISTORY_COMMITS_PER_PATH]:
                blob = self._git("show", f"{commit}:{path}", check=False)
                if not blob:
                    continue
                text = blob.decode("utf-8", "replace")
                findings.extend(self.credential_scanner.scan_text(path, text, source="history"))
        report = GuardReport()
        for item in findings:
            report.add(item)
        return report.findings


class AETHELEnvGuard:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or Path(__file__).resolve().parent).resolve()
        self.env_scanner = EnvFileScanner()
        self.credential_scanner = CredentialPatternScanner()

    def _git_bytes(self, *args: str, check: bool = True) -> bytes:
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if check and result.returncode:
            raise RuntimeError("Git scan failed; command output suppressed.")
        return result.stdout

    def _read_worktree(self, rel_path: str) -> bytes | None:
        candidate = self.root / rel_path
        try:
            if candidate.is_symlink() or not candidate.is_file():
                return None
            resolved = candidate.resolve()
            if self.root not in resolved.parents and resolved != self.root:
                return None
            if candidate.stat().st_size > MAX_SCAN_BYTES:
                return None
            return candidate.read_bytes()
        except (OSError, ValueError):
            return None

    @staticmethod
    def _decode_for_scan(raw: bytes | None) -> str | None:
        if raw is None or len(raw) > MAX_SCAN_BYTES or b"\0" in raw[:8192]:
            return None
        return raw.decode("utf-8", "replace")

    def _scan_contents(self, report: GuardReport, paths: Iterable[str], *, source: str) -> None:
        for path in sorted(set(paths)):
            raw = self._read_worktree(path)
            text = self._decode_for_scan(raw)
            if text is None:
                continue
            for finding in self.credential_scanner.scan_text(path, text, source=source):
                report.add(finding)

    def run_ci(self, *, strict_history: bool = False) -> GuardReport:
        report = GuardReport()
        tracked = [
            entry.decode("utf-8", "surrogateescape")
            for entry in self._git_bytes("ls-files", "-z").split(b"\0")
            if entry
        ]
        for finding in self.env_scanner.scan_paths(tracked, source="tracked"):
            report.add(finding)
        self._scan_contents(report, tracked, source="tracked")
        try:
            history_findings = GitHistoryScanner(self.root).scan()
            for finding in history_findings:
                report.add(finding)
        except RuntimeError:
            report.add(Finding(
                "HISTORY_SCAN_UNAVAILABLE",
                "high",
                ".git",
                (),
                "history",
                "Full-history inspection did not complete; review required.",
            ))
        if strict_history and report.has_history_findings():
            report.add(Finding(
                "STRICT_HISTORY_BLOCK",
                "critical",
                ".git",
                (),
                "tracked",
                "Strict history mode blocks unresolved historical env-file exposure.",
            ))
        return report

    def run_precommit(self) -> GuardReport:
        report = GuardReport()
        staged = [
            entry.decode("utf-8", "surrogateescape")
            for entry in self._git_bytes(
                "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"
            ).split(b"\0")
            if entry
        ]
        for finding in self.env_scanner.scan_paths(staged, source="staged"):
            report.add(finding)
        for path in staged:
            raw = self._git_bytes("show", f":{path}", check=False)
            exists = subprocess.run(
                ["git", "-C", str(self.root), "cat-file", "-e", f":{path}"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            ).returncode == 0
            if not exists:
                continue
            text = self._decode_for_scan(raw)
            if text is None:
                continue
            for finding in self.credential_scanner.scan_text(path, text, source="staged"):
                report.add(finding)
        return report

    def run_history(self) -> GuardReport:
        report = GuardReport()
        for finding in GitHistoryScanner(self.root).scan():
            report.add(finding)
        return report


def render_report(report: GuardReport) -> str:
    lines = [
        f"AETHEL Env Guard: {len(report.findings)} finding(s)",
        "Credential values and source snippets are never displayed.",
    ]
    for item in report.findings:
        locations = ",".join(str(value) for value in item.line_numbers) or "n/a"
        lines.append(
            f"{item.severity.upper()} {item.rule_id} source={item.source} "
            f"path={item.path} line={locations}: {item.message}"
        )
    if report.has_history_findings():
        lines.append(
            "HISTORY NOTE: historical exposure is reported but does not block default CI; "
            "rotate any real keys and coordinate history cleanup. Use --strict-history to block."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("ci", "precommit", "history"))
    parser.add_argument("--strict-history", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)
    try:
        guard = AETHELEnvGuard()
        if args.mode == "ci":
            strict = args.strict_history or os.environ.get("AETHEL_ENV_GUARD_STRICT_HISTORY") == "1"
            report = guard.run_ci(strict_history=strict)
            blocked = report.has_current_blockers() or (
                strict and report.has_history_findings()
            )
        elif args.mode == "precommit":
            report = guard.run_precommit()
            blocked = report.has_current_blockers()
        else:
            report = guard.run_history()
            blocked = args.strict_history and report.has_history_findings()
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"AETHEL Env Guard failed safely ({type(exc).__name__}); output suppressed.", file=sys.stderr)
        return 2

    print(json.dumps(report.as_dict(), indent=2) if args.json_output else render_report(report))
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
