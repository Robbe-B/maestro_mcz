"""Diagnostics support for maestro_mcz."""
from __future__ import annotations
import dataclasses

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from . import MczCoordinator

CONFIG_FIELDS_TO_REDACT = [CONF_USERNAME, CONF_PASSWORD]
DATA_FIELDS_TO_REDACT = ["UniqueCode", "sm_sn", "ssid_wifi", "pwd_wifi", "mac_wifi"]
OPTION_FIELDS_TO_REDACT = []



async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinators: list = hass.data[DOMAIN][config_entry.entry_id]
    
    diagnostics_data = {
        "config_entry_data": async_redact_data(dict(config_entry.data), CONFIG_FIELDS_TO_REDACT),
        "devices": {},
        "options": async_redact_data(config_entry.options, OPTION_FIELDS_TO_REDACT)
    }

    for coordinator in coordinators:
        coordinator: MczCoordinator = coordinator
        diagnostics_data["devices"][coordinator.maestroapi.Name] = async_redact_data(
            {
            "coordinator.data": coordinator.data,
            "coordinator.stove_data": {
                "Id": coordinator.maestroapi.Id,
                "ModelId": coordinator.maestroapi.ModelId,
                "SensorSetTypeId": coordinator.maestroapi.SensorSetTypeId,
                "Name": coordinator.maestroapi.Name,
                "UniqueCode": coordinator.maestroapi.UniqueCode,
                "State": dataclasses.asdict(coordinator.maestroapi.State),
                "Status": dataclasses.asdict(coordinator.maestroapi.Status),
                "Model": dataclasses.asdict(coordinator.maestroapi.Model),
            },
        }, DATA_FIELDS_TO_REDACT)
    return diagnostics_data
