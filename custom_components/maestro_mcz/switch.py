"""Platform for Switch integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MczDeviceCoordinator
from .maestro.controller.responses.model import SensorConfiguration
from .maestro.models import models


class MczSwitchEntity(CoordinatorEntity, SwitchEntity):
    """Switch entity for Maestro MCZ stoves."""

    _attr_has_entity_name = True
    _attr_is_on = None

    #
    _switch_configuration: SensorConfiguration | None = None

    def __init__(
        self,
        coordinator: MczDeviceCoordinator,
        supported_switch: models.SwitchMczConfigItem,
        matching_switch_configuration: SensorConfiguration,
    ):
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self.coordinator: MczDeviceCoordinator = coordinator
        self._attr_name = supported_switch.user_friendly_name
        self._attr_unique_id = (
            f"{self.coordinator.stove.UniqueCode}-{supported_switch.sensor_get_name}"
        )
        self._attr_icon = supported_switch.icon
        self._prop = supported_switch.sensor_get_name
        self._enabled_default = supported_switch.enabled_by_default
        self._category = supported_switch.category
        self._switch_configuration = matching_switch_configuration
        # if(matching_switch_configuration.configuration.type == TypeEnum.BOOLEAN.value):
        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def is_on(self):
        return self._attr_is_on

    async def async_turn_on(self, **kwargs):
        """Set the switch on."""
        if self._switch_configuration is not None:
            await self.coordinator.stove.activateProgram(
                self._switch_configuration.configuration.sensor_id,
                self._switch_configuration.configuration_id,
                True,
            )
            await self.coordinator.update_data_after_set()

    async def async_turn_off(self, **kwargs):
        """Set the switch off."""
        if self._switch_configuration is not None:
            await self.coordinator.stove.activateProgram(
                self._switch_configuration.configuration.sensor_id,
                self._switch_configuration.configuration_id,
                False,
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
        if hasattr(self.coordinator.stove.Status, self._prop):
            self._attr_is_on = getattr(self.coordinator.stove.Status, self._prop)
        elif hasattr(self.coordinator.stove.State, self._prop):
            self._attr_is_on = getattr(self.coordinator.stove.State, self._prop)
        else:
            self._attr_is_on = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up switch entities from a config entry."""
    coordinators = entry.runtime_data
    entities = []
    for coordinator in coordinators.values():
        entities.extend(_getStoveSwitchEntities(coordinator))
    async_add_entities(entities)


def _getStoveSwitchEntities(
    coordinator: MczDeviceCoordinator,
) -> list[CoordinatorEntity]:
    """Get the switch entities to create for this stove."""
    entities = []
    supported_switches = coordinator.stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        models.supported_switches
    )
    if supported_switches is not None:
        entities.extend(
            MczSwitchEntity(coordinator, supported_switch[0], supported_switch[1])
            for supported_switch in supported_switches
            if supported_switch[0] is not None and supported_switch[1] is not None
        )
    return entities
