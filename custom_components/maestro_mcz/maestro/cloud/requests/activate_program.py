"""This module defines the ActivateProgramRequest dataclass."""

from dataclasses import dataclass


@dataclass
class ActivateProgramRequest:
    """Describe the wire envelope for addressed commands, without dispatching them."""

    ModelId: str
    ConfigurationId: str | None
    SensorSetTypeId: str
    Commands: list[ProgramCommand]

    def __init__(
        self,
        model_id: str,
        configuration_id: str | None,
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
    """Carry one sensor ID and wire value, without choosing or sending the action."""

    SensorId: str | None = None
    Value: object | None = None

    def __init__(self, sensor_id: str | None, value: object | None) -> None:
        """Initialize the ProgramCommand."""
        self.SensorId = sensor_id
        self.Value = value
