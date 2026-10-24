"""Access and secret-handling helpers for the loopback-only TenAgent dashboard."""

import base64
import binascii
import hmac
import os
import re
from collections.abc import Mapping
from typing import NamedTuple
from urllib.parse import urlsplit, urlunsplit


# A field is treated as a credential when its name merely *contains* one of
# these (so secret_key, x-api-key, openai_api_key, auth_token, passphrase ...
# are covered without enumerating them).  Plural "...tokens" names are counts
# (max_tokens), not credentials.
_SECRET_NAME_PARTS = (
    "key", "secret", "token", "password", "passwd", "passphrase",
    "credential", "authorization", "bearer", "cookie",
)


def is_secret_field(name) -> bool:
    normal = re.sub(r"[^a-z0-9]", "", str(name).lower())
    if normal.endswith("tokens"):
        return False
    return any(part in normal for part in _SECRET_NAME_PARTS)


def redact_url(value: str) -> str:
    """Hide userinfo and secret-named query values of a URL; other text is returned as is."""
    if "://" not in value:
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not parts.scheme or not parts.netloc:
        return value
    netloc = parts.netloc
    if "@" in netloc:
        netloc = "***@" + netloc.rsplit("@", 1)[1]
    query = "&".join(
        f"{piece.split('=', 1)[0]}=***"
        if "=" in piece and is_secret_field(piece.split("=", 1)[0]) else piece
        for piece in parts.query.split("&")
    ) if parts.query else ""
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


def valid_operator_authorization(header: str | None, password: str) -> bool:
    """Accept HTTP Basic authorization for the local operator, not remote identities."""
    if not password or not header or len(header) > 1024:
        return False
    scheme, separator, credential = header.partition(" ")
    if not separator or scheme.lower() != "basic":
        return False
    try:
        decoded = base64.b64decode(credential.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeError, binascii.Error):
        return False
    username, colon, submitted_password = decoded.partition(":")
    return bool(
        colon
        and hmac.compare_digest(username.encode("utf-8"), b"tenagent")
        and hmac.compare_digest(
            submitted_password.encode("utf-8"), password.encode("utf-8")
        )
    )


def valid_local_host(host: str | None, port: int) -> bool:
    """Reject non-loopback Host headers, including DNS-rebinding hostnames."""
    return isinstance(host, str) and host.lower().strip() in {
        f"localhost:{port}", f"127.0.0.1:{port}",
    }


def valid_mutation_origin(
    origin: str | None, host: str | None, fetch_site: str | None, port: int
) -> bool:
    """Only authorize same-origin writes (or explicit local nonbrowser clients)."""
    if not valid_local_host(host, port):
        return False
    if fetch_site and fetch_site.lower() not in {"none", "same-origin"}:
        return False
    return origin is None or origin.lower() == f"http://{host.lower()}"


STATIC_EXTENSIONS = frozenset({
    ".html", ".css", ".js", ".json", ".log", ".txt",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
})
_STATIC_FORBIDDEN_CHARS = re.compile(r'[%\\:*?"<>|\x00-\x1f\x7f-\U0010ffff]')
# Win32 maps these names (with or without an extension) to devices.
_WINDOWS_DEVICE_NAME = re.compile(
    r"(con|prn|aux|nul|conin\$|conout\$|clock\$|(com|lpt)[0-9])(\..*)?", re.IGNORECASE
)


def valid_static_path(path: str) -> bool:
    """Decide from the raw request path whether it may name a static file.

    The check must judge the same string the file system will see, so anything
    that http.server or Windows would reinterpret is refused outright: percent
    escapes, backslashes, ':' (drive letters and ``name::$DATA`` streams),
    trailing dots/spaces (stripped by Win32), device names, hidden segments and
    any file whose extension is not in STATIC_EXTENSIONS.
    """
    if not path or not path.startswith('/') or _STATIC_FORBIDDEN_CHARS.search(path):
        return False
    segments = path.split('/')[1:]
    for segment in segments:
        if not segment:
            continue
        if (segment in ('.', '..') or segment.startswith('.')
                or segment.endswith(('.', ' '))
                or _WINDOWS_DEVICE_NAME.fullmatch(segment)):
            return False
    leaf = segments[-1]
    if leaf and os.path.splitext(leaf)[1].lower() not in STATIC_EXTENSIONS:
        return False
    return True


def static_target_allowed(directory: str, target: str, exact_files=()) -> bool:
    """Confirm the resolved file (after symlinks/junctions) is still servable.

    ``target`` is what http.server resolved the URL to.  It must live under
    ``<directory>/dashboard`` or ``<directory>/assets`` (or be one of
    ``exact_files``) and, unless it is a directory, carry an allowed extension.
    """
    try:
        real = os.path.normcase(os.path.realpath(target))
        base = os.path.realpath(directory)
        exact = {os.path.normcase(os.path.realpath(name)) for name in exact_files}
        if real in exact:
            return True
        for name in ("dashboard", "assets"):
            root = os.path.normcase(os.path.join(base, name))
            if os.path.commonpath([real, root]) == root:
                return (os.path.isdir(real)
                        or os.path.splitext(real)[1].lower() in STATIC_EXTENSIONS)
    except (OSError, ValueError):
        pass
    return False


def public_config(config: Mapping) -> dict:
    """Return an independently redacted configuration without mutating input."""
    def redact(value):
        if isinstance(value, Mapping):
            return {
                name: redact(item)
                for name, item in value.items()
                if not is_secret_field(name)
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        if isinstance(value, str):
            return redact_url(value)
        return value

    safe = redact(config)
    providers = config.get("providers", [])
    public_providers = safe.get("providers", [])
    if isinstance(providers, list) and isinstance(public_providers, list):
        for original, visible in zip(providers, public_providers):
            if not isinstance(original, Mapping) or not isinstance(visible, dict):
                continue
            key = original.get("key") or ""
            if not isinstance(key, str):
                key = str(key)
            visible["has_key"] = bool(key.strip())
            visible["key_masked"] = mask_key(key)
    return safe


AGENT_STATUSES = frozenset({
    "IDLE", "WORKING", "WAITING", "REVIEWING", "ERROR", "FAILED",
})
MAX_LOG_MESSAGE = 2000
_AGENT_TAG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
_LINE_BREAKS = re.compile(r"[\x00-\x1f\x7f\x85\u2028\u2029]+")


def single_line(value: str, limit: int = MAX_LOG_MESSAGE) -> str:
    """Collapse control characters so one entry can never become several log lines."""
    return _LINE_BREAKS.sub(" ", value).strip()[:limit]


class LogUpdate(NamedTuple):
    agent: str
    message: str
    status: str | None
    progress: int | None


def parse_log_update(payload) -> LogUpdate:
    """Validate a POST /api/log body; raises ValueError with a safe message.

    The status ends up in swarm-status.json and is rendered by the dashboard, so
    it must come from a closed set; the agent tag and message end up in the
    line-oriented terminal log, so they must stay on one line.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("JSON object required")
    agent = payload.get("agent", "cli")
    if not isinstance(agent, str) or not _AGENT_TAG.fullmatch(agent):
        raise ValueError("invalid agent")
    message = payload.get("message", "")
    if message is None:
        message = ""
    if not isinstance(message, str):
        raise ValueError("message must be a string")
    status = payload.get("status")
    if status is not None and (not isinstance(status, str) or status not in AGENT_STATUSES):
        raise ValueError("invalid status")
    progress = payload.get("progress")
    if progress is not None:
        if isinstance(progress, bool) or not isinstance(progress, (int, float, str)):
            raise ValueError("invalid progress")
        try:
            progress = max(0, min(100, int(float(progress))))
        except (ValueError, OverflowError):
            raise ValueError("invalid progress") from None
    return LogUpdate(agent, single_line(message), status, progress)


MASK_REVEAL_MIN_LENGTH = 24


def mask_key(key: str) -> str:
    """The redacted form shown to the browser for a stored key.

    Only keys long enough that eight visible characters are a small fraction of
    them show their ends; shorter ones are fully hidden.
    """
    if len(key) >= MASK_REVEAL_MIN_LENGTH:
        return key[:4] + "..." + key[-4:]
    return "***" if key else ""


def is_masked_key(value) -> bool:
    """True for the placeholders mask_key() produces (and the frontend echoes back)."""
    return isinstance(value, str) and (value.strip() == "***" or "..." in value)


# Fields the server computes for the browser; they are never persisted.
SERVER_OWNED_CONFIG_FIELDS = ("cli",)
SERVER_OWNED_PROVIDER_FIELDS = ("has_key", "key_masked")


def prepare_config_payload(payload, stored) -> dict:
    """Validate a POST /api/config body and resolve keys against the stored config.

    * ``key`` absent/null keeps the stored key of the same provider entry
      (``key_masked``, if echoed back, tells duplicate entries apart);
    * ``key`` == "" clears it;
    * a masked placeholder (what GET /api/config shows) is replaced by the stored
      key it was derived from, and refused if it matches none, so a placeholder
      can never be persisted as if it were a credential;
    * anything else is a new key.

    Raises ValueError with a message that is safe to show to the operator.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("JSON object required")
    entries = payload.get("providers", [])
    if not isinstance(entries, list):
        raise ValueError("providers must be a list")
    stored_entries = [
        item for item in ((stored or {}).get("providers") or [])
        if isinstance(item, Mapping) and isinstance(item.get("key"), str) and item["key"]
    ]
    used = set()

    def take(predicate):
        for index, item in enumerate(stored_entries):
            if index not in used and predicate(item):
                used.add(index)
                return item["key"]
        return None

    prepared = [
        (name, value) for name, value in payload.items()
        if name not in SERVER_OWNED_CONFIG_FIELDS
    ]
    result = dict(prepared)
    providers = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("each provider must be an object")
        hint = entry.get("key_masked")  # echoed back by clients that round-trip GET
        entry = {
            name: value for name, value in entry.items()
            if name not in SERVER_OWNED_PROVIDER_FIELDS
        }
        provider = entry.get("provider", "")
        if not isinstance(provider, str):
            raise ValueError("provider must be a string")
        key = entry.get("key")
        if key is not None and not isinstance(key, str):
            raise ValueError("key must be a string")
        if key is None:
            restored = None
            if isinstance(hint, str) and hint:
                restored = take(
                    lambda item: item.get("provider") == provider and mask_key(item["key"]) == hint
                )
            if restored is None:
                restored = take(lambda item: item.get("provider") == provider)
            if restored is not None:
                entry["key"] = restored
        elif is_masked_key(key):
            shown = key.strip()
            restored = take(
                lambda item: item.get("provider") == provider and mask_key(item["key"]) == shown
            )
            if restored is None and shown != "***":
                restored = take(lambda item: mask_key(item["key"]) == shown)
            if restored is None:
                raise ValueError(
                    f"The key shown for '{provider}' is masked and matches no saved key; "
                    "enter it again."
                )
            entry["key"] = restored
        for field in ("baseUrl", "base_url"):
            posted = entry.get(field)
            if isinstance(posted, str) and posted:
                for item in (stored or {}).get("providers") or []:
                    original = item.get(field) if isinstance(item, Mapping) else None
                    if (isinstance(original, str) and item.get("provider") == provider
                            and original != posted and redact_url(original) == posted):
                        entry[field] = original
                        break
        providers.append(entry)
    result["providers"] = providers
    return result


_SHAPES = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{20,}|gsk_[A-Za-z0-9]{16,}"
    r"|xai-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"
)
_AUTH_HEADER = re.compile(r"(?i)(\bauthorization\s*[:=]\s*(?:(?:bearer|basic|token)\s+)?)[^\s,;\"']+")
_BEARER = re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]{6,}")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(\b[a-z0-9_-]*(?:key|token|secret|password|passwd|passphrase|credential)[a-z0-9_-]*\s*=\s*)"
    r"[^\s&\"'<>]+"
)


def redact_text(text: str, secrets=()) -> str:
    """Scrub credentials from a line destined for logs or status files.

    Removes the exact ``secrets`` given (dashboard password, session token),
    ``Authorization``/``Bearer`` values, ``name=value`` pairs whose name looks
    like a credential, and strings shaped like common provider keys.
    """
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    text = _AUTH_HEADER.sub(lambda m: m.group(1) + "***", text)
    text = _BEARER.sub(lambda m: m.group(1) + "***", text)
    text = _SECRET_ASSIGNMENT.sub(lambda m: m.group(1) + "***", text)
    return _SHAPES.sub("***", text)
