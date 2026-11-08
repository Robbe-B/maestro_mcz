"""Explicit cloud response field contracts, including M1 and hydro fields."""

from dataclasses import asdict, fields

import pytest

from custom_components.maestro_mcz.maestro.controller.responses.model import Model
from custom_components.maestro_mcz.maestro.controller.responses.state import State
from custom_components.maestro_mcz.maestro.controller.responses.status import Status
from custom_components.maestro_mcz.maestro.controller.responses.stove_info import (
    AccessControl,
    Node,
    StoveInfo,
)


# The cloud sometimes spells a field differently from our Python attribute.
STATE_ALIASES = {
    "mode": "mod_lav_att",
    "status_timestamp": "StatusTimestamp",
    "last_stdt": "LastSTDT",
    "site_time_zone": "SiteTimeZone",
    "blocking_event_id": "BlockingEventId",
    "description": "Description",
    "is_connected": "IsConnected",
    "is_in_error": "IsInError",
    "is_live_only": "IsLiveOnly",
}
STATUS_ALIASES = STATE_ALIASES | {
    "status": "Status",
    "mod_lav_att": "mod_lav_att",
    "turbo_activation_timestamp": "TurboActivationTimestamp",
    "scheduled_turn_off_timestamp": "ScheduledTurnOffTimestamp",
    "is_crono_empty": "IsCronoEmpty",
    "is_ble_connected": "IsBLEConnected",
    "ssid_wifi": "SSID_wifi",
    "is_pump_active": "IsPumpActive",
    "is_config_valid": "isConfigValid",
}
NODE_ALIASES = {
    "id": "Id",
    "class_type": "ClassType",
    "node_type": "NodeType",
    "created": "Created",
    "modified": "Modified",
    "name": "Name",
    "description": "Description",
    "unique_code": "UniqueCode",
    "sensor_set_type_id": "SensorSetTypeId",
    "model_id": "ModelId",
    "time_zone_iana": "TimezoneIANA",
    "location": "Location",
    "is_banned": "IsBanned",
    "is_live_only": "IsLiveOnly",
    "longitude": "Longitude",
    "latitude": "Latitude",
    "ssid_wifi": "SSID_wifi",
    "mac_address_ble": "MAC_ADDRESS_BLE",
}


@pytest.mark.parametrize(
    "response_type,expected_count", [(State, 70), (Status, 145), (Node, 19)]
)
def test_baseline_schema_does_not_silently_drop_fields(response_type, expected_count):
    """Keep every supported reading, so a parser change cannot silently lose data."""
    # 1. Count the fields in this kind of stove response.
    actual_count = len(fields(response_type))
    # 2. The established field count must stay intact.
    assert actual_count == expected_count


def declared_payload_field_cases():
    """Give each supported field its own test, including renamed cloud fields."""
    test_cases = []
    response_types_and_aliases = (
        (State, STATE_ALIASES),
        (Status, STATUS_ALIASES),
        (Node, NODE_ALIASES),
    )
    for response_type, aliases in response_types_and_aliases:
        for response_field in fields(response_type):
            if response_field.name == "unknown_fields":
                continue
            attribute_name = response_field.name
            cloud_field_name = aliases.get(attribute_name, attribute_name)
            test_cases.append((response_type, attribute_name, cloud_field_name))
    return test_cases


@pytest.mark.parametrize(
    ("response_type", "attribute", "wire_name"),
    declared_payload_field_cases(),
)
def test_each_declared_payload_field(response_type, attribute, wire_name):
    """Put a cloud reading in the right place, rather than discarding or renaming it."""
    # 1. Send one field with an easily recognizable example value.
    parsed = response_type({wire_name: 17})
    # 2. It belongs in its expected attribute, not the unknown-fields collection.
    assert getattr(parsed, attribute) == 17
    assert parsed.unknown_fields is None


@pytest.mark.parametrize(
    "response_type", [State, Status, Node, AccessControl, StoveInfo]
)
@pytest.mark.parametrize("empty", [None, {}])
def test_empty_payload(response_type, empty):
    """Leave missing readings empty, so HA does not display invented measurements."""
    # 1. Parse a response containing no readings.
    parsed = response_type(empty)
    # 2. Every field should remain empty.
    for field_name, value in asdict(parsed).items():
        assert value is None, f"{field_name} should be empty"


@pytest.mark.parametrize(
    "response_type", [State, Status, Node, AccessControl, StoveInfo]
)
def test_unknown_fields_are_preserved_and_warned(response_type, caplog):
    """Keep unfamiliar readings for investigation when the cloud adds new fields."""
    # 1. Supply a field that this parser has never been taught about.
    parsed = response_type({"FutureField": {"value": 0}})
    # 2. Save the original data and warn, rather than silently dropping it.
    assert parsed.unknown_fields == {"FutureField": {"value": 0}}
    assert "FutureField" in caplog.text


@pytest.mark.parametrize("value", [None, 0, False, ""])
@pytest.mark.parametrize(
    "response_type,wire_name,attribute",
    [
        (State, "temp_amb_install", "temp_amb_install"),
        (Status, "IsConnected", "is_connected"),
        (Node, "UniqueCode", "unique_code"),
    ],
)
def test_falsy_values_are_not_replaced(response_type, wire_name, attribute, value):
    """Preserve zero, false, and empty values because they can be genuine stove readings."""
    # 1. Parse the small or empty value chosen for this case.
    parsed = response_type({wire_name: value})
    # 2. The value must not be replaced with a guessed default.
    assert getattr(parsed, attribute) == value


@pytest.mark.parametrize(
    "response_type", [State, Status, Node, AccessControl, StoveInfo]
)
def test_mocked_payload_mode(response_type):
    """Read saved reports faithfully so offline troubleshooting uses the original data."""
    # 1. Load a saved-report field instead of a live cloud field.
    parsed = response_type({"synthetic": False}, True)
    # 2. Its original value remains accessible.
    assert parsed.synthetic is False


def test_nested_stove_info(stove_info_payload):
    """Keep account permissions separate from stove identity so the right device is used."""
    # 1. Parse a response containing both stove details and access permissions.
    parsed = StoveInfo(stove_info_payload)
    # 2. Both sections are understood, and the stove keeps its own IDs.
    assert isinstance(parsed.node, Node)
    assert isinstance(parsed.access_control, AccessControl)
    assert parsed.node.id == "device-1"
    assert parsed.node.unique_code == "SERIAL-001"


def test_model_live_and_diagnostics_round_trip(model_payload):
    """Preserve supported controls when a live model is saved and replayed later."""
    # 1. Parse the live model, then save its report representation.
    parsed = Model(model_payload)
    saved_model = asdict(parsed)
    # 2. Read the saved representation back as an offline model.
    restored = Model(saved_model, True)
    # 3. No control information or identifiers should change.
    assert asdict(restored) == asdict(parsed)
    assert restored.model_name == "Synthetic Air Stove"
    configuration = restored.model_configurations[0]
    assert configuration.configuration_id == "config-Spegnimento"
    assert configuration.configurations[0].sensor_id == "id-com_on_off"


@pytest.mark.parametrize(
    "key,attribute",
    [
        ("Id", "id"),
        ("SourceId", "source_id"),
        ("SourceType", "source_type"),
        ("TargetId", "target_id"),
        ("TargetType", "target_type"),
        ("ClassType", "class_type"),
        ("IsTop", "is_top"),
        ("Created", "created"),
        ("Modified", "modified"),
    ],
)
def test_access_control_fields(key, attribute):
    """Read account permission fields correctly so access information is not lost."""
    # 1. Parse one cloud permission field.
    permissions = AccessControl({key: 42})
    # 2. Its value appears under the corresponding Python name.
    assert getattr(permissions, attribute) == 42


def test_access_control_roles():
    """Retain the account's role, rather than confusing it with device details."""
    # 1. The cloud says this account is an owner.
    permissions = AccessControl({"Roles": ["owner"]})
    # 2. Parsing should keep that role unchanged.
    assert permissions.roles == ["owner"]


def test_access_control_role_operations():
    """Retain allowed operations so an account's permissions remain understandable."""
    # 1. The cloud permits this account to read stove information.
    permissions = AccessControl({"RoleOperations": ["read"]})
    # 2. The parser should preserve that operation.
    assert permissions.role_operations == ["read"]


def test_access_control_roles_and_operations_round_trip():
    """Preserve permissions through report replay without inventing a stove serial number."""
    # 1. Parse an account with both a role and an allowed operation.
    parsed = AccessControl({"Roles": ["owner"], "RoleOperations": ["read"]})
    assert parsed.roles == ["owner"]
    assert parsed.role_operations == ["read"]
    assert not hasattr(parsed, "unique_code")
    # 2. Save and restore those permissions; the result must stay identical.
    restored = AccessControl(asdict(parsed), True)
    assert asdict(restored) == asdict(parsed)
