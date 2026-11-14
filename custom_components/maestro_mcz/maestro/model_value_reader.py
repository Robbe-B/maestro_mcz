"""Read model-declared fields from cached State/Status responses, without HTTP."""

from .controller.responses.state import State
from .controller.responses.status import Status
from .models.models_types import (
    MczConfigItem,
    MczResponseSource,
    MczStoveModelGeneration,
)


def read_response_value(
    source: MczResponseSource,
    state: State | None,
    status: Status | None,
    sensor_name: str,
) -> bool | int | float | str | None:
    """Read one response, preserving None, zero and False."""
    response = status if source is MczResponseSource.STATUS else state
    return getattr(response, sensor_name, None)


def get_response_value(
    config: MczConfigItem,
    state: State | None,
    status: Status | None,
    model_generation: MczStoveModelGeneration | None = None,
    sensor_get_name: str | None = None,
) -> bool | int | float | str | None:
    """Resolve a configured primary or auxiliary reading from one response."""
    name = sensor_get_name or config.sensor_get_name
    if name is None:
        raise ValueError("A response reading requires a sensor name")
    source = config.value_response_source
    if isinstance(source, dict):
        source = source[
            model_generation
            if model_generation is not None
            else MczStoveModelGeneration.M2_PLUS
        ]
    return read_response_value(source, state, status, name)
