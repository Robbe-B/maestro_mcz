"""Platform for Climate integration."""
import logging

from . import MczCoordinator

from homeassistant.components.climate import ClimateEntity
from homeassistant.core import callback
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from .const import DOMAIN
from .maestro.types.mode import ModeEnum

async def async_setup_entry(hass, entry, async_add_entities):
    stoveList = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(MczEntity(stove) for stove in stoveList)

class MczEntity(CoordinatorEntity, ClimateEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator:MczCoordinator):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        self._attr_fan_modes = ["0", "1", "2", "3", "4", "5", "6"]
        self._attr_swing_modes = ["1", "2", "3", "4", "5"]
        self._attr_preset_modes = ["manual", "auto", "overnight", "comfort", "turbo"]
        self._attr_min_temp = 5
        self._attr_max_temp = 40
        self._attr_name = None
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}"
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
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator._maestroapi.Status.sm_sn)},
            name=self.coordinator._maestroapi.Name,
            manufacturer="MCZ",
            model=self.coordinator._maestroapi.Model.model_name,
            sw_version=f"{self.coordinator._maestroapi.Status.sm_nome_app}.{self.coordinator._maestroapi.Status.sm_vs_app}"
            + f", Panel:{self.coordinator._maestroapi.Status.mc_vs_app}"
            + f", DB:{self.coordinator._maestroapi.Status.nome_banca_dati_sel}",
        )

    @property
    def current_temperature(self):
        return self.coordinator._maestroapi.State.temp_amb_install

    @property
    def target_temperature(self):
        return self.coordinator._maestroapi.State.set_amb1

    @property
    def preset_mode(self):
        return self.coordinator._maestroapi.State.mode

    async def async_set_preset_mode(self, preset_mode):
        await self.coordinator._maestroapi.Mode(ModeEnum[preset_mode])
        await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode):
        await self.coordinator._maestroapi.Power()
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode):
        await self.coordinator._maestroapi.Fan(1,int(fan_mode))
        await self.coordinator.async_request_refresh()

    async def async_set_swing_mode(self, swing_mode):
        await self.coordinator._maestroapi.Pot(int(swing_mode))
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        await self.coordinator._maestroapi.Temperature(float(kwargs["temperature"]))
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_target_temperature = self.coordinator._maestroapi.State.set_amb1
        self._attr_fan_mode = str(self.coordinator._maestroapi.Status.set_vent_v1)
        self._attr_swing_mode = str(self.coordinator._maestroapi.Status.set_pot_man)
        self._attr_preset_mode = self.coordinator._maestroapi.State.mode
        self.async_write_ha_state()
