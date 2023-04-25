"""Platform for Sensor integration."""
from . import MczCoordinator, models

from homeassistant.components.sensor import (
    SensorEntity,
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
        supported_sensors = filter(lambda supported_sensor:any(supported_sensor.sensor_get_name == sensor_name for sensor_name in dir(stove.maestroapi.State)),iter(models.supported_sensors))
        if(supported_sensors is not None):
            for supported_sensor in supported_sensors:
                if(supported_sensor is not None):
                    entities.append(MczSensorEntity(stove, supported_sensor))

    async_add_entities(entities)


class MczSensorEntity(CoordinatorEntity, SensorEntity):

    _attr_has_entity_name = True

    def __init__(self, coordinator, supported_sensor:models.SensorMczConfigItem):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = supported_sensor.user_friendly_name
        self._attr_native_unit_of_measurement = supported_sensor.unit
        self._attr_device_class = supported_sensor.device_class
        self._attr_state_class = supported_sensor.state_class
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_sensor.sensor_get_name}"
        self._attr_icon = supported_sensor.icon
        self._prop = supported_sensor.sensor_get_name
        self._enabled_default = supported_sensor.enabled_by_default
        self._category = supported_sensor.category

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
