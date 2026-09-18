import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import directive, mock_client, model_output


def test_health_and_repeated_requests(base_request):
    calls = []
    with mock_client(base_request, [directive()], calls) as client:
        assert client.get("/health").json() == {"status": "ok"}
        responses = [client.post("/optimize-energy", json=base_request) for _ in range(4)]
    assert all(r.status_code == 200 for r in responses)
    assert all(r.json() == responses[0].json() for r in responses)
    assert len(calls) == 4  # Model is on the path for every request, even repeated notes.


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "extra",
        "hours",
        "duplicate",
        "empty_notes",
        "many_notes",
        "blank_note",
        "string_number",
        "boolean_number",
        "float_hour",
        "negative",
        "battery",
    ],
)
def test_structural_invalidity_is_400(base_request, change):
    if change == "missing":
        del base_request["battery"]
    elif change == "extra":
        base_request["unknown"] = 2
    elif change == "hours":
        base_request["hours"].pop()
    elif change == "duplicate":
        base_request["hours"][23]["hour"] = 22
    elif change == "empty_notes":
        base_request["operator_notes"] = []
    elif change == "many_notes":
        base_request["operator_notes"] *= 4
    elif change == "blank_note":
        base_request["operator_notes"] = ["  "]
    elif change == "string_number":
        base_request["hours"][0]["demand_kwh"] = "12"
    elif change == "boolean_number":
        base_request["hours"][0]["demand_kwh"] = True
    elif change == "float_hour":
        base_request["hours"][0]["hour"] = 0.0
    elif change == "negative":
        base_request["hours"][0]["solar_kwh"] = -1
    elif change == "battery":
        base_request["battery"]["initial_energy_kwh"] = 1000
    calls = []
    with mock_client(base_request, [], calls) as client:
        assert client.post("/optimize-energy", json=base_request).status_code == 400
    assert not calls


@pytest.mark.parametrize("raw", ["{", "null", "[]", '{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}', '"text"'])
def test_malformed_json(raw):
    with TestClient(create_app(Settings(api_key="test"))) as client:
        result = client.post("/optimize-energy", content=raw, headers={"Content-Type": "application/json"})
    assert result.status_code == 400


@pytest.mark.parametrize("status", [401, 429, 500])
def test_provider_errors_safe(base_request, status, caplog):
    secret = "do-not-expose-this-value"
    calls = []

    def fail(request):
        calls.append(request)
        return httpx.Response(status, text=secret)

    with TestClient(create_app(Settings(api_key=secret), httpx.MockTransport(fail))) as client:
        response = client.post("/optimize-energy", json=base_request)
        assert client.get("/health").status_code == 200
    assert response.status_code == 500
    assert secret not in response.text + caplog.text
    assert len(calls) == (1 if status == 401 else 2)


def test_repair_once(base_request):
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        content = "{bad" if len(calls) == 1 else json.dumps(model_output(base_request, [directive()]))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}]})

    with TestClient(create_app(Settings(api_key="test"), httpx.MockTransport(respond))) as client:
        response = client.post("/optimize-energy", json=base_request)
    assert response.status_code == 200
    assert len(calls) == 2
    assert "{bad" not in json.dumps(calls[-1])


@pytest.mark.parametrize("mode", ["timeout", "malformed", "refusal", "truncated"])
def test_unrecoverable_model_failure(base_request, mode):
    calls = []

    def respond(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("secret")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "length" if mode == "truncated" else "stop",
                        "message": {"content": "{}", "refusal": "no" if mode == "refusal" else None},
                    }
                ]
            },
        )

    with TestClient(create_app(Settings(api_key="test"), httpx.MockTransport(respond))) as client:
        response = client.post("/optimize-energy", json=base_request)
    assert response.status_code == 500
    assert len(calls) == 2


def test_missing_key_is_not_ready(base_request):
    with TestClient(create_app(Settings())) as client:
        assert client.get("/health").status_code == 500
        assert client.post("/optimize-energy", json=base_request).status_code == 500
