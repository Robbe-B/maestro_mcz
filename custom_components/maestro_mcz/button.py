"""Platform for Button integration."""
from ..maestro_mcz.datetime import MczDateTimeEntity
from ..maestro_mcz.maestro.responses.model import SensorConfiguration
from ..maestro_mcz.maestro.types.enums import TypeEnum
from . import MczCoordinator, models

from homeassistant.util import dt as dt_util
from homeassistant.components.button import (
    ButtonEntity,
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

        #buttons
        supported_buttons = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(models.supported_buttons)
        if(supported_buttons is not None):
            for supported_button in supported_buttons:
                if(supported_button[0] is not None and supported_button[1] is not None):
                    entities.append(MczButtonEntity(stove, supported_button[0], supported_button[1]))

        #time sync buttons 
        supported_time_sync_buttons = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(models.supported_time_sync_buttons)
        if(supported_time_sync_buttons is not None):
            for supported_time_sync_button in supported_time_sync_buttons:
                if(supported_time_sync_button[0] is not None and supported_time_sync_button[1] is not None):
                    entities.append(MczTimeSyncButtonEntity(stove, supported_time_sync_button[0], supported_time_sync_button[1]))


    async_add_entities(entities)


class MczButtonEntity(CoordinatorEntity, ButtonEntity):

    _attr_has_entity_name = True

    #
    _button_configuration: SensorConfiguration | None = None

    def __init__(self, coordinator, supported_button: models.ButtonMczConfigItem, matching_button_configuration: SensorConfiguration) -> None:
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = supported_button.user_friendly_name
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_button.sensor_set_name}"
        self._attr_icon = supported_button.icon
        self._prop = supported_button.sensor_set_name
        self._enabled_default = supported_button.enabled_by_default
        self._category = supported_button.category

        self.set_button_configuration(matching_button_configuration)

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()
    
    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category
    
    def set_button_configuration(self, matching_button_configuration: SensorConfiguration):
        self._button_configuration = matching_button_configuration
        self._attr_return_value = None

        if(matching_button_configuration.configuration.type == TypeEnum.BOOLEAN.value):
            self._attr_return_value = True
        elif(matching_button_configuration.configuration.type == TypeEnum.INT.value):
            for key in matching_button_configuration.configuration.variants:
                if key in matching_button_configuration.configuration.mappings.keys():
                    if(key == "reset"):
                        self._attr_return_value = matching_button_configuration.configuration.mappings[key]

    async def async_press(self) -> None:
        """Button pressed action execute."""
        if(self._button_configuration is not None and self._attr_return_value is not None):
            if(self._button_configuration.configuration.type == TypeEnum.BOOLEAN.value):
                await self.coordinator._maestroapi.ActivateProgram(self._button_configuration.configuration.sensor_id, self._button_configuration.configuration_id, bool(self._attr_return_value))
                await self.coordinator.update_data_after_set()
            elif(self._button_configuration.configuration.type == TypeEnum.INT.value):
                await self.coordinator._maestroapi.ActivateProgram(self._button_configuration.configuration.sensor_id, self._button_configuration.configuration_id, int(self._attr_return_value))
                await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class MczTimeSyncButtonEntity(CoordinatorEntity, ButtonEntity):
     
    _attr_has_entity_name = True
    #
    _time_sync_button_configuration: SensorConfiguration | None = None
    _mczDateTimeEntity: MczDateTimeEntity | None = None
    
    def __init__(self, coordinator, supported_time_sync_button: models.TimeSyncButtonMczConfigItem, matching_time_sync_button_configuration: SensorConfiguration) -> None:
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator

        self._mczDateTimeEntity = MczDateTimeEntity(coordinator, supported_time_sync_button, matching_time_sync_button_configuration)

        self._attr_name = supported_time_sync_button.user_friendly_name
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_time_sync_button.sensor_set_name}"
        self._attr_icon = supported_time_sync_button.icon
        self._prop = supported_time_sync_button.sensor_set_name
        self._enabled_default = supported_time_sync_button.enabled_by_default
        self._category = supported_time_sync_button.category

        self.set_time_sync_button_configuration(matching_time_sync_button_configuration)

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()
    
    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category
    
    def set_time_sync_button_configuration(self, matching_time_sync_button_configuration: SensorConfiguration):
        self._time_sync_button_configuration = matching_time_sync_button_configuration
        if(self._mczDateTimeEntity is not None):
            self._mczDateTimeEntity.set_date_time_configuration(matching_time_sync_button_configuration)
      

    async def async_press(self) -> None:
        """Button pressed action execute."""
        if(self._time_sync_button_configuration is not None and self._mczDateTimeEntity is not None):
            system_date_time = dt_util.utcnow()
            if(system_date_time is not None):
                await self._mczDateTimeEntity.async_set_value(system_date_time)
                await self.coordinator.update_data_after_set()


    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()