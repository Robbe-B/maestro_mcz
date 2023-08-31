"""The maestro_mcz integration."""
from __future__ import annotations
from datetime import timedelta
import logging
import async_timeout
from custom_components.maestro_mcz.config_flow import CONF_POLLING_INTERVAL
from custom_components.maestro_mcz.maestro.responses.model import Configuration, ModelConfiguration, SensorConfiguration
from custom_components.maestro_mcz.models import MczConfigItem

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

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.FAN, Platform.NUMBER, Platform.SWITCH, Platform.SELECT, Platform.BINARY_SENSOR, Platform.BUTTON]
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

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)

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
    
    def get_model_configuration_by_model_configuration_name(self, model_configuration_name:str) -> ModelConfiguration | None:
        return next((x for x in self._maestroapi.Model.model_configurations if x.configuration_name.lower() == model_configuration_name.lower()), None)
    
    def get_sensor_configuration_by_model_configuration_name_and_sensor_name(self, model_configuration_name:str, sensor_name:str) -> SensorConfiguration | None:
        model_configuration = self.get_model_configuration_by_model_configuration_name(model_configuration_name)
        if(model_configuration is None):
            return None
        else:
            sensor_configuration = next((x for x in model_configuration.configurations if x.sensor_name.lower() == sensor_name.lower()), None)
            if(sensor_configuration is not None):
                return SensorConfiguration(sensor_configuration, model_configuration.configuration_id)
            
    def get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(self, mcz_config_items_list_to_match: list[MczConfigItem]) -> tuple[MczConfigItem,SensorConfiguration] | None:
        for x in mcz_config_items_list_to_match:
             matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(x.sensor_set_config_name, x.sensor_set_name)
             if(matching_configuration is not None):
                return (x, matching_configuration)
        return None
    
    def get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(self, mcz_config_items_list_to_match: list[MczConfigItem]) -> list(tuple[MczConfigItem,SensorConfiguration]) | None:
        temp_list = []
        for x in mcz_config_items_list_to_match:
             matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(x.sensor_set_config_name, x.sensor_set_name)
             if(matching_configuration is not None):
                temp_list.append((x, matching_configuration))
        if temp_list:
            return temp_list
        else:
            return None
