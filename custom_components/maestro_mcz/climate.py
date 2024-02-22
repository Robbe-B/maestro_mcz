"""Platform for Climate integration."""
import logging

from ..maestro_mcz import models
from ..maestro_mcz.maestro.responses.model import SensorConfiguration

from . import MczCoordinator

from homeassistant.components.climate import ClimateEntity
from homeassistant.core import callback
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from .const import DOMAIN
from .maestro.types.enums import TypeEnum

async def async_setup_entry(hass, entry, async_add_entities):
    stove_list = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for stove in stove_list:
        stove:MczCoordinator = stove
        first_supported_power_sensor = stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(models.supported_power_settings)
        if(first_supported_power_sensor is not None and first_supported_power_sensor[0] is not None and first_supported_power_sensor[1] is not None):
            entities.append(MczClimateEntity(stove, first_supported_power_sensor[0], first_supported_power_sensor[1]))
            
    async_add_entities(entities)

class MczClimateEntity(CoordinatorEntity, ClimateEntity):
    
    _attr_has_entity_name = True
    _attr_hvac_mode = None
    _attr_current_temperature = None
    _attr_target_temperature = None
    _attr_preset_mode = None
    _attr_translation_key: str = "main_climate"

    _enable_turn_on_off_backwards_compatibility = False # to be removed after 2025.1

    _supported_power_sensor: models.MczConfigItem | None = None
    _supported_thermostat: models.MczConfigItem | None = None
    _supported_climate_function_mode: models.MczConfigItem | None = None
    #
    _climate_function_mode_configuration: SensorConfiguration | None = None
    _power_configuration: SensorConfiguration | None = None
    _thermostat_configuration: SensorConfiguration | None = None

    
    def __init__(self, coordinator:MczCoordinator, supported_power_sensor: models.PowerSettingMczConfigItem, matching_power_configuration: SensorConfiguration):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator

        #general 
        self._attr_name = None
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}"
        self._attr_icon = "mdi:stove"

        #set power on/off config
        self._supported_power_sensor = supported_power_sensor
        self.set_power_configuration(matching_power_configuration)

        #set thermostat config 
        first_supported_thermostat = coordinator.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(models.supported_thermostats)
        if(first_supported_thermostat is not None and first_supported_thermostat[0] is not None and first_supported_thermostat[1] is not None):
            self._supported_thermostat = first_supported_thermostat[0]
            self.set_thermostat_configuration(first_supported_thermostat[1])

        #set preset/mode config
        first_supported_climate_function_mode = coordinator.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(models.supported_climate_function_modes)
        if(first_supported_climate_function_mode is not None and first_supported_climate_function_mode[0] is not None and first_supported_climate_function_mode[1] is not None):
            self._supported_climate_function_mode = first_supported_climate_function_mode[0]
            self.set_climate_function_mode_configuration(first_supported_climate_function_mode[1])

        #getting the initial update directly without delay
        self.handle_coordinator_update_internal() 
                               
    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()
    
    @property
    def hvac_mode(self):
        return self._attr_hvac_mode

    @property
    def current_temperature(self):
        return self._attr_current_temperature

    @property
    def target_temperature(self):
        return self._attr_target_temperature

    @property
    def preset_mode(self):
        return self._attr_preset_mode

    def set_power_configuration(self, matching_power_configuration: SensorConfiguration):
        self._power_configuration = matching_power_configuration
        if(matching_power_configuration.configuration.type == TypeEnum.BOOLEAN.value):
            self._attr_supported_features |= (ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON)
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        elif(matching_power_configuration.configuration.type == TypeEnum.INT.value):
            self._attr_supported_features |= (ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON)
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
            self._attr_hvac_modes_mappings = dict()
            for key in matching_power_configuration.configuration.variants:
                if key in matching_power_configuration.configuration.mappings.keys():
                    if(key == "on"):
                        self._attr_hvac_modes_mappings[HVACMode.HEAT] = matching_power_configuration.configuration.mappings[key]
                    elif(key == "off"):
                        self._attr_hvac_modes_mappings[HVACMode.OFF] = matching_power_configuration.configuration.mappings[key]

    def set_thermostat_configuration(self, matching_thermostat_configuration: SensorConfiguration):
        self._thermostat_configuration = matching_thermostat_configuration
        if(matching_thermostat_configuration.configuration.type == TypeEnum.DOUBLE.value):
            self._attr_min_temp = float(matching_thermostat_configuration.configuration.min)
            self._attr_max_temp = float(matching_thermostat_configuration.configuration.max)
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE
    
    def set_climate_function_mode_configuration(self, matching_climate_function_mode_configuration: SensorConfiguration):
        self._climate_function_mode_configuration = matching_climate_function_mode_configuration
        if(matching_climate_function_mode_configuration.configuration.type == TypeEnum.INT.value):
            self._attr_preset_modes = []
            self._attr_preset_modes_mappings = matching_climate_function_mode_configuration.configuration.mappings
            for key in matching_climate_function_mode_configuration.configuration.variants:
                if key in self._supported_climate_function_mode.api_mappings_key_rename.keys():
                    self._attr_preset_modes.append(self._supported_climate_function_mode.api_mappings_key_rename[key])
                    #Add the internal mapped key (from the config) in the public mappings (api mappings), with same value but mapped key
                    if(key in self._attr_preset_modes_mappings):
                        self._attr_preset_modes_mappings[self._supported_climate_function_mode.api_mappings_key_rename[key]] = self._attr_preset_modes_mappings[key]
                else:
                    self._attr_preset_modes.append(key)
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

    async def async_set_preset_mode(self, preset_mode):
        if(self._climate_function_mode_configuration is not None):
            if (self._attr_preset_modes_mappings is not None and preset_mode in self._attr_preset_modes_mappings.keys()):
                converted_preset_mode = self._attr_preset_modes_mappings[preset_mode]
                await self.coordinator._maestroapi.ActivateProgram(self._climate_function_mode_configuration.configuration.sensor_id, self._climate_function_mode_configuration.configuration_id, converted_preset_mode)
                await self.coordinator.update_data_after_set()

    async def async_set_hvac_mode(self, hvac_mode):
        if(self._power_configuration is not None):
            if(self.hvac_mode is not None and self.hvac_mode is not hvac_mode): #avoid sending the same hvac mode to the API because this will result in a toggle of the power setting of the stove
                if(self._power_configuration.configuration.type == TypeEnum.BOOLEAN.value):
                    await self.coordinator._maestroapi.ActivateProgram(self._power_configuration.configuration.sensor_id, self._power_configuration.configuration_id, True)
                    await self.coordinator.update_data_after_set()
                elif(self._power_configuration.configuration.type == TypeEnum.INT.value):
                    if (self._attr_hvac_modes_mappings and hvac_mode in self._attr_hvac_modes_mappings.keys()):
                        await self.coordinator._maestroapi.ActivateProgram(self._power_configuration.configuration.sensor_id, self._power_configuration.configuration_id, int(self._attr_hvac_modes_mappings[hvac_mode]))
                        await self.coordinator.update_data_after_set()

    async def async_set_temperature(self, **kwargs):
        if(self._thermostat_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self._thermostat_configuration.configuration.sensor_id, self._thermostat_configuration.configuration_id, float(kwargs["temperature"]))
            await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.handle_coordinator_update_internal()   
        self.async_write_ha_state()

    def handle_coordinator_update_internal(self) -> None:
        #HVAC mode
        if(self._supported_power_sensor is not None): 
            stato_stufa = getattr(self.coordinator._maestroapi.Status, self._supported_power_sensor.sensor_get_name)
            if(stato_stufa is not None):
                if(stato_stufa == 0 or stato_stufa == 1):
                    self._attr_hvac_mode = HVACMode.OFF
                else:
                    self._attr_hvac_mode = HVACMode.HEAT
            else:
                self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = None
            

        #current temp
        self._attr_current_temperature = self.coordinator._maestroapi.State.temp_amb_install

        #target temp 
        if(self._supported_thermostat is not None): 
            self._attr_target_temperature = getattr(self.coordinator._maestroapi.State, self._supported_thermostat.sensor_get_name)
        else:
            self._attr_target_temperature = None

        #preset modes
        if(self._supported_climate_function_mode is not None): 
            preset_mode_value = str(getattr(self.coordinator._maestroapi.State, self._supported_climate_function_mode.sensor_get_name))
            if(self._supported_climate_function_mode.api_mappings_key_rename is not None and preset_mode_value in self._supported_climate_function_mode.api_mappings_key_rename.keys()):
                self._attr_preset_mode = self._supported_climate_function_mode.api_mappings_key_rename[preset_mode_value]
            else:
                self._attr_preset_mode = preset_mode_value
        else:
            self._attr_preset_mode = None
