"""Real-HTTP checks of the dashboard server's current routes and access rules.

The tests start the actual ``ThreadedSwarmServer`` on 127.0.0.1:<ephemeral port>
and talk to it over sockets (see ``http_harness.py`` for the isolation
guarantees).  They pin what the server does today, so that later changes to a
route or a guard have to say so in their own tests.  Skipped off Windows, where
``dashboard/serve.py`` cannot be imported.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from http_harness import (  # noqa: E402  (import after sys.path tweak)
    CANARIES, DROPPED, FAKE_PROVIDER_KEY, FAKE_SESSION_TOKEN, DashboardCase,
)

POST_ROUTES = ("/api/config", "/api/models", "/api/command", "/api/log")


def assert_no_canary(test, response):
    for canary in CANARIES:
        test.assertNotIn(canary.encode(), response.body, f"leaked {canary!r}")


def assert_refused(test, response):
    """A rejected POST: 403, or - while the server leaves a rejected body unread - a dropped connection."""
    test.assertIn(response.status, (403, DROPPED), response)


class RouteTests(DashboardCase):
    def test_root_redirects_to_the_dashboard_and_sets_the_token_cookie(self):
        reply = self.get("/")
        self.assertEqual(reply.status, 302)
        self.assertEqual(reply.header("location"), "/dashboard/")
        self.assertIn("tenagent_token=" + FAKE_SESSION_TOKEN, reply.header("set-cookie"))

    def test_the_dashboard_page_is_served(self):
        for path in ("/dashboard", "/dashboard/", "/dashboard/index.html"):
            with self.subTest(path=path):
                reply = self.get(path)
                self.assertEqual(reply.status, 200)
                self.assertIn("text/html", reply.header("content-type"))
                self.assertIn(b"<html", reply.body.lower())

    def test_the_csrf_token_endpoint_hands_the_page_its_token(self):
        reply = self.get("/api/csrf-token")
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.json(), {"token": FAKE_SESSION_TOKEN})

    def test_status_and_log_files_are_served(self):
        (self.root / "specs" / "terminal.log").write_text("[00:00:00] [cli] hello\n", encoding="utf-8")
        status = self.get("/specs/swarm-status.json")
        self.assertEqual(status.status, 200)
        self.assertEqual(status.json(), self.read_status())
        log = self.get("/specs/terminal.log")
        self.assertEqual(log.status, 200)
        self.assertIn(b"hello", log.body)

    def test_favicons_and_assets_are_served(self):
        for path in ("/favicon.ico", "/favicon.png", "/favicon.svg", "/dashboard/favicon.ico",
                     "/assets/logo.png"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status, 200)

    def test_cli_status_is_json(self):
        self.patch_serve("get_cached_cli_status", lambda root: {"agy": {"installed": False}})
        reply = self.get("/api/cli-status")
        self.assertEqual(reply.status, 200)
        self.assertEqual(reply.json(), {"agy": {"installed": False}})

    def test_unknown_routes_are_not_found(self):
        for path in ("/nope", "/api/unknown", "/specs/", "/api/command", "/api/log"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status, 404)

    def test_responses_are_not_cacheable(self):
        self.assertIn("no-store", self.get("/dashboard/").header("cache-control"))
        self.assertIn("no-store", self.get("/api/config").header("cache-control"))


class BlockedPathTests(DashboardCase):
    """Nothing outside the dashboard, assets and the two state files is ever served."""

    BLOCKED = (
        "/.env", "/.git/config", "/secret.txt", "/other/x.txt", "/specs/notes.md",
        "/specs/swarm-config.json", "/dashboard/serve.py", "/dashboard/.hidden.txt",
        "/dashboard/../secret.txt", "/../secret.txt", "/%2e%2e/secret.txt",
        "/dashboard/%2e%2e/secret.txt", "/dashboard/%252e%252e/secret.txt",
        "/dashboard/..%5csecret.txt", "/dashboard\\..\\secret.txt",
        "/dashboard/%2e%2e%2fsecret.txt",
    )

    def test_blocked_paths_never_return_file_content(self):
        (self.root / "specs" / "swarm-config.json").write_text(
            json.dumps({"providers": [{"provider": "x", "key": FAKE_PROVIDER_KEY}]}),
            encoding="utf-8")
        for path in self.BLOCKED:
            with self.subTest(path=path):
                reply = self.raw_request("GET", path)
                self.assertIn(reply.status, (400, 403, 404), reply)
                assert_no_canary(self, reply)
                self.assertNotIn(FAKE_PROVIDER_KEY.encode(), reply.body)

    def test_query_strings_do_not_change_routing(self):
        self.assertEqual(self.get("/dashboard/?x=1").status, 200)
        self.assertEqual(self.get("/.env?x=/dashboard/").status, 403)


class HostHeaderTests(DashboardCase):
    def test_loopback_host_names_are_accepted(self):
        for host in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            with self.subTest(host=host):
                self.assertEqual(self.get("/dashboard/", host=host).status, 200)

    def test_other_host_names_are_refused_for_reads_and_writes(self):
        for host in ("evil.example", f"evil.example:{self.port}", f"localhost.evil.example:{self.port}",
                     "10.0.0.5", "192.168.1.2:7777"):
            with self.subTest(host=host):
                self.assertEqual(self.get("/api/config", host=host).status, 403)
                reply = self.post_json("/api/log", {"agent": "cli", "message": "x"}, host=host)
                assert_refused(self, reply)

    def test_a_rebinding_host_cannot_run_a_command(self):
        reply = self.post_json("/api/command", {"command": "dir"}, host=f"rebind.example:{self.port}")
        assert_refused(self, reply)
        self.assertEqual((self.shell_runs, self.agy_runs), ([], []))


class WriteGateTests(DashboardCase):
    """Every POST needs the session token and a same-site browser context."""

    def payload(self, path):
        return {
            "/api/config": {"engine": "custom", "providers": []},
            "/api/models": {"provider": "groq", "key": FAKE_PROVIDER_KEY},
            "/api/command": {"command": "dir"},
            "/api/log": {"agent": "01_pm", "message": "hello"},
        }[path]

    def assert_nothing_happened(self):
        self.assertEqual((self.shell_runs, self.agy_runs, self.verified), ([], [], []))
        self.assertFalse((self.root / "specs" / "swarm-config.json").exists())
        self.assertFalse((self.root / "specs" / "terminal.log").exists())

    def test_a_post_without_the_token_is_refused(self):
        for path in POST_ROUTES:
            with self.subTest(path=path):
                reply = self.request("POST", path, json_body=self.payload(path))
                assert_refused(self, reply)
        self.assert_nothing_happened()

    def test_a_post_with_the_wrong_token_is_refused(self):
        for path in POST_ROUTES:
            with self.subTest(path=path):
                reply = self.request("POST", path, json_body=self.payload(path),
                                     headers={"X-TenAgent-Token": "wrong"})
                assert_refused(self, reply)
        self.assert_nothing_happened()

    def test_cross_origin_posts_are_refused_even_with_the_token(self):
        for path in POST_ROUTES:
            for headers in ({"Origin": "https://evil.example"},
                            {"Sec-Fetch-Site": "cross-site"},
                            {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}):
                with self.subTest(path=path, headers=headers):
                    reply = self.post_json(path, self.payload(path), headers=headers)
                    assert_refused(self, reply)
        self.assert_nothing_happened()

    def test_the_token_is_also_accepted_as_the_page_cookie(self):
        reply = self.request("POST", "/api/command", json_body={"command": "dir"},
                             headers={"Cookie": f"tenagent_token={FAKE_SESSION_TOKEN}"})
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.shell_runs, ["dir"])

    def test_the_page_itself_is_allowed_to_write(self):
        for path in POST_ROUTES:
            with self.subTest(path=path):
                reply = self.post_json(path, self.payload(path), headers=self.same_origin_headers())
                self.assertEqual(reply.status, 200)

    def test_a_non_browser_client_with_the_token_is_allowed_to_write(self):
        reply = self.post_json("/api/log", {"agent": "01_pm", "message": "from stream.py"})
        self.assertEqual(reply.status, 200)


class CommandEndpointTests(DashboardCase):
    def test_shell_commands_go_to_the_shell_runner_and_are_logged(self):
        reply = self.post_json("/api/command", {"command": "git status"})
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.shell_runs, ["git status"])
        self.assertIn("[founder] > git status", self.read_log())

    def test_plain_text_goes_to_the_prompt_runner(self):
        reply = self.post_json("/api/command", {"command": "build me a login page"})
        self.assertEqual(reply.status, 200)
        self.assertEqual((self.shell_runs, self.agy_runs), ([], ["build me a login page"]))

    def test_agy_prefixes_are_unwrapped(self):
        self.post_json("/api/command", {"command": 'agy -p "say hi"'})
        self.post_json("/api/command", {"command": "agy hello there"})
        self.assertEqual(self.agy_runs, ["say hi", "hello there"])

    def test_an_empty_command_is_a_400(self):
        reply = self.post_json("/api/command", {"command": "   "})
        self.assertEqual(reply.status, 400)
        self.assertEqual((self.shell_runs, self.agy_runs), ([], []))


class LogEndpointTests(DashboardCase):
    def agent(self, agent_id="01_pm"):
        return next(a for a in self.read_status()["agents"] if a["id"] == agent_id)

    def test_a_valid_update_reaches_the_log_and_the_agent(self):
        reply = self.post_json("/api/log", {"agent": "01_pm", "message": "drafting",
                                            "status": "WORKING", "progress": 40})
        self.assertEqual(reply.status, 200)
        self.assertIn("[01_pm] drafting", self.read_log())
        agent = self.agent()
        self.assertEqual((agent["status"], agent["progress"], agent["processDetail"]),
                         ("WORKING", 40, "drafting"))

    def test_progress_is_clamped_to_a_percentage(self):
        self.post_json("/api/log", {"agent": "01_pm", "progress": 250})
        self.assertEqual(self.agent()["progress"], 100)
        self.post_json("/api/log", {"agent": "01_pm", "progress": -5})
        self.assertEqual(self.agent()["progress"], 0)

    def test_an_unknown_agent_changes_no_agent(self):
        before = self.read_status()["agents"]
        reply = self.post_json("/api/log", {"agent": "99_nobody", "message": "x", "status": "WORKING"})
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.read_status()["agents"], before)


class ConfigEndpointTests(DashboardCase):
    KEY = FAKE_PROVIDER_KEY

    def provider(self, **extra):
        return {"provider": "groq", "key": self.KEY, **extra}

    def test_the_stored_key_is_never_sent_to_the_browser(self):
        self.write_config({"engine": "custom", "providers": [self.provider()]})
        reply = self.get("/api/config")
        self.assertEqual(reply.status, 200)
        self.assertNotIn(self.KEY.encode(), reply.body)
        shown = reply.json()["providers"][0]
        self.assertTrue(shown["has_key"])
        self.assertNotIn("key", shown)

    def test_saving_a_config_stores_it_and_answers_without_the_key(self):
        reply = self.post_json("/api/config", {"engine": "custom", "providers": [self.provider()]})
        self.assertEqual(reply.status, 200)
        self.assertNotIn(self.KEY.encode(), reply.body)
        self.assertEqual(self.read_config()["providers"][0]["key"], self.KEY)

    def test_round_tripping_the_redacted_view_keeps_the_stored_key(self):
        self.write_config({"engine": "custom", "providers": [self.provider()]})
        view = self.get("/api/config").json()
        self.assertNotEqual(view["providers"][0]["key_masked"], "")
        view["providers"][0]["key"] = view["providers"][0]["key_masked"]
        self.assertEqual(self.post_json("/api/config", view).status, 200)
        self.assertEqual(self.read_config()["providers"][0]["key"], self.KEY)

    def test_a_masked_key_in_the_models_call_is_replaced_by_the_stored_key_and_url(self):
        self.write_config({"engine": "custom", "providers": [
            self.provider(baseUrl="http://127.0.0.1:9/v1")]})
        masked = self.get("/api/config").json()["providers"][0]["key_masked"]
        reply = self.post_json("/api/models", {"provider": "groq", "key": masked,
                                               "baseUrl": "http://attacker.invalid/"})
        self.assertEqual(reply.status, 200)
        # the credential goes only where it was saved for, never to the posted address
        self.assertEqual(self.verified, [("groq", self.KEY, "http://127.0.0.1:9/v1")])

    def test_a_masked_key_with_nothing_stored_is_not_sent_anywhere(self):
        reply = self.post_json("/api/models", {"provider": "groq", "key": "sk-t...cdef"})
        self.assertEqual(reply.json()["status"], "empty")
        self.assertEqual(self.verified, [])


class BindingTests(DashboardCase):
    def test_the_server_listens_on_loopback_only(self):
        self.assertEqual(self.httpd.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
