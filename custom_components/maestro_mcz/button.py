"""Platform for Button integration."""
from ..maestro_mcz.maestro.responses.model import SensorConfiguration
from ..maestro_mcz.maestro.types.enums import TypeEnum
from . import MczCoordinator, models

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
        supported_buttons = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(models.supported_buttons)
        if(supported_buttons is not None):
            for supported_button in supported_buttons:
                if(supported_button[0] is not None and supported_button[1] is not None):
                    entities.append(MczButtonEntity(stove, supported_button[0], supported_button[1]))


    async_add_entities(entities)


class MczButtonEntity(CoordinatorEntity, ButtonEntity):

    _attr_has_entity_name = True

    #
    _button_configuration: SensorConfiguration | None = None

    def __init__(self, coordinator, supported_button: models.ButtonMczConfigItem, matching_button_configuration: SensorConfiguration):
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
                await self.coordinator.update_date_after_set()
            elif(self._button_configuration.configuration.type == TypeEnum.INT.value):
                await self.coordinator._maestroapi.ActivateProgram(self._button_configuration.configuration.sensor_id, self._button_configuration.configuration_id, int(self._attr_return_value))
                await self.coordinator.update_date_after_set()

    @property
    def entity_registry_enabled_default(self) -> bool:
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()