"""The maestro_mcz integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import os

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .config_flow import CONF_POLLING_INTERVAL
from .const import DEFAULT_POLLING_INTERVAL, DOMAIN, MANUFACTURER
from .maestro import MaestroStove
from .maestro.controller.controller_interface import MaestroControllerInterface
from .maestro.controller.maestro_controller import MaestroController
from .maestro.controller.mocked_controller import MockedController
from .maestro.responses.model import (
    ModelConfiguration,
    SensorConfiguration,
    SensorConfigurationMultipleModes,
)
from .models import MczConfigItem

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.DATETIME,
    Platform.FAN,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up maestro_mcz from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    pollling_interval = entry.options.get(
        CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
    )

    mocked_files = await has_mocked_files()

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
        coordinator = MczCoordinator(hass, stove, pollling_interval)
        await coordinator.async_config_entry_first_refresh()
        if coordinator.maestroapi.UniqueCode:  # avoid adding a stove without serial number as this is the unique identifier in HA
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


async def has_mocked_files() -> list[str] | None:
    """Check if there are mocked files, if so returns it."""
    try:
        loop = asyncio.get_running_loop()
        folder_path = "config/custom_components/maestro_mcz/mocked"
        files_in_dir = await loop.run_in_executor(None, os.listdir, folder_path)
        if files_in_dir is not None:
            return [folder_path + "/" + file for file in files_in_dir]
    except:
        return None
    else:
        return None


class MczCoordinator(DataUpdateCoordinator):
    """MCZ Coordinator."""

    _avoid_ping: bool = False

    def __init__(
        self,
        hass: HomeAssistant | None,
        maestroapi: MaestroStove,
        polling_interval: int,
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="MCZ Stove",
            update_interval=timedelta(seconds=polling_interval),
        )
        self._maestroapi = maestroapi

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        async with asyncio.timeout(10):
            await self._maestroapi.Refresh(not self._avoid_ping)
            return True

    async def update_data_after_set(self):
        """Force refresh of data from API endpoint after a SET was executed."""
        # we need to wait here because there is an actual delay between sending a SET and receiving the updated value from the polled MCZ database
        await asyncio.sleep(3)
        await self.async_refresh()
        await asyncio.sleep(3)
        self._avoid_ping = True
        await self.async_refresh()
        self._avoid_ping = False

    @property
    def maestroapi(self) -> MaestroStove:
        """Return the Maestro api."""
        return self._maestroapi

    def get_device_info(self) -> DeviceInfo:
        """Return device info."""
        sw_version = ""

        if self.maestroapi.Status.is_connected:
            sw_version = (
                f"{self._maestroapi.Status.sm_nome_app}.{self._maestroapi.Status.sm_vs_app}"
                f", Panel:{self._maestroapi.Status.mc_vs_app}"
                f", DB:{self._maestroapi.Status.nome_banca_dati_sel}"
            )
        else:
            sw_version = "Device Disconnected"

        return DeviceInfo(
            identifiers={(DOMAIN, self._maestroapi.UniqueCode)},
            name=self._maestroapi.Name,
            manufacturer=MANUFACTURER,
            model=self._maestroapi.Model.model_name,
            sw_version=sw_version,
        )

    def get_model_configuration_by_model_configuration_name(
        self, model_configuration_name: str
    ) -> ModelConfiguration | None:
        """Get the model configuration by the name of the model configuration."""
        return next(
            (
                x
                for x in self._maestroapi.Model.model_configurations
                if x.configuration_name is not None
                and model_configuration_name is not None
                and x.configuration_name.lower().strip()
                == model_configuration_name.lower().strip()
            ),
            None,
        )

    def get_sensor_configuration_by_model_configuration_name_and_sensor_name(
        self, model_configuration_name: str, sensor_name: str
    ) -> SensorConfiguration | None:
        """Get the sensor configuration by the name of the model configuration and sensor name."""
        model_configuration = self.get_model_configuration_by_model_configuration_name(
            model_configuration_name
        )
        if model_configuration is None:
            return None

        sensor_configuration = next(
            (
                x
                for x in model_configuration.configurations
                if x.sensor_name is not None
                and sensor_name is not None
                and x.sensor_name.lower() == sensor_name.lower()
            ),
            None,
        )
        if sensor_configuration is not None:
            return SensorConfiguration(
                sensor_configuration, model_configuration.configuration_id
            )
        return None

    def get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
        self, mcz_config_items_list_to_match: list[MczConfigItem]
    ) -> tuple[MczConfigItem, SensorConfiguration] | None:
        """Get the first sensor configuration matching by the name of the model configuration and sensor name."""
        for x in mcz_config_items_list_to_match:
            if x.sensor_set_config_name is not None:
                matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    x.sensor_set_config_name, x.sensor_set_name
                )
                if matching_configuration is not None:
                    return (x, matching_configuration)
        return None

    def get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        self, mcz_config_items_list_to_match: list[MczConfigItem]
    ) -> list[tuple[MczConfigItem, SensorConfiguration]] | None:
        """Get the all sensor configurations matching by the name of the model configuration and sensor name."""
        temp_list = []
        for x in mcz_config_items_list_to_match:
            if x.sensor_set_config_name is not None:
                matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    x.sensor_set_config_name, x.sensor_set_name
                )
                if matching_configuration is not None:
                    temp_list.append((x, matching_configuration))
        if temp_list:
            return temp_list
        return None

    def get_all_matching_sensor_for_all_configurations_by_model_mode_and_sensor_name(
        self, mcz_config_items_list_to_match: list[MczConfigItem]
    ) -> list[tuple[MczConfigItem, SensorConfigurationMultipleModes]] | None:
        """Get the all sensor configurations matching for the matching mode by the name of the model configuration and sensor name."""
        temp_list = []
        for x in mcz_config_items_list_to_match:
            if x.mode_to_configuration_name_mapping is not None:
                temp_mode_configurations: dict[str, SensorConfiguration] = {}
                for mode in x.mode_to_configuration_name_mapping:
                    matching_configuration = self.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                        x.mode_to_configuration_name_mapping[mode], x.sensor_set_name
                    )
                    if matching_configuration is not None:
                        temp_mode_configurations[mode] = matching_configuration

            if (
                temp_mode_configurations is not None
                and len(temp_mode_configurations) > 0
            ):
                temp_list.append(
                    (x, SensorConfigurationMultipleModes(temp_mode_configurations))
                )
        if temp_list:
            return temp_list
        return None
