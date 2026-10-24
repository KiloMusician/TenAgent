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
        before = os.stat(self.path).st_mtime_ns
        time.sleep(0.02)
        self.assertFalse(statefile.update_json_file(self.path, lambda d: False))
        self.assertEqual(os.stat(self.path).st_mtime_ns, before)

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
