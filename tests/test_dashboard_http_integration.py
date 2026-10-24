"""Real-HTTP checks of the dashboard's route x method access matrix.

Unlike ``test_dashboard_security.py`` (pure helpers) these tests start the
actual ``ThreadedSwarmServer`` on 127.0.0.1:<ephemeral port> and talk to it over
sockets.  See ``http_harness.py`` for the isolation guarantees.
"""

import json
import shutil
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from http_harness import (  # noqa: E402  (import after sys.path tweak)
    CANARY_ENV, CANARY_GIT, CANARY_HIDDEN, CANARY_ROOT, CANARY_SOURCE,
    CANARY_SPEC, FAKE_PASSWORD, FAKE_PROVIDER_KEY, FAKE_SESSION_TOKEN,
    DashboardCase, basic_auth,
)

CANARIES = (CANARY_ENV, CANARY_GIT, CANARY_HIDDEN, CANARY_ROOT, CANARY_SOURCE,
            CANARY_SPEC)

GET_ROUTES = (
    "/", "/dashboard", "/dashboard/", "/dashboard/index.html", "/api/config",
    "/api/csrf-token", "/api/cli-status", "/specs/swarm-status.json",
    "/specs/terminal.log", "/favicon.ico", "/favicon.png", "/favicon.svg",
    "/dashboard/favicon.ico", "/assets/", "/assets/logo.png", "/nope",
    "/api/unknown", "/dashboard/serve.py", "/.env", "/specs/swarm-config.json",
    "/api/command", "/api/log", "/api/models",
)
POST_ROUTES = (
    "/api/config", "/api/models", "/api/command", "/api/log", "/api/unknown",
    "/", "/dashboard/",
)


class UnauthenticatedAccessTests(DashboardCase):
    def assert_challenge(self, response, label):
        self.assertEqual(response.status, 401, label)
        self.assertTrue(
            response.header("www-authenticate", "").startswith("Basic realm="),
            label,
        )
        self.assertEqual(response.body, b"", label)
        self.assertIsNone(response.header("set-cookie"), label)

    def test_every_get_route_challenges_without_credentials(self):
        for path in GET_ROUTES:
            with self.subTest(path=path):
                self.assert_challenge(self.get(path, auth=False), path)

    def test_every_post_route_challenges_without_credentials(self):
        headers = {
            **self.same_origin_headers(),
            "X-TenAgent-Token": FAKE_SESSION_TOKEN,
        }
        for path in POST_ROUTES:
            with self.subTest(path=path):
                # raw_request sends headers and body in one segment; a server
                # that closes before reading the body is covered separately.
                response = self.raw_request(
                    "POST", path, auth=False,
                    headers=[("Content-Type", "application/json")] + list(headers.items()),
                    body=json.dumps({
                        "command": "echo unauthenticated", "message": "unauth",
                        "providers": [{"provider": "gemini", "key": FAKE_PROVIDER_KEY}],
                    }).encode(),
                )
                self.assert_challenge(response, path)
        # A rejected request must not have had any effect.
        self.assertEqual(self.shell_runs, [])
        self.assertEqual(self.agy_runs, [])
        self.assertEqual(self.verified, [])
        self.assertFalse((self.root / "specs" / "swarm-config.json").exists())
        self.assertNotIn("unauth", self.read_log())

    def test_head_requires_credentials_and_never_returns_a_body(self):
        self.assert_challenge(self.request("HEAD", "/dashboard/", auth=False), "HEAD")
        self.assert_challenge(
            self.request("HEAD", "/specs/swarm-status.json", auth=False), "HEAD json"
        )
        authed = self.request("HEAD", "/dashboard/")
        self.assertEqual(authed.status, 405)
        self.assertEqual(authed.body, b"")

    def test_wrong_credentials_are_rejected(self):
        wrong = (
            basic_auth("tenagent", "wrong-password-FAKE"),
            basic_auth("operator", FAKE_PASSWORD),
            basic_auth("TENAGENT", FAKE_PASSWORD),
            basic_auth("tenagent", ""),
            basic_auth("", ""),
            "Bearer " + FAKE_PASSWORD,
            "Digest username=tenagent",
            FAKE_PASSWORD,
        )
        for header in wrong:
            with self.subTest(header=header[:20]):
                response = self.get("/api/csrf-token", auth=False,
                                    headers={"Authorization": header})
                self.assert_challenge(response, header[:20])

    def test_basic_auth_parser_is_robust_over_http(self):
        import base64
        good = base64.b64encode(f"tenagent:{FAKE_PASSWORD}".encode()).decode()
        accepted = (
            f"Basic {good}",
            f"basic {good}",
            f"BASIC {good}",
            f"Basic {good} ",
        )
        for header in accepted:
            with self.subTest(accepted=header[:12]):
                response = self.get("/api/csrf-token", auth=False,
                                    headers={"Authorization": header})
                self.assertEqual(response.status, 200)
        rejected = (
            "Basic", "Basic ", "Basic !!!not-base64!!!",
            "Basic " + base64.b64encode(b"\xff\xfe:\xff").decode(),
            "Basic " + base64.b64encode(b"no-colon-at-all").decode(),
            "Basic " + good[:-4],
            "Basic " + good + "A" * 2000,
            "Basic  " + good + " extra",
        )
        for header in rejected:
            with self.subTest(rejected=header[:24]):
                response = self.get("/api/csrf-token", auth=False,
                                    headers={"Authorization": header})
                self.assertEqual(response.status, 401)

    def test_password_may_contain_colons_and_unicode(self):
        for password in ("pw:with:colons", "pässwörd-FAKE-ünï", " padded "):
            with self.subTest(password=password):
                self.serve._DASHBOARD_PASSWORD = password
                ok = self.get("/api/csrf-token", auth=False,
                              headers={"Authorization": basic_auth("tenagent", password)})
                self.assertEqual(ok.status, 200)
                prefix = self.get("/api/csrf-token", auth=False, headers={
                    "Authorization": basic_auth("tenagent", password[:-1])})
                self.assertEqual(prefix.status, 401)


class MethodMatrixTests(DashboardCase):
    def test_options_exposes_no_cors_permission(self):
        for auth in (False, True):
            with self.subTest(auth=auth):
                response = self.request(
                    "OPTIONS", "/api/command", auth=auth,
                    headers={"Origin": "http://hostile.example",
                             "Access-Control-Request-Method": "POST"},
                )
                self.assertEqual(response.status, 405)
                self.assertNotIn("access-control-allow-origin", response.headers)
                self.assertNotIn("access-control-allow-methods", response.headers)
                self.assertEqual(response.body, b"")

    def test_unsupported_methods_return_501_without_data(self):
        for method in ("PUT", "DELETE", "PATCH", "TRACE", "CONNECT", "PROPFIND"):
            for auth in (False, True):
                with self.subTest(method=method, auth=auth):
                    response = self.raw_request(method, "/api/config", auth=auth)
                    self.assertEqual(response.status, 501)
                    for canary in CANARIES + (FAKE_PROVIDER_KEY,):
                        self.assertNotIn(canary.encode(), response.body)

    def test_state_changing_methods_have_no_effect(self):
        for method in ("PUT", "DELETE", "PATCH"):
            self.raw_request(method, "/api/log", auth=True,
                             headers=[("Content-Type", "application/json")],
                             body=b'{"message":"method-effect"}')
        self.assertNotIn("method-effect", self.read_log())


class HostHeaderTests(DashboardCase):
    def test_accepted_host_forms(self):
        for host in (
            "{ip}", "localhost:{port}", "LOCALHOST:{port}", "Localhost:{port}",
        ):
            host = host.format(ip=self.local_host, port=self.port)
            with self.subTest(host=host):
                self.assertEqual(
                    self.raw_request("GET", "/api/csrf-token", host=host).status, 200
                )

    def test_rejected_host_forms_even_with_valid_credentials(self):
        port = self.port
        for host in (
            f"localhost.:{port}", f"[::1]:{port}", "localhost", "127.0.0.1",
            f"evil.example:{port}", "evil.example", f"127.0.0.1:{port + 1}",
            f"user@127.0.0.1:{port}", f"127.0.0.1:{port}@evil.example",
            f"127.0.0.1.evil.example:{port}", f"localhost:{port}.evil.example",
            f"127.1:{port}", f"2130706433:{port}", f"0x7f.0.0.1:{port}",
            f"0:{port}", f"[::ffff:127.0.0.1]:{port}", "",
        ):
            with self.subTest(host=host):
                response = self.raw_request("GET", "/api/config", host=host)
                self.assertEqual(response.status, 403)
                self.assertNotIn(b"providers", response.body)

    def test_missing_host_is_rejected_on_http_1_0(self):
        response = self.raw_request("GET", "/api/csrf-token", version="HTTP/1.0",
                                    host=None)
        self.assertEqual(response.status, 403)

    def test_host_is_checked_before_credentials(self):
        # A rebinding page must not even learn whether a password is needed.
        response = self.raw_request("GET", "/api/config", auth=False,
                                    host=f"evil.example:{self.port}")
        self.assertEqual(response.status, 403)
        self.assertIsNone(response.header("www-authenticate"))

    def test_rebinding_host_cannot_mutate(self):
        response = self.raw_request(
            "POST", "/api/log", host=f"evil.example:{self.port}",
            headers=[("Content-Type", "application/json"),
                     ("Origin", f"http://evil.example:{self.port}")],
            body=b'{"message":"rebind-attempt"}',
        )
        self.assertEqual(response.status, 403)
        self.assertNotIn("rebind-attempt", self.read_log())

    def test_http_1_0_requests_are_authenticated_too(self):
        self.assertEqual(
            self.raw_request("GET", "/api/config", version="HTTP/1.0",
                             auth=False).status, 401)
        self.assertEqual(
            self.raw_request("GET", "/api/csrf-token", version="HTTP/1.0").status, 200)


class OriginPolicyTests(DashboardCase):
    def log_with(self, marker, headers, **kwargs):
        merged = [("Content-Type", "application/json")] + list(headers)
        return self.raw_request(
            "POST", "/api/log", headers=merged,
            body=f'{{"agent":"cli","message":"{marker}"}}'.encode(), **kwargs
        )

    def test_same_origin_and_non_browser_clients_may_write(self):
        origin = f"http://{self.local_host}"
        self.assertEqual(self.log_with("m-same", [("Origin", origin),
                                                  ("Sec-Fetch-Site", "same-origin")]).status, 200)
        self.assertEqual(self.log_with("m-none", []).status, 200)
        self.assertEqual(self.log_with("m-fetch-none", [("Sec-Fetch-Site", "none")]).status, 200)
        log = self.read_log()
        for marker in ("m-same", "m-none", "m-fetch-none"):
            self.assertIn(marker, log)

    def test_cross_origin_writes_are_refused_and_have_no_effect(self):
        port = self.port
        refused = {
            "null-origin": [("Origin", "null")],
            "hostile": [("Origin", "http://hostile.example")],
            "other-port": [("Origin", f"http://127.0.0.1:{port + 1}")],
            "other-loopback-name": [("Origin", f"http://localhost:{port}")],
            "https-scheme": [("Origin", f"https://{self.local_host}")],
            "trailing-slash": [("Origin", f"http://{self.local_host}/")],
            "userinfo": [("Origin", f"http://u@{self.local_host}")],
            "cross-site-fetch": [("Origin", f"http://{self.local_host}"),
                                 ("Sec-Fetch-Site", "cross-site")],
            "same-site-fetch": [("Origin", f"http://{self.local_host}"),
                                ("Sec-Fetch-Site", "same-site")],
            "fetch-metadata-only": [("Sec-Fetch-Site", "cross-site")],
        }
        for label, headers in refused.items():
            with self.subTest(case=label):
                marker = "refused-" + label
                response = self.log_with(marker, headers)
                self.assertEqual(response.status, 403, label)
                self.assertNotIn(marker, self.read_log())

    def test_text_plain_cross_origin_post_cannot_reach_handlers(self):
        # The classic CSRF form post: simple content type, no preflight.
        for path in ("/api/log", "/api/config", "/api/command", "/api/models"):
            with self.subTest(path=path):
                response = self.raw_request(
                    "POST", path,
                    headers=[("Content-Type", "text/plain;charset=UTF-8"),
                             ("Origin", "http://hostile.example"),
                             ("Sec-Fetch-Site", "cross-site"),
                             ("X-TenAgent-Token", FAKE_SESSION_TOKEN)],
                    body=b'{"command":"echo csrf","message":"csrf-text-plain"}',
                )
                self.assertEqual(response.status, 403)
        self.assertEqual(self.shell_runs, [])
        self.assertNotIn("csrf-text-plain", self.read_log())

    def test_cross_origin_get_is_not_given_cors_permission(self):
        response = self.get("/api/csrf-token",
                            headers={"Origin": "http://hostile.example"})
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertNotIn("access-control-allow-credentials", response.headers)


class CommandEndpointTests(DashboardCase):
    def command(self, command, extra_headers=(), same_origin=True):
        headers = [("Content-Type", "application/json")]
        if same_origin:
            headers += [("Origin", f"http://{self.local_host}"),
                        ("Sec-Fetch-Site", "same-origin")]
        headers += list(extra_headers)
        import json
        return self.raw_request("POST", "/api/command", headers=headers,
                                body=json.dumps({"command": command}).encode())

    def test_requires_the_session_token(self):
        for label, extra in {
            "missing": [],
            "wrong-header": [("X-TenAgent-Token", "wrong")],
            "empty-header": [("X-TenAgent-Token", "")],
            "wrong-cookie": [("Cookie", "tenagent_token=wrong")],
        }.items():
            with self.subTest(case=label):
                self.assertEqual(self.command("echo nope", extra).status, 403)
        self.assertEqual(self.shell_runs, [])

    def test_token_and_credentials_are_both_needed(self):
        token = [("X-TenAgent-Token", FAKE_SESSION_TOKEN)]
        self.assertEqual(self.command("echo ok", token).status, 200)
        self.assertEqual(self.shell_runs, ["echo ok"])
        no_auth = self.raw_request(
            "POST", "/api/command", auth=False,
            headers=[("Content-Type", "application/json")] + token,
            body=b'{"command":"echo no-auth"}')
        self.assertEqual(no_auth.status, 401)
        self.assertEqual(self.shell_runs, ["echo ok"])

    def test_cookie_token_is_accepted_for_the_dashboard_frontend(self):
        response = self.command("echo cookie", [("Cookie", f"tenagent_token={FAKE_SESSION_TOKEN}")])
        self.assertEqual(response.status, 200)

    def test_non_shell_text_is_routed_to_the_prompt_runner_not_a_shell(self):
        token = [("X-TenAgent-Token", FAKE_SESSION_TOKEN)]
        self.assertEqual(self.command("please write a haiku", token).status, 200)
        self.assertEqual(self.shell_runs, [])
        self.assertEqual(self.agy_runs, ["please write a haiku"])

    def test_empty_and_malformed_commands(self):
        token = [("X-TenAgent-Token", FAKE_SESSION_TOKEN)]
        self.assertEqual(self.command("   ", token).status, 400)
        bad = self.raw_request(
            "POST", "/api/command",
            headers=[("Content-Type", "application/json"),
                     ("Origin", f"http://{self.local_host}")] + token,
            body=b"{not json")
        self.assertEqual(bad.status, 400)
        self.assertEqual(self.shell_runs, [])


class LogEndpointTests(DashboardCase):
    """POST /api/log feeds swarm-status.json, which the page renders."""

    def log(self, payload):
        return self.post_json("/api/log", payload, headers=self.same_origin_headers())

    def agent(self, agent_id="01_pm"):
        return next(a for a in self.read_status()["agents"] if a["id"] == agent_id)

    def test_valid_update_is_applied(self):
        response = self.log({"agent": "01_pm", "message": "drafting", "status": "WORKING",
                             "progress": 40})
        self.assertEqual(response.status, 200)
        agent = self.agent()
        self.assertEqual((agent["status"], agent["progress"], agent["processDetail"]),
                         ("WORKING", 40, "drafting"))
        self.assertIn("[01_pm] drafting", self.read_log())

    def test_status_is_limited_to_known_values(self):
        before = self.agent()["status"]
        for status in ('<img src=x onerror="alert(1)">', 'WORKING" onmouseover="x',
                       "working", "", "DONE-ish", 5, ["WORKING"], {"a": 1}):
            with self.subTest(status=status):
                response = self.log({"agent": "01_pm", "message": "m", "status": status})
                self.assertEqual(response.status, 400)
                self.assertEqual(self.agent()["status"], before)
        stored = (self.root / "specs" / "swarm-status.json").read_text("utf-8")
        self.assertNotIn("onerror", stored)

    def test_agent_tag_is_a_plain_identifier(self):
        for agent in ("[founder] ", "a\n[00:00:00] [founder]", "x" * 200, "", 5, None,
                      "<b>", "../x"):
            with self.subTest(agent=agent):
                self.assertEqual(self.log({"agent": agent, "message": "m"}).status, 400)
        self.assertEqual(self.read_log(), "")

    def test_message_cannot_forge_log_lines(self):
        forged = "real\r\n[10:00:00] [founder] > fake command\n[10:00:01] [01_pm] fake"
        self.assertEqual(self.log({"agent": "cli", "message": forged}).status, 200)
        lines = self.read_log().splitlines()
        self.assertEqual(len(lines), 1, lines)
        self.assertIn("real", lines[0])

    def test_message_is_length_limited(self):
        self.assertEqual(self.log({"agent": "cli", "message": "x" * 100_000}).status, 200)
        self.assertLess(len(self.read_log()), 5_000)

    def test_payload_types_are_validated(self):
        for payload in ([1], "text", 5, None, {"message": 5}, {"message": ["a"]},
                        {"progress": "abc"}, {"progress": [1]}, {"progress": {}}):
            with self.subTest(payload=payload):
                self.assertEqual(self.log(payload).status, 400)

    def test_progress_is_clamped(self):
        self.assertEqual(self.log({"agent": "01_pm", "progress": 5000}).status, 200)
        self.assertEqual(self.agent()["progress"], 100)
        self.assertEqual(self.log({"agent": "01_pm", "progress": "-7"}).status, 200)
        self.assertEqual(self.agent()["progress"], 0)

    def test_rejected_request_writes_nothing(self):
        self.log({"agent": "01_pm", "message": "must-not-appear", "status": "BOGUS"})
        self.assertNotIn("must-not-appear", self.read_log())
        self.assertNotEqual(self.agent()["processDetail"], "must-not-appear")


class AuthenticatedRouteTests(DashboardCase):
    def test_root_redirects_and_sets_token_cookie(self):
        response = self.get("/")
        self.assertEqual(response.status, 302)
        self.assertEqual(response.header("location"), "/dashboard/")
        cookie = response.header("set-cookie", "")
        self.assertIn(f"tenagent_token={FAKE_SESSION_TOKEN}", cookie)
        self.assertIn("SameSite=Strict", cookie)

    def test_dashboard_page_and_token(self):
        page = self.get("/dashboard/")
        self.assertEqual(page.status, 200)
        self.assertIn(b"TenAgent", page.body)
        self.assertEqual(self.get("/api/csrf-token").json(), {"token": FAKE_SESSION_TOKEN})

    def test_responses_are_not_cacheable(self):
        for path in ("/api/csrf-token", "/api/config", "/dashboard/"):
            with self.subTest(path=path):
                self.assertIn("no-store", self.get(path).header("cache-control", ""))

    def test_status_and_log_are_served_to_the_operator(self):
        # write_bytes: Path.write_text would turn \n into \r\n on Windows.
        (self.root / "specs" / "terminal.log").write_bytes(b"[00:00:00] [cli] hello\n")
        self.assertEqual(self.get("/specs/swarm-status.json").status, 200)
        self.assertEqual(self.get("/specs/terminal.log").body, b"[00:00:00] [cli] hello\n")

    def test_config_api_never_returns_the_key(self):
        self.write_config({"engine": "custom", "providers": [
            {"provider": "gemini", "key": FAKE_PROVIDER_KEY, "name": "g"}]})
        body = self.get("/api/config").text()
        self.assertNotIn(FAKE_PROVIDER_KEY, body)
        self.assertIn('"has_key": true', body)

    def test_post_config_response_never_returns_the_key(self):
        response = self.post_json(
            "/api/config",
            {"providers": [{"provider": "gemini", "key": FAKE_PROVIDER_KEY}]},
            headers=self.same_origin_headers())
        self.assertEqual(response.status, 200)
        self.assertNotIn(FAKE_PROVIDER_KEY, response.text())
        self.assertEqual(self.read_config()["providers"][0]["key"], FAKE_PROVIDER_KEY)

    def test_config_post_masked_key_keeps_the_stored_key(self):
        self.write_config({"engine": "custom", "providers": [
            {"provider": "gemini", "key": FAKE_PROVIDER_KEY}]})
        masked = FAKE_PROVIDER_KEY[:4] + "..." + FAKE_PROVIDER_KEY[-4:]
        response = self.post_json(
            "/api/config", {"providers": [{"provider": "gemini", "key": masked}]},
            headers=self.same_origin_headers())
        self.assertEqual(response.status, 200)
        self.assertEqual(self.read_config()["providers"][0]["key"], FAKE_PROVIDER_KEY)
        self.assertEqual(self.verified[-1][1], FAKE_PROVIDER_KEY)


class StaticPathTests(DashboardCase):
    BLOCKED = (
        "/dashboard/serve.py", "/dashboard/SERVE.PY", "/dashboard/security.py",
        "/dashboard/SERVE~1.PY", "/specs/swarm-config.json",
        "/specs/SWARM-CONFIG.JSON", "/.env", "/.git/config", "/secret.txt",
        "/other/x.txt", "/specs/notes.md", "/dashboard/.hidden.txt",
        "/dashboard/../secret.txt", "/dashboard/./index.html",
        "/dashboard/%2e%2e/secret.txt", "/dashboard/%2E%2E/secret.txt",
        "/dashboard/%252e%252e/secret.txt", "/dashboard/....//secret.txt",
        "/dashboard/..%5csecret.txt", "/dashboard/..%5Csecret.txt",
        "/dashboard/%2e%2e%2fsecret.txt", "/dashboard/..\\secret.txt",
        "/dashboard\\..\\secret.txt", "/assets/..\\secret.txt",
        "/specs/swarm-status.json/../notes.md",
        "/specs/swarm-status.json/../../secret.txt", "/dashboard/%00",
        "/dashboard/index.html%00.py", "/dashboard/%ff", "/favicon./../secret.txt",
        "//secret.txt", "///dashboard/serve.py",
        "http://127.0.0.1/dashboard/serve.py", "http://127.0.0.1/secret.txt",
        "http://evil.example/dashboard/index.html", "http:///secret.txt",
        "/dashboard/c:/windows/win.ini", "/dashboard/C:\\windows\\win.ini",
        "/dashboard/\\\\127.0.0.1\\share\\x", "/dashboard/index.html/../../secret.txt",
    )

    def test_blocked_paths_never_return_file_content(self):
        for target in self.BLOCKED:
            with self.subTest(target=target):
                response = self.raw_request("GET", target, timeout=5)
                self.assertIn(response.status, (301, 400, 403, 404), response)
                for canary in CANARIES:
                    self.assertNotIn(canary.encode(), response.body)

    def test_blocked_paths_are_also_blocked_for_head_and_post(self):
        for method in ("HEAD", "POST"):
            for target in ("/dashboard/serve.py", "/secret.txt", "/.env"):
                with self.subTest(method=method, target=target):
                    response = self.raw_request(method, target)
                    self.assertNotEqual(response.status, 200)
                    for canary in CANARIES:
                        self.assertNotIn(canary.encode(), response.body)

    def test_query_strings_do_not_change_routing(self):
        self.assertEqual(self.get("/api/csrf-token?x=1&y=/../..").status, 200)
        self.assertEqual(self.get("/dashboard/?a=b").status, 200)
        self.assertEqual(self.get("/dashboard/serve.py?x=.txt").status, 403)

    def test_error_pages_escape_reflected_input(self):
        response = self.raw_request("GET", "/%3Cscript%3Ealert(1)%3C/script%3E")
        self.assertNotIn(b"<script>alert", response.body)
        response = self.raw_request("FOO<b>", "/")
        self.assertNotIn(b"<b>", response.body)

    def test_allowed_static_files(self):
        self.assertEqual(self.get("/dashboard/index.html").status, 200)
        self.assertEqual(self.get("/dashboard/").status, 200)
        self.assertEqual(self.get("/favicon.ico").status, 200)
        self.assertEqual(self.get("/assets/logo.png").status, 200)
        redirect = self.get("/dashboard")
        self.assertEqual(redirect.status, 301)
        self.assertEqual(redirect.header("location"), "/dashboard/")


class StaticGuardBypassTests(DashboardCase):
    """The deny-list in do_GET used to look at a different string than the
    file system: http.server drops '#...', Windows drops trailing dots and
    resolves 'name::$DATA' to the file's default stream."""

    def assert_not_served(self, target, *, content_markers=()):
        response = self.raw_request("GET", target, timeout=5)
        self.assertIn(response.status, (400, 403, 404), (target, response))
        for marker in tuple(CANARIES) + tuple(content_markers):
            self.assertNotIn(marker.encode(), response.body, target)

    def test_denied_extensions_cannot_be_hidden_behind_a_fragment(self):
        for target in ("/dashboard/serve.py#x", "/dashboard/security.py#.txt",
                       "/dashboard/serve.py#.png", "/dashboard/SERVE.PY#.html"):
            with self.subTest(target=target):
                self.assert_not_served(target)

    def test_windows_name_normalisation_cannot_reach_denied_files(self):
        for target in ("/dashboard/serve.py.", "/dashboard/serve.py..",
                       "/dashboard/serve.py::$DATA", "/dashboard/serve.py:stream",
                       "/dashboard/security.py::$DATA", "/dashboard/serve.py.png:x.png"):
            with self.subTest(target=target):
                self.assert_not_served(target)

    def test_only_the_two_state_files_are_served_from_specs(self):
        (self.root / "specs" / "swarm-status.json.tmp").write_text(CANARY_SPEC, "utf-8")
        (self.root / "specs" / "swarm-status.jsonx").write_text(CANARY_SPEC, "utf-8")
        for target in ("/specs/swarm-status.json.tmp", "/specs/swarm-status.jsonx",
                       "/specs/swarm-status.json.", "/specs/swarm-status.json::$DATA",
                       "/specs/swarm-status.json/", "/specs/"):
            with self.subTest(target=target):
                self.assert_not_served(target)
        self.assertEqual(self.get("/specs/swarm-status.json").status, 200)

    def test_extension_allow_list_applies_inside_served_directories(self):
        (self.root / "dashboard" / "notes.bak").write_text(CANARY_SPEC, "utf-8")
        (self.root / "assets" / "data.db").write_text(CANARY_SPEC, "utf-8")
        (self.root / "assets" / "NOEXT").write_text(CANARY_SPEC, "utf-8")
        for target in ("/dashboard/notes.bak", "/assets/data.db", "/assets/NOEXT"):
            with self.subTest(target=target):
                self.assert_not_served(target)

    def test_windows_device_names_are_not_opened(self):
        for name in ("nul", "NUL", "nul.txt", "con", "aux.png", "prn.html", "com1",
                     "COM9.svg", "lpt1.png", "conin$", "CLOCK$"):
            with self.subTest(name=name):
                response = self.raw_request("GET", f"/dashboard/{name}", timeout=5)
                self.assertIn(response.status, (400, 403, 404), name)

    def test_directory_listings_are_not_generated(self):
        for target in ("/assets/", "/dashboard/sub/", "/specs/"):
            with self.subTest(target=target):
                response = self.raw_request("GET", target)
                self.assertIn(response.status, (403, 404))
                self.assertNotIn(b"Directory listing", response.body)

    def test_junction_inside_a_served_directory_cannot_escape_the_tree(self):
        import subprocess
        outside = Path(tempfile.mkdtemp(prefix="tenagent-outside-"))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / "leak.txt").write_text(CANARY_ROOT, "utf-8")
        link = self.root / "assets" / "link"
        made = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                              capture_output=True, text=True)
        if made.returncode != 0:
            self.skipTest("cannot create a directory junction: " + made.stdout + made.stderr)
        try:
            self.assert_not_served("/assets/link/leak.txt")
        finally:
            subprocess.run(["cmd", "/c", "rmdir", str(link)], capture_output=True)

    def test_legitimate_assets_are_still_served(self):
        for target in ("/dashboard/", "/dashboard/index.html", "/dashboard/favicon.png?v=2",
                       "/dashboard/logoTenAgent.png", "/assets/logo.png", "/favicon.ico",
                       "/specs/swarm-status.json"):
            with self.subTest(target=target):
                self.assertEqual(self.get(target).status, 200)


class RequestBodyTests(DashboardCase):
    """Body handling must fail closed, quickly, and with a real HTTP answer."""

    ENDPOINTS = ("/api/config", "/api/models", "/api/command", "/api/log")

    def post(self, path, body=b"", extra=(), declared=None):
        headers = [("Content-Type", "application/json"),
                   ("Origin", f"http://{self.local_host}"),
                   ("Sec-Fetch-Site", "same-origin"),
                   ("X-TenAgent-Token", FAKE_SESSION_TOKEN)]
        headers += list(extra)
        if declared is not None:
            headers.append(("Content-Length", str(declared)))
        return self.raw_request("POST", path, headers=headers, body=body, timeout=6,
                                shutdown_write=True)

    def test_non_numeric_content_length_is_a_400(self):
        for path in self.ENDPOINTS:
            for declared in ("abc", "1e3", "0x10", "12 34", "+-5", ""):
                with self.subTest(path=path, declared=declared):
                    self.assertEqual(self.post(path, b"{}", declared=declared).status, 400)

    def test_negative_content_length_does_not_hang(self):
        for path in self.ENDPOINTS:
            with self.subTest(path=path):
                started = time.monotonic()
                response = self.post(path, b"{}", declared=-1)
                self.assertEqual(response.status, 400)
                self.assertLess(time.monotonic() - started, 4)

    def test_oversized_declared_length_is_refused_without_reading_it(self):
        for path in self.ENDPOINTS:
            with self.subTest(path=path):
                started = time.monotonic()
                response = self.post(path, b"{}", declared=50_000_000)
                self.assertEqual(response.status, 413)
                self.assertLess(time.monotonic() - started, 4)

    def test_oversized_actual_body_is_refused(self):
        body = b'{"message":"' + b"x" * (2 * 1024 * 1024) + b'"}'
        self.assertEqual(self.post("/api/log", body).status, 413)
        self.assertEqual(self.read_log(), "")

    def test_body_below_the_limit_is_accepted(self):
        body = json.dumps({"agent": "cli", "message": "y" * 900_000}).encode()
        self.assertEqual(self.post("/api/log", body).status, 200)

    def test_truncated_body_is_a_400(self):
        response = self.post("/api/log", b'{"mess', declared=500)
        self.assertEqual(response.status, 400)

    def test_chunked_bodies_are_refused(self):
        response = self.post(
            "/api/log", b'a\r\n{"agent":"x"}\r\n0\r\n\r\n',
            extra=[("Transfer-Encoding", "chunked")])
        self.assertEqual(response.status, 411)
        self.assertEqual(self.read_log(), "")

    def test_malformed_payloads_are_a_400_not_a_dropped_connection(self):
        for path in self.ENDPOINTS:
            for label, body in (("non-utf8", b"\xff\xfe{"), ("not json", b"{nope"),
                                ("array", b"[1,2]"), ("scalar", b"7"), ("null", b"null"),
                                ("empty", b""), ("nesting", b"[" * 100_000)):
                with self.subTest(path=path, body=label):
                    self.assertEqual(self.post(path, body).status, 400)

    def test_error_bodies_do_not_echo_exception_internals(self):
        response = self.post("/api/config", b'{"providers": 5}')
        self.assertEqual(response.status, 400)
        self.assertNotIn("object has no attribute", response.text())
        self.assertNotIn("Traceback", response.text())

    def test_rejected_post_still_delivers_its_answer_when_the_body_follows(self):
        # http.client (and some browsers) send the headers first and the body
        # afterwards.  If the server answers 401/403 and closes while unread
        # body bytes are still coming, Windows answers them with a reset and the
        # client's recv() fails instead of returning the status line.
        body = b"x" * 300_000
        cases = (
            ("no-credentials", False, ""),
            ("bad-origin", True, "Origin: http://hostile.example\r\n"),
        )
        for label, with_auth, extra in cases:
            with self.subTest(case=label):
                sock = socket.create_connection(("127.0.0.1", self.port), timeout=8)
                head = (
                    f"POST /api/log HTTP/1.1\r\nHost: {self.local_host}\r\n"
                    + (f"Authorization: {self.auth_header}\r\n" if with_auth else "")
                    + extra
                    + f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
                ).encode()
                received = b""
                try:
                    sock.sendall(head)
                    time.sleep(0.4)  # the server has answered (and, unfixed, closed)
                    try:
                        sock.sendall(body)
                    except OSError:
                        pass
                    while True:
                        chunk = sock.recv(65536)
                        if not chunk:
                            break
                        received += chunk
                except OSError:
                    pass
                finally:
                    sock.close()
                self.assertRegex(received[:12], rb"HTTP/1\.[01] (401|403)", label)

    def test_slow_clients_are_disconnected(self):
        handler = self.serve.SwarmHandler
        self.assertIsNotNone(handler.timeout)
        self.assertLessEqual(handler.timeout, 120)
        self.addCleanup(setattr, handler, "timeout", handler.timeout)
        handler.timeout = 1
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=6)
        self.addCleanup(sock.close)
        sock.sendall(b"GET /api/csrf-token HTTP/1.1\r\nHost: ")  # never finishes
        self.assertEqual(sock.recv(1024)[:0], b"")  # EOF (or error page), not a hang


class StateFileConcurrencyTests(DashboardCase):
    """The dashboard's threads share swarm-status.json / swarm-config.json."""

    def agent_ids(self, count):
        return [a["id"] for a in self.read_status()["agents"]][:count]

    def leftovers(self):
        return sorted(p.name for p in (self.root / "specs").glob("*.tmp"))

    def test_concurrent_status_updates_are_neither_lost_nor_corrupted(self):
        import threading
        ids = self.agent_ids(8)
        barrier = threading.Barrier(len(ids))

        def work(agent_id):
            barrier.wait()
            for step in range(1, 26):
                self.serve.set_agent_status_direct(agent_id, "WORKING", f"step {step}", step)

        threads = [threading.Thread(target=work, args=(i,)) for i in ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        final = {a["id"]: a["progress"] for a in self.read_status()["agents"]}
        self.assertEqual([final[i] for i in ids], [25] * len(ids))
        self.assertEqual(self.leftovers(), [])

    def test_concurrent_log_posts_keep_the_status_file_consistent(self):
        import threading
        ids = self.agent_ids(6)
        barrier = threading.Barrier(len(ids))
        statuses = []

        def work(agent_id):
            barrier.wait()
            for step in range(1, 11):
                reply = self.post_json(
                    "/api/log",
                    {"agent": agent_id, "message": f"s{step}", "progress": step * 10},
                    headers=self.same_origin_headers())
                statuses.append(reply.status)

        threads = [threading.Thread(target=work, args=(i,)) for i in ids]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        self.assertEqual(set(statuses), {200})
        final = {a["id"]: a["progress"] for a in self.read_status()["agents"]}
        self.assertEqual([final[i] for i in ids], [100] * len(ids))
        self.assertEqual(self.leftovers(), [])

    def test_update_waits_for_a_reader_instead_of_being_dropped(self):
        # SimpleHTTPRequestHandler keeps the file open while it streams it; on
        # Windows os.replace onto an open file fails, and the update used to be
        # swallowed silently.
        import threading
        status = self.root / "specs" / "swarm-status.json"
        agent_id = self.agent_ids(1)[0]
        reader = open(status, "rb")
        self.addCleanup(reader.close)
        worker = threading.Thread(
            target=self.serve.set_agent_status_direct,
            args=(agent_id, "WORKING", "after-reader", 77))
        worker.start()
        time.sleep(0.3)
        reader.close()
        worker.join(10)
        agent = next(a for a in self.read_status()["agents"] if a["id"] == agent_id)
        self.assertEqual((agent["progress"], agent["processDetail"]), (77, "after-reader"))
        self.assertEqual(self.leftovers(), [])

    def test_config_saved_by_the_operator_is_not_reverted_by_the_probe_worker(self):
        import threading
        serve = self.serve
        self.write_config({"engine": "custom", "providers": [
            {"provider": "9router", "key": "sk-test-FAKE-OLD-111111", "baseUrl": "http://127.0.0.1:9/v1"}]})
        probing, release = threading.Event(), threading.Event()

        def slow_probe(provider):
            probing.set()
            release.wait(10)
            provider["status"] = "connection_error"
            provider["statusDetail"] = "Offline"
            provider["valid"] = False
            return True

        original_probe, original_sleep = serve.probe_and_update_local_provider, serve.time.sleep
        calls = []

        def one_pass_sleep(seconds):
            calls.append(seconds)
            if len(calls) > 1:
                raise SystemExit  # end the worker thread after a single pass

        serve.probe_and_update_local_provider = slow_probe
        serve.time.sleep = one_pass_sleep
        self.addCleanup(setattr, serve, "probe_and_update_local_provider", original_probe)
        self.addCleanup(setattr, serve.time, "sleep", original_sleep)
        worker = threading.Thread(target=serve.local_providers_probe_worker, args=(str(self.root),))
        worker.start()
        self.assertTrue(probing.wait(10))
        saved = self.post_json(
            "/api/config",
            {"providers": [{"provider": "gemini", "key": "sk-test-FAKE-NEW-222222"}]},
            headers=self.same_origin_headers())
        self.assertEqual(saved.status, 200)
        release.set()
        worker.join(10)
        names = [p["provider"] for p in self.read_config()["providers"]]
        self.assertEqual(names, ["gemini"])

    def test_probe_results_are_merged_into_the_current_config(self):
        import threading
        serve = self.serve
        self.write_config({"engine": "custom", "providers": [
            {"provider": "9router", "key": "sk-test-FAKE-KEEP-333333", "baseUrl": "http://127.0.0.1:9/v1"}]})
        probing, release = threading.Event(), threading.Event()

        def slow_probe(provider):
            probing.set()
            release.wait(10)
            provider["status"] = "connection_error"
            provider["valid"] = False
            return True

        original_probe, original_sleep = serve.probe_and_update_local_provider, serve.time.sleep
        calls = []

        def one_pass_sleep(seconds):
            calls.append(seconds)
            if len(calls) > 1:
                raise SystemExit

        serve.probe_and_update_local_provider = slow_probe
        serve.time.sleep = one_pass_sleep
        self.addCleanup(setattr, serve, "probe_and_update_local_provider", original_probe)
        self.addCleanup(setattr, serve.time, "sleep", original_sleep)
        worker = threading.Thread(target=serve.local_providers_probe_worker, args=(str(self.root),))
        worker.start()
        self.assertTrue(probing.wait(10))
        # An unrelated edit lands while the probe is in flight.
        current = self.read_config()
        current["note"] = "edited-meanwhile"
        self.write_config(current)
        release.set()
        worker.join(10)
        stored = self.read_config()
        self.assertEqual(stored.get("note"), "edited-meanwhile")
        self.assertEqual(stored["providers"][0]["status"], "connection_error")
        self.assertEqual(stored["providers"][0]["key"], "sk-test-FAKE-KEEP-333333")


class ConfigKeyPreservationTests(DashboardCase):
    """POST /api/config must never lose, mangle or invent a stored provider key."""

    KEY_A = "sk-test-FAKE-AAAA-1111111111111111"
    KEY_B = "sk-test-FAKE-BBBB-2222222222222222"

    def mask(self, key):
        return key[:4] + "..." + key[-4:]

    def seed(self, *entries):
        self.write_config({"engine": "custom", "providers": list(entries)})

    def save(self, *entries, **extra):
        return self.post_json("/api/config", {"providers": list(entries), **extra},
                              headers=self.same_origin_headers())

    def stored_keys(self):
        return [p.get("key") for p in self.read_config()["providers"]]

    def test_round_tripping_the_redacted_view_keeps_the_key(self):
        self.seed({"provider": "gemini", "key": self.KEY_A, "name": "g"})
        view = self.get("/api/config").json()
        self.assertEqual(self.save(*view["providers"], engine=view["engine"]).status, 200)
        stored = self.read_config()
        self.assertEqual(self.stored_keys(), [self.KEY_A])
        for server_owned in ("has_key", "key_masked"):
            self.assertNotIn(server_owned, stored["providers"][0])
        self.assertNotIn("cli", stored)

    def test_absent_key_field_keeps_the_stored_key(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        self.assertEqual(self.save({"provider": "gemini", "model": "m1"}).status, 200)
        self.assertEqual(self.stored_keys(), [self.KEY_A])
        self.assertEqual(self.read_config()["providers"][0]["model"], "m1")

    def test_explicit_empty_key_clears_it(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        self.assertEqual(self.save({"provider": "gemini", "key": ""}).status, 200)
        stored = self.read_config()["providers"][0]
        self.assertEqual(stored["key"], "")
        self.assertEqual(stored["status"], "empty")

    def test_masked_key_is_restored_and_verified_with_the_real_key(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        self.assertEqual(self.save({"provider": "gemini", "key": self.mask(self.KEY_A)}).status, 200)
        self.assertEqual(self.stored_keys(), [self.KEY_A])
        self.assertEqual([call[1] for call in self.verified], [self.KEY_A])

    def test_masked_key_under_a_different_provider_name_is_refused(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        before = self.read_config()
        response = self.save({"provider": "renamed", "key": "***"})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.read_config(), before)
        self.assertEqual(self.verified, [])

    def test_masked_placeholder_is_never_stored_as_a_key(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        before = self.read_config()
        response = self.save({"provider": "other", "key": "abcd...wxyz"})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.read_config(), before)

    def test_duplicate_provider_ids_keep_their_own_keys(self):
        self.seed({"provider": "custom", "key": self.KEY_A, "baseUrl": "http://127.0.0.1:1/v1"},
                  {"provider": "custom", "key": self.KEY_B, "baseUrl": "http://127.0.0.1:2/v1"})
        view = self.get("/api/config").json()["providers"]
        self.assertEqual(self.save(*reversed(view)).status, 200)
        self.assertEqual(self.stored_keys(), [self.KEY_B, self.KEY_A])

    def test_new_key_replaces_the_old_one(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        self.assertEqual(self.save({"provider": "gemini", "key": self.KEY_B}).status, 200)
        self.assertEqual(self.stored_keys(), [self.KEY_B])

    def test_removed_providers_are_dropped(self):
        self.seed({"provider": "gemini", "key": self.KEY_A}, {"provider": "groq", "key": self.KEY_B})
        self.assertEqual(self.save({"provider": "groq", "key": self.mask(self.KEY_B)}).status, 200)
        self.assertEqual([p["provider"] for p in self.read_config()["providers"]], ["groq"])
        self.assertEqual(self.stored_keys(), [self.KEY_B])

    def test_invalid_payload_shapes_change_nothing(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        before = self.read_config()
        for payload in ({"providers": "x"}, {"providers": {"a": 1}}, {"providers": [1]},
                        {"providers": [{"provider": 5, "key": "k"}]},
                        {"providers": [{"provider": "g", "key": 5}]},
                        {"providers": [{"provider": "g", "key": ["k"]}]}):
            with self.subTest(payload=payload):
                response = self.post_json("/api/config", payload,
                                          headers=self.same_origin_headers())
                self.assertEqual(response.status, 400)
                self.assertNotIn("attribute", response.text())
                self.assertEqual(self.read_config(), before)

    def test_a_failed_entry_leaves_the_whole_config_untouched(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        before = self.read_config()
        response = self.save({"provider": "groq", "key": self.KEY_B},
                             {"provider": "ghost", "key": "***"})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.read_config(), before)

    def test_write_failure_is_reported_and_keeps_the_old_file(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        before = self.read_config()
        original = self.serve.atomic_write_json
        self.serve.atomic_write_json = lambda *a, **k: False
        self.addCleanup(setattr, self.serve, "atomic_write_json", original)
        self.assertEqual(self.save({"provider": "gemini", "key": self.KEY_B}).status, 500)
        self.assertEqual(self.read_config(), before)

    def test_models_endpoint_uses_the_stored_key_for_a_masked_one(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        response = self.post_json("/api/models", {"provider": "gemini", "key": self.mask(self.KEY_A)},
                                  headers=self.same_origin_headers())
        self.assertEqual(response.status, 200)
        self.assertEqual([call[1] for call in self.verified], [self.KEY_A])

    def test_models_endpoint_never_sends_a_mask_to_a_provider(self):
        self.seed({"provider": "gemini", "key": self.KEY_A})
        response = self.post_json("/api/models", {"provider": "unknown", "key": "abcd...wxyz"},
                                  headers=self.same_origin_headers())
        self.assertEqual(response.status, 400)
        self.assertEqual(self.verified, [])


class BindingTests(DashboardCase):
    def test_server_listens_on_loopback_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_server_is_http_1_0_without_keepalive(self):
        response = self.get("/api/csrf-token")
        self.assertEqual(response.header("connection"), None)
        self.assertEqual(self.httpd.RequestHandlerClass.protocol_version, "HTTP/1.0")


if __name__ == "__main__":
    unittest.main()
