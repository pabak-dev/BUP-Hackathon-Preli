import copy
import json
import time
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
def pace_live_requests(request):
    if "live" in request.keywords:
        time.sleep(17)  # Groq free tier: 8k tokens/minute; regression pacing, not service latency.


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
    """Explicit test double data. Never imported by production code or used as live evidence."""
    entries = []
    for d in directives:
        note = request["operator_notes"][d["note_index"]]
        kind = d["directive_type"]
        value_kind = "none"
        if kind == "solar_reduction":
            value_kind = (
                "reduction_fraction" if "reduction" in note.lower() or "by " in note.lower() else "remaining_fraction"
            )
        elif kind == "minimum_battery_reserve":
            value_kind = "reserve_fraction" if "%" in note or "percent" in note or "half" in note else "reserve_kwh"
        elif kind == "max_grid_window":
            value_kind = "grid_kwh"
        entries.append(
            {
                "interpretation": copy.deepcopy(d),
                "evidence": {
                    "time_text": None if kind == "no_op" else note,
                    "value_text": None if value_kind == "none" else note,
                    "value_kind": value_kind,
                },
            }
        )
    return {"entries": entries}


def mock_client(request, directives, capture=None):
    output = model_output(request, directives)

    def respond(http_request):
        if capture is not None:
            capture.append(json.loads(http_request.content))
        return httpx.Response(
            200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(output)}}]}
        )

    return TestClient(create_app(Settings(api_key="test-only-placeholder"), transport=httpx.MockTransport(respond)))
