"""Diagnostics support for maestro_mcz."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from . import MczCoordinator

TO_REDACT = {CONF_USERNAME, CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators: list = hass.data[DOMAIN][config_entry.entry_id]

    diagnostics_data = {
        "config_entry_data": async_redact_data(dict(config_entry.data), TO_REDACT),
        "devices": {},
    }

    for coordinator in coordinators:
        coordinator: MczCoordinator = coordinator
        diagnostics_data["devices"][coordinator.maestroapi.Name] = {
            "coordinator.data": coordinator.data,
            "coordinator.stove_data": {
                "Id": coordinator.maestroapi.Id,
                "ModelId": coordinator.maestroapi.ModelId,
                "SensorSetTypeId": coordinator.maestroapi.SensorSetTypeId,
                "Name": coordinator.maestroapi.Name,
                "UniqueCode": coordinator.maestroapi.UniqueCode,
                "State": coordinator.maestroapi.State,
                "Status": coordinator.maestroapi.Status,
                "Model": coordinator.maestroapi.Model,
            },
        }
    return diagnostics_data
