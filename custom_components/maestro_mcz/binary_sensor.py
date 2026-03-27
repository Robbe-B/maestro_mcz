"""Platform for Binary Sensor integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MczDeviceCoordinator
from .maestro.models import models


class MczBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):
    """Generic binary sensor for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_is_on = None

    def __init__(
        self,
        coordinator: MczDeviceCoordinator,
        supported_binary_sensor: models.BinarySensorMczConfigItem,
    ) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(coordinator)
        self.coordinator: MczDeviceCoordinator = coordinator
        self._attr_name = supported_binary_sensor.user_friendly_name
        self._attr_device_class = supported_binary_sensor.device_class
        self._attr_unique_id = f"{self.coordinator.stove.UniqueCode}-{supported_binary_sensor.sensor_get_name}"
        self._attr_icon = supported_binary_sensor.icon
        self._prop = supported_binary_sensor.sensor_get_name
        self._enabled_default = supported_binary_sensor.enabled_by_default
        self._category = supported_binary_sensor.category
        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        if hasattr(self.coordinator.stove.Status, self._prop):
            self._attr_is_on = getattr(self.coordinator.stove.Status, self._prop)
        elif hasattr(self.coordinator.stove.State, self._prop):
            self._attr_is_on = getattr(self.coordinator.stove.State, self._prop)
        else:
            self._attr_is_on = None


class MczCloudStatusBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):
    """Binary Sensor to represent the cloud connection status."""

    _attr_has_entity_name = True
    _attr_is_on = None

    def __init__(self, coordinator: MczDeviceCoordinator) -> None:
        """Initialize the cloud status binary sensor entity."""
        super().__init__(coordinator)
        self.coordinator: MczDeviceCoordinator = coordinator
        self._attr_name = "Cloud Connection Status"
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_unique_id = (
            f"{self.coordinator.stove.UniqueCode}-{self._attr_name.replace(' ', '_')}"
        )
        self._attr_icon = "mdi:cloud"
        self._enabled_default = True
        self._category = EntityCategory.DIAGNOSTIC
        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._enabled_default

    @property
    def available(self) -> bool:
        return True  # needs to be always available to reflect the connection status

    @property
    def entity_category(self):
        return self._category

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        self._attr_is_on = self.coordinator.stove.is_connected


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up button entities from a config entry."""
    coordinators = entry.runtime_data
    entities = []
    for coordinator in coordinators.values():
        entities.extend(_getStoveBinarySensorEntities(coordinator))
    async_add_entities(entities)


def _getStoveBinarySensorEntities(
    coordinator: MczDeviceCoordinator,
) -> list[CoordinatorEntity]:
    """Get the binary sensor entities to create for this stove."""
    entities = []
    supported_binary_sensors = filter(
        lambda supported_binary_sensor: any(
            supported_binary_sensor.sensor_get_name == binary_sensor_name
            for binary_sensor_name in dir(coordinator.stove.State)
        ),
        iter(models.supported_binary_sensors),
    )

    if supported_binary_sensors is not None:
        entities.extend(
            MczBinarySensorEntity(coordinator, supported_binary_sensor)
            for supported_binary_sensor in supported_binary_sensors
            if supported_binary_sensor is not None
        )

    entities.append(MczCloudStatusBinarySensorEntity(coordinator))
    return entities
