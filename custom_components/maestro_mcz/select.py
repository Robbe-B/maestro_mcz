"""Platform for Select integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MczAccountCoordinator
from .maestro import MaestroStove
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
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_selector: models.SelectMczConfigItem,
        matching_selector_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._attr_name = supported_selector.user_friendly_name
        self._attr_unique_id = (
            f"{stove_unique_code}-{supported_selector.sensor_get_name}"
        )
        self._attr_icon = supported_selector.icon
        self._attr_device_info = self._stove.get_device_info()
        self._prop = supported_selector.sensor_get_name
        self.entity_registry_enabled_default = supported_selector.enabled_by_default
        self.entity_category = supported_selector.category
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
    def available(self) -> bool:
        """Check availability based on coordinator and stove connection."""
        # Check 1: coordinator is available
        if not super().available:
            return False
        # Check 2: is the stove connected
        return self._stove.is_connected

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
                await self._stove.activateProgram(
                    self._selector_configuration.configuration.sensor_id,
                    self._selector_configuration.configuration_id,
                    int(found_value),
                )
                await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        current_value = None
        if hasattr(self._stove.Status, self._prop):
            current_value = str(getattr(self._stove.Status, self._prop))
        elif hasattr(self._stove.State, self._prop):
            current_value = str(getattr(self._stove.State, self._prop))

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
    coordinator: MczAccountCoordinator = entry.runtime_data
    entities = []
    for stove in coordinator.stoves.values():
        entities.extend(_getStoveSelectEntities(coordinator, stove))
    async_add_entities(entities)


def _getStoveSelectEntities(
    coordinator: MczAccountCoordinator,
    stove: MaestroStove,
) -> list[CoordinatorEntity]:
    """Get the select entities to create for this stove."""
    entities = []
    supported_pots = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_pots
    )
    if supported_pots is not None:
        entities.extend(
            MczSelectEntity(
                coordinator, stove.UniqueCode, supported_pot[0], supported_pot[1]
            )
            for supported_pot in supported_pots
            if supported_pot[0] is not None and supported_pot[1] is not None
        )

    supported_selectors = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_selectors
    )
    if supported_selectors is not None:
        entities.extend(
            MczSelectEntity(
                coordinator,
                stove.UniqueCode,
                supported_selector[0],
                supported_selector[1],
            )
            for supported_selector in supported_selectors
            if supported_selector[0] is not None and supported_selector[1] is not None
        )
    return entities
