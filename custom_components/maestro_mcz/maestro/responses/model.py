from dataclasses import dataclass, field
from uuid import UUID
from ..types.enums import TypeEnum

@dataclass
class Configuration:
    sensor_name: str
    type: TypeEnum
    visible: bool
    variants: list[str]
    sensor_id: UUID
    enabled: bool
    min: str
    max: str
    mappings: dict[str, int]

    def __init__(self, json) -> None:
        self.sensor_name = str(json["SensorName"])
        self.type = TypeEnum(json["Type"])
        self.visible = bool(json["Visible"])
        self.variants = [str(variant) for variant in json["Variants"]]
        self.sensor_id = UUID(json["SensorId"])
        self.enabled = bool(json["Enabled"])
        self.min = str(json["Min"])
        self.max = str(json["Max"])
        self.mappings = dict[str, int](json["Mappings"])

@dataclass
class ModelConfiguration:
    timed: bool
    configuration_name: str
    configurations: list[Configuration]
    configuration_id: UUID
    limitations: str

    def __init__(self, json) -> None:
        self.timed = bool(json["Timed"])
        self.configuration_name = str(json["ConfigurationName"])
        self.configurations = [Configuration(configuration) for configuration in json["Configurations"]]
        self.configuration_id = UUID(json["ConfigurationId"])
        self.limitations = str(json["Limitations"])

@dataclass
class Model:
    model_configurations: list[ModelConfiguration]
    model_name: str
    model_id: str
    sensor_set_type_id: str
    sensor_ids: list[UUID]
    properties: list[str]

    def __init__(self, json) -> None:
        self.model_configurations = [ModelConfiguration(model_configuration) for model_configuration in json["ModelConfigurations"]]
        self.model_name = str(json["ModelName"])
        self.model_id = str(json["ModelId"])
        self.sensor_set_type_id = str(json["SensorSetTypeId"])
        self.sensor_ids = [UUID(sensor_id) for sensor_id in json["SensorIds"]]
        self.properties = [str(property) for property in json["Properties"]]

@dataclass
class SensorConfiguration:
    configuration: Configuration
    configuration_id: str

    def __init__(self, configuration: Configuration, configuration_id: str) -> None:
        self.configuration = configuration
        self.configuration_id = configuration_id
