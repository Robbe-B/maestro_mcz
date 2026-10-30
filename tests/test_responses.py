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
    assert len(fields(response_type)) == expected_count


@pytest.mark.parametrize(
    ("response_type", "attribute", "wire_name"),
    [
        (response_type, field.name, aliases.get(field.name, field.name))
        for response_type, aliases in (
            (State, STATE_ALIASES),
            (Status, STATUS_ALIASES),
            (Node, NODE_ALIASES),
        )
        for field in fields(response_type)
        if field.name != "unknown_fields"
    ],
)
def test_each_declared_payload_field(response_type, attribute, wire_name):
    parsed = response_type({wire_name: 17})
    assert getattr(parsed, attribute) == 17
    assert parsed.unknown_fields is None


@pytest.mark.parametrize(
    "response_type", [State, Status, Node, AccessControl, StoveInfo]
)
@pytest.mark.parametrize("empty", [None, {}])
def test_empty_payload(response_type, empty):
    parsed = response_type(empty)
    assert all(value is None for value in asdict(parsed).values())


@pytest.mark.parametrize(
    "response_type", [State, Status, Node, AccessControl, StoveInfo]
)
def test_unknown_fields_are_preserved_and_warned(response_type, caplog):
    parsed = response_type({"FutureField": {"value": 0}})
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
    assert getattr(response_type({wire_name: value}), attribute) == value


@pytest.mark.parametrize(
    "response_type", [State, Status, Node, AccessControl, StoveInfo]
)
def test_mocked_payload_mode(response_type):
    assert response_type({"synthetic": False}, True).synthetic is False


def test_nested_stove_info(stove_info_payload):
    parsed = StoveInfo(stove_info_payload)
    assert isinstance(parsed.node, Node)
    assert isinstance(parsed.access_control, AccessControl)
    assert parsed.node.id == "device-1"
    assert parsed.node.unique_code == "SERIAL-001"


def test_model_live_and_diagnostics_round_trip(model_payload):
    parsed = Model(model_payload)
    restored = Model(asdict(parsed), True)
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
    assert getattr(AccessControl({key: 42}), attribute) == 42


def test_access_control_roles():
    assert AccessControl({"Roles": ["owner"]}).roles == ["owner"]


def test_access_control_role_operations():
    assert AccessControl({"RoleOperations": ["read"]}).role_operations == ["read"]


def test_access_control_roles_and_operations_round_trip():
    parsed = AccessControl({"Roles": ["owner"], "RoleOperations": ["read"]})
    assert parsed.roles == ["owner"]
    assert parsed.role_operations == ["read"]
    assert not hasattr(parsed, "unique_code")
    restored = AccessControl(asdict(parsed), True)
    assert asdict(restored) == asdict(parsed)
