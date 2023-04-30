"""Platform for Climate integration."""
import logging

from custom_components.maestro_mcz import models
from custom_components.maestro_mcz.maestro.responses.model import Configuration, SensorConfiguration

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

    supported_power_sensor: models.MczConfigItem | None = None
    supported_thermostat: models.MczConfigItem | None = None
    supported_climate_function_mode: models.MczConfigItem | None = None
    supported_pot: models.MczConfigItem | None = None
    supported_fan: models.MczConfigItem | None = None
    #
    climate_function_mode_configuration: SensorConfiguration | None = None
    power_configuration: SensorConfiguration | None = None
    fan_configuration: SensorConfiguration | None = None
    pot_configuration: SensorConfiguration | None = None
    thermostat_configuration: SensorConfiguration | None = None

    
    def __init__(self, coordinator:MczCoordinator, supported_power_sensor: models.PowerSettingMczConfigItem, matching_power_configuration: SensorConfiguration):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator

        #general 
        self._attr_name = None
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}"
        self._attr_icon = "mdi:stove"

        #set power on/off config
        self.supported_power_sensor = supported_power_sensor
        self.set_power_configuration(matching_power_configuration)

        #set thermostat config 
        first_supported_thermostat = coordinator.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(models.supported_thermostats)
        if(first_supported_thermostat is not None and first_supported_thermostat[0] is not None and first_supported_thermostat[1] is not None):
            self.supported_thermostat = first_supported_thermostat[0]
            self.set_thermostat_configuration(first_supported_thermostat[1])

        #set preset config
        first_supported_climate_function_mode = coordinator.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(models.supported_climate_function_modes)
        if(first_supported_climate_function_mode is not None and first_supported_climate_function_mode[0] is not None and first_supported_climate_function_mode[1] is not None):
            self.supported_climate_function_mode = first_supported_climate_function_mode[0]
            self.set_climate_function_mode_configuration(first_supported_climate_function_mode[1])

        #set pot config
        first_supported_pot = coordinator.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(models.supported_pots)
        if(first_supported_pot is not None and first_supported_pot[0] is not None and first_supported_pot[1] is not None):
            self.supported_pot = first_supported_pot[0]
            self.set_pot_configuration(first_supported_pot[1])

        #set fan config
        first_supported_fan = coordinator.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(models.supported_fans)
        if(first_supported_fan is not None and first_supported_fan[0] is not None and first_supported_fan[1] is not None):
            self.supported_fan = first_supported_fan[0]
            self.set_fan_configuration(first_supported_fan[1])
                               
    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator._maestroapi.Status.sm_sn)},
            name=self.coordinator._maestroapi.Name,
            manufacturer="MCZ",
            model=self.coordinator._maestroapi.Model.model_name,
            sw_version=f"{self.coordinator._maestroapi.Status.sm_nome_app}.{self.coordinator._maestroapi.Status.sm_vs_app}"
            + f", Panel:{self.coordinator._maestroapi.Status.mc_vs_app}"
            + f", DB:{self.coordinator._maestroapi.Status.nome_banca_dati_sel}",
        )
    
    @property
    def hvac_mode(self):
        if(self.supported_power_sensor is not None): 
            fase_op = getattr(self.coordinator._maestroapi.Status, self.supported_power_sensor.sensor_get_name)
            if(fase_op is not None):
                if(str(fase_op).lower() == "on" or str(fase_op).lower() == "turning-on"):
                    return HVACMode.HEAT
                else: # turning-off | off | cooling-down
                    return HVACMode.OFF
        else:
            return None
        
    @property
    def fan_mode(self):
        if(self.supported_fan is not None): 
            return str(getattr(self.coordinator._maestroapi.Status, self.supported_fan.sensor_get_name))
        else :
            return None

    @property
    def swing_mode(self):
        if(self.supported_pot is not None): 
            return str(getattr(self.coordinator._maestroapi.Status, self.supported_pot.sensor_get_name))
        else : 
            return None

    @property
    def current_temperature(self): #ToDo in case there can be different => needs more investigation in the future
        return self.coordinator._maestroapi.State.temp_amb_install

    @property
    def target_temperature(self):
        if(self.supported_thermostat is not None): 
            return getattr(self.coordinator._maestroapi.State, self.supported_thermostat.sensor_get_name)
        else:
            return None

    @property
    def preset_mode(self):
        if(self.supported_climate_function_mode is not None): 
            return str(getattr(self.coordinator._maestroapi.State, self.supported_climate_function_mode.sensor_get_name))
        else:
            return None


    def set_power_configuration(self, matching_power_configuration: SensorConfiguration):
        self.power_configuration = matching_power_configuration
        if(matching_power_configuration.configuration.type == TypeEnum.BOOLEAN.value):
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]

    def set_thermostat_configuration(self, matching_thermostat_configuration: SensorConfiguration):
        self.thermostat_configuration = matching_thermostat_configuration
        if(matching_thermostat_configuration.configuration.type == TypeEnum.DOUBLE.value):
            self._attr_min_temp = float(matching_thermostat_configuration.configuration.min)
            self._attr_max_temp = float(matching_thermostat_configuration.configuration.max)
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE
    
    def set_climate_function_mode_configuration(self, matching_climate_function_mode_configuration: SensorConfiguration):
        self.climate_function_mode_configuration = matching_climate_function_mode_configuration
        if(matching_climate_function_mode_configuration.configuration.type == TypeEnum.INT.value):
            self._attr_preset_modes = []
            self._attr_preset_modes_mappings = matching_climate_function_mode_configuration.configuration.mappings
            for key in matching_climate_function_mode_configuration.configuration.variants:
                if key in self.supported_climate_function_mode.mappings.keys():
                    self._attr_preset_modes.append(self.supported_climate_function_mode.mappings[key])
                    #Add the internal mapped key (from the config) in the public mappings (api mappings), with same value but mapped key
                    if(key in self._attr_preset_modes_mappings):
                        self._attr_preset_modes_mappings[self.supported_climate_function_mode.mappings[key]] = self._attr_preset_modes_mappings[key]
                else:
                    self._attr_preset_modes.append(key)
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

    def set_pot_configuration(self, matching_pot_configuration: SensorConfiguration):
        self.pot_configuration = matching_pot_configuration
        if(matching_pot_configuration.configuration.type == TypeEnum.INT.value):
            self._attr_swing_modes = list(map(str,range(int(matching_pot_configuration.configuration.min), int(matching_pot_configuration.configuration.max) + 1 , 1)))
            self._attr_supported_features |= ClimateEntityFeature.SWING_MODE

    def set_fan_configuration(self, matching_fan_configuration: SensorConfiguration):
        self.fan_configuration = matching_fan_configuration
        if(matching_fan_configuration.configuration.type == TypeEnum.INT.value):
            self._attr_fan_modes = list(map(str,range(int(matching_fan_configuration.configuration.min), int(matching_fan_configuration.configuration.max) + 1 , 1)))
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE

    async def async_set_preset_mode(self, preset_mode):
        if(self.climate_function_mode_configuration is not None):
            if (preset_mode in self._attr_preset_modes_mappings.keys()):
                converted_preset_mode = self._attr_preset_modes_mappings[preset_mode]
                await self.coordinator._maestroapi.ActivateProgram(self.climate_function_mode_configuration.configuration.sensor_id, self.climate_function_mode_configuration.configuration_id, converted_preset_mode)
                await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode):
        if(self.power_configuration is not None):
                await self.coordinator._maestroapi.ActivateProgram(self.power_configuration.configuration.sensor_id, self.power_configuration.configuration_id, True)
                await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode):
        if(self.fan_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self.fan_configuration.configuration.sensor_id, self.fan_configuration.configuration_id, int(fan_mode))
            await self.coordinator.async_request_refresh()

    async def async_set_swing_mode(self, swing_mode):
        if(self.pot_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self.pot_configuration.configuration.sensor_id, self.pot_configuration.configuration_id,int(swing_mode))
            await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs):
        if(self.thermostat_configuration is not None):
            await self.coordinator._maestroapi.ActivateProgram(self.thermostat_configuration.configuration.sensor_id, self.thermostat_configuration.configuration_id, float(kwargs["temperature"]))
            await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        if(self.supported_thermostat is not None): 
            self._attr_target_temperature = getattr(self.coordinator._maestroapi.State, self.supported_thermostat.sensor_get_name)
        if(self.supported_fan is not None): 
            self._attr_fan_mode = str(getattr(self.coordinator._maestroapi.Status, self.supported_fan.sensor_get_name))
        if(self.supported_pot is not None): 
            self._attr_swing_mode = str(getattr(self.coordinator._maestroapi.Status, self.supported_pot.sensor_get_name))   
        if(self.supported_climate_function_mode is not None): 
            self._attr_preset_mode = str(getattr(self.coordinator._maestroapi.State, self.supported_climate_function_mode.sensor_get_name))
        
        self.async_write_ha_state()
