"""Offline contracts for the credentialed acceptance entry point."""

import base64
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_acceptance():
    path = ROOT / "scripts/live_model_acceptance.py"
    assert path.is_file(), "public acceptance entry point is missing"
    spec = importlib.util.spec_from_file_location("live_model_acceptance", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def configuration(module, **overrides):
    return module.AcceptanceConfig.model_validate(
        {
            "text_models": ["model"],
            "image_models": ["image"],
            "generator_model": "model",
            "planner_model": "model",
            "evaluator_model": "model",
            **overrides,
        }
    )


def test_default_dry_run_needs_no_key_or_network(tmp_path, monkeypatch, capsys):
    module = load_acceptance()
    config = tmp_path / "config.yaml"
    config.write_text(
        "text_models: [model]\nimage_models: [image]\n"
        "generator_model: model\nplanner_model: model\nevaluator_model: model\n"
    )
    monkeypatch.setattr(module, "run_acceptance", lambda *_: pytest.fail("dry-run sent requests"))
    assert module.main(["--config", str(config), "--suite", "all"], environ={}) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "dry-run"
    assert set(result["suites"]) == {"text", "collaboration", "images"}
    assert list(tmp_path.iterdir()) == [config]


def test_paid_preflight_does_not_expose_literal_config_secret(tmp_path, capsys):
    module = load_acceptance()
    path = tmp_path / "bad.yaml"
    path.write_text("api_key: private-example-value\n")
    assert module.main(["--config", str(path), "--allow-paid-requests"], environ={}) == 2
    assert "private-example-value" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://u:p@example.com",
        "https://example.com/v1",
        "https://example.com/?token=x",
        "https://example.com/#fragment",
    ],
)
def test_gateway_root_rejects_ambiguous_or_credentialed_urls(url):
    module = load_acceptance()
    with pytest.raises(ValueError):
        module.gateway_root(url)


def test_request_budget_and_response_redaction(tmp_path):
    module = load_acceptance()
    from forgeagent.client import MockClient
    from forgeagent.models import AssistantMessage, ClientError, TokenUsage

    inner = MockClient(
        [AssistantMessage(content="private-example-value", usage=TokenUsage(), stop_reason="stop")]
    )
    budget = module.RequestBudget(1)
    client = module.RecordedClient(
        inner, budget, tmp_path / "responses.jsonl", {"private-example-value"}
    )
    assert client.complete([]).content == "private-example-value"
    assert isinstance(client.complete([]), ClientError)
    assert budget.used == 1
    assert "private-example-value" not in (tmp_path / "responses.jsonl").read_text()


@pytest.mark.parametrize("correct", [True, False])
def test_collaboration_requires_independent_candidate_checks(tmp_path, monkeypatch, correct):
    module = load_acceptance()

    def runner(_goal, **kwargs):
        work = Path(kwargs["allowed_root"])
        expression = "n*(n+1)*(2*n+1)//6" if correct else "0"
        (work / "sum_squares.py").write_text(
            "def sum_squares(n):\n    if n < 0: raise ValueError('negative')\n    return "
            + expression
            + "\n"
        )
        (work / "test_sum_squares.py").write_text(
            "import unittest\nclass Checks(unittest.TestCase):\n"
            + "".join(f"    def test_{i}(self): self.assertTrue(True)\n" for i in range(4))
        )
        return SimpleNamespace(status="completed", model_dump=lambda **_: {"status": "completed"})

    monkeypatch.setattr(module, "run_collaboration_once", runner)
    result = module.check_collaboration(configuration(module), lambda _: None, tmp_path, "duo")
    assert result["passed"] is correct
    assert result["verification"]["success"] is correct


def test_image_dimension_mismatch_is_not_a_pass(tmp_path, monkeypatch):
    module = load_acceptance()
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZ1kAAAAASUVORK5CYII="
    )
    monkeypatch.setattr(
        module, "post_image", lambda *_: {"data": [{"b64_json": base64.b64encode(png).decode()}]}
    )
    result = module.check_image(
        configuration(module),
        "https://example.com",
        "private-example-value",
        "image",
        tmp_path,
        module.RequestBudget(1),
    )
    assert not result["passed"]
    assert result["dimensions"] == [1, 1]
    assert (tmp_path / "generated.png").read_bytes() == png


def test_image_budget_exhaustion_never_calls_provider(tmp_path, monkeypatch):
    module = load_acceptance()
    budget = module.RequestBudget(1)
    assert budget.take()
    monkeypatch.setattr(module, "post_image", lambda *_: pytest.fail("budget ignored"))
    result = module.check_image(
        configuration(module),
        "https://example.com",
        "private-example-value",
        "image",
        tmp_path,
        budget,
    )
    assert not result["passed"]


def test_gateway_examples_load_in_real_registry():
    from forgeagent.model_registry import load_registry

    root = ROOT / "examples/gateway"
    assert (root / "models.yaml").is_file()
    registry = load_registry(
        user_models_path=root / "models.yaml", user_config_path=root / "config.yaml"
    )
    assert {"glm-5.3-flash", "glm-5.3-flashx", "deepseek-v4.1-flash-1017"} <= registry.models.keys()
    assert registry.groups["acceptance_gateway"].api_key is None
    assert registry.groups["acceptance_gateway"].base_url is None


def test_paid_preflight_missing_environment_sends_nothing(tmp_path, monkeypatch, capsys):
    module = load_acceptance()
    monkeypatch.setattr(
        module, "run_acceptance", lambda *_: pytest.fail("missing key reached network")
    )
    assert module.main(["--allow-paid-requests"], environ={}) == 2
    assert json.loads(capsys.readouterr().out)["mode"] == "preflight"


def test_text_checks_exact_golden_set_and_closes_client(tmp_path, monkeypatch):
    module = load_acceptance()
    from forgeagent.client import MockClient
    from forgeagent.models import AssistantMessage, TokenUsage
    from tests.golden import runner

    inner = MockClient(
        [AssistantMessage(content="ACCEPTED", usage=TokenUsage(), stop_reason="stop")]
    )
    closed = []
    monkeypatch.setattr(inner, "close", lambda: closed.append(True))
    client = module.RecordedClient(
        inner, module.RequestBudget(1), tmp_path / "responses.jsonl", set()
    )
    selected = []

    def run(scenarios, **kwargs):
        selected.extend(s.scenario_id for s in scenarios)
        assert kwargs["mode"] == "real"
        assert kwargs["real_client"] is client
        return SimpleNamespace(exit_code=0, passed=5, total=5)

    monkeypatch.setattr(runner, "run_suite", run)
    monkeypatch.setattr(runner, "write_reports", lambda *_: ())
    result = module.check_text("model", lambda _: client, tmp_path / "text")
    assert result["passed"]
    assert set(selected) == {"G01", "G03", "G08", "G11", "G43"}
    assert closed == [True]
    assert isinstance(list(client.stream([]))[0], module.ClientError)


@pytest.mark.parametrize(
    "response",
    [
        {"data": [{"url": "https://example.com/image"}]},
        {"data": [{"b64_json": "not base64"}]},
        {"data": []},
    ],
)
def test_image_rejects_unsupported_or_malformed_response(tmp_path, monkeypatch, response):
    module = load_acceptance()
    monkeypatch.setattr(module, "post_image", lambda *_: response)
    result = module.check_image(
        configuration(module),
        "https://example.com",
        "test-key",
        "image",
        tmp_path,
        module.RequestBudget(1),
    )
    assert not result["passed"]
    assert not (tmp_path / "generated.png").exists()


def test_existing_output_directory_is_preserved(tmp_path, monkeypatch, capsys):
    module = load_acceptance()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    output = tmp_path / "artifacts" / "existing"
    output.mkdir(parents=True)
    marker = output / "keep.txt"
    marker.write_text("old evidence")
    config = ROOT / "examples/gateway/acceptance.yaml"
    assert (
        module.main(
            ["--config", str(config), "--allow-paid-requests", "--output-dir", str(output)],
            environ={"MAAS_SD_API_KEY": "example-key", "MAAS_BASE_URL": "https://example.com"},
        )
        == 2
    )
    assert marker.read_text() == "old evidence"
    assert "example-key" not in capsys.readouterr().out


def test_matching_image_dimensions_pass_header_check(tmp_path, monkeypatch):
    module = load_acceptance()
    encoded = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAwMCAO+jZ1kAAAAASUVORK5CYII="
    )
    monkeypatch.setattr(module, "post_image", lambda *_: {"data": [{"b64_json": encoded}]})
    result = module.check_image(
        configuration(module, image_size="1x1"),
        "https://example.com",
        "test-key",
        "image",
        tmp_path,
        module.RequestBudget(1),
    )
    assert result["passed"]
    assert result["visual_review_required"]


def test_redaction_handles_json_escaped_secret(tmp_path):
    module = load_acceptance()
    from forgeagent.client import MockClient
    from forgeagent.models import AssistantMessage, TokenUsage

    secret = 'private-"quoted"-value'
    inner = MockClient([AssistantMessage(content=secret, usage=TokenUsage(), stop_reason="stop")])
    path = tmp_path / "response.jsonl"
    client = module.RecordedClient(inner, module.RequestBudget(1), path, {secret})
    client.complete([])
    assert secret not in json.loads(path.read_text())["content"]
