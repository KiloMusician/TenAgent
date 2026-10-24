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
        self.assertEqual(run["args"], [sys.executable, "-m", "unittest", "discover", "-s", "tests"])
        self.assertEqual(run["cwd"], str(self.root))
        self.assertGreater(run["timeout"], 0)

    def test_failing_generated_tests_stop_the_run_with_the_unit_test_phase(self):
        self.assertFalse(self.run_swarm(test_returncode=1))
        data = read_status(self.root)
        self.assertEqual(data["project"]["phase"], "FAILED: QA Unit Tests Failed")
        self.assertNotIn("security", self.calls, "stages after a failed QA run must not start")
        self.assertFalse(self.exists("specs/signoff.md"))

    def test_runner_that_cannot_start_is_reported_as_a_runner_error(self):
        self.assertFalse(self.run_swarm(test_returncode=OSError("no interpreter")))
        self.assertEqual(read_status(self.root)["project"]["phase"], "FAILED: QA Test Runner Error")


if __name__ == "__main__":
    unittest.main()
