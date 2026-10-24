"""The dashboard's threads share swarm-status.json and swarm-config.json.

These tests drive the real ``dashboard/serve.py`` module (and the swarm
pipeline) against a throw-away directory tree: no repository file is written,
no provider is contacted and no subprocess is started.  The module is
Windows-only (it exits at import elsewhere), so the whole file is skipped on
other platforms.
"""

import http.client
import importlib.util
import json
import shutil
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("dashboard/serve.py is a Windows-only server")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SERVE = None


def load_serve():
    global _SERVE
    if _SERVE is None:
        spec = importlib.util.spec_from_file_location(
            "tenagent_serve_state_tests", ROOT / "dashboard" / "serve.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SERVE = module
    return _SERVE


class StateCase(unittest.TestCase):
    def setUp(self):
        self.serve = load_serve()
        self.tmp = tempfile.TemporaryDirectory(prefix="tenagent-state-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.specs = self.root / "specs"
        self.specs.mkdir()
        shutil.copy2(ROOT / "specs" / "swarm-status.json", self.specs / "swarm-status.json")
        serve = self.serve
        for name, value in (
            ("DIRECTORY", str(self.root)),
            ("SPECS_DIR", str(self.specs)),
            ("LOG_FILE", str(self.specs / "terminal.log")),
            ("STATUS_FILE", str(self.specs / "swarm-status.json")),
        ):
            self.addCleanup(setattr, serve, name, getattr(serve, name))
            setattr(serve, name, value)

    def read_status(self):
        return json.loads((self.specs / "swarm-status.json").read_text(encoding="utf-8"))

    def agent_ids(self, count):
        return [a["id"] for a in self.read_status()["agents"]][:count]

    def leftovers(self):
        return sorted(p.name for p in self.specs.glob("*.tmp"))

    def write_config(self, config):
        (self.specs / "swarm-config.json").write_text(json.dumps(config), encoding="utf-8")

    def read_config(self):
        return json.loads((self.specs / "swarm-config.json").read_text(encoding="utf-8"))

    def run_threads(self, targets):
        threads = [threading.Thread(target=t) for t in targets]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertFalse(any(t.is_alive() for t in threads), "a worker thread hung")


class StatusFileTests(StateCase):
    def test_concurrent_status_updates_are_neither_lost_nor_corrupted(self):
        ids = self.agent_ids(8)
        barrier = threading.Barrier(len(ids))

        def work(agent_id):
            barrier.wait()
            for step in range(1, 26):
                self.serve.set_agent_status_direct(agent_id, "WORKING", f"step {step}", step)

        self.run_threads([lambda i=i: work(i) for i in ids])
        final = {a["id"]: a["progress"] for a in self.read_status()["agents"]}
        self.assertEqual([final[i] for i in ids], [25] * len(ids))
        self.assertEqual(self.leftovers(), [])

    def test_file_events_and_task_completions_share_the_same_lock(self):
        ids = self.agent_ids(4)
        barrier = threading.Barrier(len(ids) * 2)
        serve = self.serve

        def events(agent_id):
            barrier.wait()
            for step in range(15):
                serve.handle_file_event(agent_id, f"Modified file {step}", str(self.root))

        def statuses(agent_id):
            barrier.wait()
            for step in range(1, 16):
                serve.set_agent_status_direct(agent_id, "WORKING", f"direct {step}", step)

        self.run_threads([lambda i=i: events(i) for i in ids] + [lambda i=i: statuses(i) for i in ids])
        status = self.read_status()
        self.assertEqual(len(status["agents"]), 10)  # parseable and complete
        self.assertEqual(self.leftovers(), [])
        # every agent kept the last value written by *its* writers
        self.assertTrue(all(a["progress"] == 15 for a in status["agents"] if a["id"] in ids))

    def test_the_swarm_pipeline_writes_through_the_same_lock(self):
        import swarm_pipeline
        a, b = self.agent_ids(2)
        barrier = threading.Barrier(2)

        def pipeline():
            barrier.wait()
            for step in range(1, 21):
                swarm_pipeline.update_swarm_status(a, "WORKING", f"pipeline {step}", step, str(self.root))

        def dashboard():
            barrier.wait()
            for step in range(1, 21):
                self.serve.set_agent_status_direct(b, "WORKING", f"dashboard {step}", step)

        self.run_threads([pipeline, dashboard])
        final = {x["id"]: x["progress"] for x in self.read_status()["agents"]}
        self.assertEqual((final[a], final[b]), (20, 20))
        self.assertEqual(self.leftovers(), [])

    def test_an_update_waits_for_a_reader_instead_of_being_dropped(self):
        # SimpleHTTPRequestHandler keeps the file open while it streams it; on
        # Windows os.replace onto an open file fails, and the update used to be
        # swallowed silently.
        agent_id = self.agent_ids(1)[0]
        reader = open(self.specs / "swarm-status.json", "rb")
        self.addCleanup(reader.close)
        worker = threading.Thread(
            target=self.serve.set_agent_status_direct,
            args=(agent_id, "WORKING", "after-reader", 77))
        worker.start()
        time.sleep(0.3)
        reader.close()
        worker.join(10)
        agent = next(a for a in self.read_status()["agents"] if a["id"] == agent_id)
        self.assertEqual((agent["progress"], agent["processDetail"]), (77, "after-reader"))
        self.assertEqual(self.leftovers(), [])

    def test_a_started_completed_agent_is_not_reverted_by_a_created_file(self):
        # behaviour that must survive the move to the shared writer: during an
        # automated run an agent that just finished stays finished
        serve = self.serve
        agent_id = self.agent_ids(1)[0]
        data = self.read_status()
        data["project"]["phase"] = "Phase 5: Backend Domain Implementation"
        for agent in data["agents"]:
            if agent["id"] == agent_id:
                agent.update(status="REVIEWING", progress=100)
        (self.specs / "swarm-status.json").write_text(json.dumps(data), encoding="utf-8")
        serve.handle_file_event(agent_id, "Created backend/src/main.py", str(self.root))
        agent = next(a for a in self.read_status()["agents"] if a["id"] == agent_id)
        self.assertEqual((agent["status"], agent["progress"]), ("REVIEWING", 100))
        serve.handle_file_event(agent_id, "Modified backend/src/main.py", str(self.root))
        agent = next(a for a in self.read_status()["agents"] if a["id"] == agent_id)
        self.assertEqual((agent["status"], agent["progress"]), ("WORKING", 25))


class ConfigFileTests(StateCase):
    KEY = "sk-test-FAKE-KEEP-333333"

    def one_probe_pass(self, slow_probe):
        """Run local_providers_probe_worker for a single pass with ``slow_probe``."""
        serve = self.serve
        calls = []
        worker = threading.Thread(target=serve.local_providers_probe_worker, args=(str(self.root),))

        class OnePassTime:
            """serve.py's own view of ``time``: only the worker thread's sleep is intercepted."""

            def __getattr__(self, name):
                return getattr(time, name)

            def sleep(self, seconds):
                if threading.current_thread() is not worker:
                    return time.sleep(seconds)
                calls.append(seconds)
                if len(calls) > 1:
                    raise SystemExit  # end the worker thread after a single pass

        for owner, name, value in (
            (serve, "probe_and_update_local_provider", slow_probe),
            (serve, "time", OnePassTime()),
        ):
            self.addCleanup(setattr, owner, name, getattr(owner, name))
            setattr(owner, name, value)
        worker.start()
        return worker

    def make_slow_probe(self, probing, release):
        def slow_probe(provider):
            probing.set()
            release.wait(10)
            provider["status"] = "connection_error"
            provider["statusDetail"] = "Offline"
            provider["valid"] = False
            return True
        return slow_probe

    def test_a_config_saved_while_the_probe_runs_is_not_reverted(self):
        self.write_config({"engine": "custom", "providers": [
            {"provider": "9router", "key": self.KEY, "baseUrl": "http://127.0.0.1:9/v1"}]})
        probing, release = threading.Event(), threading.Event()
        worker = self.one_probe_pass(self.make_slow_probe(probing, release))
        self.assertTrue(probing.wait(10))
        # the operator saves a different provider list while the probe is in flight
        self.write_config({"engine": "custom", "providers": [
            {"provider": "gemini", "key": "sk-test-FAKE-NEW-222222"}]})
        release.set()
        worker.join(10)
        self.assertEqual([p["provider"] for p in self.read_config()["providers"]], ["gemini"])

    def test_probe_results_are_merged_into_the_current_config(self):
        self.write_config({"engine": "custom", "providers": [
            {"provider": "9router", "key": self.KEY, "baseUrl": "http://127.0.0.1:9/v1"}]})
        probing, release = threading.Event(), threading.Event()
        worker = self.one_probe_pass(self.make_slow_probe(probing, release))
        self.assertTrue(probing.wait(10))
        current = self.read_config()
        current["note"] = "edited-meanwhile"  # an unrelated edit lands during the probe
        self.write_config(current)
        release.set()
        worker.join(10)
        stored = self.read_config()
        self.assertEqual(stored.get("note"), "edited-meanwhile")
        self.assertEqual(stored["providers"][0]["status"], "connection_error")
        self.assertEqual(stored["providers"][0]["key"], self.KEY)

    def test_runtime_status_updates_keep_the_rest_of_the_file(self):
        self.write_config({"engine": "custom", "providers": [
            {"provider": "groq", "key": self.KEY, "status": "active"}]})
        self.serve.update_provider_runtime_status("groq", "rate_limited", "Rate Limited", False)
        stored = self.read_config()["providers"][0]
        self.assertEqual((stored["status"], stored["valid"], stored["key"]),
                         ("rate_limited", False, self.KEY))
        self.assertEqual(self.leftovers(), [])

    def test_council_status_updates_use_the_same_writer(self):
        import council
        self.write_config({"engine": "custom", "providers": [
            {"provider": "groq", "key": self.KEY, "status": "active"}]})
        council.update_provider_runtime_status("groq", "rate_limited", "Rate Limited", False, str(self.root))
        stored = self.read_config()["providers"][0]
        self.assertEqual((stored["status"], stored["key"]), ("rate_limited", self.KEY))
        self.assertEqual(self.leftovers(), [])


class ConfigReadTests(StateCase):
    """GET /api/config shows a redacted view; it must not write that view back."""

    def test_reading_the_config_never_strips_the_stored_keys(self):
        # Pins a latent defect.  The old handler wrote the key-stripped view back from inside
        # ``with open(cfg_file)``; on Windows that replace is refused while the handle is open
        # (the error was swallowed and the keys survived by accident).  Anywhere the replace
        # succeeds - or if the handle were closed first - every stored key would be deleted.
        key = "sk-test-FAKE-STORED-444444"
        # nothing listens on port 1, so the local-provider probe flips the status
        self.write_config({"engine": "custom", "providers": [
            {"provider": "ollama", "key": key, "baseUrl": "http://127.0.0.1:1/v1", "status": "active"}]})
        httpd = self.serve.ThreadedSwarmServer(("127.0.0.1", 0), self.serve.SwarmHandler)
        thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1], timeout=10)
        try:
            conn.request("GET", "/api/config")
            reply = conn.getresponse()
            body = reply.read().decode("utf-8")
        finally:
            conn.close()
        self.assertEqual(reply.status, 200)
        self.assertNotIn(key, body)  # the browser never sees it
        stored = self.read_config()["providers"][0]
        self.assertEqual(stored.get("key"), key)  # and the file still has it
        self.assertEqual(stored["status"], "connection_error")  # the probe result was kept


if __name__ == "__main__":
    unittest.main()
