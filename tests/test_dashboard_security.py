"""Regression coverage for the localhost dashboard's access policy."""

import base64
import sys
import unittest
from pathlib import Path

# Allow ``python -I -m unittest discover -s tests`` (isolated mode does not
# put the repository root on sys.path).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard.security import (
    is_secret_field,
    mask_key,
    parse_log_update,
    prepare_config_payload,
    public_config,
    redact_url,
    single_line,
    valid_local_host,
    valid_mutation_origin,
    valid_operator_authorization,
    valid_static_path,
)


def basic(user, password):
    value = base64.b64encode(f"{user}:{password}".encode()).decode()
    return f"Basic {value}"


class DashboardSecurityTests(unittest.TestCase):
    def test_valid_local_operator(self):
        self.assertTrue(valid_operator_authorization(basic("tenagent", "correct"), "correct"))

    def test_invalid_basic_auth(self):
        for header in (
            None, "", "Bearer fake", "Basic ??", basic("someone", "correct"),
            basic("tenagent", "wrong"), basic("tënagent", "correct"),
        ):
            with self.subTest(header=header):
                self.assertFalse(valid_operator_authorization(header, "correct"))

    def test_empty_password_is_not_a_credential(self):
        self.assertFalse(valid_operator_authorization(basic("tenagent", ""), ""))

    def test_host_validation(self):
        self.assertTrue(valid_local_host("localhost:7777", 7777))
        self.assertTrue(valid_local_host("127.0.0.1:7777", 7777))
        for host in ("localhost.evil:7777", "localhost:7778", "example.org", None):
            with self.subTest(host=host):
                self.assertFalse(valid_local_host(host, 7777))

    def test_mutations_reject_cross_origin(self):
        self.assertFalse(valid_mutation_origin(
            "http://hostile.example", "localhost:7777", "cross-site", 7777
        ))
        self.assertFalse(valid_mutation_origin(
            "http://localhost:8888", "localhost:7777", "same-site", 7777
        ))
        self.assertTrue(valid_mutation_origin(
            "http://localhost:7777", "localhost:7777", "same-origin", 7777
        ))

    def test_cli_local_authenticated_requests_are_supported(self):
        self.assertTrue(valid_mutation_origin(None, "127.0.0.1:7777", None, 7777))

    def test_redaction_does_not_modify_stored_keys(self):
        raw = {
            "providers": [{"provider": "gemini", "key": "EXAMPLEKEY-1234567890-ABCDEFGH", "valid": True}],
            "nested": {"api_key": "PRIVATE", "client-secret": "VERY_PRIVATE"},
        }
        result = public_config(raw)
        self.assertEqual(raw["providers"][0]["key"], "EXAMPLEKEY-1234567890-ABCDEFGH")
        self.assertNotIn("key", result["providers"][0])
        self.assertNotIn("api_key", result["nested"])
        self.assertNotIn("client-secret", result["nested"])
        self.assertEqual(result["providers"][0]["valid"], True)
        self.assertEqual(result["providers"][0]["key_masked"], "EXAM...EFGH")

    def test_empty_key_and_short_keys(self):
        result = public_config({"providers": [{"key": "a"}, {"key": ""}]})
        self.assertTrue(result["providers"][0]["has_key"])
        self.assertEqual(result["providers"][0]["key_masked"], "***")
        self.assertFalse(result["providers"][1]["has_key"])

    def test_static_paths_reject_encoded_traversal(self):
        self.assertTrue(valid_static_path("/dashboard/index.html"))
        self.assertTrue(valid_static_path("/assets/example.png"))
        for path in (
            "/dashboard/%2e%2e/specs/config.json",
            "/dashboard/%252e%252e/secrets",
            "/dashboard/../secret",
            "/dashboard/.env",
            "/dashboard/\\\\secret",
        ):
            with self.subTest(path=path):
                self.assertFalse(valid_static_path(path))

    def test_static_paths_reject_names_windows_would_reinterpret(self):
        for path in (
            "/dashboard/serve.py", "/dashboard/serve.py.", "/dashboard/serve.py ",
            "/dashboard/serve.py::$DATA", "/dashboard/index.html:stream",
            "/dashboard/nul", "/dashboard/NUL.txt", "/dashboard/com1.png",
            "/dashboard/CLOCK$", "/assets/data.db", "/assets/NOEXT",
            "/dashboard/c:/windows/win.ini", "/dashboard", "relative/path.png",
            "/dashboard/caf\u00e9.png",
        ):
            with self.subTest(path=path):
                self.assertFalse(valid_static_path(path))
        for path in ("/dashboard/", "/dashboard/index.html", "/assets/logo.png",
                     "/specs/swarm-status.json", "/specs/terminal.log",
                     "/dashboard/favicon.PNG", "/assets//logo.png"):
            with self.subTest(path=path):
                self.assertTrue(valid_static_path(path))

    def test_dashboard_cli_never_skips_permissions(self):
        server_source = (Path(__file__).resolve().parents[1] / "dashboard" / "serve.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--dangerously-skip-permissions", server_source)
        self.assertNotIn('"-ExecutionPolicy", "Bypass"', server_source)
        self.assertIn('"ERROR", "Error communicating with AI engine."', server_source)


class LogUpdateParsingTests(unittest.TestCase):
    def test_accepts_the_documented_shape(self):
        update = parse_log_update(
            {"agent": "05_backend", "message": " done ", "status": "REVIEWING", "progress": "99"}
        )
        self.assertEqual(tuple(update), ("05_backend", "done", "REVIEWING", 99))

    def test_defaults_match_the_original_endpoint(self):
        self.assertEqual(tuple(parse_log_update({})), ("cli", "", None, None))

    def test_rejects_markup_in_status(self):
        with self.assertRaises(ValueError):
            parse_log_update({"status": "<img src=x onerror=alert(1)>"})

    def test_single_line_flattens_every_line_break(self):
        self.assertEqual(single_line("a\r\nb\nc\u2028d\x00e"), "a b c d e")
        self.assertEqual(len(single_line("x" * 5000)), 2000)


class RedactionTests(unittest.TestCase):
    def test_secret_field_names_are_matched_by_substring(self):
        for name in ("key", "api_key", "x-api-key", "openai_api_key", "secret_key", "clientSecret",
                     "auth_token", "access_token", "Passphrase", "password", "Authorization",
                     "cookie", "private-key", "bearerToken"):
            with self.subTest(name=name):
                self.assertTrue(is_secret_field(name))
        for name in ("provider", "baseUrl", "model", "status", "statusDetail", "max_tokens",
                     "valid", "models", "engine", "name"):
            with self.subTest(name=name):
                self.assertFalse(is_secret_field(name))

    def test_url_userinfo_and_secret_query_values_are_hidden(self):
        self.assertEqual(
            redact_url("http://user:pw@127.0.0.1:1/v1?token=T&model=m&API_KEY=K#frag"),
            "http://***@127.0.0.1:1/v1?token=***&model=m&API_KEY=***#frag")
        for plain in ("http://localhost:20128/v1", "localhost:20128", "not a url", ""):
            self.assertEqual(redact_url(plain), plain)
        once = redact_url("https://a:b@h/p?key=1")
        self.assertEqual(redact_url(once), once)

    def test_masks_reveal_only_the_ends_of_long_keys(self):
        self.assertEqual(mask_key(""), "")
        self.assertEqual(mask_key("a" * 23), "***")
        self.assertEqual(mask_key("abcd" + "x" * 16 + "wxyz"), "abcd...wxyz")


class PrepareConfigPayloadTests(unittest.TestCase):
    KEY = "sk-test-FAKE-123-abcdefghijklmnop"
    STORED = {"providers": [{"provider": "gemini", "key": KEY}]}

    def prepare(self, *entries, **extra):
        return prepare_config_payload({"providers": list(entries), **extra}, self.STORED)

    def test_absent_null_masked_and_new_keys(self):
        masked = mask_key(self.KEY)
        self.assertEqual(self.prepare({"provider": "gemini"})["providers"][0]["key"], self.KEY)
        self.assertEqual(self.prepare({"provider": "gemini", "key": None})["providers"][0]["key"], self.KEY)
        self.assertEqual(self.prepare({"provider": "gemini", "key": masked})["providers"][0]["key"], self.KEY)
        self.assertEqual(self.prepare({"provider": "gemini", "key": ""})["providers"][0]["key"], "")
        self.assertEqual(self.prepare({"provider": "gemini", "key": "new"})["providers"][0]["key"], "new")

    def test_server_owned_fields_are_not_persisted(self):
        result = self.prepare({"provider": "gemini", "has_key": True, "key_masked": mask_key(self.KEY)},
                              cli={"name": "x"}, engine="custom")
        self.assertNotIn("cli", result)
        self.assertEqual(result["engine"], "custom")
        self.assertEqual(set(result["providers"][0]), {"provider", "key"})

    def test_unmatched_placeholder_is_refused(self):
        for entry in ({"provider": "other", "key": "***"}, {"provider": "gemini", "key": "abcd...wxyz"},
                      {"provider": "gemini", "key": "..."}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                self.prepare(entry)

    def test_each_stored_key_is_used_once(self):
        stored = {"providers": [{"provider": "c", "key": "k" * 20 + "AAAA"},
                                {"provider": "c", "key": "k" * 20 + "BBBB"}]}
        result = prepare_config_payload({"providers": [{"provider": "c"}, {"provider": "c"}]}, stored)
        self.assertEqual([p["key"] for p in result["providers"]],
                         ["k" * 20 + "AAAA", "k" * 20 + "BBBB"])

    def test_shapes_are_validated(self):
        for payload in ([], "x", {"providers": "x"}, {"providers": [1]},
                        {"providers": [{"provider": 1}]}, {"providers": [{"key": 5}]}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                prepare_config_payload(payload, self.STORED)


if __name__ == "__main__":
    unittest.main()
