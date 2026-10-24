#!/usr/bin/env python3
"""
TenAgent Multi-Brain Collaborative Swarm Pipeline (v1.0.2)
Coordinates all 10 specialized engineering agents by dynamically distributing
workloads across connected AI provider brains (9Router, Groq, Gemini, DeepSeek, Claude, OpenAI, Ollama).
Enforces contract-first specifications, zero fake progress, honest failure reporting, and code verification.
"""

import os
import sys
import json
import time
import datetime
import threading
import urllib.request
import urllib.error
import re
import tempfile
import ast
import hashlib
import warnings
import uuid
from html.parser import HTMLParser

import council

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
SPECS_DIR = os.path.join(ROOT_DIR, "specs")
LOG_FILE = os.path.join(SPECS_DIR, "terminal.log")
STATUS_FILE = os.path.join(SPECS_DIR, "swarm-status.json")

# A stage that has only *generated* output has not been verified by anything, so
# no progress value written by this pipeline may reach 100.
MAX_UNVERIFIED_PROGRESS = 90
TOTAL_MILESTONES = 10
QUEUED_DETAIL = "Queued for this swarm run."
GENERATED_PROGRESS = MAX_UNVERIFIED_PROGRESS  # per-agent value once a stage has only *generated* output

_PATH_LOCKS = {}
_PATH_LOCKS_GUARD = threading.Lock()
_KNOWN_SECRETS = ()  # replaced, never mutated, so redact() can iterate without a lock
_SECRETS_GUARD = threading.Lock()
_WARNED = set()


def get_timestamp() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def remember_secrets(providers: list):
    """Remember provider keys so that they can be scrubbed from logs and status."""
    global _KNOWN_SECRETS
    keys = {(p.get("key") or "").strip() for p in providers or []}
    with _SECRETS_GUARD:
        _KNOWN_SECRETS = tuple(sorted({k for k in keys if len(k) >= 8} | set(_KNOWN_SECRETS), key=len, reverse=True))


def redact(text: str) -> str:
    text = str(text)
    for secret in _KNOWN_SECRETS:
        text = text.replace(secret, "[REDACTED]")
    return text


_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]+")


def single_line(text) -> str:
    """Collapse newlines and other control characters (including ANSI escapes) to one space,
    so user- or model-controlled text cannot forge log lines or drive the terminal."""
    return _CONTROL_CHARS.sub(" ", str(text))


def status_lock(path: str):
    """In-process lock guarding read-modify-write of one status file."""
    key = os.path.normcase(os.path.abspath(path))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def atomic_write_bytes(path: str, data: bytes):
    """Write via a unique temp file in the same directory, then os.replace."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                # Windows: a reader (e.g. the dashboard) briefly holds the target open.
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(path: str, text: str):
    atomic_write_bytes(path, text.encode("utf-8"))


def log_swarm_message(agent_id: str, message: str, root_dir: str = None):
    target_log = os.path.join(root_dir or ROOT_DIR, "specs", "terminal.log")
    ts = get_timestamp()
    clean_msg = single_line(redact(message)).strip()
    agent_id = single_line(agent_id)
    if not clean_msg:
        return
    log_line = f"[{ts}] [{agent_id}] {clean_msg}\n"

    try:
        print(f"[{agent_id}] {clean_msg}")
        sys.stdout.flush()
    except Exception:
        pass

    try:
        os.makedirs(os.path.dirname(target_log), exist_ok=True)
        with open(target_log, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass


def _mutate_status(root_dir: str, mutate) -> bool:
    """Locked, atomic read-modify-write of specs/swarm-status.json.

    Returns False (and says so in the log, once) when the file is absent or
    unreadable instead of silently pretending the update happened.
    """
    base = root_dir or ROOT_DIR
    target = os.path.join(base, "specs", "swarm-status.json")
    if not os.path.exists(target):
        return False
    with status_lock(target):
        try:
            with open(target, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("status root must be a JSON object")
            mutate(data)
            atomic_write_text(target, json.dumps(data, indent=2))
            return True
        except Exception as exc:
            marker = (os.path.normcase(target), type(exc).__name__)
            if marker not in _WARNED:
                _WARNED.add(marker)
                log_swarm_message(
                    "swarm", f"[WARNING] specs/swarm-status.json not updated ({type(exc).__name__}); "
                    "the dashboard may show stale state.", base)
            return False


def reset_swarm_status(root_dir: str = None) -> bool:
    """Start of a run: drop progress and states inherited from any previous run."""
    def mutate(data):
        project = data.setdefault("project", {})
        project["overallProgress"] = 0
        project["phase"] = "Run starting"
        for agent in data.get("agents", []):
            agent["status"] = "WAITING"
            agent["progress"] = 0
            agent["processDetail"] = QUEUED_DETAIL
    return _mutate_status(root_dir, mutate)


def update_swarm_status(agent_id: str, status: str, process_detail: str, progress: int = None, root_dir: str = None, overall_progress: int = None, phase: str = None) -> bool:
    detail = single_line(redact(process_detail or ""))

    def mutate(data):
        if overall_progress is not None and "project" in data:
            data["project"]["overallProgress"] = max(0, min(MAX_UNVERIFIED_PROGRESS, int(overall_progress)))
        if phase and "project" in data:
            data["project"]["phase"] = single_line(redact(phase))

        for a in data.get("agents", []):
            if a.get("id") == agent_id:
                if status:
                    a["status"] = status
                if detail:
                    a["processDetail"] = detail
                if progress is not None:
                    a["progress"] = max(0, min(MAX_UNVERIFIED_PROGRESS, int(progress)))
                break

        if "logs" not in data:
            data["logs"] = []
        data["logs"].append({
            "timestamp": get_timestamp(),
            "agent": agent_id,
            "message": f"[{agent_id}] {detail[:140]}"
        })
        data["logs"] = data["logs"][-50:]

    return _mutate_status(root_dir, mutate)

def assign_brains_to_agents(providers: list) -> dict:
    if not providers:
        fallback = {
            "id": "native",
            "name": "Native Antigravity Engine",
            "key": "",
            "profile": {"name": "Native Engine", "role": "Full-Stack Specialist", "tag": "native"}
        }
        return {aid: fallback for aid in [
            "01_pm", "02_arch", "03_designer", "04_dba", "05_backend",
            "06_client", "07_qa", "08_security", "09_devops", "10_tech_lead"
        ]}

    fast_brains = [p for p in providers if "groq" in p.get("id", "")]
    deep_brains = [p for p in providers if any(k in p.get("id", "") for k in ("9router", "deepseek", "claude", "anthropic", "openai"))]
    creative_brains = [p for p in providers if any(k in p.get("id", "") for k in ("gemini", "google", "claude"))]
    fallback = providers[0]

    pm_brain = (creative_brains or deep_brains or providers)[0]
    arch_brain = (deep_brains or creative_brains or providers)[0]
    designer_brain = (creative_brains or providers)[-1]
    dba_brain = (deep_brains or providers)[0]
    backend_brain = (deep_brains or providers)[0]
    client_brain = (creative_brains or deep_brains or providers)[-1]
    qa_brain = (fast_brains or providers)[0]
    sec_brain = (fast_brains or deep_brains or providers)[-1]
    devops_brain = (deep_brains or providers)[-1]
    lead_brain = (deep_brains or creative_brains or providers)[0]

    return {
        "01_pm": pm_brain,
        "02_arch": arch_brain,
        "03_designer": designer_brain,
        "04_dba": dba_brain,
        "05_backend": backend_brain,
        "06_client": client_brain,
        "07_qa": qa_brain,
        "08_security": sec_brain,
        "09_devops": devops_brain,
        "10_tech_lead": lead_brain
    }

# ---------------------------------------------------------------------------
# Output validation
#
# Every validator returns (ok, detail). Nothing here executes model output:
# Python is only parsed (ast.parse / compile to a code object, never run), SQL
# and YAML are only scanned, HTML is only tokenised.
# ---------------------------------------------------------------------------
_FENCE_LINE = re.compile(r"^[ \t]*```", re.M)
_REQUIRED_TOKEN_KEYS = ("colors", "typography", "spacing")
_ASSERT_SELF_COMPARING = {"assertEqual", "assertIs", "assertIn", "assertCountEqual", "assertListEqual",
                          "assertDictEqual", "assertSequenceEqual", "assertTupleEqual", "assertSetEqual",
                          "assertGreaterEqual", "assertLessEqual", "assertAlmostEqual"}


def clean_markdown_block(text: str, code_fence: str = None) -> str:
    """Return the body of the first fenced block (tag matched case-insensitively), else the text.

    An unterminated fence is returned untouched, marker included, so that the
    validators (which reject any leftover ```) can flag the truncated output.
    """
    cleaned = (text or "").strip()
    if code_fence:
        match = re.search(r"```[ \t]*" + re.escape(code_fence) + r"[ \t]*\r?\n?(.*?)```", cleaned, re.S | re.I)
        if not match:
            match = re.search(r"```[^\n`]*\r?\n(.*?)```", cleaned, re.S)
        if match:
            cleaned = match.group(1).strip()
    return cleaned


def normalize_model_text(text: str) -> str:
    """Strip byte-order marks and normalise line endings to LF."""
    return text.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")


def _text_problem(text: str, allow_fences: bool = False):
    if not text or not text.strip():
        return "empty output"
    if "\x00" in text:
        return "contains NUL characters"
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return "contains characters that are not valid UTF-8 text (lone surrogate)"
    if not allow_fences and "```" in text:
        return "contains a leftover code fence (unterminated or nested block, likely truncated output)"
    return None


MIN_MARKDOWN_CHARS = 40
_HEADING_LINE = re.compile(r"^ {0,3}#{1,6}[ \t]+\S", re.M)
_REFUSAL_OPENING = re.compile(
    r"^\W*(?:i(?:'m| am)\s+(?:sorry|unable|not able)|sorry\b|i\s+can(?:'t|not)\b|i\s+won't\b|"
    r"as an ai\b|unfortunately,?\s+i\b)", re.I)


def validate_markdown(text: str) -> tuple:
    """Structure only: no NUL or lone surrogates, balanced code fences, at least one markdown
    heading, a minimum amount of text, and a first paragraph that is not an obvious refusal.

    It cannot tell whether the document is correct, complete or relevant: a well-formed
    document that is wrong passes, and so does a refusal phrased in words the pattern
    does not know. A person (or a later review) has to read the content.
    """
    problem = _text_problem(text, allow_fences=True)
    if problem:
        return False, problem
    if len(_FENCE_LINE.findall(text)) % 2:
        return False, "odd number of code fences (likely truncated output)"
    if not _HEADING_LINE.search(text):
        return False, "no markdown heading"
    substance = len("".join(text.split()))
    if substance < MIN_MARKDOWN_CHARS:
        return False, f"only {substance} non-blank characters (minimum {MIN_MARKDOWN_CHARS})"
    for line in text.splitlines():
        if line.strip() and not _HEADING_LINE.match(line):
            if _REFUSAL_OPENING.match(line.strip()):
                return False, "text opens like a refusal"
            break
    return True, f"{len(text)} characters; structure only, content not judged"


def _reject_constant(name):
    raise ValueError(f"non-finite number {name} is not valid JSON")


def validate_design_tokens(text: str) -> tuple:
    problem = _text_problem(text)
    if problem:
        return False, problem
    try:
        doc = json.loads(text, parse_constant=_reject_constant)
    except ValueError as exc:
        return False, f"not valid JSON: {exc}"
    if not isinstance(doc, dict):
        return False, "top level must be a JSON object"
    missing = [k for k in _REQUIRED_TOKEN_KEYS if k not in doc]
    if missing:
        return False, "missing required keys: " + ", ".join(missing)
    if not isinstance(doc["colors"], dict) or not doc["colors"]:
        return False, "colors must be a non-empty object"
    return True, "JSON object with colors, typography, spacing"


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    return value


def _yaml_top_level(text: str):
    """Minimal scan of a block-style YAML mapping: top-level keys, inline values, child lines.

    Not a YAML parser. Returns (keys, error) where keys maps name -> {"value", "children"}.
    """
    keys = {}
    current = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line.strip() in ("---", "..."):
            continue
        if line[0] in " \t":
            if current is not None:
                keys[current]["children"].append(line)
            continue
        match = re.match(r"""^("[^"]+"|'[^']+'|[A-Za-z_][\w.\-]*)\s*:(?:\s+(.*?))?\s*$""", line)
        if not match:
            return None, f"line is not a top-level mapping entry: {line[:60]!r}"
        name = _unquote(match.group(1))
        if name in keys:
            return None, f"duplicate top-level key {name!r}"
        value = (match.group(2) or "").split(" #")[0].strip()
        keys[name] = {"value": value, "children": []}
        current = name
    return keys, None


def validate_openapi(text: str) -> tuple:
    """Structural check of an OpenAPI 3.x document (JSON, or block-style YAML).

    The YAML path is a structural scan of top-level keys, NOT a full YAML parse:
    the standard library has no YAML parser and this project adds no dependency.
    """
    problem = _text_problem(text)
    if problem:
        return False, problem
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            doc = json.loads(stripped, parse_constant=_reject_constant)
        except ValueError as exc:
            return False, f"not valid JSON: {exc}"
        if not isinstance(doc, dict):
            return False, "top level must be an object"
        version = str(doc.get("openapi", ""))
        info = doc.get("info")
        paths = doc.get("paths")
        has_info = isinstance(info, dict) and bool(info.get("title")) and bool(info.get("version"))
        has_routes = isinstance(paths, dict) and any(isinstance(k, str) and k.startswith("/") for k in paths)
        method = "JSON parse"
    else:
        keys, error = _yaml_top_level(text)
        if error:
            return False, error
        version = _unquote(keys.get("openapi", {}).get("value", ""))
        info_children = keys.get("info", {}).get("children", [])
        has_info = (any(re.match(r"\s+title\s*:", c) for c in info_children)
                    and any(re.match(r"\s+version\s*:", c) for c in info_children))
        path_children = keys.get("paths", {}).get("children", [])
        has_routes = any(re.match(r"""\s+["']?/""", c) for c in path_children) or bool(
            re.search(r"""[{,]\s*["']?/""", keys.get("paths", {}).get("value", "")))
        method = "structural scan of top-level keys, not a full YAML parse"
    if not re.fullmatch(r"3\.\d+(\.\d+)?", version):
        return False, f"'openapi' must be a 3.x version string (found {version!r})"
    if not has_info:
        return False, "'info' needs a title and a version"
    if not has_routes:
        return False, "'paths' defines no routes"
    return True, f"OpenAPI {version} with info and routes ({method})"


def _strip_sql_comments(text: str) -> str:
    """Remove -- line comments and /* block */ comments in a single linear pass.

    An unterminated block comment swallows the rest of the text. (A lazy regex for block
    comments is quadratic on input like repeated "/* ".) String literals are not
    parsed: this is a scan, not an SQL parser.
    """
    out, i, n = [], 0, len(text)
    while i < n:
        block, line = text.find("/*", i), text.find("--", i)
        if block == -1 and line == -1:
            out.append(text[i:])
            break
        if line != -1 and (block == -1 or line < block):
            out.append(text[i:line])
            end = text.find("\n", line)
            i = n if end == -1 else end
        else:
            out.append(text[i:block])
            end = text.find("*/", block + 2)
            i = n if end == -1 else end + 2
        out.append(" ")
    return "".join(out)


def validate_sql(text: str) -> tuple:
    problem = _text_problem(text)
    if problem:
        return False, problem
    no_comments = _strip_sql_comments(text)
    if not re.search(r"\bCREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\b", no_comments, re.I):
        return False, "no CREATE TABLE statement"
    return True, "contains CREATE TABLE (SQL is not parsed or executed)"


class _TagCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = 0

    def handle_starttag(self, tag, attrs):
        self.tags += 1


def validate_html(text: str) -> tuple:
    problem = _text_problem(text)
    if problem:
        return False, problem
    counter = _TagCounter()
    counter.feed(text)
    if not counter.tags:
        return False, "no HTML elements"
    return True, f"{counter.tags} HTML elements"


def validate_dockerfile(text: str) -> tuple:
    problem = _text_problem(text)
    if problem:
        return False, problem
    instructions = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if not instructions or not re.match(r"(?i)(FROM|ARG)\s+\S", instructions[0]):
        return False, "first instruction must be FROM (or ARG)"
    if not any(re.match(r"(?i)FROM\s+\S", ln) for ln in instructions):
        return False, "no FROM instruction"
    return True, f"{len(instructions)} instructions (Dockerfile is not built)"


LEAD_READY_TOKEN = "[READY FOR INDEPENDENT VERIFICATION]"
_NEGATION = re.compile(
    r"\b(?:not|no|never|none|cannot|can't|cant|unable|without|missing|incomplete|invalid|"
    r"fail\w*|reject\w*|block\w*|den(?:y|ied|ies)|refus\w*)\b|n't\b", re.I)


def validate_lead_verdict(text: str) -> tuple:
    """Fail closed. The review passes only if the exact token stands alone on one line and
    nothing else in the text contains a rejection or negation word."""
    lines = text.replace("\u2019", "'").splitlines()
    verdicts = [i for i, line in enumerate(lines) if line.strip() == LEAD_READY_TOKEN]
    if len(verdicts) != 1:
        return False, f"expected exactly one line holding {LEAD_READY_TOKEN} (found {len(verdicts)})"
    rest = "\n".join(line for i, line in enumerate(lines) if i != verdicts[0])
    word = _NEGATION.search(rest)
    if word:
        return False, f"review text contains a rejection or negation ({word.group(0)!r}); defaulting to rejection"
    return True, "model opinion only; not evidence"


def validate_python_source(text: str, require_definitions: bool = False) -> tuple:
    """Parse (never run) generated Python."""
    problem = _text_problem(text)
    if problem:
        return False, problem
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # e.g. invalid escape sequences: noise, not a finding
            tree = ast.parse(text, "generated")
            compile(tree, "generated", "exec")
    except (SyntaxError, ValueError, RecursionError, MemoryError, OverflowError) as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"
    if require_definitions and not any(
            isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) for n in tree.body):
        return False, "defines no function or class"
    return True, "parses; not executed"


def _decorated_as_skipped(node) -> bool:
    for dec in node.decorator_list:
        label = ast.dump(dec).lower()
        if "skip" in label or "expectedfailure" in label:
            return True
    return False


def _literal_only(node, constants) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id not in constants:
            return False
        if isinstance(n, (ast.Call, ast.Attribute, ast.Subscript, ast.Await, ast.Yield, ast.YieldFrom,
                          ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.NamedExpr)):
            return False
    return True


def _plain_reference(node) -> bool:
    return all(isinstance(n, (ast.Name, ast.Attribute, ast.Load)) for n in ast.walk(node))


def _local_constants(func) -> set:
    """Names bound exactly once, to a literal expression, directly in the function body."""
    counts, literal = {}, {}
    for n in ast.walk(func):
        targets = []
        if isinstance(n, ast.Assign):
            targets = [t for t in n.targets if isinstance(t, ast.Name)]
            for t in targets:
                literal[t.id] = n.value
        elif isinstance(n, (ast.AugAssign, ast.AnnAssign, ast.For, ast.AsyncFor)):
            targets = [t for t in ast.walk(n.target) if isinstance(t, ast.Name)]
            for t in targets:
                literal[t.id] = None
        elif isinstance(n, ast.withitem) and n.optional_vars is not None:
            targets = [t for t in ast.walk(n.optional_vars) if isinstance(t, ast.Name)]
            for t in targets:
                literal[t.id] = None
        for t in targets:
            counts[t.id] = counts.get(t.id, 0) + 1
    constants = set()
    for _ in range(3):  # allow a = 1; b = a
        for name, value in literal.items():
            if counts.get(name) == 1 and value is not None and _literal_only(value, constants | {name}) \
                    and not any(isinstance(x, ast.Name) and x.id == name for x in ast.walk(value)):
                constants.add(name)
    return constants


def _is_trivial_assertion(call, constants) -> bool:
    name = call.func.attr
    args = list(call.args)
    if name.startswith(("assertRaises", "assertWarns")):
        return len(args) < 2 or _literal_only(args[1], constants)
    if not args:
        return True
    if all(_literal_only(a, constants) for a in args):
        return True
    if name in _ASSERT_SELF_COMPARING and len(args) >= 2 and ast.dump(args[0]) == ast.dump(args[1]) \
            and _plain_reference(args[0]):
        return True
    return False


def _has_real_assertion(func) -> bool:
    constants = _local_constants(func)
    for n in ast.walk(func):
        if isinstance(n, ast.Assert):
            test = n.test
            if _literal_only(test, constants):
                continue
            if isinstance(test, ast.Compare) and len(test.comparators) == 1 \
                    and ast.dump(test.left) == ast.dump(test.comparators[0]) and _plain_reference(test.left):
                continue
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith("assert"):
            if not _is_trivial_assertion(n, constants):
                return True
        if isinstance(n, ast.With):
            for item in n.items:
                ctx = item.context_expr
                if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute) \
                        and ctx.func.attr.startswith(("assertRaises", "assertWarns", "assertLogs")):
                    if any(isinstance(x, ast.Call) for stmt in n.body for x in ast.walk(stmt)):
                        return True
    return False


def validate_generated_tests(text: str) -> tuple:
    """Reject test files that cannot fail: no unittest tests, or only constant assertions.

    Judged on the syntax tree, so text inside comments or strings is irrelevant.
    A test counts only if it sits in a unittest.TestCase subclass, is not
    decorated skip/expectedFailure, and holds at least one assertion that depends
    on something other than literals. It is a heuristic: it cannot prove that a
    test exercises the generated backend, only that it is not vacuous.
    """
    ok, detail = validate_python_source(text)
    if not ok:
        return False, detail
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tree = ast.parse(text, "generated-tests")
    total = real = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or _decorated_as_skipped(node):
            continue
        is_testcase = any(
            (isinstance(b, ast.Name) and b.id.endswith("TestCase"))
            or (isinstance(b, ast.Attribute) and b.attr.endswith("TestCase"))
            for b in node.bases)
        if not is_testcase:
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test") \
                    and not _decorated_as_skipped(item):
                total += 1
                if _has_real_assertion(item):
                    real += 1
    summary = f"{total} test(s) found, {real} with a non-trivial assertion"
    if total == 0:
        return False, "no unittest test methods found (empty discovery); " + summary
    if real == 0:
        return False, "every test is vacuous or skipped; " + summary
    return True, summary


def safe_call_brain(brain: dict, system_prompt: str, user_prompt: str, fallback_brains: list = None, base_dir: str = None) -> tuple:
    """
    Calls assigned AI brain with fallback chain.
    Returns (content_str, success_bool).
    If all brains fail, returns ('', False) to allow honest failure handling (Fail Loudly).
    """
    if brain.get("id") == "native":
        return "", False

    try:
        res = council.call_llm(brain, system_prompt, user_prompt, timeout=75)
        if res and res.strip():
            return res.strip(), True
    except Exception as e:
        log_swarm_message("swarm", f"Notice: [{brain['name']}] latency ({redact(str(e))[:45]}). Engaging backup brain...", base_dir)

    if fallback_brains:
        for fb in fallback_brains:
            if fb.get("id") != brain.get("id") and fb.get("id") != "native":
                try:
                    res = council.call_llm(fb, system_prompt, user_prompt, timeout=60)
                    if res and res.strip():
                        log_swarm_message("swarm", f"Assisted by backup brain: [{fb['name']}]", base_dir)
                        return res.strip(), True
                except Exception:
                    continue

    return "", False

# ---------------------------------------------------------------------------
# Run lifecycle
#
# NOT_STARTED -> RUNNING -> AWAITING_VERIFICATION | FAILED
# NOT_STARTED -> BLOCKED            (another run is active)
# AWAITING_VERIFICATION -> VERIFIED | FAILED   (reserved for an independent
#                                   verifier; nothing in this module can reach VERIFIED)
# FAILED / BLOCKED / VERIFIED are terminal. (An interrupt such as Ctrl-C ends the run as FAILED.)
# ---------------------------------------------------------------------------
NOT_STARTED = "NOT_STARTED"
RUNNING = "RUNNING"
AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
VERIFIED = "VERIFIED"
FAILED = "FAILED"
BLOCKED = "BLOCKED"

LEGAL_TRANSITIONS = {
    NOT_STARTED: {RUNNING, BLOCKED},
    RUNNING: {AWAITING_VERIFICATION, FAILED},
    AWAITING_VERIFICATION: {VERIFIED, FAILED},
    VERIFIED: set(),
    FAILED: set(),
    BLOCKED: set(),
}

RUN_FILE = "swarm-run.json"
LOCK_FILE = ".swarm-run.lock"
LOCK_STALE_SECONDS = 2 * 60 * 60
# Checked between model calls (a call blocked inside a socket cannot be interrupted from here;
# council.call_llm applies its own per-request timeout).
MAX_RUN_SECONDS = 45 * 60
PIPELINE_AGENTS = (
    "01_pm", "02_arch", "03_designer", "04_dba", "05_backend",
    "06_client", "07_qa", "08_security", "09_devops", "10_tech_lead",
)



class IllegalTransition(RuntimeError):
    pass


class StageFailure(Exception):
    """A stage could not produce a valid deliverable; the run must stop."""

    def __init__(self, agent_id: str, message: str, detail: str, phase: str):
        super().__init__(message)
        self.agent_id = agent_id
        self.message = message
        self.detail = detail
        self.phase = phase


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8", errors="replace")
    return hashlib.sha256(data).hexdigest()


# The only paths the pipeline may write. Model output never chooses a path.
ARTIFACT_PATHS = frozenset({
    "specs/prd/user-stories.md",
    "specs/architecture/adr-001.md",
    "specs/design/tokens.json",
    "specs/design/screen-flows.md",
    "specs/database/schema.sql",
    "specs/api/openapi.yaml",
    "backend/src/main.py",
    "frontend/public/index.html",
    "specs/qa/test-matrix.md",
    "tests/test_api.py",
    "specs/security/audit-report.md",
    "specs/devops/Dockerfile",
    "specs/devops/ci.yml",
    "specs/signoff.md",
    "specs/signoff.rejected.md",
})
# Artifacts that read as a gate/approval: never left behind by an earlier run.
GATE_ARTIFACTS = ("specs/signoff.md", "specs/signoff.rejected.md")
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}


class ArtifactPathError(ValueError):
    pass


class ArtifactConflict(RuntimeError):
    pass


def safe_artifact_path(base_dir: str, rel_path: str) -> str:
    """Canonical absolute path for a project-relative artifact, or ArtifactPathError.

    Rejects absolute, drive-letter, UNC, traversal, alternate-stream, reserved
    device and trailing-dot/space names, and anything whose real path (after
    resolving symlinks/junctions) leaves the project directory.
    """
    if not isinstance(rel_path, str) or not rel_path:
        raise ArtifactPathError("empty artifact path")
    if rel_path.startswith(("/", "\\")):
        raise ArtifactPathError(f"absolute or UNC path not allowed: {rel_path!r}")
    parts = re.split(r"[\\/]", rel_path)
    for part in parts:
        if part in ("", ".", ".."):
            raise ArtifactPathError(f"empty or traversal component in {rel_path!r}")
        if ":" in part or any(ord(ch) < 32 for ch in part):
            raise ArtifactPathError(f"drive, stream or control character in {rel_path!r}")
        if part != part.rstrip(" ."):
            raise ArtifactPathError(f"trailing dot or space in {rel_path!r}")
        if part.split(".")[0].lower() in _WINDOWS_RESERVED:
            raise ArtifactPathError(f"reserved device name in {rel_path!r}")
    root = os.path.realpath(base_dir)
    full = os.path.realpath(os.path.join(root, *parts))
    try:
        inside = os.path.commonpath([root, full]) == root
    except ValueError:  # different drives
        inside = False
    if not inside:
        raise ArtifactPathError(f"{rel_path!r} resolves outside the project directory")
    return full


def _check_not_clobbering(full: str, rel_path: str, owned: dict, new_sha: str = None):
    if not os.path.lexists(full):
        return
    if os.path.islink(full) or not os.path.isfile(full):
        raise ArtifactConflict(f"{rel_path} exists and is not a regular file")
    try:
        with open(full, "rb") as f:
            current = _sha256(f.read())
    except OSError as exc:  # e.g. held open by another process on Windows
        raise ArtifactConflict(f"{rel_path} exists but cannot be read ({type(exc).__name__}); not overwriting it")
    if current == new_sha or current in (owned or {}).get(rel_path, ()):
        return
    raise ArtifactConflict(
        f"{rel_path} already exists and was not written by this pipeline (or was edited since); refusing to overwrite it")


def write_artifact(base_dir: str, rel_path: str, text: str, owned: dict = None) -> dict:
    """Atomically write one deliverable and return its receipt (path, sha256, bytes)."""
    if rel_path not in ARTIFACT_PATHS:
        raise ArtifactPathError(f"not a pipeline deliverable: {rel_path!r}")
    full = safe_artifact_path(base_dir, rel_path)
    data = text.encode("utf-8")  # a lone surrogate raises here, before any file is touched
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactPathError(f"{rel_path} would be {len(data)} bytes (limit {MAX_ARTIFACT_BYTES})")
    sha = _sha256(data)
    _check_not_clobbering(full, rel_path, owned, sha)
    atomic_write_bytes(full, data)
    return {"path": rel_path, "sha256": sha, "bytes": len(data)}


class RunRecord:
    """State machine plus per-stage receipts for one pipeline run.

    The record is persisted to specs/swarm-run.json (no secrets: provider id and
    name only) and is the authoritative answer to "what happened", not the
    dashboard status file.
    """

    def __init__(self, base_dir: str, goal: str):
        self.base_dir = base_dir
        self.path = os.path.join(base_dir, "specs", RUN_FILE)
        self.lock_path = os.path.join(base_dir, "specs", LOCK_FILE)
        self.persisting = False
        self._locked = False
        self.milestones = 0
        self.current_agent = None
        self._deadline = None
        self.owned = {}  # rel path -> sha256 values this pipeline has written (may be overwritten)
        self.data = {
            "schema": 1,
            "run_id": uuid.uuid4().hex,
            "goal_sha256": _sha256(goal),
            "goal_chars": len(goal),
            "state": NOT_STARTED,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "stages": [],
            "retired": [],
            "owned": self.owned,
            "verification": {"tests": "NOT_RUN", "security_scan": "NOT_RUN", "build": "NOT_RUN", "ci": "NOT_RUN"},
        }

    # -- persistence / locking -------------------------------------------------
    def persist(self):
        if self.persisting:
            atomic_write_text(self.path, json.dumps(self.data, indent=2))

    def _lock_owner(self):
        """run_id recorded in the lock file, or None if it is missing or unreadable."""
        try:
            with open(self.lock_path, "r", encoding="utf-8") as f:
                return json.load(f).get("run_id")
        except (OSError, ValueError, AttributeError):
            return None

    def _claim_stale_lock(self) -> bool:
        """Atomically move an apparently stale lock aside, then re-check it before discarding.

        Only one contender can win the rename. If the moved file turns out to be fresh (the
        holder replaced the stale lock after we looked), put it back and report failure.
        """
        graveyard = f"{self.lock_path}.{uuid.uuid4().hex}.stale"
        try:
            os.replace(self.lock_path, graveyard)
        except OSError:
            return False
        try:
            age = time.time() - os.path.getmtime(graveyard)
        except OSError:
            age = 0
        if age <= LOCK_STALE_SECONDS:
            try:
                os.link(graveyard, self.lock_path)  # fails if somebody already created a new lock
            except OSError:
                pass
            claimed = False
        else:
            claimed = True
        try:
            os.unlink(graveyard)
        except OSError:
            pass
        return claimed

    def acquire_lock(self) -> bool:
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                try:
                    age = time.time() - os.path.getmtime(self.lock_path)
                except OSError:
                    continue
                if age <= LOCK_STALE_SECONDS or not self._claim_stale_lock():
                    return False
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "run_id": self.data["run_id"], "started_at": _utc_now()}, f)
            self._locked = True
            self.persisting = True
            return True
        return False

    def release_lock(self):
        if not self._locked:
            return
        if self._lock_owner() == self.data["run_id"]:  # never delete a lock that is now somebody else's
            try:
                os.unlink(self.lock_path)
            except OSError:
                pass
        self._locked = False

    # -- state machine -------------------------------------------------------
    @property
    def state(self) -> str:
        return self.data["state"]

    def transition(self, new_state: str, error: str = None):
        if new_state not in LEGAL_TRANSITIONS.get(self.state, set()):
            raise IllegalTransition(f"{self.state} -> {new_state}")
        self.data["state"] = new_state
        if new_state == RUNNING:
            self.data["started_at"] = _utc_now()
            self._deadline = time.monotonic() + MAX_RUN_SECONDS
        if not LEGAL_TRANSITIONS[new_state] or new_state == AWAITING_VERIFICATION:
            self.data["finished_at"] = _utc_now()
        if error:
            self.data["error"] = redact(error)[:300]
        self.persist()

    def check_deadline(self):
        if self._deadline is not None and time.monotonic() > self._deadline:
            raise StageFailure(self.current_agent or PIPELINE_AGENTS[0],
                               f"Run exceeded its {MAX_RUN_SECONDS}s wall-clock budget.",
                               "Run timed out.", "FAILED: TIMEOUT")

    # -- stage receipts --------------------------------------------------------
    def _stage(self, stage_id: str) -> dict:
        for stage in self.data["stages"]:
            if stage["id"] == stage_id:
                return stage
        stage = {
            "id": stage_id, "state": "PENDING", "started_at": None, "finished_at": None,
            "model_calls": [], "artifacts": [], "validators": [], "error": None,
        }
        self.data["stages"].append(stage)
        return stage

    def begin_stage(self, stage_id: str):
        self.check_deadline()
        stage = self._stage(stage_id)
        stage["state"] = "RUNNING"
        stage["started_at"] = _utc_now()
        self.current_agent = stage_id
        self.persist()

    def finish_stage(self, stage_id: str):
        stage = self._stage(stage_id)
        stage["state"] = "GENERATED"
        stage["finished_at"] = _utc_now()
        self.milestones += 1
        self.persist()

    def fail_stage(self, stage_id: str, message: str):
        stage = self._stage(stage_id)
        stage["state"] = "FAILED"
        stage["finished_at"] = _utc_now()
        stage["error"] = redact(message)[:300]

    def call_model(self, stage_id: str, purpose: str, brain: dict, system_prompt: str,
                   user_prompt: str, providers: list) -> tuple:
        """safe_call_brain plus a secret-free receipt of the call."""
        self.check_deadline()
        content, ok = safe_call_brain(brain, system_prompt, user_prompt, providers, self.base_dir)
        if isinstance(content, str):
            content = normalize_model_text(content).strip()
        self._stage(stage_id)["model_calls"].append({
            "purpose": purpose,
            "assigned_provider": brain.get("id"),
            "assigned_name": brain.get("name"),
            "ok": bool(ok and content and content.strip()),
            "input_sha256": _sha256(system_prompt + "\n---\n" + user_prompt),
            "output_sha256": _sha256(content) if content else None,
        })
        self.persist()
        self.check_deadline()
        return content, ok

    def validated(self, stage_id: str, name: str, ok: bool, detail: str = ""):
        self._stage(stage_id)["validators"].append(
            {"name": name, "result": "PASS" if ok else "FAIL", "detail": redact(detail)[:200]})

    def require(self, stage_id: str, name: str, result: tuple, message: str, detail: str, phase: str):
        """Record a validator result; a failed validator stops the run."""
        ok, why = result
        self.validated(stage_id, name, ok, why)
        if not ok:
            raise StageFailure(stage_id, f"{message}: {why}", detail, phase)

    def write(self, stage_id: str, rel_path: str, text: str):
        try:
            receipt = write_artifact(self.base_dir, rel_path, text, self.owned)
        except (ArtifactConflict, ArtifactPathError) as exc:
            raise StageFailure(stage_id, f"Refusing to write {rel_path}: {exc}",
                               "Output path blocked.", "FAILED: ARTIFACT_BLOCKED")
        except UnicodeEncodeError as exc:
            raise StageFailure(stage_id, f"Model output for {rel_path} is not valid UTF-8 text: {exc.reason}",
                               "Model output was not valid text.", "FAILED: INVALID_OUTPUT")
        self._stage(stage_id)["artifacts"].append(receipt)
        shas = self.owned.setdefault(rel_path, [])
        if receipt["sha256"] not in shas:
            shas.append(receipt["sha256"])
            del shas[:-10]
        self.persist()
        return receipt

    # -- start-of-run checks -------------------------------------------------
    def load_prior(self):
        """Adopt the ownership lineage of the previous run's record, if readable."""
        try:
            with open(self.path, "r", encoding="utf-8-sig") as f:
                prior = json.load(f)
            for rel, shas in (prior.get("owned") or {}).items():
                if isinstance(rel, str) and isinstance(shas, list):
                    self.owned[rel] = [x for x in shas if isinstance(x, str)][-10:]
        except (OSError, ValueError, AttributeError):
            pass

    def preflight(self) -> list:
        """Problems that would make a deliverable unwritable. Checked before any model call."""
        problems = []
        for rel in sorted(ARTIFACT_PATHS):
            try:
                _check_not_clobbering(safe_artifact_path(self.base_dir, rel), rel, self.owned)
            except (ArtifactConflict, ArtifactPathError, OSError) as exc:
                problems.append(f"{rel}: {exc}")
        return problems

    def retire_stale_gates(self):
        """Remove gate artifacts (sign-off) that an earlier run of this pipeline wrote."""
        for rel in GATE_ARTIFACTS:
            full = safe_artifact_path(self.base_dir, rel)
            try:
                with open(full, "rb") as f:
                    current = _sha256(f.read())
            except OSError:
                continue
            if current in self.owned.get(rel, ()):
                os.unlink(full)
                self.data["retired"].append(rel)
        self.persist()


def compute_progress(milestones: int) -> int:
    # Generation alone cannot satisfy the downstream verification/release gates.
    return min(MAX_UNVERIFIED_PROGRESS, int((milestones / TOTAL_MILESTONES) * MAX_UNVERIFIED_PROGRESS))


def _finish_unsuccessfully(run: RunRecord, agent_id: str, message: str, detail: str, phase: str):
    """Record a FAILED outcome everywhere a consumer might look. Never raises."""
    base_dir = run.base_dir
    agent_id = agent_id or run.current_agent or PIPELINE_AGENTS[0]
    try:
        log_swarm_message(agent_id, f"[FATAL ERROR] {message}", base_dir)
        run.fail_stage(agent_id, message)

        def release_queued(data):
            for agent in data.get("agents", []):
                if agent.get("status") == "WAITING" and agent.get("processDetail") == QUEUED_DETAIL:
                    agent["status"] = "IDLE"
                    agent["processDetail"] = "Not run: the swarm run stopped before this stage."
        _mutate_status(base_dir, release_queued)
        update_swarm_status(
            agent_id, "ERROR", detail, 0, base_dir,
            overall_progress=compute_progress(run.milestones), phase=phase)
        run.transition(FAILED, error=message)
    except Exception as exc:  # pragma: no cover - last-resort guard
        log_swarm_message("swarm", f"[WARNING] could not record the FAILED outcome: {type(exc).__name__}", base_dir)


def _run_stages(run: RunRecord, goal: str):
    """Runs the ten generation stages. Raises StageFailure; returns normally on success."""
    base_dir = run.base_dir
    providers = council.get_active_providers(base_dir)
    remember_secrets(providers)
    reset_swarm_status(base_dir)
    brains = assign_brains_to_agents(providers)

    if not providers:
        raise StageFailure("01_pm", "No active AI provider; no engineering stages executed.",
                           "No AI provider available.", "FAILED: NO_PROVIDER")

    log_swarm_message("swarm", f"=== Multi-Brain Collaborative Swarm Activated for: '{goal[:60]}...' ===", base_dir)
    log_swarm_message("swarm", f"Active Brains: {', '.join(p['name'] for p in providers)}", base_dir)
    log_swarm_message("swarm", f"Assignments: PM->{brains['01_pm']['name']} | Arch->{brains['02_arch']['name']} | Design->{brains['03_designer']['name']} | DBA->{brains['04_dba']['name']} | Backend->{brains['05_backend']['name']} | Client->{brains['06_client']['name']} | QA->{brains['07_qa']['name']} | Sec->{brains['08_security']['name']} | DevOps->{brains['09_devops']['name']} | Lead->{brains['10_tech_lead']['name']}", base_dir)

    def done(stage_id, agent_msg):
        run.finish_stage(stage_id)
        update_swarm_status(stage_id, "REVIEWING", agent_msg, GENERATED_PROGRESS, base_dir,
                            overall_progress=compute_progress(run.milestones))
        time.sleep(0.5)

    # -------------------------------------------------------------
    # PRE-FLIGHT MULTI-AI COUNCIL DEBATE (If 2+ Providers Connected)
    # -------------------------------------------------------------
    debate_context = ""
    if len(providers) >= 2:
        run.check_deadline()
        log_swarm_message("swarm", f"Engaging pre-flight debate between {len(providers)} active brains...", base_dir)
        update_swarm_status("10_tech_lead", "WORKING", f"Synthesizing multi-model council debate on '{goal[:35]}...'", 20, base_dir, phase="Phase 0: Multi-AI Council Debate")
        debate_res = council.run_council_debate(f"Architecture, Race Conditions, and Edge Cases for: {goal}", base_dir)
        if debate_res and debate_res.get("consensus"):
            debate_context = f"\n\n## Multi-AI Council Pre-Flight Debate Consensus:\n{debate_res['consensus']}\n"
            log_swarm_message("10_tech_lead", "Council consensus established and fed into PRD/Architecture pipelines.", base_dir)
        elif debate_res and debate_res.get("status") == "failed":
            log_swarm_message("10_tech_lead", f"[WARNING] Council pre-flight debate inconclusive: {debate_res.get('error')}. Proceeding with individual agent governance.", base_dir)
        update_swarm_status("10_tech_lead", "WAITING", "Standing by to review deliverables against Quality Gates.", 0, base_dir)

    # -------------------------------------------------------------
    # STAGE 1: 01_PM (Product Manager)
    # -------------------------------------------------------------
    run.begin_stage("01_pm")
    b_pm = brains["01_pm"]
    log_swarm_message("01_pm", f"Brain [{b_pm['name']}]: Formulating PRD, User Stories, and Acceptance Criteria...", base_dir)
    update_swarm_status("01_pm", "WORKING", f"[{b_pm['name']}] Writing specs/prd/user-stories.md", 30, base_dir, phase="Phase 1: PRD & Requirements")

    pm_sys = (
        "You are the Product Manager in an autonomous software engineering swarm. "
        "Formulate a complete, professional Product Requirements Document (PRD). "
        "Include: 1) Executive Summary, 2) Target End-User Persona, 3) Core MVP User Stories with Acceptance Criteria (Given-When-Then format), "
        "and 4) Scope Boundaries. Output clean, crafted Markdown adhering to anti-slop guidelines."
    )
    prd_content, ok = run.call_model("01_pm", "prd", b_pm, pm_sys, f"Project Goal: {goal}{debate_context}", providers)
    if not ok or not prd_content.strip():
        raise StageFailure("01_pm", "Stage 01_pm FAILED: All connected AI brains failed to respond. Halting pipeline to prevent silent corruption.",
                           "Generation failed. API offline or quota exhausted.", "FAILED: 01_PM")

    run.require("01_pm", "markdown", validate_markdown(prd_content), "PRD output rejected",
                "PRD output was invalid.", "FAILED: 01_PM")
    run.write("01_pm", "specs/prd/user-stories.md", prd_content.strip() + "\n")
    log_swarm_message("01_pm", f"Deliverable locked: specs/prd/user-stories.md ({len(prd_content)} bytes)", base_dir)
    done("01_pm", "PRD locked. Handoff to 02_arch.")

    # -------------------------------------------------------------
    # STAGE 2: 02_Arch (System Architect)
    # -------------------------------------------------------------
    run.begin_stage("02_arch")
    b_arch = brains["02_arch"]
    log_swarm_message("02_arch", f"Brain [{b_arch['name']}]: Establishing Clean Architecture layer boundaries (ADR-001)...", base_dir)
    update_swarm_status("02_arch", "WORKING", f"[{b_arch['name']}] Writing specs/architecture/adr-001.md", 35, base_dir, phase="Phase 2: Architecture & ADR")

    arch_sys = (
        "You are the System Architect in an autonomous software engineering swarm. "
        "Read the PRD context and formulate Architecture Decision Record ADR-001. "
        "Include: 1) Architectural Style (Clean Architecture separating Domain, UseCase, Repository, Controller layers), "
        "2) Tech Stack Decision with trade-offs, 3) Layer Dependency Inversion rules, 4) Concrete Directory Layout. Output clean Markdown."
    )
    arch_content, ok = run.call_model("02_arch", "adr", b_arch, arch_sys, f"PRD Context:\n{prd_content[:2000]}\n\nTask: Design Clean Architecture for {goal}", providers)
    if not ok or not arch_content.strip():
        raise StageFailure("02_arch", "Stage 02_arch FAILED: Architecture generation failed across all AI brains.",
                           "Generation failed. API offline.", "FAILED: 02_ARCH")

    run.require("02_arch", "markdown", validate_markdown(arch_content), "ADR output rejected",
                "ADR output was invalid.", "FAILED: 02_ARCH")
    run.write("02_arch", "specs/architecture/adr-001.md", arch_content.strip() + "\n")
    log_swarm_message("02_arch", "Deliverable locked: specs/architecture/adr-001.md", base_dir)
    done("02_arch", "Architecture locked. Handoff to 03_designer & 04_dba.")

    # -------------------------------------------------------------
    # STAGE 3: 03_Designer (UI/UX Designer)
    # -------------------------------------------------------------
    run.begin_stage("03_designer")
    b_des = brains["03_designer"]
    log_swarm_message("03_designer", f"Brain [{b_des['name']}]: Synthesizing design tokens, typography, and screen navigation...", base_dir)
    update_swarm_status("03_designer", "WORKING", f"[{b_des['name']}] Writing specs/design/tokens.json & screen-flows.md", 40, base_dir, phase="Phase 3: Design Tokens & UI/UX")

    des_sys = (
        "You are the Senior UI/UX Designer enforcing anti-slop guidelines (WCAG AA contrast, purposeful tokens, tactile controls). "
        "Generate a valid JSON object of design tokens containing: colors (primary, surface, background, border, textPrimary, accent), "
        "typography (fontFamily, scale), and spacing. Only output pure JSON inside a markdown ```json block."
    )
    tokens_raw, ok = run.call_model("03_designer", "tokens", b_des, des_sys, f"Project Goal: {goal}\nPRD Context:\n{prd_content[:1500]}", providers)
    tokens_clean = clean_markdown_block(tokens_raw, "json") if ok else ""
    run.require("03_designer", "design_tokens",
                validate_design_tokens(tokens_clean) if ok else (False, "no model output"),
                "Design token generation invalid", "Invalid or missing design tokens.", "FAILED: 03_DESIGNER")

    run.write("03_designer", "specs/design/tokens.json", tokens_clean.strip() + "\n")

    screen_flow_sys = (
        "You are the Senior UI/UX Designer. Create a concise Screen Flow Document (screen-flows.md). "
        "Detail the primary user journeys, screen layout hierarchy, and tactile interaction patterns. Output clean Markdown."
    )
    screen_flow_content, flow_ok = run.call_model("03_designer", "screen_flows", b_des, screen_flow_sys, f"Project: {goal}\nTokens:\n{tokens_clean[:500]}", providers)
    if not flow_ok or not screen_flow_content.strip():
        raise StageFailure("03_designer", "Screen-flow generation failed.", "Screen flows unavailable.", "FAILED: 03_DESIGNER")
    run.require("03_designer", "markdown", validate_markdown(screen_flow_content), "Screen-flow output rejected",
                "Screen flows were invalid.", "FAILED: 03_DESIGNER")
    run.write("03_designer", "specs/design/screen-flows.md", screen_flow_content.strip() + "\n")

    log_swarm_message("03_designer", "Deliverables locked: specs/design/tokens.json & screen-flows.md", base_dir)
    done("03_designer", "Design specifications complete.")

    # -------------------------------------------------------------
    # STAGE 4: 04_DBA (Database Engineer)
    # -------------------------------------------------------------
    run.begin_stage("04_dba")
    b_dba = brains["04_dba"]
    log_swarm_message("04_dba", f"Brain [{b_dba['name']}]: Designing 3NF database schema & OpenAPI 3.0 contract...", base_dir)
    update_swarm_status("04_dba", "WORKING", f"[{b_dba['name']}] Writing specs/database/schema.sql & openapi.yaml", 40, base_dir, phase="Phase 4: Database & API Contract")

    dba_sys = (
        "You are the Database Engineer. Produce a production-grade 3NF normalized SQL schema. "
        "Enforce zero redundant tables, primary keys (UUID/VARCHAR), foreign keys with indexes, timestamps (created_at, updated_at). "
        "Only output pure valid SQL inside a markdown ```sql code block."
    )
    sql_raw, ok = run.call_model("04_dba", "schema", b_dba, dba_sys, f"Project: {goal}\nArchitecture Context:\n{arch_content[:1500]}", providers)
    if not ok or not sql_raw.strip():
        raise StageFailure("04_dba", "Stage 04_dba FAILED: Database schema generation failed across all AI brains.",
                           "Generation failed. API offline.", "FAILED: 04_DBA")

    sql_clean = clean_markdown_block(sql_raw, "sql")
    run.require("04_dba", "sql_schema", validate_sql(sql_clean), "Schema output rejected",
                "Invalid schema output.", "FAILED: 04_DBA")
    run.write("04_dba", "specs/database/schema.sql", sql_clean.strip() + "\n")

    api_sys = (
        "You are an API Architect. Generate a complete OpenAPI 3.0 YAML specification for this system. "
        "Include health check, CRUD endpoints, request/response schemas. Only output pure valid YAML inside a markdown ```yaml code block."
    )
    api_raw, ok = run.call_model("04_dba", "openapi", b_dba, api_sys, f"Project: {goal}\nDatabase Schema:\n{sql_clean[:1500]}", providers)
    api_clean = clean_markdown_block(api_raw, "yaml") if ok else ""
    run.require("04_dba", "openapi_structure",
                validate_openapi(api_clean) if ok else (False, "no model output"),
                "OpenAPI generation rejected", "Missing or invalid OpenAPI specification.", "FAILED: 04_DBA")

    run.write("04_dba", "specs/api/openapi.yaml", api_clean.strip() + "\n")

    log_swarm_message("04_dba", "Deliverables locked: specs/database/schema.sql & specs/api/openapi.yaml", base_dir)
    done("04_dba", "Schema and OpenAPI locked. Handoff to 05_backend & 06_client.")

    # -------------------------------------------------------------
    # STAGE 5: 05_Backend (Backend Engineer)
    # -------------------------------------------------------------
    run.begin_stage("05_backend")
    b_back = brains["05_backend"]
    log_swarm_message("05_backend", f"Brain [{b_back['name']}]: Scaffolding domain entities, use cases, and REST routes...", base_dir)
    update_swarm_status("05_backend", "WORKING", f"[{b_back['name']}] Writing backend/src/ domain layer", 50, base_dir, phase="Phase 5: Backend Domain Implementation")

    backend_sys = (
        "You are the Backend Engineer. Implement core domain entities, repository interfaces, and use-case handlers "
        "matching the OpenAPI specification and database schema. Provide clean, self-contained Python code adhering to Clean Architecture. "
        "Only output pure valid Python code inside a markdown ```python block."
    )
    code_raw, ok = run.call_model("05_backend", "backend", b_back, backend_sys, f"Goal: {goal}\nOpenAPI:\n{api_clean[:1200]}\nSchema:\n{sql_clean[:1200]}", providers)
    if not ok or not code_raw.strip():
        raise StageFailure("05_backend", "Stage 05_backend FAILED: Backend code generation failed across all AI brains.",
                           "Generation failed. API offline.", "FAILED: 05_BACKEND")

    code_clean = clean_markdown_block(code_raw, "python")
    run.require("05_backend", "python_syntax", validate_python_source(code_clean, require_definitions=True),
                "Invalid backend Python", "Invalid backend source.", "FAILED: 05_BACKEND")
    run.write("05_backend", "backend/src/main.py", code_clean.strip() + "\n")

    log_swarm_message("05_backend", "Deliverable locked: backend/src/main.py", base_dir)
    done("05_backend", "Backend domain implementation complete.")

    # -------------------------------------------------------------
    # STAGE 6: 06_Client (Client Engineer)
    # -------------------------------------------------------------
    run.begin_stage("06_client")
    b_client = brains["06_client"]
    log_swarm_message("06_client", f"Brain [{b_client['name']}]: Scaffolding client interface views & API integration...", base_dir)
    update_swarm_status("06_client", "WORKING", f"[{b_client['name']}] Building client views consuming OpenAPI & tokens", 50, base_dir, phase="Phase 6: Client UI Implementation")

    client_sys = (
        "You are the Client Engineer. Build a clean, tactile frontend application component (or HTML5/JavaScript dashboard view) "
        "that consumes the REST API endpoints and applies the design tokens from specs/design/tokens.json. "
        "Output clean code inside a markdown ```html code block."
    )
    client_raw, ok = run.call_model("06_client", "client", b_client, client_sys, f"Goal: {goal}\nAPI Contract:\n{api_clean[:1000]}\nTokens:\n{tokens_clean[:600]}", providers)
    client_clean = clean_markdown_block(client_raw, "html") if ok else ""
    run.require("06_client", "html", validate_html(client_clean) if ok else (False, "no model output"),
                "Client implementation rejected", "Client generation failed.", "FAILED: 06_CLIENT")

    run.write("06_client", "frontend/public/index.html", client_clean.strip() + "\n")

    log_swarm_message("06_client", "Deliverable locked: frontend/public/index.html", base_dir)
    done("06_client", "Client view components compiled.")

    # -------------------------------------------------------------
    # STAGE 7: 07_QA (QA Engineer)
    # -------------------------------------------------------------
    run.begin_stage("07_qa")
    b_qa = brains["07_qa"]
    log_swarm_message("07_qa", f"Brain [{b_qa['name']}]: Generating QA Test Matrix and executable unit test suite...", base_dir)
    update_swarm_status("07_qa", "WORKING", f"[{b_qa['name']}] Formulating test matrix & writing tests/test_api.py", 60, base_dir, phase="Phase 7: QA Test Engineering")

    qa_sys = (
        "You are the QA Engineer. 1) Analyze the API specification and implementation, 2) Formulate a QA Test Matrix "
        "covering Happy Path, Edge Cases, Boundary Limits, and Concurrency Scenarios. Output clean Markdown."
    )
    qa_raw, ok = run.call_model("07_qa", "test_matrix", b_qa, qa_sys, f"Goal: {goal}\nAPI Contract:\n{api_clean[:1200]}\nBackend Code:\n{code_clean[:1200]}", providers)
    if not ok or not qa_raw.strip():
        raise StageFailure("07_qa", "QA test matrix missing.", "QA matrix generation failed.", "FAILED: 07_QA")
    run.require("07_qa", "markdown", validate_markdown(qa_raw), "QA matrix rejected",
                "QA matrix was invalid.", "FAILED: 07_QA")
    run.write("07_qa", "specs/qa/test-matrix.md", qa_raw.strip() + "\n")

    # Generate executable test file
    test_code_sys = (
        "You are the QA Engineer. Write a self-contained, executable Python unittest suite (tests/test_api.py) "
        "testing the domain entity constraints, input boundaries, and error cases from the backend implementation. "
        "Only output pure valid Python code inside a markdown ```python block."
    )
    test_code_raw, tests_ok = run.call_model("07_qa", "tests", b_qa, test_code_sys, f"Goal: {goal}\nBackend Code:\n{code_clean[:1500]}", providers)
    test_clean = clean_markdown_block(test_code_raw, "python")
    run.require("07_qa", "generated_tests",
                validate_generated_tests(test_clean) if tests_ok else (False, "no model output"),
                "Generated QA tests rejected", "No usable generated tests.", "FAILED: 07_QA")

    run.write("07_qa", "tests/test_api.py", test_clean.strip() + "\n")

    log_swarm_message("07_qa", "QA tests generated; NOT executed or verified.", base_dir)
    done("07_qa", "Generated test source requires isolated test execution.")

    # -------------------------------------------------------------
    # STAGE 8: 08_Security (Security Engineer - Real Code Audit)
    # -------------------------------------------------------------
    run.begin_stage("08_security")
    b_sec = brains["08_security"]
    log_swarm_message("08_security", f"Brain [{b_sec['name']}]: Auditing backend source code & schema against OWASP Top 10...", base_dir)
    update_swarm_status("08_security", "WORKING", f"[{b_sec['name']}] Performing code-level OWASP vulnerability inspection", 70, base_dir, phase="Phase 8: Security Vulnerability Audit")

    sec_sys = (
        "You are an OWASP Application Security Auditor. Perform an objective code-level security audit on the provided "
        "backend source code and database schema. Audit against: 1) Injection vulnerabilities (SQL/Command), 2) Broken Authentication/Token lifecycles, "
        "3) Sensitive Data Exposure, 4) Security Misconfiguration, 5) Input Validation. "
        "For each category, provide status (PASS / WARN / FAIL) with concrete line references and remediation notes. Output clean Markdown."
    )
    sec_raw, ok = run.call_model("08_security", "security_review", b_sec, sec_sys, f"Backend Code:\n{code_clean[:1800]}\n\nDatabase Schema:\n{sql_clean[:1200]}", providers)
    if not ok or not sec_raw.strip():
        raise StageFailure("08_security", "Security review model did not respond.", "No security review generated.", "FAILED: 08_SECURITY")
    run.require("08_security", "markdown", validate_markdown(sec_raw), "Security review output rejected",
                "Security review was invalid.", "FAILED: 08_SECURITY")
    run.write("08_security", "specs/security/audit-report.md",
              "# AI security review (advisory, unverified)\n\n"
              "No automated scanner or real security test was executed by this stage.\n\n"
              + sec_raw.strip() + "\n")

    log_swarm_message("08_security", "Advisory security review generated; security gate NOT verified.", base_dir)
    done("08_security", "Advisory review only; independent scanning required.")

    # -------------------------------------------------------------
    # STAGE 9: 09_DevOps (DevOps Engineer)
    # -------------------------------------------------------------
    run.begin_stage("09_devops")
    b_dev = brains["09_devops"]
    log_swarm_message("09_devops", f"Brain [{b_dev['name']}]: Designing reproducible multi-stage Docker build & CI workflow...", base_dir)
    update_swarm_status("09_devops", "WORKING", f"[{b_dev['name']}] Writing Dockerfile and .github/workflows/ci.yml", 80, base_dir, phase="Phase 9: DevOps & Containerization")

    docker_sys = (
        "You are the DevOps Engineer. Generate a production-grade multi-stage Dockerfile for this service. "
        "Enforce minimal attack surface (distroless/alpine), non-root user, health checks, and reproducible builds. "
        "Only output pure valid Dockerfile content inside a markdown ```dockerfile block."
    )
    docker_raw, docker_ok = run.call_model("09_devops", "dockerfile", b_dev, docker_sys, f"Goal: {goal}\nTech Stack Context:\n{arch_content[:1000]}", providers)
    docker_clean = clean_markdown_block(docker_raw, "dockerfile")
    if not docker_ok or not docker_clean.strip():
        raise StageFailure("09_devops", "Dockerfile generation failed.", "No Dockerfile generated.", "FAILED: 09_DEVOPS")

    run.require("09_devops", "dockerfile", validate_dockerfile(docker_clean), "Dockerfile rejected",
                "Invalid Dockerfile generated.", "FAILED: 09_DEVOPS")

    # Stage generated DevOps files separately; never overwrite TenAgent's own
    # Dockerfile and CI pipeline with unreviewed model-generated output.
    run.write("09_devops", "specs/devops/Dockerfile", docker_clean.strip() + "\n")

    # Generate CI workflow
    ci_workflow = (
        "name: CI Pipeline\n"
        "on: [push, pull_request]\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - name: Set up Python\n"
        "        uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.11'\n"
        "      - name: Run Quality Gate Tests\n"
        "        run: |\n"
        "          python -m unittest discover tests\n"
    )
    run.write("09_devops", "specs/devops/ci.yml", ci_workflow)

    log_swarm_message("09_devops", "Generated specs/devops/Dockerfile and ci.yml; NOT built or executed.", base_dir)
    done("09_devops", "Generated DevOps templates require verification.")

    # -------------------------------------------------------------
    # STAGE 10: 10_Tech Lead (Gatekeeper Review & Signoff)
    # -------------------------------------------------------------
    run.begin_stage("10_tech_lead")
    b_lead = brains["10_tech_lead"]
    log_swarm_message("10_tech_lead", f"Brain [{b_lead['name']}]: Evaluating deliverables against all 6 Quality Gates...", base_dir)
    update_swarm_status("10_tech_lead", "WORKING", f"[{b_lead['name']}] Evaluating artifacts for production signoff", 90, base_dir, phase="Phase 10: Final Quality Gate Audit")

    lead_sys = (
        "You are the Technical Lead and ultimate gatekeeper in an elite engineering swarm. "
        "Critically evaluate the generated project deliverables: 1) PRD, 2) Clean Architecture ADR, 3) 3NF Schema & OpenAPI, "
        "4) Backend Implementation, 5) Client Views, 6) QA Matrix & Executable Tests, 7) Security Code Audit. "
        "Verify: No architectural drift, no silent failures, contract compliance. "
        "Output an advisory review only. Put exactly one verdict alone on its own line: [READY FOR INDEPENDENT VERIFICATION] or [REJECTED - REMEDIATION REQUIRED]. "
        "Use the ready verdict only if you found no problems at all, and then keep any notes free of negations. Do not authorize production release."
    )
    review_context = f"Project: {goal}\nPRD:\n{prd_content[:600]}\nADR:\n{arch_content[:600]}\nBackend:\n{code_clean[:800]}\nSecurity:\n{sec_raw[:600]}"
    lead_raw, ok = run.call_model("10_tech_lead", "lead_review", b_lead, lead_sys, review_context, providers)
    if not ok or not lead_raw.strip():
        raise StageFailure("10_tech_lead", "Technical review generation failed.", "No lead review available.", "FAILED: 10_TECH_LEAD")

    # Even an optimistic model verdict is only an opinion, not release proof.
    advisory = re.sub(r"approved\s+for\s+production", "AI MODEL OPINION ONLY", lead_raw, flags=re.I)
    verdict_ok, verdict_why = validate_lead_verdict(lead_raw)
    run.validated("10_tech_lead", "lead_verdict", verdict_ok, verdict_why)
    if not verdict_ok:
        # The sign-off file is only ever created for a cleared review.
        run.write("10_tech_lead", "specs/signoff.rejected.md",
                  "# REJECTED draft technical review: NOT VERIFIED FOR PRODUCTION\n\n"
                  + advisory.strip() + "\n")
        raise StageFailure("10_tech_lead", f"Model review did not clear the deliverables: {verdict_why}",
                           "Model review rejected deliverables.", "FAILED: LEAD_REVIEW")
    run.write("10_tech_lead", "specs/signoff.md",
              "# Draft technical review: NOT VERIFIED FOR PRODUCTION\n\n"
              "No generated QA tests, security scanners, builds or CI jobs were run "
              "by this pipeline. Independent checks are still required.\n\n"
              + advisory.strip() + "\n")

    log_swarm_message("10_tech_lead", "Generation stages complete, but production readiness remains UNVERIFIED.", base_dir)
    run.finish_stage("10_tech_lead")
    update_swarm_status("10_tech_lead", "REVIEWING", "Pending independent QA, security and CI evidence.", GENERATED_PROGRESS, base_dir,
                        overall_progress=compute_progress(run.milestones), phase="Generated: Awaiting Verification")
    log_swarm_message("swarm", "=== Draft Generated; NOT Verified or Approved for Production ===", base_dir)


def execute_multi_brain_swarm(goal: str, root_dir: str = None):
    """Run the generation pipeline. True means "draft generated, awaiting verification" only."""
    base_dir = root_dir or ROOT_DIR
    run = RunRecord(base_dir, goal)
    if not run.acquire_lock():
        log_swarm_message(
            "swarm", "[BLOCKED] Another swarm run is active (specs/.swarm-run.lock); refusing to start a second one. "
            "Delete the lock file only if you are sure no run is active.", base_dir)
        return False
    try:
        try:
            run.load_prior()
            problems = run.preflight()
        except Exception as exc:  # anything unexpected here is a blocked start, not a dead thread
            problems = [f"preflight failed: {type(exc).__name__}: {exc}"]
        if problems:
            for problem in problems:
                log_swarm_message("swarm", f"[BLOCKED] {problem}", base_dir)
            update_swarm_status("swarm", None, "Run blocked: output files unavailable or would be overwritten.", None, base_dir,
                                phase="BLOCKED: output files unavailable")
            run.transition(BLOCKED, error="; ".join(problems))
            return False
        run.transition(RUNNING)
        try:
            run.retire_stale_gates()
            _run_stages(run, goal)
        except StageFailure as failure:
            _finish_unsuccessfully(run, failure.agent_id, failure.message, failure.detail, failure.phase)
            return False
        except Exception as exc:
            _finish_unsuccessfully(
                run, None, f"Unexpected {type(exc).__name__}: {exc}",
                f"Unexpected {type(exc).__name__}; see specs/terminal.log.", "FAILED: UNEXPECTED_ERROR")
            return False
        except BaseException:
            _finish_unsuccessfully(run, None, "Run interrupted.", "Interrupted.", "FAILED: INTERRUPTED")
            raise
        run.transition(AWAITING_VERIFICATION)
        return True
    finally:
        run.release_lock()

def start_swarm_pipeline_thread(goal: str, root_dir: str = None):
    t = threading.Thread(target=execute_multi_brain_swarm, args=(goal, root_dir), daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Automated Inventory POS System"
    # Exit 0 only when a draft was generated; failure or a blocked start must not look like success.
    sys.exit(0 if execute_multi_brain_swarm(prompt) else 1)
