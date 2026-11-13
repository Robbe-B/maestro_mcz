"""Platform for Binary Sensor integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MczAccountCoordinator
from .maestro import MaestroStove
from .maestro.models import models


def _binary_sensor_enabled(
    stove: MaestroStove, supported_binary_sensor: models.BinarySensorMczConfigItem
) -> bool:
    """Check optional model configuration and its reported enable setting."""
    if (
        supported_binary_sensor.sensor_set_config_name is not None
        and supported_binary_sensor.sensor_set_name is not None
    ):
        configuration = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
            supported_binary_sensor.sensor_set_config_name,
            supported_binary_sensor.sensor_set_name,
        )
        if configuration is None:
            return False
    enabled_sensor = supported_binary_sensor.enabled_sensor_get_name
    if enabled_sensor is None:
        return True
    enabled = getattr(stove.Status, enabled_sensor, None)
    if enabled is None:
        enabled = getattr(stove.State, enabled_sensor, None)
    return enabled is True


class MczBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):
    """Generic binary sensor for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_is_on = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_binary_sensor: models.BinarySensorMczConfigItem,
    ) -> None:
        """Initialize the binary sensor entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._attr_name = supported_binary_sensor.user_friendly_name
        self._attr_device_class = supported_binary_sensor.device_class
        self._attr_unique_id = (
            f"{stove_unique_code}-{supported_binary_sensor.sensor_get_name}"
        )
        self._attr_icon = supported_binary_sensor.icon
        self._attr_device_info = self._stove.get_device_info()
        self._prop = supported_binary_sensor.sensor_get_name
        self._supported_binary_sensor = supported_binary_sensor
        self._inverted = getattr(supported_binary_sensor, "inverted", False)
        self.entity_registry_enabled_default = (
            supported_binary_sensor.enabled_by_default
        )
        self.entity_category = supported_binary_sensor.category
        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def available(self) -> bool:
        """Check availability based on coordinator and stove connection."""
        # Check 1: coordinator is available
        if not super().available:
            return False
        # Check 2: is the stove connected
        return self._stove.is_connected

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        value = getattr(self._stove.Status, self._prop, None)
        if value is None:
            value = getattr(self._stove.State, self._prop, None)
        if not _binary_sensor_enabled(self._stove, self._supported_binary_sensor):
            value = None
        if value is not None and self._inverted:
            value = not value
        self._attr_is_on = value


class MczConnectionStatusBinarySensorEntity(CoordinatorEntity, BinarySensorEntity):
    """Binary Sensor to represent the connection status."""

    _attr_has_entity_name = True
    _attr_is_on = None

    _stove_field: str | None = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        entity_name: str,
        entity_icon: str,
        stove_field: str,
        stove_unique_code: str,
    ) -> None:
        """Initialize the cloud status binary sensor entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._attr_name = entity_name
        self._attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._attr_unique_id = (
            f"{stove_unique_code}-{self._attr_name.replace(' ', '_')}"
        )
        self._stove_field = stove_field
        self._attr_icon = entity_icon
        self._attr_device_info = self._stove.get_device_info()
        self.entity_registry_enabled_default = True
        self.entity_category = EntityCategory.DIAGNOSTIC
        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def is_on(self):
        return self._attr_is_on

    @property
    def available(self) -> bool:
        return True  # needs to be always available to reflect the connection status

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        if hasattr(self._stove, self._stove_field):
            self._attr_is_on = getattr(self._stove, self._stove_field)


class MczCloudStatusBinarySensorEntity(MczConnectionStatusBinarySensorEntity):
    """Binary Sensor to represent the integration to cloud connection status."""

    _attr_has_entity_name = True
    _attr_is_on = None

    def __init__(
        self, coordinator: MczAccountCoordinator, stove_unique_code: str
    ) -> None:
        """Initialize the cloud status binary sensor entity."""
        super().__init__(
            coordinator,
            "Cloud Connection Status",
            "mdi:cloud",
            "is_integration_connected_to_cloud",
            stove_unique_code,
        )


class MczStoveStatusBinarySensorEntity(MczConnectionStatusBinarySensorEntity):
    """Binary Sensor to represent the stove to cloud connection status."""

    _attr_has_entity_name = True
    _attr_is_on = None

    def __init__(
        self, coordinator: MczAccountCoordinator, stove_unique_code: str
    ) -> None:
        """Initialize the cloud status binary sensor entity."""
        super().__init__(
            coordinator,
            "Device Connection Status",
            "mdi:connection",
            "is_stove_connected_to_cloud",
            stove_unique_code,
        )

    @property
    def available(self) -> bool:
        """Check availability based on coordinator and cloud connection."""
        # Check 1: coordinator is available
        if not super().available:
            return False
        # Check 2: is the cloud connected
        return self._stove.is_integration_connected_to_cloud


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up button entities from a config entry."""
    coordinator: MczAccountCoordinator = entry.runtime_data
    entities = []
    for stove in coordinator.stoves.values():
        entities.extend(_getStoveBinarySensorEntities(coordinator, stove))
    async_add_entities(entities)


def _getStoveBinarySensorEntities(
    coordinator: MczAccountCoordinator,
    stove: MaestroStove,
) -> list[CoordinatorEntity]:
    """Get the binary sensor entities to create for this stove."""
    entities = []
    supported_binary_sensors = filter(
        lambda supported_binary_sensor: (
            _binary_sensor_enabled(stove, supported_binary_sensor)
            and (
                any(
                    supported_binary_sensor.sensor_get_name == binary_sensor_name
                    for binary_sensor_name in dir(stove.State)
                )
                # Status fields are declared for every stove; require a reading.
                or getattr(stove.Status, supported_binary_sensor.sensor_get_name, None)
                is not None
            )
        ),
        iter(models.supported_binary_sensors),
    )

    if supported_binary_sensors is not None:
        entities.extend(
            MczBinarySensorEntity(
                coordinator, stove.UniqueCode, supported_binary_sensor
            )
            for supported_binary_sensor in supported_binary_sensors
            if supported_binary_sensor is not None
        )

    entities.append(MczCloudStatusBinarySensorEntity(coordinator, stove.UniqueCode))
    entities.append(MczStoveStatusBinarySensorEntity(coordinator, stove.UniqueCode))
    return entities
