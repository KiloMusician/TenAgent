"""Real-HTTP checks of the dashboard's route x method access matrix.

Unlike ``test_dashboard_security.py`` (pure helpers) these tests start the
actual ``ThreadedSwarmServer`` on 127.0.0.1:<ephemeral port> and talk to it over
sockets.  See ``http_harness.py`` for the isolation guarantees.
"""

import json
import sys
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


class BindingTests(DashboardCase):
    def test_server_listens_on_loopback_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")

    def test_server_is_http_1_0_without_keepalive(self):
        response = self.get("/api/csrf-token")
        self.assertEqual(response.header("connection"), None)
        self.assertEqual(self.httpd.RequestHandlerClass.protocol_version, "HTTP/1.0")


if __name__ == "__main__":
    unittest.main()
