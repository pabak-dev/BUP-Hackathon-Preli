"""Independent replay of public serialized response; no solver/matrix/effective-profile reuse."""

import math

from pydantic import ValidationError

from app.errors import ScheduleError
from app.schemas import Directive, OptimizeRequest, OptimizeResponse

INTERNAL_TOLERANCE = 1e-6
JUDGE_TOLERANCE = 0.01


def validate_schedule(
    request: OptimizeRequest, directives: list[Directive], response: dict, tolerance: float = INTERNAL_TOLERANCE
) -> OptimizeResponse:
    def check(condition, message):
        if not condition:
            raise ScheduleError(message)

    def equal(left, right):
        return math.isclose(left, right, rel_tol=0, abs_tol=tolerance)

    try:
        parsed = OptimizeResponse.model_validate(response)
    except ValidationError:
        raise ScheduleError("Invalid response schema") from None
    check(parsed.scenario_id == request.scenario_id, "Scenario mismatch")
    check(parsed.directive_interpretation == directives, "Interpretation changed after validation")
    check([d.note_index for d in directives] == list(range(len(request.operator_notes))), "Invalid note coverage")
    plan = sorted(parsed.hourly_plan, key=lambda item: item.hour)
    check([item.hour for item in plan] == list(range(24)), "Invalid hourly coverage")
    inputs = {item.hour: item for item in request.hours}
    battery = request.battery
    before = battery.initial_energy_kwh
    for item in plan:
        original = inputs[item.hour]
        effective_solar = original.solar_kwh
        minimum = battery.minimum_energy_kwh
        grid_cap = math.inf
        no_charge = no_discharge = False
        solar_factor = None
        for directive in directives:
            adj = directive.structured_adjustment
            if adj is None or item.hour not in adj.hours:
                continue
            if directive.directive_type == "solar_reduction":
                check(solar_factor is None or solar_factor == adj.factor, "Ambiguous solar overlap")
                solar_factor = adj.factor
                effective_solar = original.solar_kwh * adj.factor
            elif directive.directive_type == "minimum_battery_reserve":
                minimum = max(minimum, adj.minimum_energy_kwh)
            elif directive.directive_type == "max_grid_window":
                grid_cap = min(grid_cap, adj.max_grid_kwh)
            elif directive.directive_type == "no_charge_window":
                no_charge = True
            elif directive.directive_type == "no_discharge_window":
                no_discharge = True
        charge = item.battery_kwh if item.battery_action == "charge" else 0.0
        discharge = item.battery_kwh if item.battery_action == "discharge" else 0.0
        check(item.battery_action != "idle" or item.battery_kwh == 0, "Idle must have zero magnitude")
        check(item.battery_action == "idle" or item.battery_kwh > 0, "Zero action must be idle")
        check(charge <= battery.max_charge_kwh_per_hour + tolerance, "Charge rate exceeded")
        check(discharge <= battery.max_discharge_kwh_per_hour + tolerance, "Discharge rate exceeded")
        check(not no_charge or charge <= tolerance, "No-charge directive violated")
        check(not no_discharge or discharge <= tolerance, "No-discharge directive violated")
        check(item.grid_kwh <= grid_cap + tolerance, "Grid cap exceeded")
        check(item.solar_used_kwh <= effective_solar + tolerance, "Effective solar exceeded")
        check(
            equal(item.grid_kwh + item.solar_used_kwh + discharge, original.demand_kwh + charge),
            "Energy balance failed",
        )
        after = before + charge - discharge
        check(equal(after, item.battery_energy_after_kwh), "Battery transition failed")
        check(minimum - tolerance <= after <= battery.capacity_kwh + tolerance, "Replayed battery bounds violated")
        check(
            minimum - tolerance <= item.battery_energy_after_kwh <= battery.capacity_kwh + tolerance,
            "Reported battery bounds violated",
        )
        before = after
    check(equal(before, battery.initial_energy_kwh), "Replayed battery neutrality failed")
    check(equal(plan[-1].battery_energy_after_kwh, battery.initial_energy_kwh), "Final battery neutrality failed")
    check(equal(parsed.total_grid_kwh, math.fsum(item.grid_kwh for item in plan)), "Grid total mismatch")
    check(
        equal(parsed.total_cost_bdt, math.fsum(item.grid_kwh * inputs[item.hour].tariff_bdt_per_kwh for item in plan)),
        "Cost total mismatch",
    )
    check(equal(parsed.peak_grid_kwh, max(item.grid_kwh for item in plan)), "Peak mismatch")
    return parsed
