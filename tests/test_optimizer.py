import copy
import random

import pytest

from app.errors import InfeasibleError, ScheduleError
from app.schemas import Directive, OptimizeRequest
from app.service import build_response
from app.validator import validate_schedule
from tests.conftest import directive


def test_input_order_and_determinism(base_request):
    ds = [Directive.model_validate(directive())]
    request = OptimizeRequest.model_validate(base_request)
    response = build_response(request, ds)
    base_request["hours"].reverse()
    assert build_response(OptimizeRequest.model_validate(base_request), ds) == response
    assert request.model_dump() != base_request  # Optimization did not mutate original.


def test_zero_and_full_battery(base_request):
    for capacity in (0, 40):
        base_request["battery"].update(
            capacity_kwh=capacity,
            initial_energy_kwh=capacity,
            minimum_energy_kwh=capacity,
            max_charge_kwh_per_hour=0,
            max_discharge_kwh_per_hour=0,
        )
        for h in base_request["hours"]:
            h.update(demand_kwh=0, solar_kwh=100, tariff_bdt_per_kwh=0)
        response = build_response(OptimizeRequest.model_validate(base_request), [Directive.model_validate(directive())])
        assert response["total_grid_kwh"] == response["total_cost_bdt"] == 0


def test_infeasible_is_detected(base_request):
    ds = [Directive.model_validate(directive("max_grid_window", list(range(24)), 0))]
    with pytest.raises(InfeasibleError):
        build_response(OptimizeRequest.model_validate(base_request), ds)


@pytest.mark.parametrize("seed", range(12))
def test_lp_matches_independent_integer_dynamic_program(base_request, seed):
    rng = random.Random(seed)
    base_request["battery"].update(
        capacity_kwh=6,
        initial_energy_kwh=3,
        minimum_energy_kwh=1,
        max_charge_kwh_per_hour=2,
        max_discharge_kwh_per_hour=2,
    )
    for hour in base_request["hours"]:
        hour.update(
            demand_kwh=rng.randrange(1, 8), solar_kwh=rng.randrange(0, 10), tariff_bdt_per_kwh=rng.randrange(0, 9)
        )
    states = {3: 0}
    for hour in base_request["hours"]:
        next_states = {}
        for before, cost in states.items():
            for after in range(1, 7):
                delta = after - before
                load = hour["demand_kwh"] + delta
                if abs(delta) > 2 or load < 0:
                    continue
                candidate = cost + max(0, load - hour["solar_kwh"]) * hour["tariff_bdt_per_kwh"]
                next_states[after] = min(next_states.get(after, float("inf")), candidate)
        states = next_states
    response = build_response(OptimizeRequest.model_validate(base_request), [Directive.model_validate(directive())])
    assert response["total_cost_bdt"] == pytest.approx(states[3], abs=1e-6)


@pytest.mark.parametrize(
    "field",
    [
        "grid_kwh",
        "solar_used_kwh",
        "battery_kwh",
        "battery_energy_after_kwh",
        "battery_action",
        "hour",
        "total_grid_kwh",
        "total_cost_bdt",
        "peak_grid_kwh",
        "scenario_id",
    ],
)
def test_replay_rejects_tampering(base_request, field):
    request = OptimizeRequest.model_validate(base_request)
    ds = [Directive.model_validate(directive())]
    response = copy.deepcopy(build_response(request, ds))
    if field == "scenario_id":
        response[field] = "different"
    elif field.startswith("total_") or field == "peak_grid_kwh":
        response[field] += 10
    elif field == "hour":
        response["hourly_plan"][0][field] = 1
    elif field == "battery_action":
        response["hourly_plan"][0][field] = "idle"
        response["hourly_plan"][0]["battery_kwh"] = 4
    else:
        response["hourly_plan"][0][field] += 10
    with pytest.raises(ScheduleError):
        validate_schedule(request, ds, response)
