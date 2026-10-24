"""Validation of model output before it is written or counted as a deliverable."""

import json
import time
import unittest

import support
from support import GOOD_OUTPUTS, PipelineCase, fenced, read_status
import swarm_pipeline


def real_test(extra=""):
    return (
        "import unittest\n"
        "from main import example\n\n"
        "class TestExample(unittest.TestCase):\n"
        f"{extra}"
        "    def test_example_returns_one(self):\n"
        "        self.assertEqual(example(), 1)\n"
    )


class GeneratedTests(PipelineCase):
    def assert_rejected(self, source):
        self.new_root()
        self.assertFalse(self.run_swarm({"tests": source}))
        self.assertFalse(self.exists("tests/test_api.py"))
        self.assertTrue(read_status(self.root)["project"]["phase"].startswith("FAILED"))

    def test_tautological_variants_are_rejected(self):
        header = "import unittest\nclass T(unittest.TestCase):\n"
        variants = {
            "assertTrue(True) with spaces": header + "    def test_a(self):\n        self.assertTrue( True )\n",
            "assert True": header + "    def test_a(self):\n        assert True\n",
            "assertEqual of equal literals": header + "    def test_a(self):\n        self.assertEqual(1, 1)\n",
            "assertEqual of equal strings": header + "    def test_a(self):\n        self.assertEqual('a', 'a')\n",
            "assertIsNone(None)": header + "    def test_a(self):\n        self.assertIsNone(None)\n",
            "assertFalse(False)": header + "    def test_a(self):\n        self.assertFalse(False)\n",
            "constant through a variable": header + "    def test_a(self):\n        ok = True\n        self.assertTrue(ok)\n",
            "same name on both sides": header + "    def test_a(self):\n        x = object()\n        self.assertEqual(x, x)\n",
            "assert literal comparison": header + "    def test_a(self):\n        assert 2 + 2 == 4\n",
            "body is pass": header + "    def test_a(self):\n        pass\n",
            "no test methods at all": header + "    def helper(self):\n        self.assertEqual(1, 2)\n",
            "only imports": "import unittest\n",
            "tests are skipped": header + "    @unittest.skip('later')\n    def test_a(self):\n        self.assertEqual(example(), 1)\n",
            "function style tests unittest will not discover": "def test_a():\n    assert example() == 1\n",
        }
        for label, source in variants.items():
            with self.subTest(label):
                self.new_root()
                self.assert_rejected(source)

    def test_real_assertions_are_accepted(self):
        accepted = {
            "plain": real_test(),
            "assertRaises context manager": real_test(
                "    def test_bad(self):\n        with self.assertRaises(TypeError):\n            example(1, 2)\n"),
            "assertRaises call form": real_test(
                "    def test_bad(self):\n        self.assertRaises(TypeError, example, 1)\n"),
        }
        for label, source in accepted.items():
            with self.subTest(label):
                self.new_root()
                self.assertTrue(self.run_swarm({"tests": source}))
                self.assertTrue(self.exists("tests/test_api.py"))

    def test_text_inside_comments_and_strings_is_not_a_tautology(self):
        source = (
            "import unittest\nfrom main import example\n\n"
            "# Never write assertTrue(True): it proves nothing.\n"
            "class TestExample(unittest.TestCase):\n"
            "    \"\"\"Avoid self.assertTrue(True) style checks.\"\"\"\n"
            "    def test_example_returns_one(self):\n"
            "        label = 'assertTrue(True) is banned'\n"
            "        self.assertEqual(example(), 1, label)\n"
        )
        self.assertTrue(self.run_swarm({"tests": source}))
        self.assertTrue(self.exists("tests/test_api.py"))

    def test_one_real_test_among_trivial_ones_is_accepted_and_counted(self):
        source = real_test("    def test_filler(self):\n        self.assertTrue(True)\n")
        self.assertTrue(self.run_swarm({"tests": source}))
        record = json.loads(self.read("specs/swarm-run.json"))
        detail = [v["detail"] for s in record["stages"] if s["id"] == "07_qa" for v in s["validators"]
                  if v["name"] == "generated_tests"][0]
        self.assertIn("2 test", detail)
        self.assertIn("1 with a non-trivial assertion", detail)


class OpenApi(PipelineCase):
    def test_documents_that_are_not_openapi_contracts_are_rejected(self):
        bad = {
            "prose mentioning the key": "Sorry, I cannot produce an openapi: document today.",
            "only the version line": "openapi: 3.0.0\n",
            "commented out version": "# openapi: 3.0.0\ninfo:\n  title: x\n  version: '1'\npaths:\n  /a:\n    get: {}\n",
            "empty paths": "openapi: 3.0.0\ninfo:\n  title: x\n  version: '1'\npaths: {}\n",
            "swagger 2": "openapi: 2.0\ninfo:\n  title: x\n  version: '1'\npaths:\n  /a:\n    get: {}\n",
            "missing info": "openapi: 3.0.0\npaths:\n  /a:\n    get: {}\n",
            "paths without any route": "openapi: 3.0.0\ninfo:\n  title: x\n  version: '1'\npaths:\n  note: nothing\n",
            "unterminated fence": "```yaml\nopenapi: 3.0.0\ninfo:\n  title: x\n  version: '1'\npaths:\n  /a:\n    get: {}\n",
            "duplicate top level key": "openapi: 3.0.0\nopenapi: 3.0.1\ninfo:\n  title: x\n  version: '1'\npaths:\n  /a:\n    get: {}\n",
        }
        for label, document in bad.items():
            with self.subTest(label):
                self.new_root()
                self.assertFalse(self.run_swarm({"openapi": document}))
                self.assertFalse(self.exists("specs/api/openapi.yaml"))

    def test_valid_contracts_are_accepted(self):
        good = {
            "quoted version in a fence": fenced("yaml", GOOD_OUTPUTS["openapi"].replace("3.0.0", '"3.0.3"')),
            "json form": json.dumps({"openapi": "3.0.0", "info": {"title": "x", "version": "1"},
                                     "paths": {"/health": {"get": {}}}}),
            "quoted path keys": "openapi: 3.1.0\ninfo:\n  title: x\n  version: '1'\npaths:\n  '/items':\n    get: {}\n",
        }
        for label, document in good.items():
            with self.subTest(label):
                self.new_root()
                self.assertTrue(self.run_swarm({"openapi": document}))
                self.assertNotIn("```", self.read("specs/api/openapi.yaml"))

    def test_receipt_says_this_is_a_structural_check_not_a_full_yaml_parse(self):
        self.assertTrue(self.run_swarm())
        record = json.loads(self.read("specs/swarm-run.json"))
        details = [v["detail"] for s in record["stages"] for v in s["validators"] if v["name"] == "openapi_structure"]
        self.assertEqual(len(details), 1)
        self.assertIn("not a full YAML parse", details[0])


class DesignTokens(PipelineCase):
    def test_fence_tag_case_and_prose_are_handled(self):
        self.assertTrue(self.run_swarm({"tokens": fenced("JSON", GOOD_OUTPUTS["tokens"])}))
        self.assertEqual(json.loads(self.read("specs/design/tokens.json"))["colors"]["primary"], "#fff")

    def test_byte_order_mark_is_tolerated_and_not_written(self):
        self.assertTrue(self.run_swarm({"tokens": "\ufeff" + GOOD_OUTPUTS["tokens"]}))
        self.assertFalse((self.root / "specs" / "design" / "tokens.json").read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_incomplete_or_non_json_tokens_are_rejected(self):
        bad = {
            "wrong shape": '{"x": 1}',
            "empty colors": '{"colors": {}, "typography": {}, "spacing": {}}',
            "not an object": "[1, 2, 3]",
            "NaN": '{"colors": {"a": NaN}, "typography": {}, "spacing": {}}',
            "truncated fence": '```json\n{"colors": {"primary": "#fff"',
            "prose": "Here are some lovely tokens for you.",
        }
        for label, text in bad.items():
            with self.subTest(label):
                self.new_root()
                self.assertFalse(self.run_swarm({"tokens": text}))
                self.assertFalse(self.exists("specs/design/tokens.json"))


class SourceAndFormats(PipelineCase):
    def test_python_without_any_definition_is_rejected(self):
        for label, source in {"comment only": "# TODO implement later\n", "bare assignment": "x = 1\n",
                              "pass": "pass\n", "return outside function": "return 1\n"}.items():
            with self.subTest(label):
                self.new_root()
                self.assertFalse(self.run_swarm({"backend": source}))
                self.assertFalse(self.exists("backend/src/main.py"))

    def test_non_python_text_with_nul_is_rejected(self):
        self.assertFalse(self.run_swarm({"backend": "def f():\n    return 1\x00"}))

    def test_prose_instead_of_artifacts_is_rejected(self):
        cases = {
            "sql": ("Sorry, I cannot design that schema.", "specs/database/schema.sql"),
            "client": ("Sorry, no UI for you.", "frontend/public/index.html"),
            "docker": ("Sorry, no container for you.", "specs/devops/Dockerfile"),
        }
        for key, (text, path) in cases.items():
            with self.subTest(key):
                self.new_root()
                self.assertFalse(self.run_swarm({key: text}))
                self.assertFalse(self.exists(path))

    def test_truncated_fenced_output_is_rejected_everywhere(self):
        cases = {
            "sql": ("```sql\nCREATE TABLE a (id INTEGER);", "specs/database/schema.sql"),
            "client": ("```html\n<html><body>cut off", "frontend/public/index.html"),
            "docker": ("```dockerfile\nFROM python:3.11-slim", "specs/devops/Dockerfile"),
            "prd": ("# PRD\n\n```python\nprint('cut off')", "specs/prd/user-stories.md"),
        }
        for key, (text, path) in cases.items():
            with self.subTest(key):
                self.new_root()
                self.assertFalse(self.run_swarm({key: text}))
                self.assertFalse(self.exists(path))

    def test_every_stage_accepts_properly_fenced_output(self):
        outputs = {
            "tokens": fenced("json", GOOD_OUTPUTS["tokens"]),
            "sql": fenced("sql", GOOD_OUTPUTS["sql"]),
            "openapi": fenced("yaml", GOOD_OUTPUTS["openapi"]),
            "backend": fenced("python", GOOD_OUTPUTS["backend"]),
            "client": fenced("html", GOOD_OUTPUTS["client"]),
            "tests": fenced("python", GOOD_OUTPUTS["tests"]),
            "docker": fenced("dockerfile", GOOD_OUTPUTS["docker"]),
        }
        self.assertTrue(self.run_swarm(outputs))
        for rel in self.files():
            if rel.endswith((".json", ".sql", ".yaml", ".py", ".html", "Dockerfile", ".md")):
                self.assertNotIn("```", self.read(rel), rel)

    def test_unicode_and_bom_are_written_as_clean_utf8_with_lf(self):
        text = "\ufeff# Caf\u00e9 \u2615 \u65e5\u672c\u8a9e\r\n\r\nline two of a longer requirements document\r\n"
        self.assertTrue(self.run_swarm({"prd": text}))
        data = (self.root / "specs" / "prd" / "user-stories.md").read_bytes()
        self.assertEqual(data, "# Caf\u00e9 \u2615 \u65e5\u672c\u8a9e\n\nline two of a longer requirements document\n".encode("utf-8"))

    def test_oversized_output_is_rejected(self):
        self.assertFalse(self.run_swarm({"prd": "# big\n" + "x" * (3 * 1024 * 1024)}))
        self.assertFalse(self.exists("specs/prd/user-stories.md"))


class AdversarialInput(unittest.TestCase):
    """Model output is untrusted: validators must stay fast on hostile text (no regex blow-up)."""

    LIMIT_SECONDS = 2.0

    def test_validators_run_in_linear_time(self):
        nl = chr(10)
        cases = {
            "sql: unterminated block comments": (swarm_pipeline.validate_sql, "/* " * 40000),
            "sql: line comments": (swarm_pipeline.validate_sql, ("-- x" + nl) * 40000),
            "sql: comment then table": (swarm_pipeline.validate_sql, "/* " * 20000 + "*/ CREATE TABLE t (id INT);"),
            "markdown: punctuation run": (swarm_pipeline.validate_markdown, "# h" + nl + "!" * 100000),
            "openapi: long space run": (swarm_pipeline.validate_openapi, "openapi:" + " " * 100000 + "x"),
            "html: unclosed tags": (swarm_pipeline.validate_html, "<a " * 40000),
            "dockerfile: space run": (swarm_pipeline.validate_dockerfile, "FROM" + " " * 100000),
            "lead: negation run": (swarm_pipeline.validate_lead_verdict, "n't " * 50000),
            "fences: repeated openers": (lambda t: swarm_pipeline.clean_markdown_block(t, "json"), "```json " * 40000),
        }
        for label, (function, text) in cases.items():
            with self.subTest(label):
                started = time.perf_counter()
                function(text)
                self.assertLess(time.perf_counter() - started, self.LIMIT_SECONDS)

    def test_sql_comment_stripping_still_finds_real_tables(self):
        self.assertTrue(swarm_pipeline.validate_sql("-- header" + chr(10) + "/* a */ CREATE TABLE t (id INT);")[0])
        self.assertFalse(swarm_pipeline.validate_sql("/* CREATE TABLE t (id INT); */")[0])
        self.assertFalse(swarm_pipeline.validate_sql("-- CREATE TABLE t (id INT);")[0])
        self.assertFalse(swarm_pipeline.validate_sql("/* never closed CREATE TABLE t (id INT);")[0])


class MarkdownSubstance(PipelineCase):
    REFUSALS = [
        "I'm sorry, I can't help with that request.",
        "Sorry, but I cannot assist with this.",
        "As an AI language model, I am unable to write a PRD.",
        "# Product requirements" + chr(10) + chr(10) + "I'm sorry, I can't help with that request, so there is nothing here to read.",
        "A perfectly long paragraph of prose without any heading, " * 4,
        "# Title only",
    ]
    STAGES = {"prd": "specs/prd/user-stories.md", "adr": "specs/architecture/adr-001.md",
              "flows": "specs/design/screen-flows.md", "qa_matrix": "specs/qa/test-matrix.md",
              "security": "specs/security/audit-report.md"}

    def test_refusals_and_empty_shells_are_rejected_at_every_markdown_stage(self):
        for stage, path in self.STAGES.items():
            for text in self.REFUSALS:
                with self.subTest(stage=stage, text=text[:30]):
                    self.new_root()
                    self.assertFalse(self.run_swarm({stage: text}))
                    self.assertFalse(self.exists(path))

    def test_heading_plus_substance_is_accepted(self):
        text = "# Requirements" + chr(10) + chr(10) + "Users can list, create and delete items from the main screen."
        for stage in self.STAGES:
            with self.subTest(stage=stage):
                self.new_root()
                self.assertTrue(self.run_swarm({stage: text}))

    def test_the_check_is_structural_and_says_so_in_its_receipt(self):
        self.assertTrue(self.run_swarm())
        record = json.loads(self.read("specs/swarm-run.json"))
        details = [v["detail"] for s in record["stages"] for v in s["validators"] if v["name"] == "markdown"]
        self.assertTrue(details)
        self.assertTrue(all("structure only" in d for d in details), details)


class LeadVerdict(unittest.TestCase):
    TOKEN = "[READY FOR INDEPENDENT VERIFICATION]"

    def test_negated_or_unbracketed_verdicts_are_rejected(self):
        rejected = [
            "Not yet READY FOR INDEPENDENT VERIFICATION; tests fail",
            "not" + chr(10) + "ready for independent verification",
            "NOT  READY FOR INDEPENDENT VERIFICATION",
            "Cannot be marked READY FOR INDEPENDENT VERIFICATION",
            "READY FOR INDEPENDENT VERIFICATION",
            "Looks good, ship it.",
            "Approved for production.",
            "[REJECTED - REMEDIATION REQUIRED]",
            "",
            "Verdict: " + self.TOKEN,
            self.TOKEN + " as soon as the schema is fixed",
        ]
        for text in rejected:
            with self.subTest(text=text):
                self.assertFalse(swarm_pipeline.validate_lead_verdict(text)[0])

    def test_token_with_a_contradicting_word_anywhere_is_rejected(self):
        for note in ("However the tests fail.", "Cannot confirm the schema.", "There is no OpenAPI route for delete.",
                     "Security review was rejected earlier.", "It isn't finished.", "Unable to run anything.",
                     "Blocked on the migration."):
            with self.subTest(note=note):
                text = self.TOKEN + chr(10) + note
                self.assertFalse(swarm_pipeline.validate_lead_verdict(text)[0])

    def test_exact_token_on_its_own_line_passes(self):
        for text in (self.TOKEN, self.TOKEN + chr(10) + "Contracts line up with the schema.",
                     "Summary of the review." + chr(10) + "  " + self.TOKEN + "  " + chr(10)):
            with self.subTest(text=text):
                self.assertTrue(swarm_pipeline.validate_lead_verdict(text)[0])

    def test_two_verdict_lines_are_ambiguous(self):
        self.assertFalse(swarm_pipeline.validate_lead_verdict(self.TOKEN + chr(10) + self.TOKEN)[0])


class LeadReview(PipelineCase):
    def test_only_an_explicit_ready_verdict_passes(self):
        for text in ("Looks good, ship it.", "Approved for production.", "NOT READY FOR INDEPENDENT VERIFICATION",
                     "Not yet READY FOR INDEPENDENT VERIFICATION; tests fail",
                     "[REJECTED - REMEDIATION REQUIRED]"):
            with self.subTest(text):
                self.new_root()
                self.assertFalse(self.run_swarm({"lead": text}))

    def test_explicit_ready_verdict_passes_but_stays_unverified(self):
        self.assertTrue(self.run_swarm({"lead": "[READY FOR INDEPENDENT VERIFICATION]" + chr(10) + "Some notes."}))
        self.assertIn("NOT VERIFIED", self.read("specs/signoff.md"))


class CleanMarkdownBlock(unittest.TestCase):
    def test_extracts_the_requested_fence_case_insensitively(self):
        self.assertEqual(swarm_pipeline.clean_markdown_block('x\n```JSON\n{"a": 1}\n```\ny', "json"), '{"a": 1}')
        self.assertEqual(swarm_pipeline.clean_markdown_block('```json\r\n{"a": 1}\r\n```', "json"), '{"a": 1}')

    def test_falls_back_to_an_untagged_or_differently_tagged_fence(self):
        self.assertEqual(swarm_pipeline.clean_markdown_block("```\nSELECT 1;\n```", "sql"), "SELECT 1;")
        self.assertEqual(swarm_pipeline.clean_markdown_block("```py\nx = 1\n```", "python"), "x = 1")

    def test_unterminated_fence_is_returned_with_its_marker_so_validators_can_reject_it(self):
        self.assertIn("```", swarm_pipeline.clean_markdown_block("```sql\nCREATE TABLE a (id INT);", "sql"))


if __name__ == "__main__":
    unittest.main()
