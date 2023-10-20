"""The maestro_mcz integration."""
from __future__ import annotations
from datetime import timedelta
import logging
import os
import async_timeout
from .config_flow import CONF_POLLING_INTERVAL
from .maestro.responses.model import Configuration, ModelConfiguration, SensorConfiguration
from .models import MczConfigItem

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.const import (
    CONF_USERNAME,
    CONF_PASSWORD,
)

from .const import DOMAIN, MANUFACTURER, DEFAULT_POLLING_INTERVAL
from .maestro import MaestroStove
from .maestro.controller.controller_interface import MaestroControllerInterface
from .maestro.controller.maestro_controller import MaestroController
from .maestro.controller.mocked_controller import MockedController


PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.SENSOR, Platform.FAN, Platform.NUMBER, Platform.SWITCH, Platform.SELECT, Platform.BINARY_SENSOR, Platform.BUTTON]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up maestro_mcz from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    pollling_interval = entry.options.get(CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL)

    mocked_files = has_mocked_files()

    if mocked_files is None:
        maestroapi: MaestroControllerInterface = MaestroController(
            entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
        )
        await maestroapi.Login()
    else:   
        maestroapi: MaestroControllerInterface = MockedController(mocked_files)
        await maestroapi.Login()


    stoveList = []
    for stove in maestroapi.Stoves:
        stove:MaestroStove = stove
        coordinator = MczCoordinator(hass, stove, pollling_interval)
        await coordinator.async_config_entry_first_refresh()
        if(coordinator.maestroapi.Status.sm_sn): #avoid adding a disconnected stove without serial number
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

def has_mocked_files() -> list[str] | None:
    try:
        folder_path = "config/custom_components/maestro_mcz/mocked"
        files_in_dir = os.listdir(folder_path)
        if(files_in_dir is not None):
            return [folder_path + "/" + file for file in files_in_dir]
        else:
            return None
    except:
        return None


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
     
    def get_device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._maestroapi.Status.sm_sn)},
            name=self._maestroapi.Name,
            manufacturer=MANUFACTURER,
            model=self._maestroapi.Model.model_name,
            sw_version=f"{self._maestroapi.Status.sm_nome_app}.{self._maestroapi.Status.sm_vs_app}"
            + f", Panel:{self._maestroapi.Status.mc_vs_app}"
            + f", DB:{self._maestroapi.Status.nome_banca_dati_sel}",
        )
    
    def get_model_configuration_by_model_configuration_id(self, model_configuration_id:str) -> ModelConfiguration | None:
        return next((x for x in self._maestroapi.Model.model_configurations if x.configuration_id is not None and x.configuration_id.lower() == model_configuration_id.lower()), None)
    
    def get_model_configuration_by_model_configuration_name(self, model_configuration_name:str) -> ModelConfiguration | None:
        return next((x for x in self._maestroapi.Model.model_configurations if x.configuration_name is not None and x.configuration_name.lower() == model_configuration_name.lower()), None)
    
    def get_sensor_configuration_by_model_configuration_id_and_sensor_id(self, model_configuration_id:str, sensor_id:str) -> SensorConfiguration | None:
        model_configuration = self.get_model_configuration_by_model_configuration_id(model_configuration_id)
        if(model_configuration is None):
            return None
        else:
            sensor_configuration = next((x for x in model_configuration.configurations if x.sensor_id is not None and x.sensor_id.lower() == sensor_id.lower()), None)
            if(sensor_configuration is not None):
                return SensorConfiguration(sensor_configuration, model_configuration.configuration_id)
            
    def get_sensor_configuration_by_model_configuration_name_and_sensor_name(self, model_configuration_name:str, sensor_name:str) -> SensorConfiguration | None:
        model_configuration = self.get_model_configuration_by_model_configuration_name(model_configuration_name)
        if(model_configuration is None):
            return None
        else:
            sensor_configuration = next((x for x in model_configuration.configurations if x.sensor_name is not None and x.sensor_name.lower() == sensor_name.lower()), None)
            if(sensor_configuration is not None):
                return SensorConfiguration(sensor_configuration, model_configuration.configuration_id)

    def get_first_matching_sensor_configuration_by_model_configuration_id_and_sensor_id(self, mcz_config_items_list_to_match: list[MczConfigItem]) -> tuple[MczConfigItem,SensorConfiguration] | None:
        for x in mcz_config_items_list_to_match:
            matching_configuration = self.get_sensor_configuration_by_model_configuration_id_and_sensor_id(x.sensor_set_config_id, x.sensor_set_id)
            if(matching_configuration is not None):
                return (x, matching_configuration)
        return None
            
    def get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(self, mcz_config_items_list_to_match: list[MczConfigItem]) -> tuple[MczConfigItem,SensorConfiguration] | None:
        for x in mcz_config_items_list_to_match:
            matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(x.sensor_set_config_name, x.sensor_set_name)
            if(matching_configuration is not None):
                return (x, matching_configuration)
        return None
    
    def get_all_matching_sensor_configurations_by_model_configuration_id_and_sensor_id(self, mcz_config_items_list_to_match: list[MczConfigItem]) -> list(tuple[MczConfigItem,SensorConfiguration]) | None:
        temp_list = []
        for x in mcz_config_items_list_to_match:
             matching_configuration = self.get_sensor_configuration_by_model_configuration_id_and_sensor_id(x.sensor_set_config_id, x.sensor_set_id)
             if(matching_configuration is not None):
                temp_list.append((x, matching_configuration))
        if temp_list:
            return temp_list
        else:
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
