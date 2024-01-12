"""Platform for Switch integration."""
from ..maestro_mcz.maestro.responses.model import SensorConfiguration
from ..maestro_mcz.maestro.types.enums import TypeEnum
from . import MczCoordinator, models

from homeassistant.components.switch import (
    SwitchEntity,
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    stoveList = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for stove in stoveList:
        stove:MczCoordinator = stove
        supported_switches = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(models.supported_switches)
        if(supported_switches is not None):
            for supported_switch in supported_switches:
                if(supported_switch[0] is not None and supported_switch[1] is not None):
                    entities.append(MczSwitchEntity(stove, supported_switch[0], supported_switch[1]))

    async_add_entities(entities)


class MczSwitchEntity(CoordinatorEntity, SwitchEntity):

    _attr_has_entity_name = True
    _attr_is_on = None

     #
    _switch_configuration: SensorConfiguration | None = None

    def __init__(self, coordinator, supported_switch: models.SwitchMczConfigItem, matching_switch_configuration: SensorConfiguration):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = supported_switch.user_friendly_name
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_switch.sensor_get_name}"
        self._attr_icon = supported_switch.icon
        self._prop = supported_switch.sensor_get_name
        self._enabled_default = supported_switch.enabled_by_default
        self._category = supported_switch.category
        self._switch_configuration = matching_switch_configuration
        #if(matching_switch_configuration.configuration.type == TypeEnum.BOOLEAN.value):
        self.handle_coordinator_update_internal() #getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def is_on(self):
        return self._attr_is_on

    async def async_turn_on(self, **kwargs):
        """Set the switch on."""
        if(self._switch_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self._switch_configuration.configuration.sensor_id, self._switch_configuration.configuration_id, True)
            await self.coordinator.update_date_after_set()
            
    async def async_turn_off(self, **kwargs):
        """Set the switch off."""
        if(self._switch_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self._switch_configuration.configuration.sensor_id, self._switch_configuration.configuration_id, False)
            await self.coordinator.update_date_after_set()

    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    @callback
    def _handle_coordinator_update(self) -> None:
        self.handle_coordinator_update_internal()
        self.async_write_ha_state()

    def handle_coordinator_update_internal(self) -> None:
        if(hasattr(self.coordinator._maestroapi.State, self._prop)):
            self._attr_is_on = getattr(self.coordinator._maestroapi.State, self._prop)
        elif(hasattr(self.coordinator._maestroapi.Status, self._prop)):
            self._attr_is_on = getattr(self.coordinator._maestroapi.Status, self._prop)
        else:
            self._attr_is_on = None