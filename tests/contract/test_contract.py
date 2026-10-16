from routeflow.contracts import check_compatibility, schema


def test_schemas_are_valid() -> None:
    from jsonschema import Draft202012Validator

    for version in (1, 2):
        Draft202012Validator.check_schema(schema(version))
    check_compatibility()
