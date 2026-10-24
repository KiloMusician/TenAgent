"""Regression coverage for the localhost dashboard's access policy."""

import base64
import unittest

from dashboard.security import (
    public_config,
    valid_local_host,
    valid_mutation_origin,
    valid_operator_authorization,
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
            "providers": [{"provider": "gemini", "key": "EXAMPLEKEY-123456", "valid": True}],
            "nested": {"api_key": "PRIVATE", "client-secret": "VERY_PRIVATE"},
        }
        result = public_config(raw)
        self.assertEqual(raw["providers"][0]["key"], "EXAMPLEKEY-123456")
        self.assertNotIn("key", result["providers"][0])
        self.assertNotIn("api_key", result["nested"])
        self.assertNotIn("client-secret", result["nested"])
        self.assertEqual(result["providers"][0]["valid"], True)
        self.assertEqual(result["providers"][0]["key_masked"], "EXAM...3456")

    def test_empty_key_and_short_keys(self):
        result = public_config({"providers": [{"key": "a"}, {"key": ""}]})
        self.assertTrue(result["providers"][0]["has_key"])
        self.assertEqual(result["providers"][0]["key_masked"], "***")
        self.assertFalse(result["providers"][1]["has_key"])


if __name__ == "__main__":
    unittest.main()
