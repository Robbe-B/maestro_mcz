"""Platform for Select integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MczDeviceCoordinator
from .maestro.controller.responses.model import SensorConfiguration
from .maestro.models import models
from .maestro.types.enums import SensorTypeEnum


class MczSelectEntity(CoordinatorEntity, SelectEntity):
    """Select entity for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_current_option = None
    _selector_configuration: SensorConfiguration | None = None

    def __init__(
        self,
        coordinator: MczDeviceCoordinator,
        supported_selector: models.SelectMczConfigItem,
        matching_selector_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.coordinator: MczDeviceCoordinator = coordinator
        self._attr_name = supported_selector.user_friendly_name
        self._attr_unique_id = (
            f"{self.coordinator.stove.UniqueCode}-{supported_selector.sensor_get_name}"
        )
        self._attr_icon = supported_selector.icon
        self._prop = supported_selector.sensor_get_name
        self._enabled_default = supported_selector.enabled_by_default
        self._category = supported_selector.category
        self._selector_configuration = matching_selector_configuration

        if (
            matching_selector_configuration.configuration.type
            == SensorTypeEnum.INT.value
        ):
            self._attr_options = []
            if (
                matching_selector_configuration.configuration.min
                and matching_selector_configuration.configuration.max
            ):
                if matching_selector_configuration.configuration.mappings:
                    self._attr_options_mappings = (
                        matching_selector_configuration.configuration.mappings
                    )
                else:
                    self._attr_options_mappings = {}

                for key in list(
                    map(
                        str,
                        range(
                            int(matching_selector_configuration.configuration.min),
                            int(matching_selector_configuration.configuration.max) + 1,
                            1,
                        ),
                    )
                ):
                    if (
                        supported_selector.value_mappings
                        and key in supported_selector.value_mappings
                    ):
                        self._attr_options.append(
                            supported_selector.value_mappings[key]
                        )
                        self._attr_options_mappings[key] = (
                            supported_selector.value_mappings[key]
                        )
                    else:
                        self._attr_options.append(key)

        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def current_option(self):
        return self._attr_current_option

    async def async_select_option(self, option: str) -> None:
        """Set the value."""
        if self._selector_configuration is not None:
            if (
                self._attr_options_mappings
                and option in self._attr_options_mappings.values()
            ):
                found_value = next(
                    (
                        key
                        for key, value in self._attr_options_mappings.items()
                        if value == option
                    ),
                    None,
                )
            else:
                found_value = option

            if found_value is not None:
                await self.coordinator.stove.activateProgram(
                    self._selector_configuration.configuration.sensor_id,
                    self._selector_configuration.configuration_id,
                    int(found_value),
                )
                await self.coordinator.update_data_after_set()

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
        current_value = None
        if hasattr(self.coordinator.stove.Status, self._prop):
            current_value = str(getattr(self.coordinator.stove.Status, self._prop))
        elif hasattr(self.coordinator.stove.State, self._prop):
            current_value = str(getattr(self.coordinator.stove.State, self._prop))

        if self._selector_configuration.configuration.type == SensorTypeEnum.INT.value:
            if current_value and self._selector_configuration is not None:
                if (
                    self._attr_options_mappings
                    and current_value in self._attr_options_mappings
                ):
                    self._attr_current_option = self._attr_options_mappings[
                        current_value
                    ]
                else:
                    self._attr_current_option = current_value
            else:
                self._attr_current_option = current_value
        else:
            self._attr_current_option = current_value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up select entities from a config entry."""
    coordinators = entry.runtime_data
    entities = []
    for coordinator in coordinators.values():
        entities.extend(_getStoveSelectEntities(coordinator))
    async_add_entities(entities)


def _getStoveSelectEntities(
    coordinator: MczDeviceCoordinator,
) -> list[CoordinatorEntity]:
    """Get the select entities to create for this stove."""
    entities = []
    supported_pots = coordinator.stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_pots
    )
    if supported_pots is not None:
        entities.extend(
            MczSelectEntity(coordinator, supported_pot[0], supported_pot[1])
            for supported_pot in supported_pots
            if supported_pot[0] is not None and supported_pot[1] is not None
        )

    supported_selectors = coordinator.stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_selectors
    )
    if supported_selectors is not None:
        entities.extend(
            MczSelectEntity(coordinator, supported_selector[0], supported_selector[1])
            for supported_selector in supported_selectors
            if supported_selector[0] is not None and supported_selector[1] is not None
        )
    return entities
