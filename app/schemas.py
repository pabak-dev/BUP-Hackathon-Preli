from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Number = Annotated[float, Field(ge=0, allow_inf_nan=False)]
HourNumber = Annotated[int, Field(ge=0, le=23)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class HourInput(StrictModel):
    hour: HourNumber
    demand_kwh: Number
    solar_kwh: Number
    tariff_bdt_per_kwh: Number


class Battery(StrictModel):
    capacity_kwh: Number
    initial_energy_kwh: Number
    minimum_energy_kwh: Number
    max_charge_kwh_per_hour: Number
    max_discharge_kwh_per_hour: Number

    @model_validator(mode="after")
    def valid_bounds(self):
        if not self.minimum_energy_kwh <= self.initial_energy_kwh <= self.capacity_kwh:
            raise ValueError("Battery minimum <= initial <= capacity is required")
        return self


class OptimizeRequest(StrictModel):
    scenario_id: str
    operator_notes: Annotated[list[str], Field(min_length=1, max_length=3)]
    hours: Annotated[list[HourInput], Field(min_length=24, max_length=24)]
    battery: Battery

    @field_validator("operator_notes")
    @classmethod
    def nonempty_notes(cls, notes):
        if any(not note.strip() for note in notes):
            raise ValueError("Operator notes must be nonempty")
        return notes

    @field_validator("hours")
    @classmethod
    def complete_hours(cls, hours):
        if {hour.hour for hour in hours} != set(range(24)):
            raise ValueError("Exactly one entry for each hour 0..23 is required")
        return hours


class Window(StrictModel):
    hours: list[HourNumber]

    @field_validator("hours")
    @classmethod
    def ordered_hours(cls, hours):
        if hours != sorted(set(hours)):
            raise ValueError("Applicable hours must be unique and sorted")
        return hours


class SolarAdjustment(Window):
    factor: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ReserveAdjustment(Window):
    minimum_energy_kwh: Number


class GridAdjustment(Window):
    max_grid_kwh: Number


DirectiveType = Literal[
    "solar_reduction", "minimum_battery_reserve", "no_charge_window", "no_discharge_window", "max_grid_window", "no_op"
]


class Directive(StrictModel):
    note_index: Annotated[int, Field(ge=0)]
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: SolarAdjustment | ReserveAdjustment | GridAdjustment | Window | None
    explanation: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def exact_shape(self):
        shapes = {
            "solar_reduction": SolarAdjustment,
            "minimum_battery_reserve": ReserveAdjustment,
            "max_grid_window": GridAdjustment,
            "no_charge_window": Window,
            "no_discharge_window": Window,
            "no_op": type(None),
        }
        if self.applies != (self.directive_type != "no_op"):
            raise ValueError("Invalid applies/no_op semantics")
        if type(self.structured_adjustment) is not shapes[self.directive_type]:
            raise ValueError("Adjustment shape does not match directive type")
        if not self.explanation.strip():
            raise ValueError("Explanation must be nonempty")
        return self


class Evidence(StrictModel):
    time_text: str | None
    value_text: str | None
    value_kind: Literal[
        "none", "remaining_fraction", "reduction_fraction", "reserve_fraction", "reserve_kwh", "grid_kwh"
    ]


class ModelEntry(StrictModel):
    interpretation: Directive
    evidence: Evidence


class ModelOutput(StrictModel):
    entries: list[ModelEntry]


class PlanHour(StrictModel):
    hour: HourNumber
    grid_kwh: Number
    solar_used_kwh: Number
    battery_action: Literal["charge", "discharge", "idle"]
    battery_kwh: Number
    battery_energy_after_kwh: Number


class OptimizeResponse(StrictModel):
    scenario_id: str
    directive_interpretation: list[Directive]
    hourly_plan: Annotated[list[PlanHour], Field(min_length=24, max_length=24)]
    total_grid_kwh: Number
    total_cost_bdt: Number
    peak_grid_kwh: Number
    plan_summary: str
