"""Platform for Binary Sensor integration."""
from . import MczCoordinator, models

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN



async def async_setup_entry(hass, entry, async_add_entities):
    stoveList = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for stove in stoveList:
        stove:MczCoordinator = stove
        supported_binary_sensors = filter(lambda supported_binary_sensor:any(supported_binary_sensor.sensor_get_name == binary_sensor_name for binary_sensor_name in dir(stove.maestroapi.State)),iter(models.supported_binary_sensors))
        if(supported_binary_sensors is not None):
            for supported_binary_sensor in supported_binary_sensors:
                if(supported_binary_sensor is not None):
                    entities.append(MczBinarySensorEntity(stove, supported_binary_sensor))

    async_add_entities(entities)


class MczBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator, supported_binary_sensor: models.BinarySensorMczConfigItem):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = supported_binary_sensor.user_friendly_name
        self._attr_device_class = supported_binary_sensor.device_class
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_binary_sensor.sensor_get_name}"
        self._attr_icon = supported_binary_sensor.icon
        self._prop = supported_binary_sensor.sensor_get_name
        self._enabled_default = supported_binary_sensor.enabled_by_default
        self._category = supported_binary_sensor.category

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
    def is_on(self):
        if(hasattr(self.coordinator._maestroapi.State, self._prop)):
            return getattr(self.coordinator._maestroapi.State, self._prop)
        elif(hasattr(self.coordinator._maestroapi.Status, self._prop)):
            return getattr(self.coordinator._maestroapi.Status, self._prop)
        else:
            return None

    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()