"""Access and secret-handling helpers for the loopback-only TenAgent dashboard."""

import base64
import binascii
import hmac
from collections.abc import Mapping


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
