from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from aethel_env_guard import (
    AETHELEnvGuard,
    CredentialPatternScanner,
    EnvFileScanner,
    GuardReport,
    is_sensitive_env_path,
    is_template_env_path,
    render_report,
)


class EnvFileScannerTests(unittest.TestCase):
    def test_forbidden_env_names_are_detected(self):
        scanner = EnvFileScanner()
        paths = [
            ".env", ".env.local", ".env.production", ".env.staging",
            ".env.windows", ".env.test", "backend/.env", "services/api/.env.prod",
            "production.env", "staging.env", ".envrc", ".envrc.local",
        ]
        findings = scanner.scan_paths(paths, source="tracked")
        self.assertEqual({item.path for item in findings}, set(paths))
        self.assertTrue(all(item.severity == "critical" for item in findings))

    def test_templates_are_allowed_but_still_content_scanned(self):
        for path in (".env.example", ".env.sample", ".env.template", ".env.dist", "backend/api.env.example"):
            with self.subTest(path=path):
                self.assertTrue(is_template_env_path(path))
                self.assertFalse(is_sensitive_env_path(path))
        self.assertTrue(is_sensitive_env_path(".env.windows"))

    def test_paths_are_case_insensitive(self):
        for path in (".ENV", ".Env.Windows", "Config.PRODUCTION.ENV"):
            with self.subTest(path=path):
                self.assertTrue(is_sensitive_env_path(path))

    def test_non_env_files_are_not_misclassified(self):
        for path in ("README.md", "backend/settings.py", "frontend/.env.example", "env_guard.py"):
            with self.subTest(path=path):
                self.assertFalse(is_sensitive_env_path(path))


class CredentialPatternScannerTests(unittest.TestCase):
    def setUp(self):
        self.scanner = CredentialPatternScanner()

    def test_sensitive_assignment_is_detected_without_value(self):
        candidate_value = "never-print-this-secret-value-9087"
        findings = self.scanner.scan_text(
            "settings.env", f"COLONY_ADMIN_KEY={candidate_value}\n", source="tracked"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].line_numbers, (1,))
        self.assertNotIn(candidate_value, json.dumps([item.__dict__ for item in findings]))

    def test_bas_secret_assignment_is_detected(self):
        findings = self.scanner.scan_text(
            ".env.windows", "COLONY_BAS_" + "SEC" + "RET=actual-secret-value-not-for-logs\n", source="tracked"
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule_id, "CREDENTIAL_ASSIGNMENT")

    def test_placeholder_values_do_not_trigger(self):
        values = [
            "", "changeme", "change-me", "replace-me", "placeholder", "example",
            "dummy", "redacted", "ci-test-admin-key", "test-secret-value",
            "YOUR_API_KEY", "$" + "{COLONY_ADMIN_KEY}", "$COLONY_ADMIN_KEY",
            "CAIOS_SECURITY_API_KEY", "os.getenv('COLONY_ADMIN_KEY')",
            "not-a-secret", "xxxxxxxxxxxxxxxx", "********",
        ]
        for value in values:
            with self.subTest(value=value):
                findings = self.scanner.scan_text(
                    "sample.env", f"COLONY_ADMIN_KEY={value}\n", source="tracked"
                )
                self.assertEqual(findings, [])

    def test_high_confidence_token_patterns_detected(self):
        tokens = [
            "AKIA" + "ABCDEFGHIJKLMNOP",
            "ghp_" + "abcdefghijklmnopqrstuvwxyz123456",
            "github_pat_" + "abcdefghijklmnopqrstuvwxyz123456",
            "sk_live_" + "abcdefghijklmnop1234",
            "rk_live_" + "abcdefghijklmnop1234",
            "xoxb-" + "1234567890-abcdef",
            "eyJabcdefghijk." + "eyJabcdefghijk." + "eyJabcdefghijk",
            "-----BEGIN " + "PRIVATE KEY-----",
        ]
        for token in tokens:
            with self.subTest(rule="high-confidence-pattern"):
                findings = self.scanner.scan_text("source.txt", f"payload = '{token}'", source="tracked")
                self.assertTrue(findings)
                self.assertNotIn(token, json.dumps([item.__dict__ for item in findings]))

    def test_multiple_findings_are_line_addressed(self):
        findings = self.scanner.scan_text(
            "sample.env",
            "SAFE=ok\n" + "COLONY_ADMIN_" + "KEY=real-value-one\n" + "COLONY_BAS_" + "SEC" + "RET=real-value-two\n",
            source="tracked",
        )
        self.assertEqual({line for item in findings for line in item.line_numbers}, {2, 3})

    def test_report_messages_never_contain_candidate_value(self):
        candidate_value = "non-placeholder-super-secret-34991"
        report = GuardReport()
        for item in self.scanner.scan_text("file.env", f"COLONY_ADMIN_KEY={candidate_value}", source="tracked"):
            report.add(item)
        output = render_report(report)
        self.assertNotIn(candidate_value, output)
        self.assertIn("line=1", output)

    def test_credential_name_variants(self):
        rows = [
            "API_" + "KEY=high-entropy-api-key-value",
            "SERVICE_ACCESS_" + "KEY=high-entropy-access-key",
            "DB_" + "PASS" + "WORD=database-password-value",
            "OAUTH_" + "TO" + "KEN=long-oauth-token-value",
            "PRIVATE_" + "KEY=not-a-placeholder-key",
        ]
        for row in rows:
            with self.subTest(variable=row.split("=")[0]):
                self.assertTrue(self.scanner.scan_text("config.txt", row, source="tracked"))


class GuardReportTests(unittest.TestCase):
    def test_findings_are_deduplicated_and_lines_combined(self):
        from aethel_env_guard import Finding
        report = GuardReport()
        report.add(Finding("RULE", "high", "a.txt", (2,), "tracked", "redacted"))
        report.add(Finding("RULE", "high", "a.txt", (4,), "tracked", "redacted"))
        self.assertEqual(len(report.findings), 1)
        self.assertEqual(report.findings[0].line_numbers, (2, 4))

    def test_current_findings_block_but_history_findings_are_advisory_by_default(self):
        from aethel_env_guard import Finding
        report = GuardReport()
        report.add(Finding("HISTORY", "critical", ".env.windows", (), "history", "redacted"))
        self.assertFalse(report.has_current_blockers())
        self.assertTrue(report.has_history_findings())
        report.add(Finding("CURRENT", "high", "app.py", (2,), "tracked", "redacted"))
        self.assertTrue(report.has_current_blockers())

    def test_report_json_contains_no_candidate_values(self):
        from aethel_env_guard import Finding
        report = GuardReport()
        report.add(Finding("RULE", "high", "x.env", (7,), "tracked", "value redacted"))
        output = json.dumps(report.as_dict())
        self.assertNotIn("credential-value", output)
        self.assertEqual(report.as_dict()["schema"], "aethel-env-guard-report/v1")


class GitIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "guard-test@example.invalid")
        self.git("config", "user.name", "Env Guard Test")
        (self.root / "README.md").write_text("clean\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "initial")
        self.guard = AETHELEnvGuard(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.root), *args],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def test_ci_detects_tracked_env_path(self):
        (self.root / ".env.windows").write_text("COLONY_ADMIN_" + "KEY=realish-value-long-enough\n", encoding="utf-8")
        self.git("add", ".env.windows")
        self.git("commit", "-qm", "fixture should be blocked")
        report = self.guard.run_ci()
        rules = {item.rule_id for item in report.findings if item.source == "tracked"}
        self.assertIn("ENV_FILE_TRACKED", rules)
        self.assertIn("CREDENTIAL_ASSIGNMENT", rules)
        self.assertTrue(report.has_current_blockers())

    def test_precommit_detects_staged_sensitive_file_without_commit(self):
        (self.root / ".env.windows").write_text("COLONY_ADMIN_" + "KEY=staged-realish-value\n", encoding="utf-8")
        self.git("add", ".env.windows")
        report = self.guard.run_precommit()
        self.assertTrue(report.has_current_blockers())
        self.assertTrue(any(item.source == "staged" for item in report.findings))

    def test_precommit_scans_the_staged_blob_not_unstaged_worktree(self):
        (self.root / "settings.py").write_text("COLONY_ADMIN_" + "KEY=replace-me\n", encoding="utf-8")
        self.git("add", "settings.py")
        (self.root / "settings.py").write_text("COLONY_ADMIN_" + "KEY=unstaged-secret-value\n", encoding="utf-8")
        report = self.guard.run_precommit()
        self.assertFalse(any(item.rule_id == "CREDENTIAL_ASSIGNMENT" for item in report.findings))

    def test_precommit_blocks_credential_in_staged_normal_file(self):
        (self.root / "settings.py").write_text("COLONY_ADMIN_" + "KEY=real-secret-value-33822\n", encoding="utf-8")
        self.git("add", "settings.py")
        report = self.guard.run_precommit()
        self.assertTrue(any(item.rule_id == "CREDENTIAL_ASSIGNMENT" for item in report.findings))

    def test_history_scan_finds_deleted_env_path_and_never_prints_value(self):
        candidate_value = "historic-secret-value-should-not-appear-7782"
        (self.root / ".env.windows").write_text(f"COLONY_ADMIN_KEY={candidate_value}\n", encoding="utf-8")
        self.git("add", ".env.windows")
        self.git("commit", "-qm", "temporary env fixture")
        self.git("rm", "-q", ".env.windows")
        self.git("commit", "-qm", "remove env fixture")
        report = self.guard.run_history()
        output = render_report(report)
        self.assertTrue(any(item.rule_id == "ENV_FILE_TRACKED" and item.source == "history" for item in report.findings))
        self.assertTrue(any(item.rule_id == "CREDENTIAL_ASSIGNMENT" and item.source == "history" for item in report.findings))
        self.assertNotIn(candidate_value, output)

    def test_history_scan_failure_is_handled_by_ci_report(self):
        report = self.guard.run_ci()
        self.assertFalse(any(item.rule_id == "HISTORY_SCAN_UNAVAILABLE" for item in report.findings))

    def test_safe_template_file_is_not_blocked_by_path_rule(self):
        (self.root / ".env.example").write_text("COLONY_ADMIN_" + "KEY=replace-me\n", encoding="utf-8")
        self.git("add", ".env.example")
        self.git("commit", "-qm", "add safe env example")
        report = self.guard.run_ci()
        self.assertFalse(any(
            item.rule_id == "ENV_FILE_TRACKED" and item.path == ".env.example" and item.source == "tracked"
            for item in report.findings
        ))

    def test_ci_report_detects_secret_in_normal_tracked_file(self):
        (self.root / "config.py").write_text("COLONY_ADMIN_" + "KEY=committed-real-value-98432\n", encoding="utf-8")
        self.git("add", "config.py")
        self.git("commit", "-qm", "fixture credential")
        report = self.guard.run_ci()
        self.assertTrue(any(
            item.rule_id == "CREDENTIAL_ASSIGNMENT" and item.path == "config.py" and item.source == "tracked"
            for item in report.findings
        ))


if __name__ == "__main__":
    unittest.main(verbosity=2)
