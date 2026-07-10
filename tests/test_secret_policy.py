"""Tests for secret handling (ACTION_PLAN §三 item 7, threat-model T1).

Unit tests cover name detection / value collection / scrubbing / masking. Integration
tests exercise the two backends: trusted masks printed secrets, restricted launches its
subprocess with a scrubbed environment so the agent's credentials are unreadable there.
"""

from forgeagent.executor import RestrictedBackend, TrustedBackend
from forgeagent.runtime import Runtime
from forgeagent.secret_policy import (
    REDACTED,
    is_secret_name,
    mask_secrets,
    scrub_environment,
    sensitive_env_values,
)

# --- name detection ----------------------------------------------------------


def test_secret_names_detected():
    for name in [
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "DB_PASSWORD",
        "AWS_SECRET_ACCESS_KEY",
        "MY_PAT",
        "SSH_PRIVATE_KEY",
        "SERVICE_CREDENTIALS",
    ]:
        assert is_secret_name(name), name


def test_benign_names_not_detected():
    for name in ["PATH", "HOME", "PYTHONPATH", "LANG", "MONKEY_ISLAND", "KEYBOARD_LAYOUT"]:
        assert not is_secret_name(name), name


# --- value collection --------------------------------------------------------


def test_sensitive_values_collects_only_long_secret_named():
    env = {
        "ANTHROPIC_API_KEY": "placeholder-longvalue-123456",
        "SHORT_TOKEN": "abc",  # secret name but too short to mask safely
        "PATH": "/usr/bin:/bin",  # not a secret name
    }
    assert sensitive_env_values(env) == {"placeholder-longvalue-123456"}


# --- scrubbing ---------------------------------------------------------------


def test_scrub_removes_secrets_keeps_the_rest():
    env = {"OPENAI_API_KEY": "placeholder-value", "PATH": "/bin", "HOME": "/home/u"}
    scrubbed = scrub_environment(env)
    assert "OPENAI_API_KEY" not in scrubbed
    assert scrubbed == {"PATH": "/bin", "HOME": "/home/u"}


# --- masking -----------------------------------------------------------------


def test_mask_redacts_values_longer_first():
    text = "key=PLACEHOLDERLONG and frag=PLACEHOLDER"
    masked = mask_secrets(text, {"PLACEHOLDER", "PLACEHOLDERLONG"})
    # The longer value is replaced before the shorter, so no fragment is left dangling.
    assert masked == f"key={REDACTED} and frag={REDACTED}"


def test_mask_noop_without_secrets():
    assert mask_secrets("nothing to hide", set()) == "nothing to hide"


# --- trusted backend: masks printed secrets ----------------------------------


def test_trusted_backend_masks_secret_in_stdout():
    backend = TrustedBackend(secret_values={"placeholdervalue12345"})
    result = backend.execute("print('leak: placeholdervalue12345')", Runtime())
    assert result.success is True
    assert "placeholdervalue12345" not in result.stdout
    assert REDACTED in result.stdout


def test_trusted_backend_masks_secret_in_error():
    backend = TrustedBackend(secret_values={"placeholdervalue12345"})
    result = backend.execute("raise ValueError('placeholdervalue12345')", Runtime())
    assert result.success is False
    assert "placeholdervalue12345" not in (result.error or "")
    assert REDACTED in (result.error or "")


# --- restricted backend: subprocess env is scrubbed --------------------------


def test_restricted_subprocess_cannot_read_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TEST_API_KEY", "placeholder-long-value")
    backend = RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=15.0)
    result = backend.execute(
        "import os\nprint(os.environ.get('FORGE_TEST_API_KEY', 'ABSENT'))", Runtime()
    )
    assert result.success is True
    assert result.stdout.strip() == "ABSENT"


def test_restricted_subprocess_keeps_non_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_TEST_CONFIG_DIR", "keepme-value")
    backend = RestrictedBackend(allowed_root=str(tmp_path), timeout_seconds=15.0)
    result = backend.execute(
        "import os\nprint(os.environ.get('FORGE_TEST_CONFIG_DIR', 'ABSENT'))", Runtime()
    )
    assert result.success is True
    assert result.stdout.strip() == "keepme-value"
