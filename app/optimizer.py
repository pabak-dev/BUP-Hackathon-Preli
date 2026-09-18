"""Lossless, 24-hour linear program. The only objective is grid electricity cost."""

import math
import warnings
from threading import Lock

import numpy as np
from scipy.optimize import OptimizeWarning, linprog

from app.errors import InfeasibleError, ScheduleError
from app.guardrails import validate_directives
from app.schemas import Directive, OptimizeRequest, PlanHour

# HiGHS has process-global scheduler state; serialize these tiny local LPs.
_SOLVER_LOCK = Lock()


def optimize(request: OptimizeRequest, directives: list[Directive]) -> list[PlanHour]:
    validate_directives(request, directives)
    hours = sorted(request.hours, key=lambda item: item.hour)
    battery = request.battery
    solar = [item.solar_kwh for item in hours]
    reserve = [battery.minimum_energy_kwh] * 24
    caps: list[float | None] = [None] * 24
    charge_limit = [battery.max_charge_kwh_per_hour] * 24
    discharge_limit = [battery.max_discharge_kwh_per_hour] * 24
    for directive in directives:
        adjustment = directive.structured_adjustment
        if adjustment is None:
            continue
        for hour in adjustment.hours:
            match directive.directive_type:
                case "solar_reduction":
                    solar[hour] = hours[hour].solar_kwh * adjustment.factor
                case "minimum_battery_reserve":
                    reserve[hour] = max(reserve[hour], adjustment.minimum_energy_kwh)
                case "max_grid_window":
                    caps[hour] = (
                        min(caps[hour], adjustment.max_grid_kwh) if caps[hour] is not None else adjustment.max_grid_kwh
                    )
                case "no_charge_window":
                    charge_limit[hour] = 0
                case "no_discharge_window":
                    discharge_limit[hour] = 0

    # Blocks of explicit nonnegative variables: grid, solar, charge, discharge, E_after.
    grid, used, charge, discharge, energy = (np.arange(24) + offset for offset in (0, 24, 48, 72, 96))
    objective = np.zeros(120)
    objective[grid] = [item.tariff_bdt_per_kwh for item in hours]
    bounds = (
        [(0, caps[h]) for h in range(24)]
        + [(0, solar[h]) for h in range(24)]
        + [(0, charge_limit[h]) for h in range(24)]
        + [(0, discharge_limit[h]) for h in range(24)]
        + [(reserve[h], battery.capacity_kwh) for h in range(24)]
    )
    equalities = np.zeros((49, 120))
    rhs = np.zeros(49)
    for hour in range(24):
        equalities[hour, [grid[hour], used[hour], charge[hour], discharge[hour]]] = [1, 1, -1, 1]
        rhs[hour] = hours[hour].demand_kwh
        equalities[24 + hour, [energy[hour], charge[hour], discharge[hour]]] = [1, -1, 1]
        if hour:
            equalities[24 + hour, energy[hour - 1]] = -1
        else:
            rhs[24] = battery.initial_energy_kwh
    equalities[48, energy[23]] = 1
    rhs[48] = battery.initial_energy_kwh
    with _SOLVER_LOCK, warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=OptimizeWarning, message="Unrecognized options detected.*")
        result = linprog(
            objective,
            A_eq=equalities,
            b_eq=rhs,
            bounds=bounds,
            method="highs-ds",
            options={
                "time_limit": 3.0,
                "primal_feasibility_tolerance": 1e-9,
                "dual_feasibility_tolerance": 1e-9,
                "threads": 1,
                "parallel": False,
            },
        )
    if result.status == 2:
        raise InfeasibleError("Interpreted scenario is infeasible")
    if not result.success or result.x is None or not np.isfinite(result.x).all():
        raise ScheduleError("Solver did not produce a finite optimum")

    def nonnegative(value):
        value = float(value)
        if value < -1e-7 or not math.isfinite(value):
            raise ScheduleError("Invalid solver value")
        return max(0.0, value)

    plan = []
    for hour in range(24):
        # Net simultaneous flows. For a lossless battery this preserves balance, state,
        # objective, and all upper bounds, and cannot violate either prohibited window.
        delta = float(result.x[charge[hour]] - result.x[discharge[hour]])
        action = "charge" if delta > 0 else "discharge" if delta < 0 else "idle"
        plan.append(
            PlanHour(
                hour=hour,
                grid_kwh=nonnegative(result.x[grid[hour]]),
                solar_used_kwh=nonnegative(result.x[used[hour]]),
                battery_action=action,
                battery_kwh=abs(delta),
                battery_energy_after_kwh=nonnegative(result.x[energy[hour]]),
            )
        )
    return plan
