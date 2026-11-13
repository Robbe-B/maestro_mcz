"""Platform for Number integration."""

from __future__ import annotations

from homeassistant.components.number import (
    DEFAULT_MAX_VALUE,
    DEFAULT_MIN_VALUE,
    DEFAULT_STEP,
    NumberEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MczAccountCoordinator
from .maestro import MaestroStove
from .maestro.controller.responses.model import SensorConfiguration
from .maestro.models import models
from .maestro.types.enums import SensorTypeEnum


class MczNumberEntity(CoordinatorEntity, NumberEntity):
    """Number entity for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_native_value = None
    _number_configuration: SensorConfiguration | None = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_number: models.NumberMczConfigItem,
        matching_number_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._attr_name = supported_number.user_friendly_name
        self._attr_native_unit_of_measurement = supported_number.unit
        self._attr_device_class = supported_number.device_class
        self._attr_unique_id = f"{stove_unique_code}-{supported_number.sensor_get_name}"
        self._attr_icon = supported_number.icon
        self._attr_device_info = self._stove.get_device_info()
        self._attr_mode = supported_number.mode
        self._prop = supported_number.sensor_get_name
        self.entity_registry_enabled_default = supported_number.enabled_by_default
        self.entity_category = supported_number.category
        self._number_configuration = matching_number_configuration
        if matching_number_configuration.configuration.type in {
            SensorTypeEnum.INT.value,
            SensorTypeEnum.DOUBLE.value,
        }:
            self._attr_native_step = DEFAULT_STEP
            self._attr_native_min_value = float(
                matching_number_configuration.configuration.min or DEFAULT_MIN_VALUE
            )
            self._attr_native_max_value = float(
                matching_number_configuration.configuration.max or DEFAULT_MAX_VALUE
            )
        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def available(self) -> bool:
        """Check availability based on coordinator and stove connection."""
        # Check 1: coordinator is available
        if not super().available:
            return False
        # Check 2: is the stove connected
        return self._stove.is_connected

    @property
    def native_value(self):
        return self._attr_native_value

    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        if self._number_configuration is not None:
            if (
                self._number_configuration.configuration.type
                == SensorTypeEnum.INT.value
            ):
                converted_value = int(value)
            else:
                converted_value = value

            await self._stove.activateProgram(
                self._number_configuration.configuration.sensor_id,
                self._number_configuration.configuration_id,
                converted_value,
            )
            await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        if hasattr(self._stove.Status, self._prop):
            self._attr_native_value = getattr(self._stove.Status, self._prop)
        elif hasattr(self._stove.State, self._prop):
            self._attr_native_value = getattr(self._stove.State, self._prop)
        else:
            self._attr_native_value = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up number entities from a config entry."""
    coordinator: MczAccountCoordinator = entry.runtime_data
    entities = []
    for stove in coordinator.stoves.values():
        entities.extend(_getStoveNumberEntities(coordinator, stove))
    async_add_entities(entities)


def _getStoveNumberEntities(
    coordinator: MczAccountCoordinator,
    stove: MaestroStove,
) -> list[CoordinatorEntity]:
    """Get the number entities to create for this stove."""
    entities = []
    supported_numbers = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_numbers
    )
    if supported_numbers is not None:
        entities.extend(
            MczNumberEntity(
                coordinator, stove.UniqueCode, supported_number[0], supported_number[1]
            )
            for supported_number in supported_numbers
            if supported_number[0] is not None and supported_number[1] is not None
        )
    return entities
