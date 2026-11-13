"""The maestro_mcz integration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.config_entries import SOURCE_IMPORT, ConfigFlowContext
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, MOCKED_FOLDER
from .coordinator import (
    MczAccountCoordinator,
    MczConfigEntry,
    MczConsumptionCoordinator,
)
from .maestro import MaestroStove
from .maestro.controller.controller_interface import MaestroControllerInterface
from .maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
    MaestroController,
)
from .maestro.controller.mocked_controller import MockedController
from .maestro.models.models import MczStoveModelGeneration

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
    entry: MczConfigEntry,
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

    # 4. Create a coordinator for the account
    coordinator: MczAccountCoordinator = MczAccountCoordinator(
        hass,
        entry,
        name=f"{CONF_USERNAME}",
        stoves=[MaestroStove(maestroapi, stove_info) for stove_info in stove_infos]
        if stove_infos
        else None,
    )
    await coordinator.async_config_entry_first_refresh()

    # 5. Store the coordinator in the entry so that they can be accessed by the platforms
    entry.runtime_data = coordinator

    # 6. Create consumption coordinators, excluding M1's unsupported history
    for stove in coordinator.stoves.values():
        if stove.model_generation is MczStoveModelGeneration.M1:
            continue
        coordinator.consumption_coordinators[stove.UniqueCode] = (
            MczConsumptionCoordinator(hass, entry, maestroapi, stove)
        )

    # 7. Add an update listener to handle options updates
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # 8. Set up all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MczConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_update_listener(hass: HomeAssistant, entry: MczConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _has_mocked_folder() -> str | None:
    """Check if there is a mocked folder."""
    mocked_folder = Path("config/custom_components/maestro_mcz/mocked")
    if mocked_folder.is_dir():
        return str(mocked_folder)
    return None
