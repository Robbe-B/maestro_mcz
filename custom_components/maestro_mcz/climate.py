"""Platform for Climate integration."""

from datetime import timedelta
import logging

import async_timeout
from .maestro import MaestroController, MaestroStove

from homeassistant.components.climate import ClimateEntity
from homeassistant.core import callback
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from .const import DOMAIN
from .maestro.types.mode import ModeEnum

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    """Config entry example."""

    maestroapi:MaestroController = hass.data[DOMAIN][entry.entry_id]

    stoveList = []
    for stove in maestroapi.Stoves:
        stove:MaestroStove = stove
        coordinator = MczCoordinator(hass, stove)
        await coordinator.async_config_entry_first_refresh()
        stoveList.append(coordinator)

    async_add_entities(MczEntity(stove) for stove in stoveList)


class MczCoordinator(DataUpdateCoordinator):
    """My custom coordinator."""

    def __init__(self, hass, maestroapi):
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="MCZ Stove",
            update_interval=timedelta(seconds=30),
        )
        self._maestroapi:MaestroStove = maestroapi

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        async with async_timeout.timeout(15):
            await self._maestroapi.Refresh()
            return True


class MczEntity(CoordinatorEntity, ClimateEntity):
    """An entity using CoordinatorEntity.

    The CoordinatorEntity class provides:
      should_poll
      async_update
      async_added_to_hass
      available
    """

    def __init__(self, coordinator:MczCoordinator):
        """Pass coordinator to CoordinatorEntity."""
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._attr_fan_modes = ["0", "1", "2", "3", "4", "5", "6"]
        self._attr_swing_modes = ["1", "2", "3", "4", "5"]
        self._attr_preset_modes = ["manual", "auto", "overnight", "comfort", "turbo"]
        self._attr_min_temp = 5
        self._attr_max_temp = 40
        self._attr_name = self.coordinator._maestroapi.Name
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}_climate"
        self._attr_icon = "mdi:stove"

    _attr_supported_features = (
        ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.SWING_MODE
        | ClimateEntityFeature.PRESET_MODE
    )

    @property
    def hvac_mode(self) -> HVACMode:
        if self.coordinator._maestroapi.State.state == "on":
            return HVACMode.HEAT
        else:
            return HVACMode.OFF

    @property
    def fan_mode(self) -> str:
        return str(self.coordinator._maestroapi.Status.set_vent_v1)

    @property
    def swing_mode(self) -> str:
        return str(self.coordinator._maestroapi.Status.set_pot_man)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator._maestroapi.Status.sm_sn)},
            name=self.coordinator._maestroapi.Name,
            manufacturer="MCZ",
            model=self.coordinator._maestroapi.Status.nome_banca_dati_sel,
            sw_version=self.coordinator._maestroapi.Status.mc_vs_app,
        )

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self.coordinator._maestroapi.State.temp_amb_install

    @property
    def target_temperature(self):
        return self.coordinator._maestroapi.State.set_amb1

    @property
    def preset_mode(self):
        return self.coordinator._maestroapi.State.mode

    async def async_set_preset_mode(self, preset_mode):
        """Set new target preset mode."""
        await self.coordinator._maestroapi.Mode(ModeEnum[preset_mode])
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        await self.coordinator._maestroapi.Power()
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode):
        """Set new target fan mode."""
        await self.coordinator._maestroapi.Fan(int(fan_mode))
        await self.coordinator.async_request_refresh()

    async def async_set_swing_mode(self, swing_mode):
        """Set new target swing operation."""
        await self.coordinator._maestroapi.Pot(int(swing_mode))
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        await self.coordinator._maestroapi.Temperature(float(kwargs["temperature"]))
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_target_temperature = self.coordinator._maestroapi.State.set_amb1
        self._attr_fan_mode = str(self.coordinator._maestroapi.Status.set_vent_v1)
        self._attr_swing_mode = str(self.coordinator._maestroapi.Status.set_pot_man)
        self._attr_preset_mode = self.coordinator._maestroapi.State.mode
        self.async_write_ha_state()
