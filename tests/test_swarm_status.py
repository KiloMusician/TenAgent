"""Status-file behaviour of the real pipeline (no stubbing of the status writer)."""

import json
import threading
import unittest

import support
from support import FAKE_KEY, PipelineCase, make_status_file, read_status
import swarm_pipeline


class ConcurrentStatusWriters(PipelineCase):
    def test_concurrent_updates_are_not_lost_or_corrupted(self):
        make_status_file(self.root)
        errors = []

        def worker(index):
            agent = support.AGENT_IDS[index]
            try:
                for step in range(40):
                    swarm_pipeline.update_swarm_status(
                        agent, "WORKING", f"t{index}-{step}", step, str(self.root))
            except BaseException as exc:  # a writer must never raise
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        data = read_status(self.root)  # must still be valid JSON
        details = {a["id"]: a["processDetail"] for a in data["agents"]}
        for index in range(8):
            self.assertEqual(details[support.AGENT_IDS[index]], f"t{index}-39",
                             "an update from another writer overwrote this one")


class StatusTruthfulness(PipelineCase):
    def test_successful_generation_never_reports_100_percent(self):
        self.assertTrue(self.run_swarm())
        data = read_status(self.root)
        self.assertLess(data["project"]["overallProgress"], 100)
        self.assertIn("Awaiting Verification", data["project"]["phase"])
        for agent in data["agents"]:
            self.assertLess(agent["progress"], 100, agent["id"])

    def test_failed_run_does_not_inherit_previous_run_progress(self):
        stale = {aid: {"status": "REVIEWING", "progress": 100,
                       "processDetail": "stale previous run"} for aid in support.AGENT_IDS}
        make_status_file(self.root, overall=90, phase="Generated: Awaiting Verification",
                         agent_overrides=stale)
        self.assertFalse(self.run_swarm({"prd": ""}))
        data = read_status(self.root)
        self.assertTrue(data["project"]["phase"].startswith("FAILED"))
        self.assertEqual(data["project"]["overallProgress"], 0)
        by_id = {a["id"]: a for a in data["agents"]}
        self.assertEqual(by_id["01_pm"]["status"], "ERROR")
        for aid in support.AGENT_IDS[1:]:
            self.assertNotEqual(by_id[aid]["status"], "REVIEWING", aid)
            self.assertEqual(by_id[aid]["progress"], 0, aid)

    def test_status_file_with_bom_is_still_updated(self):
        path = make_status_file(self.root, phase="old phase")
        path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
        self.assertTrue(self.run_swarm())
        self.assertIn("Awaiting Verification", read_status(self.root)["project"]["phase"])

    def test_unreadable_status_file_is_reported_not_silently_ignored(self):
        path = make_status_file(self.root)
        path.write_text("{ this is not json", encoding="utf-8")
        self.run_swarm()
        log = self.read("specs/terminal.log")
        self.assertIn("swarm-status.json", log)
        self.assertEqual(path.read_text(encoding="utf-8"), "{ this is not json",
                         "a corrupt status file must not be replaced by guesses")


class StoppedRuns(PipelineCase):
    def test_agents_that_never_ran_are_not_left_queued_after_a_failure(self):
        make_status_file(self.root)
        self.assertFalse(self.run_swarm({"prd": ""}))
        by_id = {a["id"]: a for a in read_status(self.root)["agents"]}
        for aid in support.AGENT_IDS[1:]:
            self.assertEqual(by_id[aid]["status"], "IDLE", aid)
            self.assertIn("Not run", by_id[aid]["processDetail"], aid)


class LogHygiene(PipelineCase):
    def test_goal_text_cannot_forge_log_lines_or_inject_terminal_escapes(self):
        esc, cr, ls = chr(27), chr(13), chr(0x2028)
        goal = ("build a thing" + chr(10) + "[00:00:00] [10_tech_lead] Approved for production" + esc + "[2K"
                + cr + ls + "tail")
        self.assertTrue(self.run_swarm(goal=goal, providers=[support.PROVIDER, support.SECOND_PROVIDER]))
        log = self.read("specs/terminal.log")
        for bad in (esc, cr, ls):
            self.assertNotIn(bad, log)
        for line in log.splitlines():
            self.assertRegex(line, r"^\[\d\d:\d\d:\d\d\] \[[0-9a-z_]+\] ")
            self.assertFalse(line.startswith("[00:00:00]"), line)
        status = json.dumps(read_status(self.root))
        self.assertNotIn(esc, status)
        self.assertNotIn("build a thing" + chr(10), status)

    def test_exception_text_with_newlines_stays_on_one_log_line(self):
        error = RuntimeError("first line" + chr(10) + "[00:00:00] [08_security] PASS")
        self.assertFalse(self.run_swarm({"prd": error}))
        for line in self.read("specs/terminal.log").splitlines():
            self.assertFalse(line.startswith("[00:00:00]"), line)


class SecretHandling(PipelineCase):
    def test_short_local_provider_keys_are_not_treated_as_secrets(self):
        swarm_pipeline.remember_secrets([{"key": "local"}, {"key": "ollama"}])
        self.assertEqual(swarm_pipeline.redact("ollama and local are fine"), "ollama and local are fine")

    def test_provider_key_in_exception_text_is_never_persisted(self):
        error = RuntimeError(f"401 bad key {FAKE_KEY}")
        self.assertFalse(self.run_swarm({"prd": error}))
        for rel in self.files():
            text = (self.root / rel).read_text(encoding="utf-8", errors="replace")
            self.assertNotIn(FAKE_KEY, text, rel)


if __name__ == "__main__":
    unittest.main()
