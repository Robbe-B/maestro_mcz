"""Diagnostics support for maestro_mcz."""

from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from .coordinator import MczAccountCoordinator, MczConfigEntry

CONFIG_FIELDS_TO_REDACT = [CONF_USERNAME, CONF_PASSWORD]
DATA_FIELDS_TO_REDACT = ["UniqueCode", "sm_sn", "ssid_wifi", "pwd_wifi", "mac_wifi"]
OPTION_FIELDS_TO_REDACT = []


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: MczConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: MczAccountCoordinator = config_entry.runtime_data

    diagnostics_data = {
        "config_entry_data": async_redact_data(
            dict(config_entry.data), CONFIG_FIELDS_TO_REDACT
        ),
        "devices": {},
        "options": async_redact_data(config_entry.options, OPTION_FIELDS_TO_REDACT),
    }

    for stove in coordinator.stoves.values():
        diagnostics_data["devices"][stove.Name] = async_redact_data(
            {
                "coordinator.stove_data": {
                    "Id": stove.Id,
                    "ModelId": stove.ModelId,
                    "SensorSetTypeId": stove.SensorSetTypeId,
                    "Name": stove.Name,
                    "UniqueCode": stove.UniqueCode,
                    "State": dataclasses.asdict(stove.State),
                    "Status": dataclasses.asdict(stove.Status),
                    "Model": dataclasses.asdict(stove.Model),
                },
            },
            DATA_FIELDS_TO_REDACT,
        )
        history = coordinator.consumption_coordinators.get(stove.UniqueCode)
        if history is not None:
            data = history.data
            diagnostics_data["devices"][stove.Name]["consumption"] = {
                "last_update_success": history.last_update_success,
                "consumption_date": data.date.isoformat() if data is not None else None,
                "value": data.value if data is not None else None,
                "last_successful_update": (
                    data.last_updated.isoformat() if data is not None else None
                ),
            }
    return diagnostics_data
