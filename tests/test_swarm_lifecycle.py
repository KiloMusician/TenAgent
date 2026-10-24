"""Run lifecycle: terminal states, receipts, single flight, cancellation."""

import hashlib
import json
import os
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import patch

import support
from support import FAKE_KEY, PROVIDER, SECOND_PROVIDER, PipelineCase, make_status_file, read_status
import council
import swarm_pipeline


def sha256_of(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class UnexpectedErrors(PipelineCase):
    def read_run(self):
        return json.loads(self.read("specs/swarm-run.json"))

    def test_error_in_council_debate_ends_in_failed_state(self):
        def boom(*args, **kwargs):
            raise RuntimeError("council exploded")

        passed = self.run_swarm(providers=[PROVIDER, SECOND_PROVIDER], debate=boom)
        self.assertFalse(passed)
        self.assertTrue(read_status(self.root)["project"]["phase"].startswith("FAILED"))
        self.assertEqual(self.read_run()["state"], "FAILED")

    def test_unwritable_output_directory_fails_instead_of_hanging_in_thread(self):
        make_status_file(self.root)
        (self.root / "specs" / "prd").write_text("i am a file, not a directory", encoding="utf-8")
        with self._patched_calls():
            thread = swarm_pipeline.start_swarm_pipeline_thread("Mock task", str(self.root))
            thread.join(30)
        self.assertFalse(thread.is_alive())
        phase = read_status(self.root)["project"]["phase"]
        self.assertTrue(phase.startswith("FAILED"), phase)

    def test_pathologically_nested_generated_python_never_escapes_the_pipeline(self):
        # RecursionError/MemoryError depends on the interpreter version (3.14 compiles this
        # fine), so only the contract is asserted: a plain bool comes back, nothing raises.
        nasty = "def f():\n    return 1" + "+1" * 8000
        result = self.run_swarm({"backend": nasty})
        self.assertIsInstance(result, bool)

    def test_recursion_error_while_compiling_generated_python_fails_cleanly(self):
        real_compile = compile

        def exploding_compile(source, *args, **kwargs):
            if isinstance(source, str) and "RECURSE_MARKER" in source:
                raise RecursionError("maximum recursion depth exceeded during compilation")
            return real_compile(source, *args, **kwargs)

        with patch("builtins.compile", exploding_compile):
            passed = self.run_swarm({"backend": "def f():\n    return 1\n# RECURSE_MARKER\n"})
        self.assertFalse(passed)
        self.assertTrue(read_status(self.root)["project"]["phase"].startswith("FAILED"))
        self.assertFalse(self.exists("backend/src/main.py"))

    def test_keyboard_interrupt_is_recorded_as_failed_and_propagates(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_swarm({"tokens": KeyboardInterrupt()})
        self.assertEqual(self.read_run()["state"], "FAILED")
        self.assertEqual(read_status(self.root)["project"]["phase"], "FAILED: INTERRUPTED")
        self.assertFalse(os.path.exists(self.root / "specs" / ".swarm-run.lock"))

    def _patched_calls(self):
        """Same fake model as run_swarm, for tests that start the pipeline thread."""
        stack = ExitStack()
        stack.enter_context(patch.object(council, "get_active_providers", return_value=[PROVIDER]))
        stack.enter_context(patch.object(
            council, "call_llm",
            side_effect=lambda p, s, u, timeout=75: support.GOOD_OUTPUTS[support.stage_key(s)]))
        stack.enter_context(patch.object(swarm_pipeline.time, "sleep"))
        return stack


class RunRecord(PipelineCase):
    def test_success_record_has_state_and_hashed_receipts(self):
        self.assertTrue(self.run_swarm())
        record = json.loads(self.read("specs/swarm-run.json"))
        self.assertEqual(record["state"], "AWAITING_VERIFICATION")
        self.assertNotIn("VERIFIED", json.dumps(record).replace("AWAITING_VERIFICATION", ""))
        self.assertEqual(
            record["verification"],
            {"tests": "NOT_RUN", "security_scan": "NOT_RUN", "build": "NOT_RUN", "ci": "NOT_RUN"})
        self.assertEqual(len(record["stages"]), 10)
        seen = 0
        for stage in record["stages"]:
            self.assertEqual(stage["state"], "GENERATED", stage["id"])
            self.assertTrue(stage["model_calls"], stage["id"])
            for call in stage["model_calls"]:
                self.assertTrue(call["ok"])
                self.assertEqual(len(call["input_sha256"]), 64)
            for artifact in stage["artifacts"]:
                seen += 1
                self.assertEqual(artifact["sha256"], sha256_of(self.root / artifact["path"]), artifact["path"])
        self.assertGreaterEqual(seen, 13)
        self.assertNotIn(FAKE_KEY, json.dumps(record))

    def test_failed_run_record_names_the_failed_stage(self):
        self.assertFalse(self.run_swarm({"tokens": ""}))
        record = json.loads(self.read("specs/swarm-run.json"))
        self.assertEqual(record["state"], "FAILED")
        states = {s["id"]: s["state"] for s in record["stages"]}
        self.assertEqual(states["01_pm"], "GENERATED")
        self.assertEqual(states["03_designer"], "FAILED")
        self.assertNotIn("04_dba", states)
        self.assertIsNotNone(record["finished_at"])

    def test_terminal_states_cannot_be_left(self):
        record = swarm_pipeline.RunRecord(str(self.root), "goal")
        record.transition("RUNNING")
        record.transition("FAILED")
        for target in ("RUNNING", "AWAITING_VERIFICATION", "BLOCKED", "VERIFIED"):
            with self.assertRaises(swarm_pipeline.IllegalTransition):
                record.transition(target)

    def test_pipeline_has_no_path_to_verified(self):
        record = swarm_pipeline.RunRecord(str(self.root), "goal")
        record.transition("RUNNING")
        with self.assertRaises(swarm_pipeline.IllegalTransition):
            record.transition("VERIFIED")


class SingleFlight(PipelineCase):
    def test_second_concurrent_run_is_refused_without_touching_anything(self):
        entered = threading.Event()
        release = threading.Event()
        outcome = {}

        def hook(key):
            if key == "prd" and not entered.is_set():
                entered.set()
                release.wait(30)

        def first():
            outcome["first"] = self.run_swarm(call_hook=hook)

        thread = threading.Thread(target=first)
        thread.start()
        self.assertTrue(entered.wait(30))
        try:
            calls_before = len(self.calls)
            second = self.run_swarm()
            self.assertFalse(second, "a second run must not start while one is active")
            self.assertEqual(len(self.calls), calls_before, "refused run still called the provider")
            self.assertIn("RUNNING", self.read("specs/swarm-run.json"))
        finally:
            release.set()
            thread.join(60)
        self.assertTrue(outcome["first"])
        self.assertFalse(os.path.exists(self.root / "specs" / ".swarm-run.lock"))

    def test_fresh_lock_file_from_another_process_blocks_the_run(self):
        make_status_file(self.root)
        lock = self.root / "specs" / ".swarm-run.lock"
        lock.write_text(json.dumps({"pid": 1, "run_id": "other"}), encoding="utf-8")
        self.assertFalse(self.run_swarm())
        self.assertEqual(self.calls, [])
        self.assertTrue(lock.exists(), "must not delete a lock held by somebody else")

    def test_stale_lock_file_is_taken_over(self):
        make_status_file(self.root)
        lock = self.root / "specs" / ".swarm-run.lock"
        lock.write_text("{}", encoding="utf-8")
        old = time.time() - 3 * 3600
        os.utime(lock, (old, old))
        self.assertTrue(self.run_swarm())
        self.assertFalse(lock.exists())

    def test_rerun_after_failure_starts_clean_and_succeeds(self):
        self.assertFalse(self.run_swarm({"tokens": ""}))
        self.assertTrue(self.run_swarm())
        record = json.loads(self.read("specs/swarm-run.json"))
        self.assertEqual(record["state"], "AWAITING_VERIFICATION")
        self.assertIn("Awaiting Verification", read_status(self.root)["project"]["phase"])


class LockOwnership(PipelineCase):
    def lock_path(self):
        return self.root / "specs" / ".swarm-run.lock"

    def test_lock_names_its_owner_while_the_run_is_active(self):
        seen = {}

        def hook(key):
            if key == "prd":
                seen["lock"] = json.loads(self.lock_path().read_text(encoding="utf-8"))
                seen["record"] = json.loads(self.read("specs/swarm-run.json"))

        self.assertTrue(self.run_swarm(call_hook=hook))
        self.assertEqual(seen["lock"]["pid"], os.getpid())
        self.assertEqual(seen["lock"]["run_id"], seen["record"]["run_id"])

    def test_run_does_not_delete_a_lock_that_now_belongs_to_someone_else(self):
        def hook(key):
            if key == "prd":  # another process legitimately took the lock over meanwhile
                self.lock_path().write_text(json.dumps({"pid": 1, "run_id": "someone-else"}), encoding="utf-8")

        self.assertTrue(self.run_swarm(call_hook=hook))
        self.assertEqual(json.loads(self.lock_path().read_text(encoding="utf-8"))["run_id"], "someone-else")

    def test_takeover_never_removes_a_lock_that_turned_fresh_after_the_staleness_check(self):
        make_status_file(self.root)
        lock = self.lock_path()
        lock.write_text(json.dumps({"pid": 1, "run_id": "live-owner"}), encoding="utf-8")  # fresh mtime
        real_getmtime = os.path.getmtime
        calls = []

        def first_call_says_stale(path):
            calls.append(path)
            return time.time() - 3 * 3600 if len(calls) == 1 else real_getmtime(path)

        with patch("os.path.getmtime", first_call_says_stale):
            result = self.run_swarm()
        self.assertFalse(result)
        self.assertEqual(self.calls, [])
        self.assertEqual(json.loads(lock.read_text(encoding="utf-8"))["run_id"], "live-owner")
        self.assertEqual([f for f in os.listdir(self.root / "specs") if f.endswith(".stale")], [])

    def test_only_one_of_two_simultaneous_takeovers_of_a_stale_lock_wins(self):
        for _ in range(10):
            self.new_root()
            (self.root / "specs").mkdir()
            lock = self.lock_path()
            lock.write_text("{}", encoding="utf-8")
            old = time.time() - 3 * 3600
            os.utime(lock, (old, old))
            runs = [swarm_pipeline.RunRecord(str(self.root), "goal") for _ in range(2)]
            barrier = threading.Barrier(2)
            real_getmtime = os.path.getmtime
            results = []

            def contender(run):
                results.append(run.acquire_lock())

            def synced_getmtime(path):
                value = real_getmtime(path)
                if str(path).endswith(".swarm-run.lock"):
                    try:
                        barrier.wait(5)
                    except threading.BrokenBarrierError:
                        pass
                return value

            with patch("os.path.getmtime", synced_getmtime):
                threads = [threading.Thread(target=contender, args=(r,)) for r in runs]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(30)
            self.assertEqual(sorted(results), [False, True])
            for run in runs:
                run.release_lock()


class RejectedReview(PipelineCase):
    def test_rejected_or_ambiguous_review_never_produces_signoff_md(self):
        for text in ("[REJECTED - REMEDIATION REQUIRED]", "Looks fine to me.",
                     "[READY FOR INDEPENDENT VERIFICATION]" + chr(10) + "But the tests fail."):
            with self.subTest(text=text):
                self.new_root()
                self.assertFalse(self.run_swarm({"lead": text}))
                self.assertFalse(self.exists("specs/signoff.md"))
                rejected = self.read("specs/signoff.rejected.md")
                self.assertIn("REJECTED", rejected.splitlines()[0])
                self.assertIn("NOT VERIFIED", rejected)

    def test_stale_rejection_note_is_retired_by_the_next_run(self):
        self.assertFalse(self.run_swarm({"lead": "[REJECTED - REMEDIATION REQUIRED]"}))
        self.assertTrue(self.exists("specs/signoff.rejected.md"))
        self.assertTrue(self.run_swarm())
        self.assertFalse(self.exists("specs/signoff.rejected.md"))
        self.assertTrue(self.exists("specs/signoff.md"))


class WallClockBudget(PipelineCase):
    def test_run_that_exceeds_its_budget_fails_with_a_timeout_phase(self):
        def slow_provider(key):
            deadline = time.monotonic() + 0.15
            while time.monotonic() < deadline:  # real time passes even though sleep() is patched
                pass

        with patch.object(swarm_pipeline, "MAX_RUN_SECONDS", 0.05):
            self.assertFalse(self.run_swarm(call_hook=slow_provider))
        self.assertEqual(read_status(self.root)["project"]["phase"], "FAILED: TIMEOUT")
        self.assertEqual(json.loads(self.read("specs/swarm-run.json"))["state"], "FAILED")
        self.assertEqual(self.calls, ["prd"], "no further model call after the budget ran out")


class NoUnwiredSurface(unittest.TestCase):
    """Nothing in the repository calls a cancel API, so none is offered."""

    def test_no_cancellation_api_or_state_is_exposed(self):
        for name in ("request_cancel", "RunCancelled", "CANCELLED"):
            self.assertFalse(hasattr(swarm_pipeline, name), name)
        self.assertNotIn("CANCELLED", swarm_pipeline.LEGAL_TRANSITIONS)
        self.assertFalse(hasattr(swarm_pipeline.RunRecord, "cancel"))

    def test_no_caller_in_the_repository_references_cancellation(self):
        for rel in ("stream.py", "council.py", "setup_project.py", "dashboard/serve.py"):
            with open(os.path.join(support.REPO_ROOT, rel), encoding="utf-8") as f:
                self.assertNotIn("request_cancel", f.read(), rel)


class Documentation(unittest.TestCase):
    def read(self, rel):
        with open(os.path.join(support.REPO_ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_agent_docs_do_not_promise_locked_specs_or_final_signoff(self):
        for rel in ("AGENTS.md", ".agents/skills/swarm/SKILL.md"):
            text = self.read(rel)
            self.assertNotIn("Final Signoff", text, rel)
            self.assertNotIn("Locks Clean Architecture", text, rel)

    def test_agent_docs_state_the_exit_code_rule(self):
        for rel in ("AGENTS.md", ".agents/skills/swarm/SKILL.md"):
            text = self.read(rel)
            self.assertIn("exit", text.lower(), rel)
            self.assertIn("AWAITING_VERIFICATION", text, rel)


if __name__ == "__main__":
    unittest.main()
