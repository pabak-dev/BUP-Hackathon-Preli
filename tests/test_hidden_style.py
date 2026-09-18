import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.schemas import Directive, OptimizeRequest
from app.validator import validate_schedule
from tests.conftest import directive, mock_client

# Unseen phrasing/values, test data only. Live variants measure the language model itself.
VARIANTS = [
    (
        "For today's panel rinse, usable PV will be 30% of forecast between noon and 3 PM.",
        "solar_reduction",
        [12, 13, 14],
        0.3,
    ),
    ("Isolate the storage charging input from 03:00 to 06:00.", "no_charge_window", [3, 4, 5], None),
    (
        "Retain at least fifty percent of battery capacity from 7 PM to 10 PM.",
        "minimum_battery_reserve",
        [19, 20, 21],
        20,
    ),
    ("The battery's output must remain disabled between 16:00 and 18:00.", "no_discharge_window", [16, 17], None),
    ("Limit imported grid energy to 8 kWh per hour from 6 PM until 8 PM.", "max_grid_window", [18, 19], 8),
    ("During inspection from 10 AM to noon, only half of normal PV is usable.", "solar_reduction", [10, 11], 0.5),
    (
        "Preserve a 12 kWh emergency battery reserve between 18:00 and 22:00.",
        "minimum_battery_reserve",
        [18, 19, 20, 21],
        12,
    ),
    ("Energy must not enter the battery between 11 AM and 1 PM.", "no_charge_window", [11, 12], None),
    ("Rooftop output is reduced by 70 percent between 11:00 and 14:00.", "solar_reduction", [11, 12, 13], 0.3),
    ("During 19:00-22:00, keep utility intake below or equal to 9 kWh each hour.", "max_grid_window", [19, 20, 21], 9),
    ("Solar output is reduced to 70 percent from 1-3 PM.", "solar_reduction", [13, 14], 0.7),
    ("Rooftop washing from one until three leaves one-fifth of normal solar output.", "solar_reduction", [13, 14], 0.2),
    ("Battery charging is unavailable all day.", "no_charge_window", list(range(24)), None),
    ("Do not discharge between 10 PM and midnight.", "no_discharge_window", [22, 23], None),
    ("PV availability will be reduced by 100% from 12:00 to 13:00.", "solar_reduction", [12], 0),
    ("The campus newsletter changed its font today.", "no_op", None, None),
    ("Next month's battery workshop room has changed.", "no_op", None, None),
]


@pytest.mark.parametrize("variant", VARIANTS)
def test_hidden_style_offline(base_request, variant):
    note, kind, hours, value = variant
    base_request["operator_notes"] = [note]
    expected = directive(kind, hours, value)
    with mock_client(base_request, [expected]) as client:
        response = client.post("/optimize-energy", json=base_request)
    assert response.status_code == 200, response.text
    truth = [Directive.model_validate(expected)]
    validate_schedule(OptimizeRequest.model_validate(base_request), truth, response.json())


def test_multiple_directives(base_request):
    base_request["operator_notes"] = [
        "Keep 10 kWh in reserve from 18:00 to 22:00.",
        "Disable charging from 11 AM until 1 PM.",
        "The library poster has changed.",
    ]
    expected = [
        directive("minimum_battery_reserve", [18, 19, 20, 21], 10),
        directive("no_charge_window", [11, 12], index=1),
        directive(index=2),
    ]
    with mock_client(base_request, expected) as client:
        response = client.post("/optimize-energy", json=base_request)
    assert response.status_code == 200, response.text


@pytest.mark.live
@pytest.mark.parametrize("variant", VARIANTS)
def test_hidden_style_live(base_request, variant):
    note, kind, hours, value = variant
    base_request["operator_notes"] = [note]
    settings = Settings.from_env()
    assert settings.api_key, "Live tests require a configured provider key"
    with TestClient(create_app(settings)) as client:
        response = client.post("/optimize-energy", json=base_request)
    assert response.status_code == 200, response.text
    actual = response.json()["directive_interpretation"][0]
    expected = directive(kind, hours, value)
    for field in ("note_index", "applies", "directive_type", "structured_adjustment"):
        assert actual[field] == expected[field]
