"""Static guards for dashboard/index.html (no browser or JS engine needed).

swarm-status.json, terminal.log and provider model lists are written by agents,
scripts and remote providers, so anything read from them must be escaped before
it is placed in markup.  The page runs on the same origin as /api/command, so
an injected script can reach the command endpoint with the operator's cached
credentials.
"""

import os
import re
import unittest
from pathlib import Path

# TENAGENT_TEST_ROOT points at another checkout (e.g. the parent commit) to
# show these checks fail on the code they were written for.
ROOT = Path(os.environ.get("TENAGENT_TEST_ROOT") or Path(__file__).resolve().parents[1])
INDEX = ROOT / "dashboard" / "index.html"
LOCAL_IDENTIFIERS = {"cardId", "cfg.id", "p.id"}


def source():
    return INDEX.read_text(encoding="utf-8")


class FrontendEscapingTests(unittest.TestCase):
    def test_agent_fields_are_escaped_before_entering_markup(self):
        offenders = []
        for number, line in enumerate(source().splitlines(), 1):
            if "className" in line:  # property assignment, not markup
                continue
            for expression in re.findall(r"\$\{([^}]*)\}", line):
                if re.search(r"\bagent\.\w+", expression) and "escapeHtml(" not in expression \
                        and "escapeHTML(" not in expression and "===" not in expression:
                    offenders.append((number, expression))
        self.assertEqual(offenders, [])

    def test_inline_handlers_only_interpolate_local_identifiers(self):
        offenders = []
        for match in re.finditer(r'\bon[a-z]+="([^"]*)"', source()):
            for expression in re.findall(r"\$\{([^}]*)\}", match.group(1)):
                if expression.strip() not in LOCAL_IDENTIFIERS:
                    offenders.append(expression)
        self.assertEqual(offenders, [])

    def test_model_names_travel_through_a_data_attribute(self):
        text = source()
        self.assertIn("this.dataset.model", text)
        self.assertNotIn("escapeHtml(m)}', event", text)
        self.assertNotIn("escapeHtml(currentModel)}', event", text)

    def test_escape_helper_covers_both_quote_characters(self):
        body = re.search(r"function escapeHtml\(str\) \{(.*?)\n    \}", source(), re.S).group(1)
        self.assertIn("&quot;", body)
        self.assertIn("&#39;", body)


if __name__ == "__main__":
    unittest.main()
