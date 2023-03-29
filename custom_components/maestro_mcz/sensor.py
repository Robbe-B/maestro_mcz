"""Platform for Sensor integration."""
from . import MczCoordinator, models

from homeassistant.components.sensor import (
    SensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
ENTITY = "sensor"


async def async_setup_entry(hass, entry, async_add_entities):
    stoveList = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for stove in stoveList:
        stove:MczCoordinator = stove
        model = stove.maestroapi.State.nome_banca_dati_sel
        for (prop, attrs) in models.models[model][ENTITY].items():
            entities.append(MczEntity(stove, prop, attrs))

    async_add_entities(entities)


class MczEntity(CoordinatorEntity, SensorEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator, prop, attrs):
        super().__init__(coordinator)
        [name, unit, icon, device_class, state_class, enabled_by_default, category] = attrs
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_device_class = device_class
        self._attr_state_class = state_class
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{prop}"
        self._attr_icon = icon
        self._prop = prop
        self._enabled_default = enabled_by_default
        self._category = category

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
    def native_value(self):
        return getattr(self.coordinator._maestroapi.State, self._prop)

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category
    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
