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
"""

import json
import os
import tempfile
import threading
import time

STATE_LOCK = threading.RLock()

_REPLACE_ATTEMPTS = 60
_REPLACE_DELAY = 0.025


def atomic_write_json(path, data) -> bool:
    """Write ``data`` to ``path`` atomically; return False if it could not land.

    The data is written to a unique temporary file in the same directory, then
    moved over the target.  A busy target (a reader on Windows) is retried for
    about 1.5 seconds before giving up.  The previous file is never left
    truncated and no temporary file is left behind.
    """
    target = os.path.abspath(path)
    directory = os.path.dirname(target)
    tmp_path = None
    try:
        os.makedirs(directory, exist_ok=True)
        handle, tmp_path = tempfile.mkstemp(
            prefix=os.path.basename(target) + ".", suffix=".tmp", dir=directory
        )
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
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
    """Atomically read-modify-write ``path`` under the process-wide lock.

    ``mutate(data)`` edits the parsed document in place and returns True when it
    changed something; only then is the file rewritten.  Returns True when a new
    version was written.  A missing or unparseable file is left alone.
    """
    with STATE_LOCK:
        try:
            with open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
        except (OSError, ValueError):
            return False
        try:
            if not mutate(data):
                return False
        except (AttributeError, KeyError, TypeError):
            return False  # document does not have the expected shape
        return atomic_write_json(path, data)
