from concurrent.futures import ThreadPoolExecutor

import pytest

from app.errors import InterpretationError, ScheduleError
from app.guardrails import validate_model_output
from app.schemas import Directive, OptimizeRequest
from app.service import build_response
from app.validator import validate_schedule
from tests.conftest import directive, mock_client, model_output


@pytest.mark.parametrize(
    "kind", ["solar_reduction", "minimum_battery_reserve", "no_charge_window", "no_discharge_window", "max_grid_window"]
)
def test_replay_rejects_a_feasible_plan_that_ignores_directive(base_request, kind):
    request = OptimizeRequest.model_validate(base_request)
    response = build_response(request, [Directive.model_validate(directive())])
    # Find a genuinely active flow in the independently solved base schedule, then
    # impose a rule it violates. Energy and battery accounting remain untouched.
    if kind == "solar_reduction":
        item = next(p for p in response["hourly_plan"] if p["solar_used_kwh"] > 0)
        value = 0
    elif kind == "minimum_battery_reserve":
        item = min(response["hourly_plan"], key=lambda p: p["battery_energy_after_kwh"])
        value = request.battery.capacity_kwh
    elif kind == "max_grid_window":
        item = next(p for p in response["hourly_plan"] if p["grid_kwh"] > 0)
        value = 0
    else:
        action = "charge" if kind == "no_charge_window" else "discharge"
        item = next(p for p in response["hourly_plan"] if p["battery_action"] == action)
        value = None
    truth = [Directive.model_validate(directive(kind, [item["hour"]], value))]
    response["directive_interpretation"] = [d.model_dump() for d in truth]
    with pytest.raises(ScheduleError):
        validate_schedule(request, truth, response)


def test_overlapping_unequal_solar_factors_fail_without_invented_composition(base_request):
    base_request["operator_notes"] = ["Keep solar at 50% from 1 PM to 3 PM.", "Keep solar at 20% from 2 PM to 4 PM."]
    expected = [directive("solar_reduction", [13, 14], 0.5), directive("solar_reduction", [14, 15], 0.2, index=1)]
    with pytest.raises(InterpretationError, match="composition"):
        validate_model_output(OptimizeRequest.model_validate(base_request), model_output(base_request, expected))


def test_overlapping_reserves_and_caps_are_all_applied(base_request):
    base_request["operator_notes"] = ["reserve A", "reserve B", "cap"]
    ds = [
        Directive.model_validate(d)
        for d in [
            directive("minimum_battery_reserve", [17, 18, 19], 10),
            directive("minimum_battery_reserve", [18, 19, 20], 20, index=1),
            directive("max_grid_window", [19, 20], 8, index=2),
        ]
    ]
    result = build_response(OptimizeRequest.model_validate(base_request), ds)
    for hour in (18, 19, 20):
        assert result["hourly_plan"][hour]["battery_energy_after_kwh"] >= 20 - 1e-6
    for hour in (19, 20):
        assert result["hourly_plan"][hour]["grid_kwh"] <= 8 + 1e-6


def test_concurrent_requests_share_no_scenario_state(base_request):
    with mock_client(base_request, [directive()]) as client:

        def call(index):
            payload = {**base_request, "scenario_id": str(index)}
            response = client.post("/optimize-energy", json=payload)
            assert response.status_code == 200
            return response.json()

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(call, range(4)))
    assert [r["scenario_id"] for r in results] == ["0", "1", "2", "3"]
    assert all(r["hourly_plan"] == results[0]["hourly_plan"] for r in results)
