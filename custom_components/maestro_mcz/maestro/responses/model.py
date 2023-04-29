from dataclasses import dataclass, field
from ..types.enums import TypeEnum

@dataclass
class Configuration:
    sensor_name: str | None = None
    type: str | None = None
    visible: bool | None = None
    variants: list[str] | None = None
    sensor_id: str | None = None
    enabled: bool | None = None
    min: str | None = None
    max: str | None = None
    mappings: dict[str, int] | None = None

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
    timed: bool | None = None
    configuration_name: str | None = None
    configurations: list[Configuration] | None = None
    configuration_id: str | None = None
    limitations: str | None = None

    def __init__(self, json) -> None:
        self.timed = json["Timed"]
        self.configuration_name = json["ConfigurationName"]
        self.configurations = [Configuration(configuration) for configuration in json["Configurations"]]
        self.configuration_id = json["ConfigurationId"]
        self.limitations = json["Limitations"]

@dataclass
class Model:
    model_configurations: list[ModelConfiguration] | None = None
    model_name: str | None = None
    model_id: str | None = None
    sensor_set_type_id: str | None = None
    sensor_ids: list[str] | None = None
    properties: list[str] | None = None

    def __init__(self, json) -> None:
        self.model_configurations = [ModelConfiguration(model_configuration) for model_configuration in json["ModelConfigurations"]]
        self.model_name = json["ModelName"]
        self.model_id = json["ModelId"]
        self.sensor_set_type_id = json["SensorSetTypeId"]
        self.sensor_ids = json["SensorIds"]
        self.properties = json["Properties"]

@dataclass
class SensorConfiguration:
    configuration: Configuration | None = None
    configuration_id: str | None = None

    def __init__(self, configuration: Configuration, configuration_id: str) -> None:
        self.configuration = configuration
        self.configuration_id = configuration_id
