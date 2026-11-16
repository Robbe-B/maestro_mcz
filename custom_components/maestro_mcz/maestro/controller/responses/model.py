"""Models for Maestro Controller responses."""

from dataclasses import dataclass

from ..response_types import JsonObject


@dataclass
class Configuration:
    """Parse one control's metadata, using saved attribute names during replay."""

    sensor_name: str | None = None
    type: str | None = None
    visible: bool | None = None
    variants: list[str] | None = None
    sensor_id: str | None = None
    enabled: bool | None = None
    min: str | None = None
    max: str | None = None
    mappings: dict[str, int | str] | None = None

    def __init__(self, json: JsonObject, from_mocked_response: bool = False) -> None:
        if from_mocked_response:
            for k, v in json.items():
                setattr(self, k, v)
        else:
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
    """Group related control definitions without validating their field types."""

    timed: bool | None = None
    configuration_name: str | None = None
    configurations: list[Configuration] | None = None
    configuration_id: str | None = None
    limitations: str | None = None

    def __init__(self, json: JsonObject, from_mocked_response: bool = False) -> None:
        if from_mocked_response:
            for k, v in json.items():
                if k == "configurations":
                    self.configurations = [
                        Configuration(configuration, True) for configuration in v
                    ]
                else:
                    setattr(self, k, v)
        else:
            self.timed = json["Timed"]
            self.configuration_name = json["ConfigurationName"]
            self.configurations = [
                Configuration(configuration) for configuration in json["Configurations"]
            ]
            self.configuration_id = json["ConfigurationId"]
            self.limitations = json["Limitations"]


@dataclass
class Model:
    """Read model metadata and controls from live fields or a saved report."""

    model_configurations: list[ModelConfiguration] | None = None
    model_name: str | None = None
    model_id: str | None = None
    sensor_set_type_id: str | None = None
    sensor_ids: list[str] | None = None
    properties: list[str] | None = None

    def __init__(self, json: JsonObject, from_mocked_response: bool = False) -> None:
        if from_mocked_response:
            for k, v in json.items():
                if k == "model_configurations":
                    self.model_configurations = [
                        ModelConfiguration(model_configuration, True)
                        for model_configuration in v
                    ]
                else:
                    setattr(self, k, v)
        else:
            self.model_configurations = [
                ModelConfiguration(model_configuration)
                for model_configuration in json["ModelConfigurations"]
            ]
            self.model_name = json["ModelName"]
            self.model_id = json["ModelId"]
            self.sensor_set_type_id = json["SensorSetTypeId"]
            self.sensor_ids = json["SensorIds"]
            self.properties = json["Properties"]


@dataclass
class SensorConfiguration:
    configuration: Configuration
    configuration_id: str | None

    def __init__(
        self, configuration: Configuration, configuration_id: str | None
    ) -> None:
        self.configuration = configuration
        self.configuration_id = configuration_id


@dataclass
class SensorConfigurationMultipleModes:
    mode_configurations: dict[str, SensorConfiguration]

    def __init__(self, mode_configurations: dict[str, SensorConfiguration]) -> None:
        self.mode_configurations = mode_configurations
