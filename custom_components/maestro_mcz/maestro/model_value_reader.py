"""Read and interpret definition-declared fields from cached API responses.

Resolve response sources, canonical aliases and counter units without I/O or
cache mutation. Return values, not localized labels; polling, translation
coverage diagnostics and logging policy belong to callers outside this reader.
"""

import re
from typing import cast

from .controller.responses.counters import Counters
from .controller.responses.state import State
from .controller.responses.status import Status
from .models.model_definitions import SUPPORTED_ALARM_CODES
from .models.models_types import (
    CounterMczConfigItem,
    MczConfigItem,
    MczResponseSource,
    MczStoveModelGeneration,
    SensorMczConfigItem,
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


def normalize_sensor_value(
    config: SensorMczConfigItem,
    value: bool | float | str | None,
) -> bool | int | float | str | None:
    """Interpret cached sensor text without changing its original API response."""
    if not isinstance(value, str):
        return value
    key = value
    if config.sensor_get_name == "state":
        alarm = re.fullmatch(r"[Aa]([0-9]{2}) - ([^\r\n]+)", value)
        if alarm and alarm[2].strip() and f"A{alarm[1]}" in SUPPORTED_ALARM_CODES:
            return f"alarm-a{alarm[1]}"
        key = value.casefold()
    if config.api_value_renames is not None:
        return config.api_value_renames.get(key, value)
    return value


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
