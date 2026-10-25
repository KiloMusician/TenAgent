"""Unit tests for the atomic, serialised JSON state-file helpers."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import statefile  # noqa: E402


class StateFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="tenagent-state-")
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "state.json")
        self.write({"counters": {f"c{i}": 0 for i in range(8)}})

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as stream:
            json.dump(data, stream)

    def read(self):
        with open(self.path, "r", encoding="utf-8") as stream:
            return json.load(stream)

    def leftovers(self):
        return [n for n in os.listdir(self.tmp.name) if n != "state.json"]

    def test_concurrent_updates_are_serialised_and_atomic(self):
        barrier = threading.Barrier(8)

        def work(name):
            barrier.wait()
            for _ in range(30):
                statefile.update_json_file(
                    self.path,
                    lambda d, n=name: d["counters"].__setitem__(n, d["counters"][n] + 1) or True,
                )

        threads = [threading.Thread(target=work, args=(f"c{i}",)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(set(self.read()["counters"].values()), {30})
        self.assertEqual(self.leftovers(), [])

    def test_unchanged_document_is_not_rewritten(self):
        before = self.read()
        with mock.patch("os.replace", wraps=os.replace) as replace:
            self.assertFalse(statefile.update_json_file(self.path, lambda d: False))
        self.assertEqual(replace.call_count, 0)  # nothing was moved over the file
        self.assertEqual(self.read(), before)
        self.assertEqual(self.leftovers(), [])

    def test_missing_or_corrupt_files_are_left_alone(self):
        missing = os.path.join(self.tmp.name, "absent.json")
        self.assertFalse(statefile.update_json_file(missing, lambda d: True))
        self.assertFalse(os.path.exists(missing))
        with open(self.path, "w", encoding="utf-8") as stream:
            stream.write("{not json")
        self.assertFalse(statefile.update_json_file(self.path, lambda d: True))
        with open(self.path, "r", encoding="utf-8") as stream:
            self.assertEqual(stream.read(), "{not json")

    def test_wrongly_shaped_documents_do_not_raise(self):
        self.write([1, 2, 3])
        self.assertFalse(statefile.update_json_file(self.path, lambda d: d["counters"]))

    def test_an_update_that_raises_leaves_the_file_alone(self):
        original = self.read()

        def broken(document):
            document["counters"]["c0"] = 99
            raise ValueError("bad progress value")

        self.assertFalse(statefile.update_json_file(self.path, broken))
        self.assertEqual(self.read(), original)
        self.assertEqual(self.leftovers(), [])

    def test_failed_replace_keeps_the_old_file_and_cleans_up(self):
        original = self.read()
        with mock.patch.object(statefile, "_REPLACE_ATTEMPTS", 3), \
                mock.patch.object(statefile, "_REPLACE_DELAY", 0), \
                mock.patch("os.replace", side_effect=PermissionError):
            self.assertFalse(statefile.atomic_write_json(self.path, {"new": True}))
        self.assertEqual(self.read(), original)
        self.assertEqual(self.leftovers(), [])

    def test_unserialisable_data_keeps_the_old_file(self):
        original = self.read()
        self.assertFalse(statefile.atomic_write_json(self.path, {"bad": {1, 2}}))
        self.assertEqual(self.read(), original)
        self.assertEqual(self.leftovers(), [])

    def test_directory_is_created_on_demand(self):
        nested = os.path.join(self.tmp.name, "a", "b", "state.json")
        self.assertTrue(statefile.atomic_write_json(nested, {"ok": 1}))
        with open(nested, "r", encoding="utf-8") as stream:
            self.assertEqual(json.load(stream), {"ok": 1})

    def test_files_do_not_wait_for_each_other(self):
        # one file whose replace is stuck (a reader holds it on Windows) must not stall
        # the writers of any other file
        other = os.path.join(self.tmp.name, "other.json")
        with open(other, "w", encoding="utf-8") as stream:
            json.dump({"n": 0}, stream)
        stuck, release = threading.Event(), threading.Event()
        real_replace = os.replace

        def replace(src, dst):
            if os.path.basename(dst) == "state.json":
                stuck.set()
                release.wait(10)
            return real_replace(src, dst)

        slow = threading.Thread(target=statefile.update_json_file,
                                args=(self.path, lambda d: d["counters"].__setitem__("c0", 1) or True))
        with mock.patch("os.replace", side_effect=replace):
            slow.start()
            self.assertTrue(stuck.wait(5))
            started = time.monotonic()
            done = []
            fast = threading.Thread(target=lambda: done.append(statefile.update_json_file(
                other, lambda d: d.__setitem__("n", 1) or True)))
            fast.start()
            fast.join(3)
            elapsed = time.monotonic() - started
            release.set()
            slow.join(10)
        self.assertEqual(done, [True], "the other file's update waited for the stuck one")
        self.assertLess(elapsed, 3)
        self.assertEqual(self.read()["counters"]["c0"], 1)

    def test_the_same_file_is_still_serialised_through_symlinks_and_relative_paths(self):
        alias = os.path.join(self.tmp.name, ".", "state.json")
        self.assertIs(statefile.path_lock(self.path), statefile.path_lock(alias))
        self.assertIsNot(statefile.path_lock(self.path),
                         statefile.path_lock(os.path.join(self.tmp.name, "other.json")))

    def test_a_byte_order_mark_does_not_stop_updates(self):
        with open(self.path, "w", encoding="utf-8-sig") as stream:  # "UTF-8 with BOM", as some editors save it
            json.dump({"counters": {"c0": 1}}, stream)
        self.assertTrue(statefile.update_json_file(self.path, lambda d: d["counters"].__setitem__("c0", 2) or True))
        self.assertEqual(self.read(), {"counters": {"c0": 2}})

    @unittest.skipUnless(os.name == "posix", "file modes and symlinks are a POSIX matter here")
    def test_an_updated_file_keeps_its_permissions(self):
        os.chmod(self.path, 0o644)
        self.assertTrue(statefile.update_json_file(self.path, lambda d: d["counters"].__setitem__("c0", 1) or True))
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), oct(0o644))
        os.chmod(self.path, 0o664)
        self.assertTrue(statefile.atomic_write_json(self.path, {"counters": {}}))
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), oct(0o664))
        fresh = os.path.join(self.tmp.name, "fresh.json")
        self.assertTrue(statefile.atomic_write_json(fresh, {"new": 1}))
        self.assertEqual(oct(os.stat(fresh).st_mode & 0o777), oct(0o644))

    @unittest.skipUnless(os.name == "posix", "file modes and symlinks are a POSIX matter here")
    def test_a_symlinked_state_file_stays_a_symlink(self):
        link = os.path.join(self.tmp.name, "link.json")
        os.symlink(self.path, link)
        self.assertTrue(statefile.update_json_file(link, lambda d: d["counters"].__setitem__("c0", 7) or True))
        self.assertTrue(os.path.islink(link))
        self.assertEqual(self.read()["counters"]["c0"], 7)
        self.assertEqual(self.leftovers(), ["link.json"])

    @unittest.skipUnless(sys.platform == "win32", "os.replace onto an open file only fails on Windows")
    def test_replace_waits_for_a_reader_to_let_go(self):
        reader = open(self.path, "rb")
        self.addCleanup(reader.close)
        threading.Timer(0.2, reader.close).start()
        self.assertTrue(statefile.atomic_write_json(self.path, {"after": "reader"}))
        self.assertEqual(self.read(), {"after": "reader"})
        self.assertEqual(self.leftovers(), [])


if __name__ == "__main__":
    unittest.main()
