"""Platform for Climate integration."""

from datetime import timedelta
import logging

import async_timeout

from homeassistant.components.climate import ClimateEntity
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from .const import DOMAIN
from .maestro.types.mode import ModeEnum

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Config entry example."""
    # assuming API object stored here by __init__.py
    my_api = hass.data[DOMAIN][entry.entry_id]
    coordinator = MczCoordinator(hass, my_api)

    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    #
    await coordinator.async_config_entry_first_refresh()

    async_add_entities(MczEntity(coordinator) for ent in enumerate(["MCZ"]))


class MczCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass, my_api):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name="MCZ Stove",
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=timedelta(seconds=30),
        )
        self.my_api = my_api

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        async with async_timeout.timeout(15):
            await self.my_api.Refresh()
            return True


class MczEntity(CoordinatorEntity, ClimateEntity):
    """An entity using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available
    """

    def __init__(self, coordinator):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._attr_fan_modes = ["0", "1", "2", "3", "4", "5", "6"]
        self._attr_swing_modes = ["1", "2", "3", "4", "5"]
        self._attr_preset_modes = ["manual", "auto", "overnight", "comfort", "turbo"]
        self._attr_min_temp = 5
        self._attr_max_temp = 40
        self._attr_name = self.coordinator.my_api.Name
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_unique_id = f"{self.coordinator.my_api.Status.sm_sn}_climate"
        self._attr_icon = "mdi:stove"

    _attr_supported_features = (
        ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
    )

    @property
    def hvac_mode(self) -> HVACMode:
        if self.coordinator.my_api.State.state == "on":
            return HVACMode.HEAT
        else:
            return HVACMode.OFF

    @property
    def fan_mode(self) -> str:
        return str(self.coordinator.my_api.Status.set_vent_v1)

    @property
    def swing_mode(self) -> str:
        return str(self.coordinator.my_api.Status.set_pot_man)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.my_api.Status.sm_sn)},
            name=self.coordinator.my_api.Name,
            manufacturer="MCZ",
            model=self.coordinator.my_api.Status.nome_banca_dati_sel,
            sw_version=self.coordinator.my_api.Status.mc_vs_app,
        )

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.coordinator.my_api.State.temp_amb_install

    @property
    def target_temperature(self):
        return self.coordinator.my_api.State.set_amb1

    @property
    def preset_mode(self):
        return self.coordinator.my_api.State.mode

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        await self.coordinator.my_api.Mode(ModeEnum[preset_mode])
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        await self.coordinator.my_api.Power()
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        await self.coordinator.my_api.Fan(int(fan_mode))
        await self.coordinator.async_request_refresh()

    async def async_set_swing_mode(self, swing_mode):
        """Set new target swing operation."""
        await self.coordinator.my_api.Pot(int(swing_mode))
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        await self.coordinator.my_api.Temperature(float(kwargs["temperature"]))
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_target_temperature = self.coordinator.my_api.State.set_amb1
        self._attr_fan_mode = str(self.coordinator.my_api.Status.set_vent_v1)
        self._attr_swing_mode = str(self.coordinator.my_api.Status.set_pot_man)
        self._attr_preset_mode = self.coordinator.my_api.State.mode
        self.async_write_ha_state()
