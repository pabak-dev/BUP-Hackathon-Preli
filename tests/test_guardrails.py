import copy

import pytest

from app.errors import InterpretationError
from app.guardrails import validate_model_output
from app.schemas import OptimizeRequest
from tests.conftest import directive, model_output


@pytest.mark.parametrize(
    "mutation",
    [
        "extra",
        "type",
        "applies",
        "duplicate_hours",
        "unsorted",
        "float_hour",
        "bool_hour",
        "range",
        "index",
        "missing",
        "factor",
    ],
)
def test_invalid_model_data(base_request, mutation):
    base_request["operator_notes"] = ["Expect an 80% reduction in solar from 1 PM to 3 PM."]
    raw = model_output(base_request, [directive("solar_reduction", [13, 14], 0.2)])
    d = raw["entries"][0]
    adj = d["structured_adjustment"]
    if mutation == "extra":
        adj["demand_kwh"] = 3
    elif mutation == "type":
        d["directive_type"] = "demand_reduction"
    elif mutation == "applies":
        d["applies"] = False
    elif mutation == "duplicate_hours":
        adj["hours"] = [13, 13]
    elif mutation == "unsorted":
        adj["hours"] = [14, 13]
    elif mutation == "float_hour":
        adj["hours"] = [13.0, 14]
    elif mutation == "bool_hour":
        adj["hours"] = [True]
    elif mutation == "range":
        adj["hours"] = [24]
    elif mutation == "index":
        d["note_index"] = 1
    elif mutation == "missing":
        raw["entries"] = []
    elif mutation == "factor":
        adj["factor"] = 1.1
    with pytest.raises(InterpretationError):
        validate_model_output(OptimizeRequest.model_validate(base_request), raw)


def test_noop_semantics(base_request):
    raw = model_output(base_request, [directive()])
    assert validate_model_output(OptimizeRequest.model_validate(base_request), raw)[0].applies is False
    raw["entries"][0]["structured_adjustment"] = {"hours": [1]}
    with pytest.raises(InterpretationError):
        validate_model_output(OptimizeRequest.model_validate(base_request), raw)


def test_reserve_percent_and_capacity(base_request):
    base_request["operator_notes"] = ["Keep 50% of battery capacity from 6 PM until 9 PM."]
    raw = model_output(base_request, [directive("minimum_battery_reserve", [18, 19, 20], 20)])
    request = OptimizeRequest.model_validate(base_request)
    validate_model_output(request, raw)
    invalid = copy.deepcopy(raw)
    invalid["entries"][0]["structured_adjustment"]["minimum_energy_kwh"] = 100
    with pytest.raises(InterpretationError):
        validate_model_output(request, invalid)


@pytest.mark.parametrize(
    "note",
    [
        "দুপুর একটা থেকে তিনটা চার্জ বন্ধ রাখুন।",
        "No cargar entre la una y las tres.",
        "午後一時から三時まで充電しないでください。",
        "Unfamiliar phrasing understood by the model",
    ],
)
def test_language_is_model_responsibility(base_request, note):
    base_request["operator_notes"] = [note]
    raw = model_output(base_request, [directive("no_charge_window", [13, 14])])
    result = validate_model_output(OptimizeRequest.model_validate(base_request), raw)
    assert result[0].structured_adjustment.hours == [13, 14]


@pytest.mark.parametrize(
    "kind,field,value",
    [
        ("solar_reduction", "factor", float("nan")),
        ("solar_reduction", "factor", -0.1),
        ("minimum_battery_reserve", "minimum_energy_kwh", -1),
        ("minimum_battery_reserve", "minimum_energy_kwh", float("inf")),
        ("max_grid_window", "max_grid_kwh", -1),
        ("max_grid_window", "max_grid_kwh", float("inf")),
    ],
)
def test_finite_numeric_bounds(base_request, kind, field, value):
    raw = model_output(base_request, [directive(kind, [0, 23], value)])
    with pytest.raises(InterpretationError):
        validate_model_output(OptimizeRequest.model_validate(base_request), raw)


@pytest.mark.parametrize(
    "kind", ["solar_reduction", "minimum_battery_reserve", "max_grid_window", "no_charge_window", "no_discharge_window"]
)
def test_required_shape_and_no_scenario_mutations(base_request, kind):
    raw = model_output(base_request, [directive(kind, [0, 23], 0)])
    request = OptimizeRequest.model_validate(base_request)
    validate_model_output(request, raw)
    raw["entries"][0]["structured_adjustment"] = None
    with pytest.raises(InterpretationError):
        validate_model_output(request, raw)
    raw = model_output(base_request, [directive(kind, [0], 0)])
    raw["battery"] = {"capacity_kwh": 1000}
    with pytest.raises(InterpretationError):
        validate_model_output(request, raw)


def test_note_order_and_coverage(base_request):
    base_request["operator_notes"] *= 2
    request = OptimizeRequest.model_validate(base_request)
    for entries in ([directive(), directive()], [directive(index=1), directive()], [directive()]):
        with pytest.raises(InterpretationError):
            validate_model_output(request, {"entries": entries})
