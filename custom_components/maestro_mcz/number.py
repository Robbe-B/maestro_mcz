"""Platform for Number integration."""
from custom_components.maestro_mcz.maestro.responses.model import SensorConfiguration
from custom_components.maestro_mcz.maestro.types.enums import TypeEnum
from . import MczCoordinator, models

from homeassistant.components.number import (
    DEFAULT_MAX_VALUE,
    DEFAULT_MIN_VALUE,
    DEFAULT_STEP,
    NumberEntity
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
        supported_numbers = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(models.supported_numbers)
        if(supported_numbers is not None):
            for supported_number in supported_numbers:
                if(supported_number[0] is not None and supported_number[1] is not None):
                    entities.append(MczNumberEntity(stove, supported_number[0], supported_number[1]))

    async_add_entities(entities)


class MczNumberEntity(CoordinatorEntity, NumberEntity):

    _attr_has_entity_name = True

    # 
    _number_configuration: SensorConfiguration | None = None

    def __init__(self, coordinator, supported_number:models.NumberMczConfigItem, matching_number_configuration: SensorConfiguration):
        super().__init__(coordinator)
        self.coordinator:MczCoordinator = coordinator
        self._attr_name = supported_number.user_friendly_name
        self._attr_native_unit_of_measurement = supported_number.unit
        self._attr_device_class = supported_number.device_class
        self._attr_unique_id = f"{self.coordinator._maestroapi.Status.sm_sn}-{supported_number.sensor_get_name}"
        self._attr_icon = supported_number.icon
        self._attr_mode = supported_number.mode
        self._prop = supported_number.sensor_get_name
        self._enabled_default = supported_number.enabled_by_default
        self._category = supported_number.category
        self._number_configuration = matching_number_configuration
        if(matching_number_configuration.configuration.type == TypeEnum.INT.value or matching_number_configuration.configuration.type == TypeEnum.DOUBLE.value):
            self._attr_native_step = DEFAULT_STEP
            self._attr_native_min_value = float(matching_number_configuration.configuration.min or DEFAULT_MIN_VALUE)
            self._attr_native_max_value = float(matching_number_configuration.configuration.max or DEFAULT_MAX_VALUE)


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
    def native_value(self):
        if(hasattr(self.coordinator._maestroapi.State, self._prop)):
            return getattr(self.coordinator._maestroapi.State, self._prop)
        elif(hasattr(self.coordinator._maestroapi.Status, self._prop)):
            return getattr(self.coordinator._maestroapi.Status, self._prop)
        else:
            return None

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self._enabled_default

    @property
    def entity_category(self):
        return self._category
    
    async def async_set_native_value(self, value: float) -> None:
        """Set the value."""
        if(self._number_configuration is not None):
            if(self._number_configuration.configuration.type == TypeEnum.INT.value):
                converted_value = int(value)
            else: 
                converted_value = value
            
            await self.coordinator._maestroapi.ActivateProgram(self._number_configuration.configuration.sensor_id, self._number_configuration.configuration_id, converted_value)
            await self.coordinator.async_request_refresh()       
    
    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()
