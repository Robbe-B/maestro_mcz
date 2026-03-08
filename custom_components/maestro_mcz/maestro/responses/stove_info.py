"""Bla."""

from dataclasses import dataclass
import logging

_LOGGER = logging.getLogger(__name__)


@dataclass
class StoveInfo:
    node: Node | None = None
    access_control: AccessControl | None = None

    unknown_fields: dict | None = None

    def __init__(self, json, from_mocked_response=False) -> None:
        if json is not None:
            if from_mocked_response:
                for k, v in json.items():
                    setattr(self, k, v)
            elif len(json) > 0:
                temp_unknown_fields = {}
                for key in json:
                    match key:
                        case "Node":
                            self.node = Node(json[key])
                        case "AccessControl":
                            self.access_control = AccessControl(json[key])
                        case _:
                            temp_unknown_fields[key] = json[key]
                            _LOGGER.warning(
                                "Unknown StoveInfo property '%s' received from API endpoint. If this happens, please make an issue on the github repository",
                                key,
                            )
                if temp_unknown_fields:
                    self.unknown_fields = temp_unknown_fields


@dataclass
class Node:
    id: str | None = None
    class_type: str | None = None
    node_type: str | None = None
    created: float | None = None
    modified: float | None = None
    name: str | None = None
    description: str | None = None
    unique_code: str | None = None
    sensor_set_type_id: str | None = None
    model_id: str | None = None
    time_zone_iana: str | None = None
    location: str | None = None
    is_banned: bool | None = None
    is_live_only: bool | None = None
    longitude: float | None = None
    latitude: float | None = None
    ssid_wifi: str | None = None
    mac_address_ble: str | None = None

    def __init__(self, json, from_mocked_response=False) -> None:
        if json is not None:
            if from_mocked_response:
                for k, v in json.items():
                    setattr(self, k, v)
            elif len(json) > 0:
                temp_unknown_fields = {}
                for key in json:
                    match key:
                        case "Id":
                            self.id = json[key]
                        case "ClassType":
                            self.class_type = json[key]
                        case "NodeType":
                            self.node_type = json[key]
                        case "Created":
                            self.created = json[key]
                        case "Modified":
                            self.modified = json[key]
                        case "Name":
                            self.name = json[key]
                        case "Description":
                            self.description = json[key]
                        case "UniqueCode":
                            self.unique_code = json[key]
                        case "SensorSetTypeId":
                            self.sensor_set_type_id = json[key]
                        case "ModelId":
                            self.model_id = json[key]
                        case "TimezoneIANA":
                            self.time_zone_iana = json[key]
                        case "Location":
                            self.location = json[key]
                        case "IsBanned":
                            self.is_banned = json[key]
                        case "IsLiveOnly":
                            self.is_live_only = json[key]
                        case "Longitude":
                            self.longitude = json[key]
                        case "Latitude":
                            self.latitude = json[key]
                        case "SSID_wifi":
                            self.ssid_wifi = json[key]
                        case "MAC_ADDRESS_BLE":
                            self.mac_address_ble = json[key]
                        case _:
                            temp_unknown_fields[key] = json[key]
                            _LOGGER.warning(
                                "Unknown StoveInfo Node property '%s' received from API endpoint. If this happens, please make an issue on the github repository",
                                key,
                            )
                if temp_unknown_fields:
                    self.unknown_fields = temp_unknown_fields


@dataclass
class AccessControl:
    id: str | None = None
    source_id: str | None = None
    source_type: str | None = None
    target_id: str | None = None
    target_type: str | None = None
    class_type: str | None = None
    roles: str | None = None
    role_operations: str | None = None
    is_top: bool | None = None
    created: float | None = None
    modified: float | None = None

    def __init__(self, json, from_mocked_response=False) -> None:
        if json is not None:
            if from_mocked_response:
                for k, v in json.items():
                    setattr(self, k, v)
            elif len(json) > 0:
                temp_unknown_fields = {}
                for key in json:
                    match key:
                        case "Id":
                            self.id = json[key]
                        case "SourceId":
                            self.source_id = json[key]
                        case "SourceType":
                            self.source_type = json[key]
                        case "TargetId":
                            self.target_id = json[key]
                        case "TargetType":
                            self.target_type = json[key]
                        case "ClassType":
                            self.class_type = json[key]
                        case "Roles":
                            self.role_operations = json[key]
                        case "RoleOperations":
                            self.unique_code = json[key]
                        case "IsTop":
                            self.is_top = json[key]
                        case "Created":
                            self.created = json[key]
                        case "Modified":
                            self.modified = json[key]
                        case _:
                            temp_unknown_fields[key] = json[key]
                            _LOGGER.warning(
                                "Unknown StoveInfo AccessControl property '%s' received from API endpoint. If this happens, please make an issue on the github repository",
                                key,
                            )
                if temp_unknown_fields:
                    self.unknown_fields = temp_unknown_fields
