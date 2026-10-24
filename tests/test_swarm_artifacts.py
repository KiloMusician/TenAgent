"""Where and how the pipeline writes: containment, no clobbering, atomicity."""

import builtins
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import support
from support import PipelineCase, make_status_file, read_status
import swarm_pipeline


def make_dir_link(link, target):
    """Directory junction on Windows (no privilege needed), symlink elsewhere."""
    if os.name == "nt":
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                                capture_output=True, text=True)
        return result.returncode == 0
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


class NoClobbering(PipelineCase):
    def test_existing_user_test_file_blocks_the_run_before_any_model_call(self):
        make_status_file(self.root)
        mine = self.root / "tests" / "test_api.py"
        mine.parent.mkdir(parents=True)
        mine.write_text("# my hand written tests\n", encoding="utf-8")
        self.assertFalse(self.run_swarm())
        self.assertEqual(mine.read_text(encoding="utf-8"), "# my hand written tests\n")
        self.assertEqual(self.calls, [], "provider was called although the run could not write its output")

    def test_user_edit_of_a_generated_file_survives_a_rerun(self):
        self.assertTrue(self.run_swarm())
        main = self.root / "backend" / "src" / "main.py"
        main.write_text("# hand edited after generation\n", encoding="utf-8")
        self.calls.clear()
        self.assertFalse(self.run_swarm())
        self.assertEqual(main.read_text(encoding="utf-8"), "# hand edited after generation\n")
        self.assertEqual(self.calls, [])

    def test_unmodified_output_of_a_previous_run_can_be_regenerated(self):
        self.assertTrue(self.run_swarm())
        self.assertTrue(self.run_swarm({"prd": "# Product requirements v2\n\nMore detail for the second run. Users can create, list and remove items, and every list view shows the newest entry first."}))
        self.assertIn("v2", self.read("specs/prd/user-stories.md"))

    def test_foreign_signoff_file_is_not_replaced(self):
        make_status_file(self.root)
        foreign = self.root / "specs" / "signoff.md"
        foreign.write_text("Signed off by a human.\n", encoding="utf-8")
        self.assertFalse(self.run_swarm())
        self.assertEqual(foreign.read_text(encoding="utf-8"), "Signed off by a human.\n")

    def test_framework_files_are_untouched_by_a_full_run(self):
        (self.root / "council.py").write_text("# framework\n", encoding="utf-8")
        self.assertTrue(self.run_swarm())
        self.assertEqual(self.read("Dockerfile"), "FROM original-image\n")
        self.assertEqual(self.read("council.py"), "# framework\n")
        self.assertEqual(self.read(".github/workflows/ci.yml"), "name: Original CI\n")


class StaleOutputs(PipelineCase):
    def test_failed_rerun_retires_the_previous_runs_signoff(self):
        self.assertTrue(self.run_swarm())
        self.assertTrue(self.exists("specs/signoff.md"))
        self.assertFalse(self.run_swarm({"tokens": ""}))
        self.assertFalse(self.exists("specs/signoff.md"),
                         "a draft sign-off from an earlier run must not sit next to a FAILED run")


class AtomicWrites(PipelineCase):
    def test_failed_regeneration_keeps_the_previous_artifact_intact(self):
        self.assertTrue(self.run_swarm())
        before = self.read("specs/prd/user-stories.md")
        self.assertTrue(before.strip())
        # a lone surrogate (json.loads('"\\ud800"') produces one) cannot be encoded as UTF-8
        self.assertFalse(self.run_swarm({"prd": "# Broken \ud800 requirements\n\nPadding so that only the lone surrogate is wrong. Users can create, list and remove items, and every list view shows the newest entry first."}))
        self.assertEqual(self.read("specs/prd/user-stories.md"), before)

    def test_no_temp_files_are_left_behind(self):
        self.assertTrue(self.run_swarm())
        self.assertFalse(self.run_swarm({"prd": "# Broken \ud800 requirements\n\nPadding so that only the lone surrogate is wrong. Users can create, list and remove items, and every list view shows the newest entry first."}))
        leftovers = [f for f in self.files() if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class Containment(PipelineCase):
    def test_directory_link_cannot_redirect_output_outside_the_project(self):
        make_status_file(self.root)
        with tempfile.TemporaryDirectory() as outside:
            link = self.root / "specs" / "design"
            if not make_dir_link(link, outside):
                self.skipTest("cannot create a directory junction/symlink here")
            try:
                self.assertFalse(self.run_swarm())
                self.assertEqual(os.listdir(outside), [], "pipeline wrote through the link")
            finally:
                if os.name == "nt":
                    os.rmdir(link)  # removes the junction only, never its target
                else:
                    os.unlink(link)


class FilesystemErrorsAtStart(PipelineCase):
    """A file that cannot be read or removed (e.g. held open on Windows) must end the run
    in a recorded terminal state, never kill the calling thread without a trace."""

    def _deny(self, target_suffix, opener=None, remover=None):
        real_open, real_unlink = builtins.open, os.unlink

        def guarded_open(file, mode="r", *args, **kwargs):
            if opener and str(file).replace(chr(92), "/").endswith(target_suffix) and "r" in mode:
                raise PermissionError(13, "held open by another process")
            return real_open(file, mode, *args, **kwargs)

        def guarded_unlink(path, *args, **kwargs):
            if remover and str(path).replace(chr(92), "/").endswith(target_suffix):
                raise PermissionError(13, "held open by another process")
            return real_unlink(path, *args, **kwargs)

        stack = ExitStack()
        stack.enter_context(patch("builtins.open", guarded_open))
        stack.enter_context(patch("os.unlink", guarded_unlink))
        return stack

    def test_unreadable_existing_deliverable_blocks_the_run_with_a_record(self):
        self.assertTrue(self.run_swarm())
        self.calls.clear()
        with self._deny("backend/src/main.py", opener=True):
            result = self.run_swarm()
        self.assertFalse(result)
        self.assertEqual(self.calls, [])
        record = json.loads(self.read("specs/swarm-run.json"))
        self.assertEqual(record["state"], "BLOCKED")
        self.assertIn("backend/src/main.py", record["error"])
        self.assertTrue(read_status(self.root)["project"]["phase"].startswith("BLOCKED"))
        self.assertFalse(os.path.exists(self.root / "specs" / ".swarm-run.lock"))

    def test_sign_off_that_cannot_be_retired_fails_the_run_with_a_record(self):
        self.assertTrue(self.run_swarm())
        self.calls.clear()
        with self._deny("specs/signoff.md", remover=True):
            result = self.run_swarm()
        self.assertFalse(result)
        record = json.loads(self.read("specs/swarm-run.json"))
        self.assertEqual(record["state"], "FAILED")
        self.assertTrue(read_status(self.root)["project"]["phase"].startswith("FAILED"))
        self.assertFalse(os.path.exists(self.root / "specs" / ".swarm-run.lock"))

    def test_unreadable_previous_record_blocks_instead_of_crashing(self):
        self.assertTrue(self.run_swarm())
        with self._deny("specs/swarm-run.json", opener=True):
            result = self.run_swarm()
        self.assertFalse(result)


class PathSafety(unittest.TestCase):
    """Direct tests of the path validator; model output never chooses a path today."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = self._tmp.name

    def test_hostile_names_are_rejected(self):
        hostile = [
            "../../x", "..\\..\\x", "specs/../../x", "specs/prd/..\\..\\..\\x",
            "/etc/passwd", "\\windows\\system32\\x", "C:\\Windows\\x", "C:x", "c:/x",
            "\\\\server\\share\\x", "//server/share/x", "specs/prd/x.md:stream",
            "specs/prd/CON", "specs/prd/nul.md", "specs/prd/ ", "specs/prd/x.", "",
            "specs//", "specs/./x/../../../y", "x\x00y",
        ]
        for name in hostile:
            with self.subTest(name=name):
                with self.assertRaises(swarm_pipeline.ArtifactPathError):
                    swarm_pipeline.safe_artifact_path(self.root, name)

    def test_unicode_names_inside_the_project_are_accepted(self):
        path = swarm_pipeline.safe_artifact_path(self.root, "specs/prd/caf\u00e9-\u65e5\u672c\u8a9e.md")
        self.assertTrue(path.startswith(os.path.realpath(self.root)))

    def test_only_known_deliverables_can_be_written(self):
        for name in ("Dockerfile", ".github/workflows/ci.yml", "swarm_pipeline.py",
                     "council.py", "dashboard/serve.py", "specs/swarm-status.json"):
            with self.subTest(name=name):
                with self.assertRaises(swarm_pipeline.ArtifactPathError):
                    swarm_pipeline.write_artifact(self.root, name, "x")
        self.assertEqual(os.listdir(self.root), [])


if __name__ == "__main__":
    unittest.main()
