import copy

import pytest

from app.errors import InterpretationError
from app.guardrails import quantity, validate_model_output, validate_time
from app.schemas import OptimizeRequest
from tests.conftest import directive, model_output


@pytest.mark.parametrize(
    "text,hours",
    [
        ("1 PM to 3 PM", [13, 14]),
        ("13:00-15:00", [13, 14]),
        ("one until three", [13, 14]),
        ("11 AM until 1 PM", [11, 12]),
        ("noon until 2 PM", [12, 13]),
        ("10 PM to midnight", [22, 23]),
        ("midnight to 2 AM", [0, 1]),
        ("00:00 to 24:00", list(range(24))),
        ("all day", list(range(24))),
        ("hours 2, 5 and 8", [2, 5, 8]),
        ("from 1-3 PM", [13, 14]),
        ("from 02:00 until 05:00", [2, 3, 4]),
    ],
)
def test_time_normalization(text, hours):
    validate_time(text, hours)


@pytest.mark.parametrize(
    "text,hours",
    [
        ("1 PM to 3 PM", [13, 14, 15]),
        ("1 PM to 3 PM", [1, 2]),
        ("13:30 to 15:00", [13, 14]),
        ("all day", [12]),
        ("10 PM to 2 AM", [0, 1, 22, 23]),
        ("sometime later", [12]),
    ],
)
def test_bad_time_rejected(text, hours):
    with pytest.raises(InterpretationError):
        validate_time(text, hours)


@pytest.mark.parametrize(
    "text,fraction,expected",
    [
        ("half of forecast", True, 0.5),
        ("one-fifth of output", True, 0.2),
        ("eighty percent", True, 0.8),
        ("one hundred and twenty kWh", False, 120),
        ("1,234.5 kWh", False, 1234.5),
        ("0%", True, 0),
        ("100%", True, 1),
    ],
)
def test_numeric_evidence(text, fraction, expected):
    assert quantity(text, fraction) == pytest.approx(expected)


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
        "invention",
        "time",
        "quote",
        "polarity",
    ],
)
def test_invalid_model_data(base_request, mutation):
    base_request["operator_notes"] = ["Expect an 80% reduction in solar from 1 PM to 3 PM."]
    raw = model_output(base_request, [directive("solar_reduction", [13, 14], 0.2)])
    d = raw["entries"][0]["interpretation"]
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
    elif mutation == "invention":
        adj["factor"] = 0.6
    elif mutation == "time":
        adj["hours"] = [13, 14, 15]
    elif mutation == "quote":
        raw["entries"][0]["evidence"]["time_text"] = "12 PM to 2 PM"
    elif mutation == "polarity":
        adj["factor"] = 0.8
        raw["entries"][0]["evidence"]["value_kind"] = "remaining_fraction"
    with pytest.raises(InterpretationError):
        validate_model_output(OptimizeRequest.model_validate(base_request), raw)


def test_noop_semantics(base_request):
    raw = model_output(base_request, [directive()])
    assert validate_model_output(OptimizeRequest.model_validate(base_request), raw)[0].applies is False
    raw["entries"][0]["interpretation"]["structured_adjustment"] = {"hours": [1]}
    with pytest.raises(InterpretationError):
        validate_model_output(OptimizeRequest.model_validate(base_request), raw)


def test_reserve_percent_and_capacity(base_request):
    base_request["operator_notes"] = ["Keep 50% of battery capacity from 6 PM until 9 PM."]
    raw = model_output(base_request, [directive("minimum_battery_reserve", [18, 19, 20], 20)])
    request = OptimizeRequest.model_validate(base_request)
    validate_model_output(request, raw)
    invalid = copy.deepcopy(raw)
    invalid["entries"][0]["interpretation"]["structured_adjustment"]["minimum_energy_kwh"] = 100
    with pytest.raises(InterpretationError):
        validate_model_output(request, invalid)
