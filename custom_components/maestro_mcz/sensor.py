"""Platform for Sensor integration."""
from . import MczCoordinator

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import callback
from homeassistant.const import TEMP_CELSIUS
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    stoveList = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(MczEntity(stove) for stove in stoveList)


class MczEntity(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = "Temperature"
        self._attr_native_unit_of_measurement = TEMP_CELSIUS
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}_sensor"
        self._attr_icon = "mdi:thermometer"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator._maestroapi.Status.sm_sn)},
        )

    @property
    def native_value(self):
        return self.coordinator._maestroapi.State.temp_amb_install

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
