"""Platform for Switch integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MczAccountCoordinator, MczConfigEntry
from .maestro import MaestroStove
from .maestro.controller.responses.model import SensorConfiguration
from .maestro.model_value_reader import get_response_value
from .maestro.models import model_definitions, models_types


class MczSwitchEntity(CoordinatorEntity[MczAccountCoordinator], SwitchEntity):
    """Switch entity for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_is_on = None

    #
    _switch_configuration: SensorConfiguration | None = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_switch: models_types.SwitchMczConfigItem,
        matching_switch_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._attr_name = supported_switch.user_friendly_name
        self._attr_unique_id = f"{stove_unique_code}-{supported_switch.sensor_get_name}"
        self._attr_translation_key = supported_switch.translation_key
        self._attr_device_info = self._stove.get_device_info()
        self._prop = supported_switch.sensor_get_name
        self._supported_switch = supported_switch
        self.entity_registry_enabled_default = supported_switch.enabled_by_default
        self.entity_category = supported_switch.category
        self._switch_configuration = matching_switch_configuration
        # if(matching_switch_configuration.configuration.type == TypeEnum.BOOLEAN.value):
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
    def is_on(self) -> bool | None:
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Set the switch on."""
        if self._switch_configuration is not None:
            await self._stove.activateProgram(
                self._switch_configuration.configuration.sensor_id,
                self._switch_configuration.configuration_id,
                True,
            )
            await self.coordinator.update_data_after_set()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set the switch off."""
        if self._switch_configuration is not None:
            await self._stove.activateProgram(
                self._switch_configuration.configuration.sensor_id,
                self._switch_configuration.configuration_id,
                False,
            )
            await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        value = get_response_value(
            self._supported_switch,
            self._stove.State,
            self._stove.Status,
            self._stove.model_generation,
        )
        assert value is None or isinstance(value, bool)
        self._attr_is_on = value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MczConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch entities from a config entry."""
    coordinator: MczAccountCoordinator = entry.runtime_data.coordinator
    entities = []
    for stove in coordinator.stoves.values():
        entities.extend(_getStoveSwitchEntities(coordinator, stove))
    async_add_entities(entities)


def _getStoveSwitchEntities(
    coordinator: MczAccountCoordinator,
    stove: MaestroStove,
) -> list[CoordinatorEntity[MczAccountCoordinator]]:
    """Get the switch entities to create for this stove."""
    entities: list[CoordinatorEntity[MczAccountCoordinator]] = []
    supported_switches = stove.get_supported_sensor_configurations(
        model_definitions.supported_switches
    )
    if supported_switches is not None:
        entities.extend(
            MczSwitchEntity(
                coordinator, stove.UniqueCode, supported_switch[0], supported_switch[1]
            )
            for supported_switch in supported_switches
            if supported_switch[0] is not None and supported_switch[1] is not None
        )
    return entities
