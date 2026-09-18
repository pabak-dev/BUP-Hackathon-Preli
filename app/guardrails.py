"""Validate structure and mathematics, never reinterpret natural language."""

from pydantic import ValidationError

from app.errors import InterpretationError
from app.schemas import Directive, ModelOutput, OptimizeRequest


def validate_directives(request: OptimizeRequest, directives: list[Directive]) -> None:
    if len(directives) != len(request.operator_notes) or [d.note_index for d in directives] != list(
        range(len(request.operator_notes))
    ):
        raise InterpretationError("Exactly one ordered interpretation is required per note")
    solar_factors: dict[int, float] = {}
    for directive in directives:
        adjustment = directive.structured_adjustment
        if (
            directive.directive_type == "minimum_battery_reserve"
            and adjustment.minimum_energy_kwh > request.battery.capacity_kwh
        ):
            raise InterpretationError("Reserve exceeds capacity")
        if directive.directive_type == "solar_reduction":
            for hour in adjustment.hours:
                if hour in solar_factors and solar_factors[hour] != adjustment.factor:
                    raise InterpretationError("Overlapping unequal solar factors have no specified composition rule")
                solar_factors[hour] = adjustment.factor


def validate_model_output(request: OptimizeRequest, raw: object) -> list[Directive]:
    try:
        output = ModelOutput.model_validate(raw)
    except ValidationError:
        raise InterpretationError("Model JSON does not match the required schema") from None
    validate_directives(request, output.entries)
    return output.entries
