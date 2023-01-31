"""Platform for Sensor integration."""

from datetime import timedelta
import logging

import async_timeout
from .maestro import MaestroController, MaestroStove

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.const import UnitOfTemperature, TEMP_CELSIUS
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
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

class MczEntity(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator):
        """Pass coordinator to CoordinatorEntity."""
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
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator._maestroapi.Status.sm_sn)},
        )

    @property
    def native_value(self):
        return self.coordinator._maestroapi.State.temp_amb_install

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
