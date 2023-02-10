from dataclasses import dataclass
from uuid import UUID
from ..types.mode import TypeEnum

@dataclass
class Configuration:
    sensor_name: str
    type: TypeEnum
    visible: bool
    variants: list[str] 
    sensor_id: str
    enabled: bool
    min: object
    max: object
    mappings: dict[str, int]

    def __init__(self, json) -> None:
        self.sensor_name = json["SensorName"]
        self.type = json["Type"]
        self.visible = json["Visible"]
        self.variants = json["Variants"]
        self.sensor_id = json["SensorId"]
        self.enabled = json["Enabled"]
        self.min = json["Min"]
        self.max = json["Max"]
        self.mappings = json["Mappings"]

@dataclass
class ModelConfiguration:
    timed: bool
    configuration_name: str
    configurations: list[Configuration]
    configuration_id: UUID
    limitations: str

    def __init__(self, json) -> None:
        self.timed = json["Timed"]
        self.configuration_name = json["ConfigurationName"]
        self.configurations = json["Configurations"]
        self.configuration_id = json["ConfigurationId"]
        self.limitations = json["Limitations"]

@dataclass
class Model:
    model_configurations: list[ModelConfiguration]
    model_name: str
    model_id: str
    sensor_set_type_id: str
    sensor_ids: list[UUID]
    properties: list[str]

    def __init__(self, json) -> None:
        self.model_configurations = json["ModelConfigurations"]
        self.model_name = json["ModelName"]
        self.model_id = json["ModelId"]
        self.sensor_set_type_id = json["SensorSetTypeId"]
        self.sensor_ids = json["SensorIds"]
        self.properties = json["Properties"]
