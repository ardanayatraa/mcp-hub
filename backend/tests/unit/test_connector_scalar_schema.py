import pytest
from app.errors import HubError
from app.tools.schema_tools import validate_arguments, validate_input_schema


def schema(**properties):
    return {"type": "object", "additionalProperties": False, "properties": properties}


def test_opaque_references_and_bounded_business_strings_are_supported():
    reviewed = validate_input_schema(schema(ref={"type": "string", "maxLength": 1024},
                                           title={"type": "string", "maxLength": 512}))
    validate_arguments(reviewed, {"ref": "ref_"+"a"*700, "title": "order"})
    for name, maximum in [("ref", 1025), ("title", 513)]:
        with pytest.raises(HubError):
            validate_input_schema(schema(**{name: {"type": "string", "maxLength": maximum}}))


def test_typed_scalar_choices_and_decimal_bounds_are_validated():
    reviewed = validate_input_schema(schema(state={"type": "boolean", "enum": [True, False]},
                                           amount={"type": "number", "minimum": .25, "maximum": 1.5}))
    validate_arguments(reviewed, {"state": False, "amount": .5})
    with pytest.raises(HubError):
        validate_arguments(reviewed, {"amount": .1})
    for enum in [["wrong"], [1], [{}], [float("nan")]]:
        with pytest.raises(HubError):
            validate_input_schema(schema(state={"type": "boolean", "enum": enum}))
    with pytest.raises(HubError):
        validate_input_schema(schema(amount={"type": "number", "maximum": float("inf")}))
    with pytest.raises(HubError):
        validate_input_schema(schema(amount={"type": "number", "maximum": 10**1000}))
