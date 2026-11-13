"""Platform for Button integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .coordinator import MczAccountCoordinator
from .datetime import MczDateTimeEntity
from .maestro import MaestroStove
from .maestro.controller.responses.model import SensorConfiguration
from .maestro.models import models
from .maestro.types.enums import SensorTypeEnum


class MczButtonEntity(CoordinatorEntity, ButtonEntity):
    """Button entity for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _button_configuration: SensorConfiguration | None = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_button: models.ButtonMczConfigItem,
        matching_button_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._attr_name = supported_button.user_friendly_name
        self._attr_unique_id = f"{stove_unique_code}-{supported_button.sensor_set_name}"
        self._attr_icon = supported_button.icon
        self._attr_device_info = self._stove.get_device_info()
        self._prop = supported_button.sensor_set_name
        self.entity_registry_enabled_default = supported_button.enabled_by_default
        self.entity_category = supported_button.category

        self._set_button_configuration(matching_button_configuration)

    @property
    def available(self) -> bool:
        """Check availability based on coordinator and stove connection."""
        # Check 1: coordinator is available
        if not super().available:
            return False
        # Check 2: is the stove connected
        return self._stove.is_connected

    def _set_button_configuration(
        self, matching_button_configuration: SensorConfiguration
    ):
        self._button_configuration = matching_button_configuration
        self._attr_return_value = None

        if (
            matching_button_configuration.configuration.type
            == SensorTypeEnum.BOOLEAN.value
        ):
            self._attr_return_value = True
        elif (
            matching_button_configuration.configuration.type == SensorTypeEnum.INT.value
        ):
            for key in matching_button_configuration.configuration.variants:
                if key in matching_button_configuration.configuration.mappings:
                    if key == "reset":
                        self._attr_return_value = (
                            matching_button_configuration.configuration.mappings[key]
                        )

    async def async_press(self) -> None:
        """Button pressed action execute."""
        if (
            self._button_configuration is not None
            and self._attr_return_value is not None
        ):
            if (
                self._button_configuration.configuration.type
                == SensorTypeEnum.BOOLEAN.value
            ):
                await self._stove.activateProgram(
                    self._button_configuration.configuration.sensor_id,
                    self._button_configuration.configuration_id,
                    bool(self._attr_return_value),
                )
                await self.coordinator.update_data_after_set()
            elif (
                self._button_configuration.configuration.type
                == SensorTypeEnum.INT.value
            ):
                await self._stove.activateProgram(
                    self._button_configuration.configuration.sensor_id,
                    self._button_configuration.configuration_id,
                    int(self._attr_return_value),
                )
                await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class MczTimeSyncButtonEntity(CoordinatorEntity, ButtonEntity):
    """Button entity to trigger time synchronization."""

    _attr_has_entity_name = True
    _time_sync_button_configuration: SensorConfiguration | None = None
    _mcz_date_time_entity: MczDateTimeEntity | None = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_time_sync_button: models.TimeSyncButtonMczConfigItem,
        matching_time_sync_button_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the time sync button entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._mcz_date_time_entity = MczDateTimeEntity(
            coordinator,
            stove_unique_code,
            supported_time_sync_button,
            matching_time_sync_button_configuration,
        )

        self._attr_name = supported_time_sync_button.user_friendly_name
        self._attr_unique_id = (
            f"{stove_unique_code}-{supported_time_sync_button.sensor_set_name}"
        )
        self._attr_icon = supported_time_sync_button.icon
        self._attr_device_info = self._stove.get_device_info()
        self._prop = supported_time_sync_button.sensor_set_name
        self.entity_registry_enabled_default = (
            supported_time_sync_button.enabled_by_default
        )
        self.entity_category = supported_time_sync_button.category

        self._set_time_sync_button_configuration(
            matching_time_sync_button_configuration
        )

    @property
    def available(self) -> bool:
        """Check availability based on coordinator and stove connection."""
        # Check 1: coordinator is available
        if not super().available:
            return False
        # Check 2: is the stove connected
        return self._stove.is_connected

    def _set_time_sync_button_configuration(
        self, matching_time_sync_button_configuration: SensorConfiguration
    ):
        self._time_sync_button_configuration = matching_time_sync_button_configuration
        if self._mcz_date_time_entity is not None:
            self._mcz_date_time_entity.set_date_time_configuration(
                matching_time_sync_button_configuration
            )

    async def async_press(self) -> None:
        """Button pressed action execute."""
        if (
            self._time_sync_button_configuration is not None
            and self._mcz_date_time_entity is not None
        ):
            system_date_time = dt_util.utcnow()
            if system_date_time is not None:
                await self._mcz_date_time_entity.async_set_value(system_date_time)
                await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up button entities from a config entry."""
    coordinator: MczAccountCoordinator = entry.runtime_data
    entities = []
    for stove in coordinator.stoves.values():
        entities.extend(_getStoveButtonEntities(coordinator, stove))
    async_add_entities(entities)


def _getStoveButtonEntities(
    coordinator: MczAccountCoordinator, stove: MaestroStove
) -> list[CoordinatorEntity]:
    """Get the button entities to create for this stove."""
    entities = []
    # buttons
    supported_buttons = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_buttons
    )
    if supported_buttons is not None:
        entities.extend(
            MczButtonEntity(
                coordinator, stove.UniqueCode, supported_button[0], supported_button[1]
            )
            for supported_button in supported_buttons
            if supported_button[0] is not None and supported_button[1] is not None
        )

    # time sync buttons
    supported_time_sync_buttons = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_time_sync_buttons
    )
    if supported_time_sync_buttons is not None:
        entities.extend(
            MczTimeSyncButtonEntity(
                coordinator,
                stove.UniqueCode,
                supported_time_sync_button[0],
                supported_time_sync_button[1],
            )
            for supported_time_sync_button in supported_time_sync_buttons
            if (
                supported_time_sync_button[0] is not None
                and supported_time_sync_button[1] is not None
            )
        )
    return entities
