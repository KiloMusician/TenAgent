"""Access and secret-handling helpers for the loopback-only TenAgent dashboard."""

import base64
import binascii
import hmac
import re
from collections.abc import Mapping
from typing import NamedTuple


_SECRET_FIELD_NAMES = frozenset({
    "key", "apikey", "accesstoken", "refreshtoken", "secret",
    "password", "clientsecret", "privatekey", "authorization",
    "token", "bearertoken",
})


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


def valid_static_path(path: str) -> bool:
    """Prevent URL decoding from bypassing the raw static-file path filter."""
    if not path or '%' in path or '\\' in path:
        return False
    return not any(
        segment in ('.', '..') or segment.startswith('.')
        for segment in path.split('/') if segment
    )


def public_config(config: Mapping) -> dict:
    """Return an independently redacted configuration without mutating input."""
    def redact(value):
        if isinstance(value, Mapping):
            return {
                name: redact(item)
                for name, item in value.items()
                if name.lower().replace("_", "").replace("-", "")
                not in _SECRET_FIELD_NAMES
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
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
            visible["key_masked"] = (
                key[:4] + "..." + key[-4:] if len(key) > 8
                else ("***" if key else "")
            )
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
