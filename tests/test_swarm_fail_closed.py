"""Regression tests: generation must not be mistaken for verified production."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import swarm_pipeline


PROVIDER = {"id": "groq", "name": "Mock provider", "key": "not-a-real-key"}
OUTPUTS = [
    "# Product requirements", "# Architecture ADR",
    '{"colors": {"primary": "#fff"}, "typography": {}, "spacing": {}}',
    "# Screen flows", "CREATE TABLE thing (id INTEGER PRIMARY KEY);",
    "openapi: 3.0.0\ninfo:\n  title: Mock\n  version: 1.0.0\npaths: {}",
    "def example():\n    return 1", "<html><body>App</body></html>",
    "# QA test matrix", "import unittest\nclass TestThing(unittest.TestCase):\n    def test_one(self):\n        self.assertEqual(1, 1)",
    "# Advisory security review", "FROM python:3.11-slim",
    "READY FOR INDEPENDENT VERIFICATION",
]


class SwarmFailClosedTests(unittest.TestCase):
    def run_swarm(self, replacement=None, providers=None, prepare=None):
        outputs = list(OUTPUTS)
        if replacement is not None:
            index, value = replacement
            outputs[index] = value
        replies = iter(outputs)

        def fake_call(*args, **kwargs):
            result = next(replies)
            if not result:
                return "", False
            return result, True

        if providers is None:
            providers = [PROVIDER]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Dockerfile").write_text("FROM original-image\n", encoding="utf-8")
            (root / ".github" / "workflows").mkdir(parents=True)
            (root / ".github" / "workflows" / "ci.yml").write_text("name: Original CI\n", encoding="utf-8")
            if prepare:
                prepare(root)
            with (
                patch.object(swarm_pipeline.council, "get_active_providers", return_value=providers),
                patch.object(swarm_pipeline, "safe_call_brain", side_effect=fake_call),
                patch.object(swarm_pipeline, "update_swarm_status") as status,
                patch.object(swarm_pipeline, "log_swarm_message"),
                patch.object(swarm_pipeline.time, "sleep"),
            ):
                result = swarm_pipeline.execute_multi_brain_swarm("Mock task", str(root))
            return result, {
                "files": [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()],
                "signoff": (root / "specs" / "signoff.md").read_text(encoding="utf-8")
                if (root / "specs" / "signoff.md").exists() else "",
                "original_docker": (root / "Dockerfile").read_text(encoding="utf-8"),
                "original_ci": (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"),
                "status": status.call_args_list,
            }

    def test_no_provider_is_failure_not_success(self):
        passed, result = self.run_swarm(providers=[])
        self.assertFalse(passed)
        self.assertNotIn("specs/signoff.md", result["files"])

    def test_failed_design_does_not_generate_fake_tokens(self):
        passed, result = self.run_swarm((2, ""))
        self.assertFalse(passed)
        self.assertNotIn("specs/design/tokens.json", result["files"])

    def test_invalid_design_json_fails_closed(self):
        passed, _ = self.run_swarm((2, "not JSON"))
        self.assertFalse(passed)

    def test_failed_api_does_not_generate_fake_openapi(self):
        passed, result = self.run_swarm((5, ""))
        self.assertFalse(passed)
        self.assertNotIn("specs/api/openapi.yaml", result["files"])

    def test_fabricated_qa_pass_is_rejected(self):
        passed, result = self.run_swarm((9, "import unittest\nclass Test(unittest.TestCase):\n    def test_it(self):\n        self.assertTrue(True)"))
        self.assertFalse(passed)
        self.assertNotIn("tests/test_api.py", result["files"])

    def test_security_model_failure_cannot_claim_pass(self):
        passed, result = self.run_swarm((10, ""))
        self.assertFalse(passed)
        self.assertNotIn("specs/security/audit-report.md", result["files"])

    def test_lead_failure_does_not_create_approved_signoff(self):
        passed, result = self.run_swarm((12, ""))
        self.assertFalse(passed)
        self.assertNotIn("specs/signoff.md", result["files"])

    def test_model_rejection_is_preserved(self):
        passed, result = self.run_swarm((12, "REJECTED - REMEDIATION REQUIRED"))
        self.assertFalse(passed)
        self.assertIn("NOT VERIFIED", result["signoff"])

    def test_full_generation_requires_independent_verification(self):
        passed, result = self.run_swarm()
        self.assertTrue(passed)
        self.assertIn("NOT VERIFIED", result["signoff"])
        self.assertIn("specs/devops/Dockerfile", result["files"])
        self.assertIn("specs/devops/ci.yml", result["files"])
        self.assertEqual(result["original_docker"], "FROM original-image\n")
        self.assertEqual(result["original_ci"], "name: Original CI\n")
        self.assertFalse(any(
            call.kwargs.get("overall_progress") == 100
            for call in result["status"]
        ))


if __name__ == "__main__":
    unittest.main()
