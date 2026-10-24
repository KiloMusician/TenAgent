"""Callers of the pipeline: CLI exit codes and the dashboard/stream status writers."""

import contextlib
import http.server
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import support
from support import make_status_file, read_status
import swarm_pipeline


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(support.REPO_ROOT, relative_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeChatServer:
    """Loopback-only stand-in for an OpenAI-compatible provider. Never leaves the machine."""

    def __init__(self, answers):
        outer = self
        self.requests = 0

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                outer.requests += 1
                system_prompt = payload["messages"][0]["content"]
                text = answers(support.stage_key(system_prompt))
                body = json.dumps({"choices": [{"message": {"content": text}}]}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(10)


class ExitCodes(unittest.TestCase):
    """Run the real scripts as subprocesses from a scratch copy. Providers are either absent or a
    loopback fake server, so no network and no real key is involved."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.reset_dir()

    def reset_dir(self):
        """Empty project directory containing only the scripts under test."""
        for child in self.dir.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        for name in ("swarm_pipeline.py", "council.py", "stream.py"):
            shutil.copy(os.path.join(support.REPO_ROOT, name), self.dir / name)
        (self.dir / "specs").mkdir()

    def configure_provider(self, url):
        config = {"providers": [{"provider": "9router", "key": support.FAKE_KEY, "baseUrl": url, "model": "mock"}]}
        (self.dir / "specs" / "swarm-config.json").write_text(json.dumps(config), encoding="utf-8")

    def run_script(self, *args):
        env = dict(os.environ, NO_PROXY="127.0.0.1,localhost", no_proxy="127.0.0.1,localhost")
        return subprocess.run([sys.executable, "-E", "-s", *args], cwd=self.dir, env=env,
                              capture_output=True, text=True, timeout=180)

    def run_record(self):
        return json.loads((self.dir / "specs" / "swarm-run.json").read_text(encoding="utf-8"))

    def assert_exit(self, result, expected):
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    SCRIPTS = {"swarm_pipeline.py": ("swarm_pipeline.py", "Build me a thing"),
               "stream.py swarm": ("stream.py", "swarm", "Build me a thing")}

    def test_exit_0_only_when_a_draft_was_generated(self):
        for label, command in self.SCRIPTS.items():
            with self.subTest(label), _FakeChatServer(lambda key: support.GOOD_OUTPUTS[key]) as server:
                self.reset_dir()
                self.configure_provider(server.url)
                self.assert_exit(self.run_script(*command), 0)
                self.assertEqual(self.run_record()["state"], "AWAITING_VERIFICATION")
                self.assertGreaterEqual(server.requests, 13)

    def test_exit_1_when_no_provider_is_configured(self):
        for label, command in self.SCRIPTS.items():
            with self.subTest(label):
                self.reset_dir()
                self.assert_exit(self.run_script(*command), 1)

    def test_exit_1_when_the_provider_answers_with_unusable_output(self):
        for label, command in self.SCRIPTS.items():
            with self.subTest(label), _FakeChatServer(lambda key: "Sorry, I cannot help with that.") as server:
                self.reset_dir()
                self.configure_provider(server.url)
                self.assert_exit(self.run_script(*command), 1)
                self.assertEqual(self.run_record()["state"], "FAILED")


class DashboardWriters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.serve = load_module("tenagent_serve_under_test", os.path.join("dashboard", "serve.py"))

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.status_path = make_status_file(self.root)

    def set_agent(self, agent_id, **fields):
        data = json.loads(self.status_path.read_text(encoding="utf-8"))
        for agent in data["agents"]:
            if agent["id"] == agent_id:
                agent.update(fields)
        self.status_path.write_text(json.dumps(data), encoding="utf-8")

    def agent(self, agent_id):
        return {a["id"]: a for a in read_status(self.root)["agents"]}[agent_id]

    def test_file_event_does_not_turn_a_failed_stage_back_into_working(self):
        self.set_agent("04_dba", status="ERROR", processDetail="Invalid schema output.")
        self.serve.handle_file_event("04_dba", "Saved specs/database/schema.sql", str(self.root))
        self.assertEqual(self.agent("04_dba")["status"], "ERROR")
        self.assertEqual(self.agent("04_dba")["processDetail"], "Invalid schema output.")

    def test_file_event_still_marks_an_idle_agent_working(self):
        self.serve.handle_file_event("04_dba", "Saved specs/database/schema.sql", str(self.root))
        self.assertEqual(self.agent("04_dba")["status"], "WORKING")

    def _run_agy_with(self, popen):
        class Immediate:
            def __init__(self, target=None, daemon=None, **kwargs):
                self.target = target

            def start(self):
                self.target()

        with patch.object(self.serve, "STATUS_FILE", str(self.status_path)), \
                patch.object(self.serve, "SPECS_DIR", str(self.root / "specs")), \
                patch.object(self.serve, "LOG_FILE", str(self.root / "specs" / "terminal.log")), \
                patch.object(self.serve.subprocess, "Popen", popen), \
                patch.object(self.serve.threading, "Thread", Immediate):
            self.serve.run_agy_prompt("hello", str(self.root))

    def test_failed_agy_launch_is_an_error_not_100_percent_idle(self):
        self._run_agy_with(unittest.mock.Mock(side_effect=FileNotFoundError("agy.exe not found")))
        pm = self.agent("01_pm")
        self.assertEqual(pm["status"], "ERROR")
        self.assertLess(pm["progress"], 100)

    def test_agy_nonzero_exit_is_an_error_not_100_percent_idle(self):
        proc = unittest.mock.MagicMock()
        proc.stdout.readline.return_value = ""
        proc.wait.return_value = 3
        self._run_agy_with(unittest.mock.Mock(return_value=proc))
        pm = self.agent("01_pm")
        self.assertEqual(pm["status"], "ERROR")
        self.assertLess(pm["progress"], 100)

    def test_status_files_are_written_through_unique_temp_files(self):
        sources = []
        real_replace = os.replace

        def spy(src, dst, *args, **kwargs):
            sources.append(str(src))
            return real_replace(src, dst, *args, **kwargs)

        with patch.object(self.serve.os, "replace", spy):
            for index in range(4):
                self.serve.safe_write_json(str(self.status_path), {"project": {"n": index}, "agents": []})
        self.assertEqual(len(sources), 4)
        self.assertEqual(len(set(sources)), 4, "writers share a temp file name")
        self.assertEqual(json.loads(self.status_path.read_text(encoding="utf-8"))["project"]["n"], 3)

    def test_status_write_survives_a_reader_holding_the_file_briefly(self):
        real_replace = os.replace
        attempts = []

        def flaky_replace(src, dst, *args, **kwargs):
            attempts.append(src)
            if len(attempts) <= 2:
                raise PermissionError(13, "file in use")
            return real_replace(src, dst, *args, **kwargs)

        with patch.object(self.serve.os, "replace", flaky_replace):
            written = self.serve.safe_write_json(str(self.status_path), {"project": {"n": 7}, "agents": []})
        self.assertIs(written, True)
        self.assertEqual(json.loads(self.status_path.read_text(encoding="utf-8"))["project"]["n"], 7)

    def test_failed_status_write_is_reported_and_leaves_the_old_file(self):
        before = self.status_path.read_text(encoding="utf-8")
        err = io.StringIO()
        with (
            patch.object(self.serve.os, "replace", side_effect=PermissionError(13, "file in use")),
            patch("time.sleep"), contextlib.redirect_stderr(err),
        ):
            written = self.serve.safe_write_json(str(self.status_path), {"project": {}, "agents": []})
        self.assertIs(written, False)
        self.assertIn("swarm-status.json", err.getvalue())
        self.assertEqual(self.status_path.read_text(encoding="utf-8"), before)
        self.assertEqual([f for f in os.listdir(self.root / "specs") if f.endswith(".tmp")], [])

    def test_losing_an_error_status_write_is_not_silent(self):
        err = io.StringIO()
        with (
            patch.object(self.serve, "STATUS_FILE", str(self.status_path)),
            patch.object(self.serve.os, "replace", side_effect=PermissionError(13, "file in use")),
            patch("time.sleep"), contextlib.redirect_stderr(err),
        ):
            ok = self.serve.set_agent_status_direct("01_pm", "ERROR", "AI engine failed.", progress=0)
        self.assertIs(ok, False)
        self.assertIn("swarm-status.json", err.getvalue())

    def test_rejected_review_note_is_not_mistaken_for_agent_work(self):
        self.assertIn("signoff.rejected.md", self.serve.IGNORE_FILES)

    def test_dashboard_status_rewrites_happen_while_holding_the_pipeline_status_lock(self):
        events = []
        real_lock = swarm_pipeline.status_lock(str(self.status_path))

        class Recording:
            def __enter__(self_):
                events.append("lock")
                return real_lock.__enter__()

            def __exit__(self_, *exc):
                events.append("unlock")
                return real_lock.__exit__(*exc)

        real_write = self.serve.safe_write_json

        def spy(path, data):
            events.append("write")
            return real_write(path, data)

        with (
            patch.object(self.serve, "_pipeline_status_lock", lambda path: Recording()),
            patch.object(self.serve, "safe_write_json", spy),
        ):
            self.serve.handle_file_event("04_dba", "Saved specs/database/schema.sql", str(self.root))
        self.assertEqual(events, ["lock", "write", "unlock"])

    def test_task_completion_never_reports_100_or_verified(self):
        self.set_agent("04_dba", status="WORKING", progress=50)
        self.serve.handle_task_completion("04_dba", str(self.root))
        agent = self.agent("04_dba")
        self.assertEqual(agent["status"], "REVIEWING")
        self.assertEqual(agent["progress"], swarm_pipeline.MAX_UNVERIFIED_PROGRESS)
        self.assertIn("not independently verified", agent["processDetail"])
        self.assertNotIn("100", self.read_log())

    def test_task_completion_cannot_push_the_project_to_100(self):
        for aid in support.AGENT_IDS:
            self.set_agent(aid, status="WORKING", progress=swarm_pipeline.MAX_UNVERIFIED_PROGRESS)
        for aid in support.AGENT_IDS:
            self.serve.handle_task_completion(aid, str(self.root))
        data = read_status(self.root)
        self.assertLess(data["project"]["overallProgress"], 100)
        self.assertTrue(all(a["progress"] < 100 for a in data["agents"]))

    def read_log(self):
        return (self.root / "specs" / "terminal.log").read_text(encoding="utf-8")

    def test_run_record_and_lock_are_not_mistaken_for_agent_work(self):
        self.assertIn("swarm-run.json", self.serve.IGNORE_FILES)
        self.assertIn(".swarm-run.lock", self.serve.IGNORE_FILES)


class StreamWriter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stream = load_module("tenagent_stream_under_test", "stream.py")

    def _update(self, status_path, root, **patches):
        with (
            patch.object(self.stream, "STATUS_FILE", str(status_path)),
            patch.object(self.stream, "SPECS_DIR", str(root / "specs")),
        ):
            self.stream.update_agent_status("05_backend", "writing", status="WORKING")

    def test_status_write_survives_a_reader_holding_the_file_briefly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = make_status_file(root)
            real_replace = os.replace
            attempts = []

            def flaky_replace(src, dst, *args, **kwargs):
                attempts.append(src)
                if len(attempts) <= 2:
                    raise PermissionError(13, "file in use")
                return real_replace(src, dst, *args, **kwargs)

            with patch("os.replace", flaky_replace):
                self._update(status_path, root)
            data = json.loads(status_path.read_text(encoding="utf-8"))
            self.assertEqual({a["id"]: a["status"] for a in data["agents"]}["05_backend"], "WORKING")

    def test_failed_status_write_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = make_status_file(root)
            before = status_path.read_text(encoding="utf-8")
            err = io.StringIO()
            with (
                patch("os.replace", side_effect=PermissionError(13, "file in use")),
                patch("time.sleep"), contextlib.redirect_stderr(err),
            ):
                self._update(status_path, root)
            self.assertIn("swarm-status.json", err.getvalue())
            self.assertEqual(status_path.read_text(encoding="utf-8"), before)

    def test_crash_while_writing_status_never_truncates_the_status_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            status_path = make_status_file(root)
            before = status_path.read_text(encoding="utf-8")

            with (
                patch("os.fsync", side_effect=OSError("disk full")),  # fails after the temp file is written
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self._update(status_path, root)
            self.assertEqual(status_path.read_text(encoding="utf-8"), before)
            self.assertEqual([f for f in os.listdir(root / "specs") if f.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
