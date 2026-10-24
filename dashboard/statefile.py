"""Atomic, serialised JSON state files for the dashboard process.

The dashboard's server threads, its background workers and the swarm pipeline
thread all read-modify-write ``specs/swarm-status.json`` and
``specs/swarm-config.json``.  Writing through one shared ``<name>.tmp`` file
with no lock tore the JSON when two threads wrote at once, lost updates, and
(on Windows) silently dropped an update whenever a reader still had the target
open, because ``os.replace`` onto an open file raises PermissionError.

Writers in *other* processes (``stream.py``, agents editing the file directly)
are not covered by the in-process lock; atomic replacement still guarantees
they can never expose a half-written file to readers.

There is one re-entrant lock per file, so a writer waiting for a reader to let
go of one file never delays writers of another.  No code path holds the lock of
two files at once (``update_json_file`` callbacks must not update other state
files), so the locks cannot deadlock.
"""

import json
import os
import stat
import tempfile
import threading
import time

_REPLACE_ATTEMPTS = 60
_REPLACE_DELAY = 0.025
_NEW_FILE_MODE = 0o644  # what ``open(path, "w")`` gave under the usual umask

_locks = {}
_locks_guard = threading.Lock()


def _resolve(path) -> str:
    """The file that really gets replaced: a symlink is followed, not overwritten."""
    return os.path.realpath(os.path.abspath(path))


def path_lock(path):
    """The re-entrant lock that serialises every read-modify-write of ``path``."""
    key = os.path.normcase(_resolve(path))
    with _locks_guard:
        lock = _locks.get(key)
        if lock is None:
            lock = _locks[key] = threading.RLock()
        return lock


def atomic_write_json(path, data) -> bool:
    """Write ``data`` to ``path`` atomically; return False if it could not land.

    The data is written to a unique temporary file in the same directory, then
    moved over the target.  A busy target (a reader on Windows) is retried for
    about 1.5 seconds before giving up.  The previous file is never left
    truncated and no temporary file is left behind; an existing file keeps its
    permissions and a symlink keeps pointing at the file that is updated.
    """
    target = _resolve(path)
    directory = os.path.dirname(target)
    tmp_path = None
    with path_lock(target):
        try:
            os.makedirs(directory, exist_ok=True)
            try:
                mode = stat.S_IMODE(os.stat(target).st_mode)
            except OSError:
                mode = _NEW_FILE_MODE
            handle, tmp_path = tempfile.mkstemp(
                prefix=os.path.basename(target) + ".", suffix=".tmp", dir=directory
            )
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            if os.name != "nt":  # mkstemp creates 0600; Windows only has a read-only bit
                os.chmod(tmp_path, mode)
            for attempt in range(_REPLACE_ATTEMPTS):
                try:
                    os.replace(tmp_path, target)
                    tmp_path = None
                    return True
                except PermissionError:
                    if attempt == _REPLACE_ATTEMPTS - 1:
                        return False
                    time.sleep(_REPLACE_DELAY)
            return False
        except (OSError, TypeError, ValueError):
            return False
        finally:
            if tmp_path is not None:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass


def update_json_file(path, mutate) -> bool:
    """Atomically read-modify-write ``path`` under that file's lock.

    ``mutate(data)`` edits the parsed document in place and returns True when it
    changed something; only then is the file rewritten.  Returns True when a new
    version was written.  A missing or unparseable file is left alone, and so is
    a file whose document ``mutate`` cannot handle (it raised): the callers are
    background threads that must not die over a hand-edited state file.  A
    leading byte-order mark (an editor's "UTF-8 with BOM") is accepted.
    """
    with path_lock(path):
        try:
            with open(_resolve(path), "r", encoding="utf-8-sig") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            return False
        try:
            if not mutate(data):
                return False
        except Exception:
            return False  # document does not have the expected shape (or the update itself failed)
        return atomic_write_json(path, data)
