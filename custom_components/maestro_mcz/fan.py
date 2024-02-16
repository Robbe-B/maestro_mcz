"""Platform for Fan integration."""
import logging
import math

from typing import Any
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
from homeassistant.util.percentage import ranged_value_to_percentage, percentage_to_ranged_value


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
    _attr_available: bool = True
    #
    _attr_is_on: bool | None = None
    _attr_percentage: int | None = None
    _attr_preset_mode: str | None = None
    _attr_preset_modes: list[str] | None = None
    _attr_speed_count: int = 0
    _attr_translation_key: str = "main_fan"
    #
    _supported_fan: models.FanMczConfigItem | None = None
    _fan_configuration: SensorConfigurationMultipleModes | None = None
    _current_fan_configuration: SensorConfiguration | None = None

    def __init__(self, coordinator, supported_fan: models.FanMczConfigItem, matching_fan_configuration: SensorConfigurationMultipleModes):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = supported_fan.user_friendly_name
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_fan.sensor_get_name}"
        self._attr_icon = supported_fan.icon
        self._prop = supported_fan.sensor_get_name
        self._enabled_default = supported_fan.enabled_by_default
        self._category = supported_fan.category
        self._supported_fan = supported_fan
        self._fan_configuration = matching_fan_configuration
        
        self.update_features_based_on_current_stove_mode() #each mode of the stove has other fan settings, so we need to update this accordingly

        self.handle_coordinator_update_internal() #getting the initial update directly without delay

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()
    
    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category
      
    @property
    def available(self) -> bool:
        return self._attr_available
    
    @property
    def icon(self) -> str | None:
        if(self._supported_fan is not None):
           if(self._supported_fan.icon is not None and self.available == True):
               return self._supported_fan.icon
           elif(self._supported_fan.unavailable_icon is not None and self.available == False):
               return self._supported_fan.unavailable_icon
           else:
               return None
        else:
            return None    

    @property
    def is_on(self) -> bool | None:
        return self._attr_is_on
    
    @property
    def percentage(self) -> int | None:
        return self._attr_percentage

    @property
    def preset_mode(self) -> str | None:
        return self._attr_preset_mode
    
    @property
    def preset_modes(self) -> list[str] | None:
        return self._attr_preset_modes
    
    @property
    def speed_count(self) -> int:
        return self._attr_speed_count

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode of the fan."""
        if(self._current_fan_configuration is not None and 
           self._current_fan_configuration.configuration is not None and
           self._current_fan_configuration.configuration.mappings is not None and
           len(self._current_fan_configuration.configuration.mappings) > 0 and
           preset_mode in self._current_fan_configuration.configuration.mappings):
            await self.coordinator._maestroapi.ActivateProgram(self._current_fan_configuration.configuration.sensor_id, self._current_fan_configuration.configuration_id, preset_mode)
            await self.coordinator.update_data_after_set()

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs: Any,) -> None:
        """Turn on the fan."""
        if(self._current_fan_configuration is not None):
            if(preset_mode is not None):
                await self.async_set_preset_mode(preset_mode)
            elif(percentage is not None):
                await self.async_set_percentage(percentage)
            else:
                await self.async_set_percentage(100)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        if(self._current_fan_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self._current_fan_configuration.configuration.sensor_id, self._current_fan_configuration.configuration_id, 0) # '0' means off
            await self.coordinator.update_data_after_set()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if(self._attr_speed_count > 1):
            value_in_range = math.ceil(percentage_to_ranged_value((1, self._attr_speed_count), percentage))
            if(self._current_fan_configuration is not None):
                await self.coordinator._maestroapi.ActivateProgram(self._current_fan_configuration.configuration.sensor_id, self._current_fan_configuration.configuration_id, value_in_range)
                await self.coordinator.update_data_after_set()

    def get_configuration_for_current_stove_mode(self) -> SensorConfiguration | None:
        """Get the correct sensor configuration for the current mode that the stove is in"""
        if(self.coordinator._maestroapi.State is not None and self.coordinator._maestroapi.State.mode is not None 
           and self._fan_configuration is not None and self.coordinator._maestroapi.State.mode in self._fan_configuration.mode_configurations):
            return self._fan_configuration.mode_configurations[self.coordinator._maestroapi.State.mode]
        return None
    
    def update_features_based_on_current_stove_mode(self) -> None:
        """Refresh all fan features that are applicable for the current mode that the stove is in"""
        self._current_fan_configuration = self.get_configuration_for_current_stove_mode()

        self._attr_supported_features = FanEntityFeature(0) # resetting the features
        self._attr_preset_modes = None
        self._attr_speed_count = 0
        self._attr_available = False

        if(self._current_fan_configuration is not None and 
           self._current_fan_configuration.configuration is not None and 
           self._current_fan_configuration.configuration.enabled == True):
                self._attr_available = True
                if(self._current_fan_configuration.configuration.type == TypeEnum.INT.value):
                    self._attr_speed_count = int(self._current_fan_configuration.configuration.max)
                    self._attr_supported_features |= FanEntityFeature.SET_SPEED

                    if(self._current_fan_configuration.configuration.variants is not None and 
                        len(self._current_fan_configuration.configuration.variants) > 0):
                            self._attr_preset_modes = []             
                            for key in self._current_fan_configuration.configuration.variants:
                                if key in self._current_fan_configuration.configuration.mappings.keys():
                                    self._attr_preset_modes.append(key)         
                            self._attr_supported_features |= FanEntityFeature.PRESET_MODE

    @callback
    def _handle_coordinator_update(self) -> None:
        """handle coordinator updates"""
        self.update_features_based_on_current_stove_mode()
        self.handle_coordinator_update_internal()
        self.async_write_ha_state()

    def handle_coordinator_update_internal(self) -> None:
        """handle coordinator updates for this fan"""
        
        #determine if the fan is enabled 
        if(self._current_fan_configuration is not None and 
           self._current_fan_configuration.configuration is not None and 
           self._current_fan_configuration.configuration.enabled == True):
             self._attr_available = True
        else:
            self._attr_available = False
            return #we can return heere since the fan is disabled in the config and we don't need to update values 
        
        #determine silent mode is enabled 
        if(self._supported_fan is not None and self._supported_fan.silent_enabled_get_name is not None):
            if(hasattr(self.coordinator._maestroapi.State, self._supported_fan.silent_enabled_get_name)):
                silent_enabled = bool(getattr(self.coordinator._maestroapi.State, self._supported_fan.silent_enabled_get_name))
            elif(hasattr(self.coordinator._maestroapi.Status, self._supported_fan.silent_enabled_get_name)):
                silent_enabled = bool(getattr(self.coordinator._maestroapi.Status, self._supported_fan.silent_enabled_get_name))
            else:
                silent_enabled = None

            if(silent_enabled is not None and silent_enabled == True):
                self._attr_available = False
                return # we can return here since the rest doesn't matter anymore when the fan is not available


        #determine the fan value
        if(hasattr(self.coordinator._maestroapi.State, self._prop)):
            fan_value = str(getattr(self.coordinator._maestroapi.State, self._prop))
        elif(hasattr(self.coordinator._maestroapi.Status, self._prop)):
            fan_value = str(getattr(self.coordinator._maestroapi.Status, self._prop))
        else:
            fan_value = None
        
        try:
            fan_value = int(fan_value)
        except Exception as ex:
            pass # fan_value can be a string


        # on/off
        if(self._current_fan_configuration is not None and 
           fan_value is not None and
           (type(fan_value) is str or (type(fan_value) is int and fan_value != 0))):
            self._attr_is_on = True
        else:
            self._attr_is_on = False

        #presets
        if(self._current_fan_configuration is not None and 
           self._current_fan_configuration.configuration.mappings is not None and
           len(self._current_fan_configuration.configuration.mappings) > 0 and
           fan_value is not None and
           ((type(fan_value) is str and fan_value in self._current_fan_configuration.configuration.mappings) or
           (type(fan_value) is int and fan_value in self._current_fan_configuration.configuration.mappings.values() and fan_value != 0))):
            if(type(fan_value) is str):
                self._attr_preset_mode = fan_value
            elif(type(fan_value) is int):
                self._attr_preset_mode = self._current_fan_configuration.configuration.mappings[list(self._current_fan_configuration.configuration.mappings.values()).index(fan_value)]
        else:
            self._attr_preset_mode = None

        #speed
        if(self._current_fan_configuration is not None and
           self._current_fan_configuration.configuration.min is not None and
           self._current_fan_configuration.configuration.max is not None and
           fan_value is not None and
           type(fan_value) is int and
           self._attr_speed_count >= 1 and
           int(self._current_fan_configuration.configuration.min) <= fan_value <= int(self._current_fan_configuration.configuration.max) and 
           fan_value != 0):
            self._attr_percentage = ranged_value_to_percentage((1, self._attr_speed_count),fan_value)
        else:
            self._attr_percentage = None
