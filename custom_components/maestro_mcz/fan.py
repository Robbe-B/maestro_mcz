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
from homeassistant.util.percentage import ordered_list_item_to_percentage, percentage_to_ordered_list_item


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
            entities.append(MczEntity(stove, prop, attrs))

    async_add_entities(entities)


class MczEntity(CoordinatorEntity, FanEntity):
    _attr_has_entity_name = True

    _attr_supported_features = (
        FanEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator, prop, attrs):
        super().__init__(coordinator)
        [name, icon, presets, fannum, function, enabled_by_default, category] = attrs
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = name
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{prop}"
        self._attr_icon = icon
        self._prop = prop
        self._enabled_default = enabled_by_default
        self._category = category
        self._presets = sorted(list(presets))
        self._attr_preset_modes = sorted(list(presets))

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator._maestroapi.Status.sm_sn)},
            name=self.coordinator._maestroapi.Name,
            manufacturer="MCZ",
            model=self.coordinator._maestroapi.Status.nome_banca_dati_sel,
            sw_version=self.coordinator._maestroapi.Status.mc_vs_app,
        )

    @property
    def is_on(self) -> bool:
        if (self.coordinator._maestroapi.State.state == "on"):
            return True
        else:
            return False

    @property
    def preset_mode(self) -> str:
        return str(getattr(self.coordinator._maestroapi.Status, "set_vent_v1"))

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        await self.coordinator._maestroapi.Fan(int(preset_mode))

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
