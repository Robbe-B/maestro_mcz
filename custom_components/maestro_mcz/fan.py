"""Platform for Fan integration."""
import logging
from typing import Optional
from uuid import UUID

from custom_components.maestro_mcz.maestro.responses.model import SensorConfiguration
from custom_components.maestro_mcz.maestro.types.enums import TypeEnum
from . import MczCoordinator, models

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    stove_list = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for stove in stove_list:
        stove:MczCoordinator = stove
        supported_fans = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(models.supported_fans)
        if(supported_fans is not None):
            for supported_fan in supported_fans:
                if(supported_fan[0] is not None and supported_fan[1] is not None):
                    entities.append(MczFanEntity(stove, supported_fan[0], supported_fan[1]))

    async_add_entities(entities)


class MczFanEntity(CoordinatorEntity, FanEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, supported_fan: models.FanMczConfigItem, matching_fan_configuration: SensorConfiguration):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = supported_fan.user_friendly_name
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_fan.sensor_get_name}"
        self._attr_icon = supported_fan.icon
        self._prop = supported_fan.sensor_get_name
        self._enabled_default = supported_fan.enabled_by_default
        self._category = supported_fan.category
        self.fan_configuration = matching_fan_configuration
        if(matching_fan_configuration.configuration.type == TypeEnum.INT.value):
            self._presets = self._attr_preset_modes = list(map(str,range(int(matching_fan_configuration.configuration.min), int(matching_fan_configuration.configuration.max) + 1 , 1)))
            self._attr_supported_features = (FanEntityFeature.PRESET_MODE)

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
    def is_on(self) -> bool:
        if(self.fan_configuration is not None and self._presets is not None and len(self._presets) > 0):
            return self.preset_mode != self._presets[0]
        else:
            return False

    @property
    def preset_mode(self) -> str:
        return str(getattr(self.coordinator._maestroapi.Status, self._prop))

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        if(self.fan_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self.fan_configuration.configuration.sensor_id, self.fan_configuration.configuration_id, int(preset_mode))
            await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn on the fan."""
        if(self.fan_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self.fan_configuration.configuration.sensor_id, self.fan_configuration.configuration_id, self._presets[-1])
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn the fan off."""
        if(self.fan_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self.fan_configuration.configuration.sensor_id, self.fan_configuration.configuration_id, self._presets[0])
            await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
