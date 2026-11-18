"""Opt-in, bounded live gateway acceptance. See docs/live-model-acceptance.md."""

from __future__ import annotations

import argparse
import base64
import http.client
import io
import json
import os
import re
import struct
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rich.console import Console

from forgeagent.cli import run_collaboration_once
from forgeagent.client import ModelClient
from forgeagent.collaboration import headless_plan_confirmer
from forgeagent.executor import RestrictedBackend
from forgeagent.models import (
    ClientError,
    GenerationParams,
    Message,
    ModelCapability,
    StreamEventKind,
)
from forgeagent.openai_compatible_client import OpenAICompatibleClient
from forgeagent.protocol import FileWriteArgs
from forgeagent.runtime import Runtime
from forgeagent.secret_policy import mask_audit_data, mask_secrets, sensitive_env_values

ROOT = Path(__file__).resolve().parents[1]


class AcceptanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    api_key_env: str = "MAAS_SD_API_KEY"
    base_url_env: str = "MAAS_BASE_URL"
    text_models: list[str] = Field(min_length=1, max_length=10)
    image_models: list[str] = Field(default_factory=list, max_length=10)
    generator_model: str
    planner_model: str
    evaluator_model: str
    context_window: int = Field(default=65536, ge=8192, le=1000000)
    max_output_tokens: int = Field(default=4096, ge=256, le=16384)
    timeout_seconds: int = Field(default=120, ge=1, le=600)
    max_requests: int = Field(default=100, ge=1, le=500)
    image_path: str = "/v1/images/generations"
    image_size: str = "1024x1024"

    @model_validator(mode="after")
    def validate_settings(self):
        for name in (self.api_key_env, self.base_url_env):
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name):
                raise ValueError("invalid environment variable name")
        roles = (self.generator_model, self.planner_model, self.evaluator_model)
        for name in [*self.text_models, *self.image_models, *roles]:
            if not name or len(name) > 200 or any(ord(c) < 33 or ord(c) > 126 for c in name):
                raise ValueError("invalid model identifier")
        if not set(roles) <= set(self.text_models):
            raise ValueError("collaboration roles must use configured text models")
        if len(set(self.text_models)) != len(self.text_models):
            raise ValueError("duplicate text model")
        if self.image_path not in {"/v1/images/generations", "/api/v3/images/generations"}:
            raise ValueError("unsupported image path")
        if not re.fullmatch(r"[1-9][0-9]{0,3}x[1-9][0-9]{0,3}", self.image_size):
            raise ValueError("invalid image size")
        return self


def gateway_root(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base URL must be an HTTPS site root")
    _ = parsed.port
    return value.rstrip("/")


class RequestBudget:
    def __init__(self, maximum):
        self.maximum = maximum
        self.used = 0

    def take(self):
        if self.used >= self.maximum:
            return False
        self.used += 1
        return True


def budget_error():
    return ClientError(
        message="acceptance request budget exhausted", kind="invalid_request", attempts=1
    )


class RecordedClient(ModelClient):
    def __init__(self, inner, budget, path, secrets, timeout=120):
        self.inner, self.budget, self.path, self.secrets = inner, budget, path, secrets
        self.timeout = timeout

    @property
    def capability(self):
        return self.inner.capability

    def record(self, response):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(mask_audit_data(response.model_dump(mode="json"), self.secrets)) + "\n"
            )

    def complete(self, messages, params=None):
        if not self.budget.take():
            return budget_error()
        params = (params or GenerationParams()).model_copy(update={"timeout_seconds": self.timeout})
        result = self.inner.complete(messages, params)
        self.record(result)
        return result

    def stream(self, messages, params=None):
        if not self.budget.take():
            yield budget_error()
            return
        params = (params or GenerationParams()).model_copy(update={"timeout_seconds": self.timeout})
        for event in self.inner.stream(messages, params):
            if isinstance(event, ClientError):
                self.record(event)
            elif event.kind == StreamEventKind.DONE and event.message is not None:
                self.record(event.message)
            yield event

    def close(self):
        self.inner.close()


def check_text(model, factory, root):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from tests.golden.manifest import GOLDEN_SCENARIOS
    from tests.golden.runner import run_suite, validate_manifest, write_reports

    validate_manifest(GOLDEN_SCENARIOS)
    root.mkdir(parents=True)
    client = factory(model)
    try:
        events = list(
            client.stream(
                [Message(role="user", content="Reply with exactly ACCEPTED.")],
                GenerationParams(max_output_tokens=256),
            )
        )
        completed = [
            e.message
            for e in events
            if not isinstance(e, ClientError)
            and e.kind == StreamEventKind.DONE
            and e.message is not None
        ]
        stream_ok = (
            not any(isinstance(e, ClientError) for e in events)
            and len(completed) == 1
            and completed[0].content.strip() == "ACCEPTED"
        )
        selected = [case for case in GOLDEN_SCENARIOS if case.run_real is not None]
        suite = run_suite(selected, mode="real", model=model, real_client=client)
        for path in write_reports(suite, root):
            content = path.read_text()
            if path.suffix == ".json":
                content = json.dumps(mask_audit_data(json.loads(content), client.secrets), indent=2)
            else:
                content = mask_secrets(content, client.secrets)
            path.write_text(content, encoding="utf-8")
        return {
            "model": model,
            "passed": stream_ok and suite.exit_code == 0,
            "stream_passed": stream_ok,
            "golden_passed": suite.passed,
            "golden_total": suite.total,
        }
    finally:
        client.close()


INDEPENDENT_CHECK = """import os, sys, runpy, unittest
sys.path.insert(0, os.getcwd())
f = runpy.run_path('sum_squares.py')['sum_squares']
for n, expected in [(0,0), (1,1), (10,385), (37,17575)]:
    assert f(n) == expected, (n, f(n), expected)
try:
    f(-1)
except ValueError:
    pass
else:
    raise AssertionError('negative input must raise ValueError')
suite = unittest.defaultTestLoader.loadTestsFromName('test_sum_squares')
assert suite.countTestCases() >= 4
assert unittest.TextTestRunner().run(suite).wasSuccessful()
print('INDEPENDENT_CHECK_PASSED')
"""


def check_collaboration(config, factory, root, mode):
    work = root / "workspace"
    work.mkdir(parents=True)
    allowed = {(work / name).resolve() for name in ("sum_squares.py", "test_sum_squares.py")}

    def confirm(request):
        return isinstance(request, FileWriteArgs) and (work / request.path).resolve() in allowed

    goal = (
        "Create sum_squares.py with sum_squares(n) returning the sum of squares from 1 through n. "
        "Zero returns zero; negative input raises ValueError. Create test_sum_squares.py with "
        "at least four stdlib unittest cases covering 0, 1, 10 and -1. Run the tests. "
        "Only create these two files; use no network or third-party packages."
    )
    report = run_collaboration_once(
        goal,
        mode=mode,
        tier="restricted",
        model=config.generator_model,
        planner_model=config.planner_model,
        evaluator_model=config.evaluator_model,
        max_rejections=1,
        client_factory=factory,
        allowed_root=str(work),
        console=Console(file=io.StringIO(), force_terminal=False),
        confirmer=confirm,
        plan_confirmer=headless_plan_confirmer("preauthorize"),
        required_candidate_files=("sum_squares.py", "test_sum_squares.py"),
    )
    verification = RestrictedBackend(allowed_root=str(work)).execute(INDEPENDENT_CHECK, Runtime())
    return {
        "mode": mode,
        "passed": report.status == "completed" and verification.success,
        "report": report.model_dump(mode="json"),
        "verification": verification.model_dump(mode="json"),
    }


def post_image(base, path, key, payload, timeout):
    parsed = urlsplit(base)
    connection = http.client.HTTPSConnection(parsed.hostname, parsed.port, timeout=timeout)
    try:
        connection.request(
            "POST",
            path,
            body=json.dumps(payload),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f"image HTTP status {response.status}")
        raw = response.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError("image response exceeds limit")
        return json.loads(raw)
    finally:
        connection.close()


def check_image(config, base, key, model, root, budget):
    if not budget.take():
        return {"model": model, "passed": False, "error": "request budget exhausted"}
    try:
        response = post_image(
            base,
            config.image_path,
            key,
            {
                "model": model,
                "prompt": "A red circle on a plain white background. No text.",
                "size": config.image_size,
                "n": 1,
                "response_format": "b64_json",
            },
            config.timeout_seconds,
        )
        data = base64.b64decode(response["data"][0]["b64_json"], validate=True)
        if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
            raise ValueError("expected PNG with IHDR")
        dimensions = list(struct.unpack(">II", data[16:24]))
        root.mkdir(parents=True, exist_ok=True)
        (root / "generated.png").write_bytes(data)
        expected = [int(n) for n in config.image_size.split("x")]
        return {
            "model": model,
            "passed": dimensions == expected,
            "dimensions": dimensions,
            "expected_dimensions": expected,
            "visual_review_required": True,
        }
    except Exception as error:
        return {"model": model, "passed": False, "error_type": type(error).__name__}


def run_acceptance(config, suites, base, key, output, secrets):
    budget = RequestBudget(config.max_requests)

    def factory(model):
        capability = ModelCapability(
            model_id=model,
            client_kind="openai_compatible",
            context_window=config.context_window,
            max_output_tokens=config.max_output_tokens,
            supports_thinking=False,
            thinking_always_on=False,
            supports_effort=False,
        )
        inner = OpenAICompatibleClient(
            capability, api_key=key, base_url=base + "/v1", max_attempts=1
        )
        return RecordedClient(
            inner, budget, output / "responses.jsonl", secrets, config.timeout_seconds
        )

    results = []
    if "text" in suites:
        for i, model in enumerate(config.text_models):
            results.append(check_text(model, factory, output / "text" / str(i + 1)))
    if "collaboration" in suites:
        for mode in ("duo", "triad"):
            results.append(check_collaboration(config, factory, output / mode, mode))
    if "images" in suites:
        for i, model in enumerate(config.image_models):
            results.append(
                check_image(config, base, key, model, output / "images" / str(i + 1), budget)
            )
    return {
        "mode": "live",
        "passed": bool(results) and all(r["passed"] for r in results),
        "requests_used": budget.used,
        "max_requests": budget.maximum,
        "results": results,
    }


def main(argv=None, *, environ=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "examples/gateway/acceptance.yaml")
    parser.add_argument(
        "--suite", choices=("text", "collaboration", "images", "all"), default="text"
    )
    policy = parser.add_mutually_exclusive_group()
    policy.add_argument("--allow-paid-requests", action="store_true")
    policy.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    environment = os.environ if environ is None else environ
    secrets = set(sensitive_env_values(environment))
    try:
        raw = args.config.read_bytes()
        if len(raw) > 65536:
            raise ValueError("configuration too large")
        config = AcceptanceConfig.model_validate(yaml.safe_load(raw))
        suites = ["text", "collaboration", "images"] if args.suite == "all" else [args.suite]
        if "images" in suites and not config.image_models:
            raise ValueError("no image models configured")
        if not args.allow_paid_requests:
            print(
                mask_secrets(
                    json.dumps(
                        {"mode": "dry-run", "suites": suites, "config": config.model_dump()},
                        indent=2,
                    ),
                    secrets,
                )
            )
            return 0
        key = environment[config.api_key_env]
        if not key.strip():
            raise ValueError("empty credential")
        secrets.add(key)
        base = gateway_root(environment[config.base_url_env])
        output = (
            args.output_dir
            or ROOT
            / "artifacts/model-acceptance"
            / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8])
        ).resolve()
        if not output.is_relative_to((ROOT / "artifacts").resolve()):
            raise ValueError("output must be under artifacts")
        output.mkdir(parents=True, exist_ok=False)
    except Exception as error:
        print(
            json.dumps(
                {
                    "mode": "preflight",
                    "passed": False,
                    "error_type": type(error).__name__,
                    "hint": (
                        "Check config schema, required environment variables, "
                        "HTTPS root and fresh artifacts output."
                    ),
                }
            )
        )
        return 2
    try:
        result = run_acceptance(config, suites, base, key, output, secrets)
    except Exception as error:
        result = {"mode": "live", "passed": False, "error_type": type(error).__name__}
    rendered = json.dumps(mask_audit_data(result, secrets), indent=2)
    (output / "summary.json").write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
