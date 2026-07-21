"""Keep the agent's own credentials out of the sandbox and out of anything the model
or the user gets to see.

Two independent measures (docs/threat-model.md T1, ACTION_PLAN §三 item 7):

1. scrub_environment(): the restricted subprocess is launched with a copy of the
   environment that has secret-looking variables removed, so model code cannot read the
   agent's API keys via os.environ at all. Prevention — the strongest measure, but only
   possible for the out-of-process (restricted) backend.

2. mask_secrets(): any secret VALUE that still reaches a block's stdout/stderr/error is
   redacted before it enters the feedback loop or the console. Defense in depth, and the
   only measure available for the trusted (same-process) backend, whose contract is
   explicitly "no isolation" — masking is hygiene there, not a boundary.

Secret detection is by environment-variable NAME pattern. A sanctioned `utils.get_env()`
accessor (which would register exact values regardless of name) is deferred until a
network broker gives it a consumer — v1 denies network in restricted and reads env
directly in trusted, so there is nothing to use it yet.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

REDACTED = "***REDACTED***"
REDACTED_PATH = "<redacted-path>"

# Env var names whose values are treated as secrets. SECRET/TOKEN/PASSWORD/CREDENTIAL are
# matched anywhere (they do not occur in benign names like PATH/HOME); KEY/PAT/APIKEY are
# boundary-guarded so MONKEY, PATH, PYTHONPATH etc. do not false-positive.
_SECRET_NAME_RE = re.compile(
    r"SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|(?:^|_)(?:KEY|PAT|APIKEY)(?:$|_)",
    re.IGNORECASE,
)

# Values shorter than this are never masked: too likely to be a common substring (a port,
# "true", a single word) whose blanket replacement would corrupt unrelated output.
_MIN_SECRET_LENGTH = 8


def is_secret_name(name: str) -> bool:
    """Whether an environment variable name looks like it holds a secret."""
    return bool(_SECRET_NAME_RE.search(name))


def sensitive_env_values(environ: Mapping[str, str] | None = None) -> set[str]:
    """The set of secret VALUES to redact from output (values of secret-named vars).

    Defaults to the live process environment. Only values of a meaningful length are
    included, so masking never mangles output over a short, non-secret value.
    """
    source = os.environ if environ is None else environ
    return {
        value
        for name, value in source.items()
        if value and len(value) >= _MIN_SECRET_LENGTH and is_secret_name(name)
    }


def scrub_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """A copy of the environment with every secret-named variable removed.

    Used as the `env` for the restricted subprocess so model code cannot read the
    agent's credentials at all. Non-secret vars (PATH, HOME, ...) are preserved so the
    subprocess still starts and imports normally.
    """
    source = os.environ if environ is None else environ
    return {name: value for name, value in source.items() if not is_secret_name(name)}


def mask_secrets(text: str, secret_values: Iterable[str]) -> str:
    """Replace every occurrence of a secret value in `text` with REDACTED.

    Longer values are replaced first so an overlapping shorter value cannot leave a
    fragment of a longer secret behind.
    """
    if not text:
        return text
    for value in sorted((v for v in secret_values if v), key=len, reverse=True):
        text = text.replace(value, REDACTED)
    return text


def mask_audit_data(
    value: object,
    secret_values: Iterable[str],
    *,
    field_name: str | None = None,
) -> object:
    """Return a JSON-safe, secret-masked audit projection of ``value``.

    Audit inputs cross a logging trust boundary. Secret-named fields are removed even
    when their value is not in the known-secret set, absolute host paths are never
    retained, and unsupported objects use a type-only fallback rather than ``str()``.
    """
    secrets = set(secret_values)
    if field_name and is_secret_name(field_name):
        return REDACTED
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "<non-finite>"
    if isinstance(value, Path):
        return REDACTED_PATH if value.is_absolute() else mask_secrets(value.as_posix(), secrets)
    if isinstance(value, str):
        if field_name and "url" in field_name.casefold():
            return _mask_audit_url(value, secrets)
        if _is_path_field(field_name) and os.path.isabs(value):
            return REDACTED_PATH
        return mask_secrets(value, secrets)
    if isinstance(value, Mapping):
        return {
            mask_secrets(str(key), secrets): mask_audit_data(
                item,
                secrets,
                field_name=str(key),
            )
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [mask_audit_data(item, secrets, field_name=field_name) for item in value]
    if isinstance(value, set | frozenset):
        projected = [mask_audit_data(item, secrets, field_name=field_name) for item in value]
        return sorted(projected, key=repr)
    return f"<unsupported:{type(value).__name__}>"


def _is_path_field(field_name: str | None) -> bool:
    if field_name is None:
        return False
    normalized = field_name.casefold().replace("-", "_")
    return normalized == "path" or normalized.endswith("_path") or normalized.endswith("_root")


def _mask_audit_url(value: str, secret_values: set[str]) -> str:
    """Drop URL credentials, query, and fragment while retaining a useful route label."""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return "<redacted-url>"
    if parsed.scheme not in {"http", "https"} or not host:
        return "<redacted-url>"
    safe_host = mask_secrets(host, secret_values)
    if ":" in safe_host and not safe_host.startswith("["):
        safe_host = f"[{safe_host}]"
    netloc = f"{safe_host}:{port}" if port is not None else safe_host
    safe_path = mask_secrets(parsed.path or "/", secret_values)
    return urlunsplit((parsed.scheme, netloc, safe_path, "", ""))
