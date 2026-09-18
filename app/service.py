import math

from app.optimizer import optimize
from app.schemas import OptimizeRequest, OptimizeResponse
from app.validator import validate_schedule


def build_response(request: OptimizeRequest, directives) -> dict:
    plan = optimize(request, directives)
    prices = {item.hour: item.tariff_bdt_per_kwh for item in request.hours}
    applicable = sum(d.applies for d in directives)
    response = OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directives,
        hourly_plan=plan,
        total_grid_kwh=math.fsum(item.grid_kwh for item in plan),
        total_cost_bdt=math.fsum(item.grid_kwh * prices[item.hour] for item in plan),
        peak_grid_kwh=max(item.grid_kwh for item in plan),
        plan_summary=f"Minimum grid cost with {applicable} applicable directive(s). Solar and battery scheduling satisfy all constraints and restore the starting battery energy.",
    )
    serialized = response.model_dump(mode="json")
    validate_schedule(request, directives, serialized)
    return serialized
