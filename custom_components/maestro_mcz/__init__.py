"""Compose per-entry clients, accounts, coordinators and Home Assistant platforms.

Own setup, unload and device-removal policy; field interpretation and entity
behavior belong to their respective adapters, not this composition root.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.config_entries import (
    SOURCE_IMPORT,
    ConfigEntryState,
    ConfigFlowContext,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, MOCKED_FOLDER
from .coordinator import (
    MczAccountCoordinator,
    MczConfigEntry,
    MczConsumptionCoordinator,
    MczCountersCoordinator,
    MczRuntimeData,
)
from .maestro.account import MaestroAccount
from .maestro.controller.controller_interface import MaestroControllerInterface
from .maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
    MaestroController,
)
from .maestro.controller.mocked_controller import MockedController
from .maestro.models.models_types import MczStoveModelGeneration

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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration from code."""

    # create a new hub when there are mocked files
    mocked_folder = await _has_mocked_folder(hass)

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

    # 1. Read the optional folder containing saved diagnostics.
    mocked_folder = entry.data.get(MOCKED_FOLDER, None)

    # 2. Use the cloud controller, or replay saved diagnostics when configured.
    maestroapi: MaestroControllerInterface
    if mocked_folder is None:
        session = async_get_clientsession(hass)
        maestroapi = MaestroController(
            session,
            entry.data[CONF_USERNAME],
            entry.data[CONF_PASSWORD],
        )
    else:
        maestroapi = MockedController(mocked_folder)

    # 3. Load one independent account and its linked stoves.
    account = MaestroAccount(maestroapi, replay=mocked_folder is not None)
    try:
        await account.async_load_stoves(
            on_authentication_failed=lambda: entry.async_start_reauth(hass)
        )
    except MaestroAuthenticationException as exception:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="account_invalid_auth",
        ) from exception
    except MaestroConnectionException as exception:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="account_cannot_connect",
            translation_placeholders={"error": str(exception)},
            retry_after=exception.retry_after,
        ) from exception

    # 4. Schedule updates for this account.
    coordinator: MczAccountCoordinator = MczAccountCoordinator(
        hass,
        entry,
        name=entry.title,
        account=account,
    )

    # 5. Initialize stove models and fetch the first live readings.
    #    The models must be loaded before checking their generation below.
    await coordinator.async_config_entry_first_refresh()

    # 6. Store domain ownership separately from the polling lifecycle.
    entry.runtime_data = MczRuntimeData(account=account, coordinator=coordinator)

    # 7. Create per-stove statistics coordinators without fetching their data yet.
    for stove in coordinator.stoves.values():
        # 7.1. Create a counters coordinator for both M1 and M2+ stoves.
        coordinator.counters_coordinators[stove.UniqueCode] = MczCountersCoordinator(
            hass, entry, maestroapi, stove
        )
        # 7.2. Create a consumption coordinator for M2+ only; skip it for M1.
        if stove.model_generation is MczStoveModelGeneration.M1:
            continue
        coordinator.consumption_coordinators[stove.UniqueCode] = (
            MczConsumptionCoordinator(hass, entry, maestroapi, stove)
        )

    # 8. Set up the entity platforms.
    #    Sensor setup starts the statistics coordinators' refreshes in the background.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MczConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: MczConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Allow manual removal only after confirming the stove is no longer linked."""
    identifiers = {
        identifier
        for domain, identifier in device_entry.identifiers
        if domain == DOMAIN
    }
    if not identifiers:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_removal_cannot_verify",
        )

    replay = entry.data.get(MOCKED_FOLDER) is not None
    if replay:
        if entry.state is not ConfigEntryState.LOADED:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_removal_cannot_verify",
            )
        account = entry.runtime_data.account
    else:
        account = (
            entry.runtime_data.account
            if entry.state is ConfigEntryState.LOADED
            else MaestroAccount(
                MaestroController(
                    async_get_clientsession(hass),
                    entry.data[CONF_USERNAME],
                    entry.data[CONF_PASSWORD],
                )
            )
        )
    try:
        linked = await account.async_has_linked_stove(identifiers)
    except MaestroAuthenticationException as err:
        entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="account_invalid_auth",
        ) from err
    except (MaestroConnectionException, TypeError, ValueError) as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="device_removal_cannot_verify",
        ) from err

    if linked:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key=(
                "device_removal_replay_linked"
                if replay
                else "device_removal_still_linked"
            ),
        )
    hass.config_entries.async_schedule_reload(entry.entry_id)
    return True


async def _has_mocked_folder(hass: HomeAssistant) -> str | None:
    """Check if there is a mocked folder."""
    mocked_folder = Path("config/custom_components/maestro_mcz/mocked")
    if await hass.async_add_executor_job(mocked_folder.is_dir):
        return str(mocked_folder)
    return None
