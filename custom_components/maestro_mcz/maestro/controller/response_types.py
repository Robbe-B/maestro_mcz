"""Describe raw response dictionaries before their fields are parsed.

``JsonObject`` gives raw fields a dictionary type. Its values intentionally use
``Any`` at this external-data boundary. Neither the alias nor the helper below
validates field names, required fields, or field types.
"""

from typing import Any

type JsonObject = dict[str, Any]


def require_json_object(value: object) -> JsonObject:
    """Require a dictionary without copying or validating its keys or contents.

    Live responses can decode to lists or scalars too. Reject those before a
    parser expects named fields. Saved-report replay uses the same check at its
    own parsing entry points; this is not recursive JSON or schema validation.
    """
    if not isinstance(value, dict):
        raise TypeError("JSON response must be an object")
    return value
