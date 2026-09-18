import copy
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
PACK = json.loads((ROOT / "BUP_CSE_FEST_2026_Preli_Public_Sample_Cases.json").read_text(encoding="utf-8-sig"))
CASES = PACK["cases"]


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="Run tests against the configured real LLM (uses quota)")


@pytest.fixture(autouse=True)
def forbid_live_network(request, monkeypatch):
    if "live" not in request.keywords:

        async def blocked(*args, **kwargs):
            raise AssertionError("Offline tests must never use external HTTP")

        def blocked_sync(*args, **kwargs):
            raise AssertionError("Offline tests must never use external authentication HTTP")

        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
        import requests

        monkeypatch.setattr(requests.Session, "request", blocked_sync)


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--live"):
        for item in items:
            if "live" in item.keywords:
                item.add_marker(pytest.mark.skip(reason="Requires --live and a configured provider key"))


@pytest.fixture
def base_request():
    return {
        "scenario_id": "synthetic-test",
        "operator_notes": ["The cafeteria menu is printed."],
        "hours": [
            {
                "hour": h,
                "demand_kwh": 10,
                "solar_kwh": 12 if 9 <= h < 16 else 0,
                "tariff_bdt_per_kwh": 2 if h < 6 else 8,
            }
            for h in range(24)
        ],
        "battery": {
            "capacity_kwh": 40,
            "initial_energy_kwh": 20,
            "minimum_energy_kwh": 5,
            "max_charge_kwh_per_hour": 10,
            "max_discharge_kwh_per_hour": 10,
        },
    }


def directive(kind="no_op", hours=None, value=None, index=0):
    adj = None if kind == "no_op" else {"hours": hours}
    field = {
        "solar_reduction": "factor",
        "minimum_battery_reserve": "minimum_energy_kwh",
        "max_grid_window": "max_grid_kwh",
    }.get(kind)
    if field:
        adj[field] = value
    return {
        "note_index": index,
        "applies": kind != "no_op",
        "directive_type": kind,
        "structured_adjustment": adj,
        "explanation": "Synthetic test interpretation.",
    }


def model_output(request, directives):
    return {"entries": copy.deepcopy(directives)}


def mock_client(request, directives, capture=None):
    output = model_output(request, directives)

    def respond(http_request):
        if capture is not None:
            capture.append(json.loads(http_request.content))
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]}
        )

    return TestClient(
        create_app(
            Settings(provider_order=("groq",), groq_api_key="test-only-placeholder", groq_model="test-model"),
            transport=httpx.MockTransport(respond),
        )
    )
