import asyncio
import json
from dataclasses import replace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.errors import InfeasibleError, ScheduleError
from app.main import create_app
from app.providers import FailFastAuthRequest, VertexAuth, google_schema
from tests.conftest import directive, model_output


def configured(**kwargs):
    return Settings(
        vertex_project_id="test-project",
        vertex_location="global",
        vertex_model="test-vertex",
        groq_api_key="test-groq-key",
        groq_model="test-groq",
        gemini_api_key="test-google-key",
        aistudio_model="test-studio",
        **kwargs,
    )


@pytest.fixture
def fake_adc(monkeypatch):
    calls = []

    async def headers(self, url):
        calls.append(url)
        return {"Authorization": "Bearer test-adc-token"}

    monkeypatch.setattr(VertexAuth, "headers", headers)
    return calls


def name_of(request):
    if request.url.host == "api.groq.com":
        return "groq"
    if request.url.host == "generativelanguage.googleapis.com":
        return "aistudio"
    return "vertex"


def success(name, output):
    text = json.dumps(output)
    if name == "groq":
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": text}}]})
    return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}]})


@pytest.mark.parametrize(
    "failure",
    [
        None,
        429,
        500,
        503,
        "timeout",
        "network",
        "deadline",
        "malformed",
        "schema",
        "refusal",
        "truncated",
        "structured-error",
    ],
)
def test_vertex_then_groq(base_request, fake_adc, monkeypatch, failure):
    calls = []
    output = model_output(base_request, [directive()])
    original_sleep = asyncio.sleep

    async def forbidden_sleep(delay, *args, **kwargs):
        assert delay == 0, "No pacing or backoff"
        return await original_sleep(delay, *args, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", forbidden_sleep)

    async def respond(request):
        name = name_of(request)
        calls.append(name)
        if name == "vertex" and failure is not None:
            if isinstance(failure, int):
                return httpx.Response(failure, text="secret provider body")
            if failure == "timeout":
                raise httpx.ReadTimeout("secret timeout")
            if failure == "network":
                raise httpx.ConnectError("secret network")
            if failure == "deadline":
                await asyncio.Event().wait()
            if failure == "malformed":
                return httpx.Response(200, text="not JSON")
            if failure == "schema":
                return success(name, model_output(base_request, [directive("solar_reduction", [24], 1.2)]))
            if failure == "refusal":
                return httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}})
            if failure == "truncated":
                return httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS"}]})
            return httpx.Response(400, json={"error": {"message": "schema unsupported"}})
        assert "evidence" not in json.dumps(json.loads(request.content).get("generationConfig", {}))
        return success(name, output)

    settings = configured(timeout_seconds=0.05 if failure == "deadline" else 6)
    with TestClient(create_app(settings, httpx.MockTransport(respond))) as client:
        response = client.post("/optimize-energy", json=base_request)
    assert response.status_code == 200, response.text
    assert response.json()["directive_interpretation"] == output["entries"]
    assert calls == (["vertex"] if failure is None else ["vertex", "groq"])


@pytest.mark.parametrize("all_fail", [False, True])
def test_third_provider_and_exhaustion(base_request, fake_adc, all_fail, caplog):
    calls = []

    def respond(request):
        name = name_of(request)
        calls.append(name)
        if name != "aistudio" or all_fail:
            return httpx.Response(429, text="private-error-token")
        assert request.headers["x-goog-api-key"] == "test-google-key"
        return success(name, model_output(base_request, [directive()]))

    with TestClient(create_app(configured(), httpx.MockTransport(respond))) as client:
        result = client.post("/optimize-energy", json=base_request)
    assert result.status_code == (500 if all_fail else 200)
    assert calls == ["vertex", "groq", "aistudio"]
    assert "private-error-token" not in result.text + caplog.text


def test_invalid_client_calls_no_provider(base_request, fake_adc):
    calls = []

    def respond(request):
        calls.append(request)
        raise AssertionError("Must not call a provider")

    del base_request["hours"]
    with TestClient(create_app(configured(), httpx.MockTransport(respond))) as client:
        assert client.post("/optimize-energy", json=base_request).status_code == 400
    assert calls == fake_adc == []


@pytest.mark.parametrize("error,status", [(InfeasibleError, 422), (ScheduleError, 500), (RuntimeError, 500)])
def test_math_failure_does_not_failover(base_request, fake_adc, monkeypatch, error, status):
    calls = []

    def respond(request):
        calls.append(name_of(request))
        return success("vertex", model_output(base_request, [directive()]))

    def fail(*args):
        raise error("private internal details")

    monkeypatch.setattr("app.main.build_response", fail)
    with TestClient(create_app(configured(), httpx.MockTransport(respond))) as client:
        result = client.post("/optimize-energy", json=base_request)
    assert result.status_code == status
    assert "private internal details" not in result.text
    assert calls == ["vertex"]


def test_adc_uses_official_credentials_and_scope(monkeypatch):
    credentials = Mock()

    def before(request, method, url, headers):
        headers["Authorization"] = "Bearer test"

    credentials.before_request.side_effect = before
    default = Mock(return_value=(credentials, "project"))
    monkeypatch.setattr("google.auth.default", default)
    auth = VertexAuth()
    for _ in range(2):
        assert asyncio.run(auth.headers("https://example.invalid")) == {"Authorization": "Bearer test"}
    assert default.call_count == 1
    assert default.call_args.kwargs["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
    assert credentials.before_request.call_count == 2


def test_auth_transport_is_bounded_and_fail_fast(monkeypatch):
    from google.auth.transport.requests import Request

    from app.errors import ProviderError

    call = Mock(return_value=Mock(status=429))
    monkeypatch.setattr(Request, "__call__", call)
    transport = FailFastAuthRequest()
    with pytest.raises(ProviderError):
        transport(url="https://example.invalid", timeout=120)
    assert call.call_count == 1
    assert call.call_args.kwargs["timeout"] == 2
    transport.session.close()


def test_missing_configuration_skips_provider(base_request, fake_adc):
    calls = []

    def respond(request):
        calls.append(name_of(request))
        return success("groq", model_output(base_request, [directive()]))

    with TestClient(create_app(replace(configured(), vertex_model=""), httpx.MockTransport(respond))) as client:
        assert client.post("/optimize-energy", json=base_request).status_code == 200
    assert calls == ["groq"] and not fake_adc


@pytest.mark.parametrize("order", [(), ("vertex", "vertex"), ("other",)])
def test_invalid_order(order):
    with pytest.raises(ValueError):
        Settings(provider_order=order)


@pytest.mark.parametrize("timeout", [0, -1, 8, float("inf"), float("nan")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        Settings(timeout_seconds=timeout)


def test_google_schema_is_inlined():
    schema = json.dumps(google_schema())
    assert "$ref" not in schema and "$defs" not in schema
    assert "additionalProperties" not in schema


@pytest.mark.parametrize("provider", ["vertex", "groq", "aistudio"])
@pytest.mark.parametrize(
    "kind,value",
    [
        ("no_op", None),
        ("solar_reduction", 0.2),
        ("minimum_battery_reserve", 20),
        ("no_charge_window", None),
        ("no_discharge_window", None),
        ("max_grid_window", 15),
    ],
)
def test_same_schema_through_every_adapter(base_request, fake_adc, provider, kind, value):
    output = model_output(base_request, [directive(kind, [13, 14], value)])
    before = json.dumps(base_request, sort_keys=True)
    calls = []

    def respond(request):
        calls.append(name_of(request))
        body = json.loads(request.content)
        if provider != "groq":
            assert body["generationConfig"]["responseSchema"]["type"] == "OBJECT"
        return success(provider, output)

    with TestClient(create_app(configured(provider_order=(provider,)), httpx.MockTransport(respond))) as client:
        response = client.post("/optimize-energy", json=base_request)
    assert response.status_code == 200
    assert response.json()["directive_interpretation"] == output["entries"]
    assert json.dumps(base_request, sort_keys=True) == before
    assert calls == [provider]


def test_adc_failure_immediately_uses_groq(base_request, monkeypatch):
    from app.errors import ProviderError

    async def fail(*args):
        raise ProviderError("private auth failure")

    monkeypatch.setattr(VertexAuth, "headers", fail)
    calls = []

    def respond(request):
        calls.append(name_of(request))
        return success("groq", model_output(base_request, [directive()]))

    with TestClient(create_app(configured(), httpx.MockTransport(respond))) as client:
        result = client.post("/optimize-energy", json=base_request)
    assert result.status_code == 200 and calls == ["groq"]


def test_env_configuration_is_explicit(monkeypatch):
    monkeypatch.setattr("app.config.load_dotenv", lambda: None)
    values = {
        "LLM_PROVIDER_ORDER": "vertex,groq,aistudio",
        "VERTEX_PROJECT_ID": "project",
        "VERTEX_LOCATION": "global",
        "VERTEX_MODEL": "chosen-vertex",
        "GROQ_API_KEY": "test-only-groq",
        "GROQ_MODEL": "chosen-groq",
        "GEMINI_API_KEY": "test-only-studio",
        "AISTUDIO_MODEL": "chosen-studio",
        "LLM_PROVIDER_TIMEOUT_SECONDS": "6",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert settings.ready and all(settings.configured(p) for p in settings.provider_order)
    assert settings.vertex_model == "chosen-vertex" and settings.groq_model == "chosen-groq"
    assert settings.aistudio_model == "chosen-studio"
    assert "test-only-groq" not in repr(settings) and "test-only-studio" not in repr(settings)


def test_production_has_no_pacing_or_linguistic_parser():
    import ast
    from pathlib import Path

    for name in ("llm_interpreter.py", "providers.py", "guardrails.py"):
        tree = ast.parse((Path("app") / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"sleep", "Semaphore"}
    tree = ast.parse(Path("app/guardrails.py").read_text())
    assert not any(isinstance(node, ast.Import) and any(a.name == "re" for a in node.names) for node in ast.walk(tree))
