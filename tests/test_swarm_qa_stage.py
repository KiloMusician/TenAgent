"""The QA stage runs the generated tests; the run must reach (and honestly report) that step.

`subprocess.run` is faked in every test (see support.PipelineCase), so no generated
code is executed.
"""

import sys
import unittest

import support  # noqa: F401  (puts the repo root on sys.path for python -I)
from support import PipelineCase, read_status


class QaStageRunsTheGeneratedTests(PipelineCase):
    def test_a_complete_run_gets_past_the_test_runner(self):
        self.assertTrue(self.run_swarm())
        self.assertNotIn("FAILED", read_status(self.root)["project"]["phase"])
        self.assertEqual(self.calls[-1], "lead", "the stages after QA never ran")

    def test_the_runner_is_invoked_on_the_projects_tests_directory(self):
        self.run_swarm()
        self.assertEqual(len(self.test_runs), 1)
        run = self.test_runs[0]
        self.assertEqual(run["args"], [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_api.py"])
        self.assertEqual(run["cwd"], str(self.root))
        self.assertGreater(run["timeout"], 0)

    def test_failing_generated_tests_stop_the_run_with_the_unit_test_phase(self):
        self.assertFalse(self.run_swarm(test_returncode=1))
        data = read_status(self.root)
        self.assertEqual(data["project"]["phase"], "FAILED: QA Unit Tests Failed")
        self.assertNotIn("security", self.calls, "stages after a failed QA run must not start")
        self.assertFalse(self.exists("specs/signoff.md"))

    def test_a_runner_that_exits_zero_after_running_no_tests_is_not_a_pass(self):
        # unittest exits 0 for an empty discovery on Python <= 3.11 and 5 on 3.12+
        self.assertFalse(self.run_swarm(test_returncode=0, test_output="Ran 0 tests in 0.000s\n\nNO TESTS RAN\n"))
        self.assertEqual(read_status(self.root)["project"]["phase"], "FAILED: QA No Tests Ran")
        self.assertNotIn("security", self.calls)

    def test_a_runner_with_no_summary_line_is_not_a_pass(self):
        for output in ("", "something unrelated\n", "Ran many tests\n"):
            with self.subTest(output=output):
                self.new_root()
                self.assertFalse(self.run_swarm(test_returncode=0, test_output=output))
                self.assertEqual(read_status(self.root)["project"]["phase"], "FAILED: QA No Tests Ran")

    def test_the_number_of_tests_that_ran_is_logged(self):
        self.assertTrue(self.run_swarm(test_output="Ran 3 tests in 0.002s\n\nOK\n"))
        self.assertIn("3 tests ran", self.read("specs/terminal.log"))

    def test_the_log_line_names_the_command_that_is_run(self):
        self.run_swarm()
        self.assertIn("unittest discover -s tests -p test_api.py", self.read("specs/terminal.log"))

    def test_count_tests_run_parses_the_last_summary(self):
        import swarm_pipeline

        self.assertEqual(swarm_pipeline.count_tests_run("Ran 1 test in 0.1s\nOK"), 1)
        self.assertEqual(swarm_pipeline.count_tests_run("Ran 12 tests in 1s\n\nOK"), 12)
        self.assertEqual(swarm_pipeline.count_tests_run("Ran 0 tests in 0s"), 0)
        self.assertEqual(swarm_pipeline.count_tests_run("Ran 2 tests in 1s\nRan 5 tests in 1s"), 5)
        self.assertIsNone(swarm_pipeline.count_tests_run(""))
        self.assertIsNone(swarm_pipeline.count_tests_run(None))

    def test_runner_that_cannot_start_is_reported_as_a_runner_error(self):
        self.assertFalse(self.run_swarm(test_returncode=OSError("no interpreter")))
        self.assertEqual(read_status(self.root)["project"]["phase"], "FAILED: QA Test Runner Error")


if __name__ == "__main__":
    unittest.main()
