"""Validate model data and quoted evidence; never generate a directive from a note."""

import math
import re

from pydantic import ValidationError

from app.errors import InterpretationError
from app.schemas import Directive, ModelOutput, OptimizeRequest

SMALL = dict(
    zip(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
        range(20),
    )
)
TENS = dict(zip("twenty thirty forty fifty sixty seventy eighty ninety".split(), range(20, 100, 10)))
WORDS = {**SMALL, **TENS, "hundred": 100, "thousand": 1000}
WORD_PATTERN = re.compile(r"\b(?:" + "|".join(WORDS) + r")(?:[ -]+(?:and[ -]+)?(?:" + "|".join(WORDS) + r"))*\b")


def normalize(text: str) -> str:
    text = text.lower().replace("–", "-").replace("—", "-")
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    text = re.sub(r"\ba\.?\s*m\.?\b", "am", text)
    text = re.sub(r"\bp\.?\s*m\.?\b", "pm", text)
    fractions = {
        "half": "0.5",
        "a half": "0.5",
        "one half": "0.5",
        "one-half": "0.5",
        "quarter": "0.25",
        "a quarter": "0.25",
        "one quarter": "0.25",
        "one-quarter": "0.25",
        "one fifth": "0.2",
        "one-fifth": "0.2",
        "three quarters": "0.75",
        "three-quarters": "0.75",
        "one third": "0.3333333333333333",
        "one-third": "0.3333333333333333",
        "two thirds": "0.6666666666666666",
        "two-thirds": "0.6666666666666666",
    }
    for phrase in sorted(fractions, key=len, reverse=True):
        text = re.sub(r"\b" + re.escape(phrase) + r"\b", fractions[phrase], text)

    def number(match):
        total = part = 0
        for word in re.split(r"[ -]+", match.group()):
            if word == "and":
                continue
            value = WORDS[word]
            if value == 100:
                part = max(1, part) * value
            elif value == 1000:
                total += max(1, part) * value
                part = 0
            else:
                part += value
        return str(total + part)

    return WORD_PATTERN.sub(number, text)


CLOCK = r"(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)"
RANGE = re.compile(r"(?<![\d.])(" + CLOCK + r")\s*(?:until|to|till|and|-)\s*(" + CLOCK + r")(?!\d)")


def clock_candidates(token: str, end: bool, other: str) -> list[int]:
    token = token.strip()
    if token == "noon":
        return [12]
    if token == "midnight":
        return [24 if end else 0]
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", token)
    if not match:
        raise InterpretationError("Unrecognized clock expression")
    hour, minute, meridian = match.groups()
    hour = int(hour)
    if minute and minute != "00":
        raise InterpretationError("Only whole-hour windows are supported")
    if meridian:
        if not 1 <= hour <= 12:
            raise InterpretationError("Invalid 12-hour clock")
        result = hour % 12 + (12 if meridian == "pm" else 0)
        return [24 if end and result == 0 else result]
    if hour > 24 or (hour == 24 and not end):
        raise InterpretationError("Invalid clock hour")
    if minute is not None or hour > 12 or hour == 0:
        return [hour]
    other_meridian = re.search(r"(am|pm)\s*$", other)
    if other_meridian:
        # Shared suffix: 1-3 PM. Explicit crossing meridians should name both.
        return [hour % 12 + (12 if other_meridian[1] == "pm" else 0)]
    return sorted(set([hour % 12, hour % 12 + 12, *([24] if end and hour == 12 else [])]))


def validate_time(text: str, hours: list[int]) -> None:
    normalized = normalize(text)
    if re.search(r"\b(all day|entire day|whole day|full day|all 24 hours|entire 24.hour)\b", normalized):
        if hours != list(range(24)):
            raise InterpretationError("All-day hours disagree")
        return
    explicit = re.fullmatch(r"\s*(?:at\s+)?hours?\s+([\d,\s]+(?:and\s+\d+)?)\s*", normalized)
    if explicit and hours == sorted(set(map(int, re.findall(r"\d+", explicit[1])))):
        return
    matches = list(RANGE.finditer(normalized))
    if matches:
        alternatives = [set()]
        for match in matches:
            start_text, end_text = match.groups()
            possibilities = [
                set(range(start, end))
                for start in clock_candidates(start_text, False, end_text)
                for end in clock_candidates(end_text, True, start_text)
                if start < end
            ]
            if not possibilities:
                raise InterpretationError("Unresolved or cross-midnight window")
            alternatives = [old | new for old in alternatives for new in possibilities]
        if set(hours) not in alternatives:
            raise InterpretationError("Hours disagree with the quoted end-exclusive window")
        return
    raise InterpretationError("Time evidence cannot be safely normalized")


def quantity(text: str, fraction: bool) -> float:
    normalized = normalize(text)
    pattern = (
        r"(?<![\d.])([+-]?\d+(?:\.\d+)?)\s*(?:%|percent\b|per cent\b)"
        if fraction
        else r"(?<![\d.])([+-]?\d+(?:\.\d+)?)\s*(?:kwh\b|kilowatt[ -]?hours?\b)"
    )
    values = [float(x) / (100 if fraction else 1) for x in re.findall(pattern, normalized)]
    if not values and fraction:
        values = [
            float(x)
            for x in re.findall(
                r"(?<![\d.])(0(?:\.\d+)?|1(?:\.0+)?)\s*(?:of\b|remaining\b|remains\b|usable\b|$)", normalized
            )
        ]
    if len(values) != 1 or not math.isfinite(values[0]):
        raise InterpretationError("Numeric evidence must contain one supported quantity")
    return values[0]


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
    directives = [entry.interpretation for entry in output.entries]
    validate_directives(request, directives)
    for entry in output.entries:
        directive, evidence = entry.interpretation, entry.evidence
        note = request.operator_notes[directive.note_index]
        if directive.directive_type == "no_op":
            if evidence.time_text is not None or evidence.value_text is not None or evidence.value_kind != "none":
                raise InterpretationError("no_op must have no adjustment evidence")
            continue
        if not evidence.time_text or evidence.time_text not in note:
            raise InterpretationError("Time evidence must be an exact quote from the note")
        validate_time(evidence.time_text, directive.structured_adjustment.hours)
        if directive.directive_type in {"no_charge_window", "no_discharge_window"}:
            if evidence.value_kind != "none" or evidence.value_text is not None:
                raise InterpretationError("Window directives do not take numeric adjustments")
            continue
        if not evidence.value_text or evidence.value_text not in note:
            raise InterpretationError("Numeric evidence must be an exact quote from the note")
        kind = evidence.value_kind
        allowed = {
            "solar_reduction": {"remaining_fraction", "reduction_fraction"},
            "minimum_battery_reserve": {"reserve_fraction", "reserve_kwh"},
            "max_grid_window": {"grid_kwh"},
        }[directive.directive_type]
        if kind not in allowed:
            raise InterpretationError("Numeric evidence kind does not match directive")
        value = quantity(evidence.value_text, kind.endswith("fraction"))
        if kind.endswith("fraction") and not 0 <= value <= 1:
            raise InterpretationError("Fraction must be in [0,1]")
        if directive.directive_type == "solar_reduction":
            # Use the full original note so a quote cannot hide 'reduction' or 'to'.
            normalized = normalize(note)
            reduction = bool(
                re.search(
                    r"(?:reduc\w*|drop\w*|decreas\w*|cut|loss)\s+(?:in\s+\w+\s+)?by\b|(?:%|percent)\s+(?:reduction|drop|decrease|loss|cut)\b",
                    normalized,
                )
            )
            remaining = bool(
                re.search(
                    r"(?:reduc\w*|drop\w*|decreas\w*|cut)\s+to\b|\b(?:remain\w*|leave|leaves|usable|retain\w*)\b",
                    normalized,
                )
            )
            # Words like "usable" do not negate an explicit "reduced by" clause.
            explicit_to = bool(re.search(r"(?:reduc\w*|drop\w*|decreas\w*|cut)\s+to\b", normalized))
            if reduction and not explicit_to and kind != "reduction_fraction":
                raise InterpretationError("Reduction by a fraction must be subtracted from one")
            if remaining and not reduction and kind != "remaining_fraction":
                raise InterpretationError("Remaining fraction must not be complemented")
            expected = 1 - value if kind == "reduction_fraction" else value
            actual = directive.structured_adjustment.factor
        elif directive.directive_type == "minimum_battery_reserve":
            expected = value * request.battery.capacity_kwh if kind == "reserve_fraction" else value
            actual = directive.structured_adjustment.minimum_energy_kwh
        else:
            expected, actual = value, directive.structured_adjustment.max_grid_kwh
        if not math.isclose(expected, actual, abs_tol=1e-7, rel_tol=1e-10):
            raise InterpretationError("Numeric adjustment disagrees with quoted evidence")
    return directives
