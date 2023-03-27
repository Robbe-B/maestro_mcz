"""The maestro_mcz integration."""
from __future__ import annotations
from datetime import timedelta
import logging
import async_timeout
from custom_components.maestro_mcz.config_flow import CONF_POLLING_INTERVAL

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
)

from .const import DOMAIN, DEFAULT_POLLING_INTERVAL
from .maestro import MaestroController, MaestroStove

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.FAN]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up maestro_mcz from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    pollling_interval = entry.options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)

    maestroapi = MaestroController(entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    await maestroapi.Login()

    stoveList = []
    for stove in maestroapi.Stoves:
        stove:MaestroStove = stove
        coordinator = MczCoordinator(hass, stove, pollling_interval)
        await coordinator.async_config_entry_first_refresh()
        stoveList.append(coordinator)

    hass.data[DOMAIN][entry.entry_id] = stoveList

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

class MczCoordinator(DataUpdateCoordinator):
    """MCZ Coordinator."""

    def __init__(self, hass, maestroapi, polling_interval):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="MCZ Stove",
            update_interval=timedelta(seconds=polling_interval),
        )
        self._maestroapi:MaestroStove = maestroapi

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        async with async_timeout.timeout(15):
            await self._maestroapi.Refresh()
            return True
    
    @property
    def maestroapi(self) -> MaestroStove:
        return self._maestroapi