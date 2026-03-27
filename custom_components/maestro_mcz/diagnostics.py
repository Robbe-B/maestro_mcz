"""Diagnostics support for maestro_mcz."""

from __future__ import annotations

import dataclasses
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import MczDeviceCoordinator

CONFIG_FIELDS_TO_REDACT = [CONF_USERNAME, CONF_PASSWORD]
DATA_FIELDS_TO_REDACT = ["UniqueCode", "sm_sn", "ssid_wifi", "pwd_wifi", "mac_wifi"]
OPTION_FIELDS_TO_REDACT = []


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators: dict[str, MczDeviceCoordinator] = config_entry.runtime_data

    diagnostics_data = {
        "config_entry_data": async_redact_data(
            dict(config_entry.data), CONFIG_FIELDS_TO_REDACT
        ),
        "devices": {},
        "options": async_redact_data(config_entry.options, OPTION_FIELDS_TO_REDACT),
    }

    for coordinator in coordinators.values():
        diagnostics_data["devices"][coordinator.stove.Name] = async_redact_data(
            {
                "coordinator.stove_data": {
                    "Id": coordinator.stove.Id,
                    "ModelId": coordinator.stove.ModelId,
                    "SensorSetTypeId": coordinator.stove.SensorSetTypeId,
                    "Name": coordinator.stove.Name,
                    "UniqueCode": coordinator.stove.UniqueCode,
                    "State": dataclasses.asdict(coordinator.stove.State),
                    "Status": dataclasses.asdict(coordinator.stove.Status),
                    "Model": dataclasses.asdict(coordinator.stove.Model),
                },
            },
            DATA_FIELDS_TO_REDACT,
        )
    return diagnostics_data
