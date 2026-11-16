"""Read definition-declared fields from cached API responses, without HTTP."""

from typing import cast

from .controller.responses.counters import Counters
from .controller.responses.state import State
from .controller.responses.status import Status
from .models.models_types import (
    CounterMczConfigItem,
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
    # Field names come from the catalogue; getattr loses the response field types.
    return cast(bool | int | float | str | None, getattr(response, sensor_name, None))


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


def get_counter_value(
    config: CounterMczConfigItem,
    counters: Counters | None,
    model_generation: MczStoveModelGeneration,
) -> int | float | None:
    """Read the first available declared field and apply its configured unit divisor."""
    for name, divisor in config.value_sources.items():
        value = cast(int | float | None, getattr(counters, name, None))
        if value is not None:
            if isinstance(divisor, dict):
                divisor = divisor[model_generation]
            return value if divisor == 1 else value / divisor
    return None
