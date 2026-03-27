"""Platform for Sensor integration."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MczDeviceCoordinator
from .maestro.models import models


class MczSensorEntity(CoordinatorEntity, SensorEntity):
    """Sensor entity for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_native_value = None

    def __init__(
        self,
        coordinator: MczDeviceCoordinator,
        supported_sensor: models.SensorMczConfigItem,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator)
        self.coordinator: MczDeviceCoordinator = coordinator
        self._attr_name = supported_sensor.user_friendly_name
        self._attr_native_unit_of_measurement = supported_sensor.unit
        self._attr_suggested_display_precision = supported_sensor.display_precision
        self._attr_device_class = supported_sensor.device_class
        self._attr_state_class = supported_sensor.state_class
        self._attr_unique_id = (
            f"{self.coordinator.stove.UniqueCode}-{supported_sensor.sensor_get_name}"
        )
        self._attr_icon = supported_sensor.icon
        self._prop = supported_sensor.sensor_get_name
        self._enabled_default = supported_sensor.enabled_by_default
        self._category = supported_sensor.category
        self._api_value_renames = supported_sensor.api_value_renames
        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def native_value(self):
        return self._attr_native_value

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        value = None
        if hasattr(self.coordinator.stove.Status, self._prop):
            value = getattr(self.coordinator.stove.Status, self._prop)
        elif hasattr(self.coordinator.stove.State, self._prop):
            value = getattr(self.coordinator.stove.State, self._prop)

        if self._api_value_renames is not None and value in self._api_value_renames:
            self._attr_native_value = self._api_value_renames[value]
        else:
            self._attr_native_value = value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    coordinators = entry.runtime_data
    entities = []
    for coordinator in coordinators.values():
        entities.extend(_getStoveSensorEntities(coordinator))
    async_add_entities(entities)


def _getStoveSensorEntities(
    coordinator: MczDeviceCoordinator,
) -> list[CoordinatorEntity]:
    """Get the sensor entities to create for this stove."""
    entities = []
    supported_sensors = filter(
        lambda supported_sensor: (
            any(
                (
                    supported_sensor.sensor_get_name == sensor_name_status
                    and getattr(coordinator.stove.Status, sensor_name_status)
                    is not None
                )
                for sensor_name_status in dir(coordinator.stove.Status)
            )
            or any(
                (
                    supported_sensor.sensor_get_name == sensor_name_state
                    and getattr(coordinator.stove.State, sensor_name_state) is not None
                )
                for sensor_name_state in dir(coordinator.stove.State)
            )
        ),
        iter(models.supported_sensors),
    )

    entities.extend(
        MczSensorEntity(coordinator, supported_sensor)
        for supported_sensor in supported_sensors
        if supported_sensor is not None
    )
    return entities
