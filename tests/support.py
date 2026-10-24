"""Shared fixtures for the swarm pipeline tests.

Everything here is a fake: providers are plain dicts with a fake key, the
model call (`council.call_llm`) is replaced, and `subprocess.run` is replaced,
so no network is touched and no model-generated code is ever executed.

Importing this module also puts the repository root on ``sys.path`` so the
tests work under ``python -I`` (isolated mode drops the working directory
from the import path).
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = str(Path(os.environ.get("TENAGENT_TEST_ROOT") or Path(__file__).resolve().parent.parent))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import council  # noqa: E402
import swarm_pipeline  # noqa: E402

FAKE_KEY = "sk-FAKE-do-not-use-0123456789"
PROVIDER = {"id": "groq", "name": "Mock provider", "key": FAKE_KEY}
AGENT_IDS = [
    "01_pm", "02_arch", "03_designer", "04_dba", "05_backend",
    "06_client", "07_qa", "08_security", "09_devops", "10_tech_lead",
]

# (substring of the system prompt, output key)
STAGE_MARKERS = [
    ("Product Manager", "prd"),
    ("System Architect", "adr"),
    ("design tokens containing", "tokens"),
    ("Screen Flow Document", "flows"),
    ("Database Engineer", "sql"),
    ("API Architect", "openapi"),
    ("You are the Backend Engineer", "backend"),
    ("Client Engineer", "client"),
    ("Formulate a QA Test Matrix", "qa_matrix"),
    ("executable Python unittest suite", "tests"),
    ("OWASP Application Security Auditor", "security"),
    ("DevOps Engineer", "docker"),
    ("Technical Lead", "lead"),
]

PROSE = " Users can create, list and remove items, and every list view shows the newest entry first."

GOOD_OUTPUTS = {
    "prd": "# Product requirements\n\nUsers can list things." + PROSE,
    "adr": "# Architecture ADR\n\nClean architecture with domain, use case and repository layers." + PROSE,
    "tokens": '{"colors": {"primary": "#fff"}, "typography": {}, "spacing": {}}',
    "flows": "# Screen flows\n\nHome -> list -> detail." + PROSE,
    "sql": "CREATE TABLE thing (id INTEGER PRIMARY KEY);",
    "openapi": (
        "openapi: 3.0.0\ninfo:\n  title: Mock\n  version: 1.0.0\n"
        "paths:\n  /health:\n    get:\n      responses:\n        '200':\n          description: ok\n"
    ),
    "backend": "def example():\n    return 1\n",
    "client": "<html><body>App</body></html>",
    "qa_matrix": "# QA test matrix\n\nHappy path, empty list, boundary sizes." + PROSE,
    "tests": (
        "import unittest\n\n"
        "class TestExample(unittest.TestCase):\n"
        "    def test_example(self):\n"
        "        self.assertEqual(1 + 1, 2)\n"
    ),
    "security": "# Advisory security review\n\nNo findings are claimed here; a scanner must confirm." + PROSE,
    "docker": "FROM python:3.11-slim\n",
    "lead": "[APPROVED FOR PRODUCTION]",
}


def stage_key(system_prompt):
    for marker, key in STAGE_MARKERS:
        if marker in system_prompt:
            return key
    raise AssertionError("unrecognised stage prompt: " + system_prompt[:60])


def make_status_file(root, overall=0, phase="Phase 1", agent_overrides=None):
    specs = Path(root) / "specs"
    specs.mkdir(parents=True, exist_ok=True)
    agents = []
    for aid in AGENT_IDS:
        agent = {
            "id": aid, "role": aid, "status": "IDLE", "currentTask": "",
            "processDetail": "", "progress": 0, "deliverable": "",
        }
        agent.update((agent_overrides or {}).get(aid, {}))
        agents.append(agent)
    data = {
        "project": {"name": "t", "phase": phase, "overallProgress": overall},
        "agents": agents,
        "logs": [],
    }
    path = specs / "swarm-status.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def read_status(root):
    return json.loads((Path(root) / "specs" / "swarm-status.json").read_text(encoding="utf-8-sig"))


def list_files(root):
    return sorted(p.relative_to(root).as_posix() for p in Path(root).rglob("*") if p.is_file())


class PipelineCase(unittest.TestCase):
    """Runs the real pipeline entry point with a faked model call and a faked test runner."""

    def setUp(self):
        quiet = patch.object(swarm_pipeline, "print", create=True)  # the pipeline echoes its log to stdout
        quiet.start()
        self.addCleanup(quiet.stop)
        self.new_root()

    def new_root(self):
        """Fresh project directory (also used between subTests so they cannot leak state)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "Dockerfile").write_text("FROM original-image\n", encoding="utf-8")
        (self.root / ".github" / "workflows").mkdir(parents=True)
        (self.root / ".github" / "workflows" / "ci.yml").write_text("name: Original CI\n", encoding="utf-8")
        self.calls = []
        self.test_runs = []

    def run_swarm(self, outputs=None, providers=None, status=True, goal="Mock task",
                  call_hook=None, run_fn=None, debate=None, test_returncode=0):
        merged = dict(GOOD_OUTPUTS)
        merged.update(outputs or {})
        if status and not (self.root / "specs" / "swarm-status.json").exists():
            make_status_file(self.root)
        providers = [PROVIDER] if providers is None else providers

        def fake_call_llm(provider, system_prompt, user_prompt, timeout=75):
            key = stage_key(system_prompt)
            self.calls.append(key)
            if call_hook:
                call_hook(key)
            value = merged[key]
            if isinstance(value, BaseException):
                raise value
            return value() if callable(value) else value

        def fake_run(args, **kwargs):
            # The QA stage would run the generated tests; here nothing is ever executed.
            self.test_runs.append({"args": list(args), **kwargs})
            if isinstance(test_returncode, BaseException):
                raise test_returncode
            return subprocess.CompletedProcess(args, test_returncode, "", "fake runner output")

        with ExitStack() as stack:
            stack.enter_context(patch.object(council, "get_active_providers", return_value=providers))
            stack.enter_context(patch.object(council, "call_llm", side_effect=fake_call_llm))
            stack.enter_context(patch("subprocess.run", side_effect=fake_run))
            if debate is None:
                debate_patch = patch.object(
                    council, "run_council_debate", return_value={"status": "native_only", "consensus": None})
            else:
                debate_patch = patch.object(council, "run_council_debate", side_effect=debate)
            stack.enter_context(debate_patch)
            stack.enter_context(patch.object(swarm_pipeline.time, "sleep"))
            runner = run_fn or swarm_pipeline.execute_multi_brain_swarm
            return runner(goal, str(self.root))

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def exists(self, rel):
        return (self.root / rel).exists()

    def files(self):
        return list_files(self.root)
