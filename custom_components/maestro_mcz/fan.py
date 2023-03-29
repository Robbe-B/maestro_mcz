"""Platform for Sensor integration."""
import logging
from typing import Optional
from . import MczCoordinator, models

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


from .const import DOMAIN
ENTITY = "fan"
_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    stoveList = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for stove in stoveList:
        stove:MczCoordinator = stove
        model = stove.maestroapi.State.nome_banca_dati_sel
        for (prop, attrs) in models.models[model][ENTITY].items():
            entities.append(MczFanEntity(stove, prop, attrs))

    async_add_entities(entities)


class MczFanEntity(CoordinatorEntity, FanEntity):
    _attr_has_entity_name = True

    _attr_supported_features = (
        FanEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator, prop, attrs):
        super().__init__(coordinator)
        [name, icon, presets, fan_number, function, enabled_by_default, category] = attrs
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = name
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{prop}"
        self._attr_icon = icon
        self._prop = prop
        self._fan_number = fan_number
        self._enabled_default = enabled_by_default
        self._category = category
        self._presets = sorted(list(presets))
        self._attr_preset_modes = sorted(list(presets))

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator._maestroapi.Status.sm_sn)}
        )

    @property
    def is_on(self) -> bool:
        return self.preset_mode != "0"

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
        await self.coordinator._maestroapi.Fan(self._fan_number, int(preset_mode))

    async def async_turn_on(self) -> None:
        """Turn on the fan."""
        await self.coordinator._maestroapi.Fan(self._fan_number, 6)

    async def async_turn_off(self) -> None:
        """Turn the fan off."""
        await self.coordinator._maestroapi.Fan(self._fan_number, 0)

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
