"""The maestro_mcz integration."""

from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from pathlib import Path

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigFlowContext
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .config_flow import CONF_POLLING_INTERVAL
from .const import DEFAULT_POLLING_INTERVAL, DOMAIN, MANUFACTURER, MOCKED_FOLDER
from .maestro import MaestroStove
from .maestro.controller.controller_interface import MaestroControllerInterface
from .maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
    MaestroController,
)
from .maestro.controller.mocked_controller import MockedController

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


async def async_setup(hass: HomeAssistant, config: ConfigType):
    """Set up the integration from code."""

    # create a new hub when there are mocked files
    mocked_folder = await _has_mocked_folder()

    if mocked_folder is not None:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,  # Required: specifies which integration's flow to trigger
                context=ConfigFlowContext(source=SOURCE_IMPORT),
                data={
                    MOCKED_FOLDER: mocked_folder,
                    CONF_HOST: "MockedHost",
                    CONF_USERNAME: "DummyUsername",
                    CONF_PASSWORD: "DummyPassword",
                },
            )
        )
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up maestro_mcz from a config entry."""

    # 1. Check if we have a mocked folder
    mocked_folder = entry.data.get(MOCKED_FOLDER, None)

    # 2. Create the api / controller to use for the coordinator
    #    if mocked_folder is not None it means we want to use mocked data instead of connecting to the real API
    if mocked_folder is None:
        session = async_get_clientsession(hass)
        maestroapi: MaestroControllerInterface = MaestroController(
            session,
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
    else:
        maestroapi: MaestroControllerInterface = MockedController(mocked_folder)

    # 3. Get all stoves stove linked to the account
    try:
        stove_infos = await maestroapi.retrieve_linked_stove_infos()
    except MaestroAuthenticationException as exception:
        _LOGGER.error("Authentication failed: %s", exception)
        return False
    except MaestroConnectionException as exception:
        _LOGGER.error("Connection failed: %s", exception)
        return False

    # 4. Create a coordinator for each stove linked to the account
    coordinators: dict[str, MczDeviceCoordinator] = {}
    for stove_info in stove_infos:
        coordinator = MczDeviceCoordinator(
            hass, entry, MaestroStove(maestroapi, stove_info)
        )
        await coordinator.async_config_entry_first_refresh()
        coordinators[stove_info.node.unique_code] = coordinator

    # 5. Store the coordinators in the entry so that they can be accessed by the platforms
    entry.runtime_data = coordinators

    # 6. Add an update listener to handle options updates
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # 7. Set up all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _has_mocked_folder() -> str | None:
    """Check if there is a mocked folder."""
    mocked_folder = Path("config/custom_components/maestro_mcz/mocked")
    if mocked_folder.is_dir():
        return str(mocked_folder)
    return None


class MczDeviceCoordinator(DataUpdateCoordinator):
    """MCZ Coordinator."""

    _stove: MaestroStove = None

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        stove: MaestroStove,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name=stove.Name,
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
                )
            ),
        )
        self._stove = stove

    async def _async_setup(self):
        """Set up the coordinator."""
        try:
            return await self.stove.AsyncInit()
        except MaestroConnectionException as err:
            raise UpdateFailed(f"Error communicating with Maestro API: {err}") from err

    async def _async_update_data(self):
        """Fetch data from API endpoint."""

        try:
            return await self.stove.refresh()
        except MaestroAuthenticationException as err:
            # Cancels future updates & Triggers re-auth flow
            raise ConfigEntryAuthFailed from err
        except MaestroConnectionException as err:
            # This marks entities as unavailable and schedules a retry
            raise UpdateFailed(f"Error communicating with Maestro API: {err}") from err

    async def update_data_after_set(
        self,
    ):  # should be revised in the future to be more efficient
        """Force refresh of data from API endpoint after a SET was executed."""
        # we need to wait here because there is an actual delay between sending a SET and receiving the updated value from the polled MCZ database
        await asyncio.sleep(3)
        await self.async_refresh()
        await asyncio.sleep(3)
        await self.async_refresh()

    @property
    def stove(self) -> MaestroStove:
        """Return the stove."""
        return self._stove

    def get_device_info(self) -> DeviceInfo:
        """Return device info."""
        sw_version = ""

        if self.stove.Status.is_connected:
            sw_version = (
                f"{self.stove.Status.sm_nome_app}.{self.stove.Status.sm_vs_app}"
                f", Panel:{self.stove.Status.mc_vs_app}"
                f", DB:{self.stove.Status.nome_banca_dati_sel}"
            )
        else:
            sw_version = "Device Disconnected"

        return DeviceInfo(
            identifiers={(DOMAIN, self.stove.UniqueCode)},
            name=self.stove.Name,
            manufacturer=MANUFACTURER,
            model=self.stove.Model.model_name,
            sw_version=sw_version,
        )
