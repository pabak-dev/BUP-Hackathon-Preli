import json

from app.schemas import ModelOutput


def provider_schema():
    """Portable strict JSON Schema; constraints still checked locally by Pydantic."""
    schema = ModelOutput.model_json_schema()

    def clean(node):
        if isinstance(node, dict):
            for key in ("title", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
                node.pop(key, None)
            for value in node.values():
                clean(value)
        elif isinstance(node, list):
            for value in node:
                clean(value)

    clean(schema)
    # Groq requires distinct object alternatives. The type is the discriminator.
    definitions = schema["$defs"]
    base = definitions["Directive"]
    alternatives = []
    for kind, shape in {
        "solar_reduction": "SolarAdjustment",
        "minimum_battery_reserve": "ReserveAdjustment",
        "max_grid_window": "GridAdjustment",
        "no_charge_window": "Window",
        "no_discharge_window": "Window",
        "no_op": None,
    }.items():
        variant = json.loads(json.dumps(base))
        variant["properties"]["directive_type"] = {"type": "string", "enum": [kind]}
        variant["properties"]["structured_adjustment"] = {"$ref": "#/$defs/" + shape} if shape else {"type": "null"}
        alternatives.append(variant)
    definitions["Directive"] = {"anyOf": alternatives}
    return schema
