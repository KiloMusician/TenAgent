"""Every writer of terminal.log / status text must scrub credentials.

Prompts and tool output are free text; a pasted key must not end up in
specs/terminal.log or specs/swarm-status.json, both of which the dashboard serves.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(os.environ.get("TENAGENT_TEST_ROOT") or Path(__file__).resolve().parents[1])
sys.path.insert(0, str(ROOT))

from dashboard import security  # noqa: E402
import council  # noqa: E402
import stream  # noqa: E402
import swarm_pipeline  # noqa: E402

KEY = "sk-test-FAKE-ABCDEFGHIJKLMNOP12345"
LINE = f"please use {KEY} and password=hunter2-FAKE for this"
STATUS = {"project": {}, "agents": [
    {"id": "01_pm", "status": "IDLE", "progress": 0, "processDetail": ""},
    {"id": "05_backend", "status": "IDLE", "progress": 0, "processDetail": ""}]}


class ScrubbingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tenagent-scrub-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "specs").mkdir()
        (self.root / "specs" / "swarm-status.json").write_text(json.dumps(STATUS), "utf-8")
        self.log = self.root / "specs" / "terminal.log"
        self.status = self.root / "specs" / "swarm-status.json"

    def assert_clean(self, *paths):
        for path in paths:
            text = path.read_text("utf-8") if path.exists() else ""
            self.assertNotIn(KEY, text, path.name)
            self.assertNotIn("hunter2-FAKE", text, path.name)

    def test_shared_scrubber_handles_registered_and_environment_secrets(self):
        security.register_secrets("registered-secret-FAKE")
        self.addCleanup(security._REGISTERED_SECRETS.discard, "registered-secret-FAKE")
        os.environ["TENAGENT_DASHBOARD_PASSWORD"] = "env-password-FAKE-1"
        self.addCleanup(os.environ.pop, "TENAGENT_DASHBOARD_PASSWORD", None)
        out = security.scrub_log_text(f"a\nregistered-secret-FAKE env-password-FAKE-1 {LINE}")
        self.assertNotIn("\n", out)
        for secret in ("registered-secret-FAKE", "env-password-FAKE-1", KEY, "hunter2-FAKE"):
            self.assertNotIn(secret, out)

    def test_swarm_pipeline_log_and_status(self):
        with contextlib.redirect_stdout(io.StringIO()):
            swarm_pipeline.log_swarm_message("swarm", LINE, str(self.root))
            swarm_pipeline.update_swarm_status("01_pm", "WORKING", LINE, 10, str(self.root))
        self.assertIn("please use", self.log.read_text("utf-8"))
        self.assertIn("please use", self.status.read_text("utf-8"))
        self.assert_clean(self.log, self.status)

    def test_council_log(self):
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            council.log_council_message("council", LINE, str(self.root))
        self.assertIn("please use", self.log.read_text("utf-8"))
        self.assert_clean(self.log)
        self.assertNotIn(KEY, captured.getvalue())

    def test_stream_log_and_status(self):
        saved = (stream.LOG_FILE, stream.STATUS_FILE, stream.SPECS_DIR)
        stream.LOG_FILE, stream.STATUS_FILE, stream.SPECS_DIR = (
            str(self.log), str(self.status), str(self.root / "specs"))
        self.addCleanup(lambda: setattr_all(stream, ("LOG_FILE", "STATUS_FILE", "SPECS_DIR"), saved))
        stream.append_terminal_log("05_backend", LINE)
        stream.update_agent_status("05_backend", LINE)
        self.assertIn("please use", self.log.read_text("utf-8"))
        self.assert_clean(self.log, self.status)


def setattr_all(module, names, values):
    for name, value in zip(names, values):
        setattr(module, name, value)


if __name__ == "__main__":
    unittest.main()
