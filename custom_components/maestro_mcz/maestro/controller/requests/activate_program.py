"""This module defines the ActivateProgramRequest dataclass."""

from dataclasses import dataclass


@dataclass
class ActivateProgramRequest:
    """Represents a request to activate a program on the stove."""

    ModelId: str | None = None
    ConfigurationId: str | None = None
    SensorSetTypeId: str | None = None
    Commands: list[ProgramCommand] | None = None

    def __init__(
        self,
        model_id: str,
        configuration_id: str,
        sensor_set_type_id: str,
        commands: list[ProgramCommand],
    ) -> None:
        """Initialize the ActivateProgramRequest."""
        self.ModelId = model_id
        self.ConfigurationId = configuration_id
        self.SensorSetTypeId = sensor_set_type_id
        self.Commands = commands


@dataclass
class ProgramCommand:
    """Represents a command to be sent to the stove."""

    SensorId: str | None = None
    Value: object | None = None

    def __init__(self, sensor_id: str | None, value: object | None) -> None:
        """Initialize the ProgramCommand."""
        self.SensorId = sensor_id
        self.Value = value
