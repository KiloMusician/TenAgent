"""Shared harness that boots the real ``dashboard/serve.py`` handler on loopback.

The dashboard module is Windows-only (it calls ``sys.exit`` on other platforms
at import time), so importing this module on another platform skips the test
module that uses it.

Set ``TENAGENT_TEST_ROOT`` to a different checkout (for example an export of
the parent commit) to run the same tests against that tree's ``serve.py``.  This
is how a test is shown to fail on the defect it was written for.

Everything runs against a throw-away directory tree: no repository file is
written, no provider is contacted and no subprocess is started.  The functions
that would do so are replaced and record their arguments instead
(``self.shell_runs``, ``self.agy_runs``, ``self.verified``); an attempt to open
a real URL fails the test.
"""

import http.client
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path

if sys.platform != "win32":
    raise unittest.SkipTest("dashboard/serve.py is a Windows-only server")

SOURCE_ROOT = Path(__file__).resolve().parents[1]
MODULE_ROOT = Path(os.environ.get("TENAGENT_TEST_ROOT") or SOURCE_ROOT).resolve()

FAKE_SESSION_TOKEN = "session-token-FAKE-123"
FAKE_PROVIDER_KEY = "sk-test-FAKE-123-abcdefghijklmnop"

# Content that must never be served; a response containing one of these is a leak.
CANARY_ROOT = "CANARY-ROOT-FILE-9a1f"
CANARY_ENV = "sk-test-FAKE-ENV-CANARY"
CANARY_GIT = "CANARY-GIT-CONFIG-77c2"
CANARY_SPEC = "CANARY-SPEC-NOTES-31d8"
CANARY_HIDDEN = "CANARY-HIDDEN-FILE-5be0"
CANARY_SOURCE = "def verify_ai_provider_key"
CANARIES = (CANARY_ENV, CANARY_GIT, CANARY_HIDDEN, CANARY_ROOT, CANARY_SOURCE,
            CANARY_SPEC)

DROPPED = 0  # Response.status when the connection was closed without an answer

_SERVE = None
_ABSENT = object()


def load_serve():
    """Import the module under test once per process, under a private name."""
    global _SERVE
    if _SERVE is None:
        path = MODULE_ROOT / "dashboard" / "serve.py"
        spec = importlib.util.spec_from_file_location(
            "tenagent_dashboard_serve_under_test", path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _SERVE = module
    return _SERVE


class Response:
    def __init__(self, status, headers, body, raw_head=b""):
        self.status = status
        self.headers = headers
        self.body = body
        self.raw_head = raw_head

    def header(self, name, default=None):
        return self.headers.get(name.lower(), default)

    def json(self):
        return json.loads(self.body.decode("utf-8"))

    def text(self):
        return self.body.decode("utf-8", errors="replace")

    def __repr__(self):
        return f"<Response {self.status} {len(self.body)}B {self.body[:80]!r}>"


def _copy_tree(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name == "__pycache__":
            continue
        if item.is_dir():
            _copy_tree(item, dst / item.name)
        else:
            shutil.copy2(item, dst / item.name)


class DashboardCase(unittest.TestCase):
    """Starts a real ThreadedSwarmServer on 127.0.0.1:<ephemeral> per test."""

    def setUp(self):
        self.serve = load_serve()
        self.tmp = tempfile.TemporaryDirectory(prefix="tenagent-http-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self._build_tree()

        serve = self.serve
        self.patch_serve("DIRECTORY", str(self.root))
        self.patch_serve("SPECS_DIR", str(self.root / "specs"))
        self.patch_serve("LOG_FILE", str(self.root / "specs" / "terminal.log"))
        self.patch_serve("STATUS_FILE", str(self.root / "specs" / "swarm-status.json"))
        self.patch_serve("_SESSION_TOKEN", FAKE_SESSION_TOKEN)

        # Safety net: nothing in these tests may reach a provider or spawn a
        # process.  Any attempt is recorded (or fails the test).
        self.verified = []
        self.shell_runs = []
        self.agy_runs = []

        def fake_verify(provider_id, key, base_url=""):
            self.verified.append((provider_id, key, base_url))
            return {"status": "active", "valid": True,
                    "statusDetail": "Active", "models": []}

        self.patch_serve("verify_ai_provider_key", fake_verify)
        self.patch_serve("run_powershell_subprocess",
                         lambda cmd, root: self.shell_runs.append(cmd))
        self.patch_serve("run_agy_prompt",
                         lambda prompt, root: self.agy_runs.append(prompt))

        def no_network(*args, **kwargs):
            raise AssertionError("test attempted a real network request")

        self.patch(urllib.request, "urlopen", no_network)

        self.httpd = serve.ThreadedSwarmServer(("127.0.0.1", 0), serve.SwarmHandler)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(
            target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
            daemon=True,
        )
        self._thread.start()
        self.addCleanup(self._stop_server)

    def patch(self, owner, name, value):
        """Replace ``owner.name`` for the length of the test (restored, or removed, afterwards)."""
        previous = getattr(owner, name, _ABSENT)
        setattr(owner, name, value)
        if previous is _ABSENT:
            self.addCleanup(delattr, owner, name)
        else:
            self.addCleanup(setattr, owner, name, previous)

    def patch_serve(self, name, value):
        self.patch(self.serve, name, value)

    def _stop_server(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=5)

    def _build_tree(self):
        root = self.root
        _copy_tree(MODULE_ROOT / "dashboard", root / "dashboard")
        if (MODULE_ROOT / "assets").is_dir():
            _copy_tree(MODULE_ROOT / "assets", root / "assets")
        (root / "specs").mkdir()
        status = MODULE_ROOT / "specs" / "swarm-status.json"
        shutil.copy2(status, root / "specs" / "swarm-status.json")
        (root / "specs" / "notes.md").write_text(CANARY_SPEC, encoding="utf-8")
        (root / "secret.txt").write_text(CANARY_ROOT, encoding="utf-8")
        (root / ".env").write_text(f"KEY={CANARY_ENV}\n", encoding="utf-8")
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text(CANARY_GIT, encoding="utf-8")
        (root / "dashboard" / ".hidden.txt").write_text(CANARY_HIDDEN, encoding="utf-8")
        (root / "other").mkdir()
        (root / "other" / "x.txt").write_text(CANARY_ROOT, encoding="utf-8")

    # -- request helpers -------------------------------------------------

    @property
    def local_host(self):
        return f"127.0.0.1:{self.port}"

    def token_headers(self):
        """What the dashboard page sends with every write: the session token."""
        return {"X-TenAgent-Token": FAKE_SESSION_TOKEN}

    def same_origin_headers(self, host=None):
        """A browser's write from the dashboard page itself (token + fetch metadata)."""
        host = host or self.local_host
        return {**self.token_headers(),
                "Origin": f"http://{host}", "Sec-Fetch-Site": "same-origin"}

    def request(self, method, path, *, headers=None, body=None, host=None,
                json_body=None):
        sent = {}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            sent["Content-Type"] = "application/json"
        sent.update(headers or {})
        if host is not None:
            sent["Host"] = host
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=sent)
            reply = conn.getresponse()
            data = reply.read()
            return Response(
                reply.status,
                {k.lower(): v for k, v in reply.getheaders()},
                data,
            )
        except (ConnectionError, http.client.RemoteDisconnected):
            # The server closed the connection before the client read its answer.
            # Windows does this to a client whose request body the server never
            # read (a rejected POST): the reset can overtake the reply.
            return Response(DROPPED, {}, b"")
        finally:
            conn.close()

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post_json(self, path, payload, **kwargs):
        """POST as the dashboard page does: session token header, JSON body."""
        kwargs["headers"] = {**self.token_headers(), **(kwargs.get("headers") or {})}
        return self.request("POST", path, json_body=payload, **kwargs)

    def raw(self, data: bytes, *, timeout=8, shutdown_write=False):
        """Send exact bytes and parse whatever comes back."""
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=timeout)
        try:
            sock.sendall(data)
            if shutdown_write:
                sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                try:
                    chunk = sock.recv(65536)
                except (socket.timeout, ConnectionResetError):
                    break
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            sock.close()
        return parse_response(b"".join(chunks))

    def raw_request(self, method, target, *, version="HTTP/1.1", headers=None,
                    body=b"", host="default", **kwargs):
        """Build a request by hand so malformed forms can be sent verbatim."""
        lines = [f"{method} {target} {version}".encode("latin-1")]
        if host == "default":
            lines.append(f"Host: {self.local_host}".encode("latin-1"))
        elif host is not None:
            lines.append(f"Host: {host}".encode("latin-1"))
        for name, value in (headers or []):
            if isinstance(value, str):
                value = value.encode("latin-1")
            lines.append(f"{name}: ".encode("latin-1") + value)
        if body and not any(n.lower() == "content-length" for n, _ in (headers or [])):
            lines.append(f"Content-Length: {len(body)}".encode("latin-1"))
        return self.raw(b"\r\n".join(lines) + b"\r\n\r\n" + body, **kwargs)

    # -- fixture helpers -------------------------------------------------

    def write_config(self, config):
        path = self.root / "specs" / "swarm-config.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        return path

    def read_config(self):
        path = self.root / "specs" / "swarm-config.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def read_log(self):
        path = self.root / "specs" / "terminal.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def read_status(self):
        path = self.root / "specs" / "swarm-status.json"
        return json.loads(path.read_text(encoding="utf-8"))


def parse_response(blob: bytes) -> Response:
    head, _, body = blob.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    status = 0
    if lines and lines[0]:
        parts = lines[0].split(b" ", 2)
        if len(parts) >= 2 and parts[1].isdigit():
            status = int(parts[1])
    headers = {}
    for line in lines[1:]:
        name, _, value = line.partition(b":")
        headers[name.decode("latin-1").strip().lower()] = value.decode("latin-1").strip()
    return Response(status, headers, body, raw_head=head)
