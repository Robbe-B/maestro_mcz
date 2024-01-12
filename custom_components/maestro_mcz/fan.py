"""Platform for Fan integration."""
import logging

from ..maestro_mcz.maestro.responses.model import SensorConfiguration, SensorConfigurationMultipleModes
from ..maestro_mcz.maestro.types.enums import TypeEnum
from . import MczCoordinator, models

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature
)
from homeassistant.core import callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, entry, async_add_entities):
    stove_list = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for stove in stove_list:
        stove:MczCoordinator = stove

        supported_fans = stove.get_all_matching_sensor_for_all_configurations_by_model_mode_and_sensor_name(models.supported_fans)

        if(supported_fans is not None):
            for supported_fan in supported_fans:
                if(supported_fan[0] is not None and supported_fan[1] is not None):
                    entities.append(MczFanEntity(stove, supported_fan[0], supported_fan[1]))

    async_add_entities(entities)


class MczFanEntity(CoordinatorEntity, FanEntity):
    _attr_has_entity_name = True
    _attr_preset_mode = None
    _attr_is_on = None
    #
    _fan_configuration: SensorConfigurationMultipleModes | None = None
    _current_fan_configuration: SensorConfiguration | None = None
    _presets: list | None = None

    def __init__(self, coordinator, supported_fan: models.FanMczConfigItem, matching_fan_configuration: SensorConfigurationMultipleModes):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = supported_fan.user_friendly_name
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_fan.sensor_get_name}"
        self._attr_icon = supported_fan.icon
        self._prop = supported_fan.sensor_get_name
        self._enabled_default = supported_fan.enabled_by_default
        self._category = supported_fan.category
        self._fan_configuration = matching_fan_configuration
        
        self.update_features_based_on_current_stove_state()

        self.handle_coordinator_update_internal() #getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def is_on(self) -> bool:
        return self._attr_is_on

    @property
    def preset_mode(self) -> str:
        return self._attr_preset_mode

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        if(self._current_fan_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self._current_fan_configuration.configuration.sensor_id, self._current_fan_configuration.configuration_id, int(preset_mode))
            await self.coordinator.async_refresh()

    async def async_turn_on(self) -> None:
        """Turn on the fan."""
        if(self._current_fan_configuration is not None and self._presets is not None and len(self._presets) > 0):
            await self.coordinator._maestroapi.ActivateProgram(self._current_fan_configuration.configuration.sensor_id, self._current_fan_configuration.configuration_id, int(self._presets[-1]))
            await self.coordinator.async_refresh()

    async def async_turn_off(self) -> None:
        """Turn off the fan."""
        if(self._current_fan_configuration is not None and self._presets is not None and len(self._presets) > 0):
            await self.coordinator._maestroapi.ActivateProgram(self._current_fan_configuration.configuration.sensor_id, self._current_fan_configuration.configuration_id, int(self._presets[0]))
            await self.coordinator.async_refresh()

    def get_configuration_for_current_stove_mode(self) -> SensorConfiguration | None:
        """Get the correct sensor configuration for the current mode that the stove is in"""
        if(self.coordinator._maestroapi.State is not None and self.coordinator._maestroapi.State.mode is not None 
           and self._fan_configuration is not None and self.coordinator._maestroapi.State.mode in self._fan_configuration.mode_configurations):
            return self._fan_configuration.mode_configurations[self.coordinator._maestroapi.State.mode]
        return None
    
    def update_features_based_on_current_stove_state(self) -> None:
        """Refresh all fan features that are applicable for the current mode that the stove is in"""
        self._current_fan_configuration = self.get_configuration_for_current_stove_mode()

        self._attr_supported_features = FanEntityFeature(0) # resetting the features
        if(self._current_fan_configuration is not None and 
           self._current_fan_configuration.configuration is not None and 
           self._current_fan_configuration.configuration.enabled == True):
            if(self._current_fan_configuration.configuration.type == TypeEnum.INT.value):
                self._presets = self._attr_preset_modes = list(map(str,range(int(self._current_fan_configuration.configuration.min), int(self._current_fan_configuration.configuration.max) + 1 , 1)))
                self._attr_supported_features = (FanEntityFeature.PRESET_MODE)

    @callback
    def _handle_coordinator_update(self) -> None:
        """handle coordinator updates"""
        self.update_features_based_on_current_stove_state()
        self.handle_coordinator_update_internal()
        self.async_write_ha_state()

    def handle_coordinator_update_internal(self) -> None:
        """handle coordinator updates for this fan"""
        #presets
        if(hasattr(self.coordinator._maestroapi.State, self._prop)):
            self._attr_preset_mode = str(getattr(self.coordinator._maestroapi.State, self._prop))
        elif(hasattr(self.coordinator._maestroapi.Status, self._prop)):
            self._attr_preset_mode = str(getattr(self.coordinator._maestroapi.Status, self._prop))
        else:
            self._attr_preset_mode = None

        # on/off
        if(self._current_fan_configuration is not None and self._presets is not None and len(self._presets) > 0):
            self._attr_is_on = self.preset_mode != self._presets[0]
        else:
            self._attr_is_on = False