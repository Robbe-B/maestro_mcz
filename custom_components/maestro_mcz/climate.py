"""Platform for Climate integration."""

from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MczDeviceCoordinator
from .maestro.controller.responses.model import SensorConfiguration
from .maestro.models import models
from .maestro.types.enums import SensorTypeEnum


class MczClimateEntity(CoordinatorEntity, ClimateEntity):
    """Representation of a MCZ climate entity."""

    _attr_has_entity_name = True
    _attr_hvac_mode: HVACMode | None = None
    _attr_hvac_action: HVACAction | None = None
    _attr_current_temperature = None
    _attr_target_temperature = None
    _attr_preset_mode = None
    _attr_translation_key: str = "main_climate"

    _supported_power_sensor: models.PowerSettingMczConfigItem | None = None
    _supported_thermostat: models.ThermostatMczConfigItem | None = None
    _supported_climate_function_mode: models.ClimateFunctionModeMczConfigItem | None = (
        None
    )

    _climate_function_mode_configuration: SensorConfiguration | None = None
    _power_configuration: SensorConfiguration | None = None
    _thermostat_configuration: SensorConfiguration | None = None

    def __init__(
        self,
        coordinator: MczDeviceCoordinator,
        supported_power_sensor: models.PowerSettingMczConfigItem,
        matching_power_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self.coordinator: MczDeviceCoordinator = coordinator

        # general
        self._attr_name = None
        self._attr_unique_id = f"{self.coordinator.stove.UniqueCode}"
        self._attr_icon = "mdi:stove"

        # set power on/off config
        self._supported_power_sensor = supported_power_sensor
        self._set_power_configuration(matching_power_configuration)

        # set thermostat config
        first_supported_thermostat = coordinator.stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
            models.supported_thermostats
        )
        if (
            first_supported_thermostat is not None
            and first_supported_thermostat[0] is not None
            and first_supported_thermostat[1] is not None
        ):
            self._supported_thermostat = first_supported_thermostat[0]
            self._set_thermostat_configuration(first_supported_thermostat[1])

        # set preset/mode config
        first_supported_climate_function_mode = coordinator.stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
            models.supported_climate_function_modes
        )
        if (
            first_supported_climate_function_mode is not None
            and first_supported_climate_function_mode[0] is not None
            and first_supported_climate_function_mode[1] is not None
        ):
            self._supported_climate_function_mode = (
                first_supported_climate_function_mode[0]
            )
            self._set_climate_function_mode_configuration(
                first_supported_climate_function_mode[1]
            )

        # getting the initial update directly without delay
        self._handle_coordinator_update_internal()

    @property
    def device_info(self) -> DeviceInfo:
        return self.coordinator.get_device_info()

    @property
    def hvac_mode(self):
        return self._attr_hvac_mode

    @property
    def hvac_action(self):
        return self._attr_hvac_action

    @property
    def current_temperature(self):
        return self._attr_current_temperature

    @property
    def target_temperature(self):
        return self._attr_target_temperature

    @property
    def preset_mode(self):
        return self._attr_preset_mode

    def _set_power_configuration(
        self, matching_power_configuration: SensorConfiguration
    ):
        self._power_configuration = matching_power_configuration
        if (
            matching_power_configuration.configuration.type
            == SensorTypeEnum.BOOLEAN.value
        ):
            self._attr_supported_features |= (
                ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
            )
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
        elif (
            matching_power_configuration.configuration.type == SensorTypeEnum.INT.value
        ):
            self._attr_supported_features |= (
                ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.TURN_ON
            )
            self._attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
            self._attr_hvac_modes_mappings = {}
            for key in matching_power_configuration.configuration.variants:
                if key in matching_power_configuration.configuration.mappings:
                    if key == "on":
                        self._attr_hvac_modes_mappings[HVACMode.HEAT] = (
                            matching_power_configuration.configuration.mappings[key]
                        )
                    elif key == "off":
                        self._attr_hvac_modes_mappings[HVACMode.OFF] = (
                            matching_power_configuration.configuration.mappings[key]
                        )

    def _set_thermostat_configuration(
        self, matching_thermostat_configuration: SensorConfiguration
    ):
        self._thermostat_configuration = matching_thermostat_configuration
        if (
            matching_thermostat_configuration.configuration.type
            == SensorTypeEnum.DOUBLE.value
        ):
            self._attr_min_temp = float(
                matching_thermostat_configuration.configuration.min
            )
            self._attr_max_temp = float(
                matching_thermostat_configuration.configuration.max
            )
            self._attr_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE

    def _set_climate_function_mode_configuration(
        self, matching_climate_function_mode_configuration: SensorConfiguration
    ):
        self._climate_function_mode_configuration = (
            matching_climate_function_mode_configuration
        )
        if (
            matching_climate_function_mode_configuration.configuration.type
            == SensorTypeEnum.INT.value
        ):
            self._attr_preset_modes = []
            self._attr_preset_modes_mappings = (
                matching_climate_function_mode_configuration.configuration.mappings
            )
            for (
                key
            ) in matching_climate_function_mode_configuration.configuration.variants:
                if key in self._supported_climate_function_mode.api_mappings_key_rename:
                    self._attr_preset_modes.append(
                        self._supported_climate_function_mode.api_mappings_key_rename[
                            key
                        ]
                    )
                    # Add the internal mapped key (from the config) in the public mappings (api mappings), with same value but mapped key
                    if key in self._attr_preset_modes_mappings:
                        self._attr_preset_modes_mappings[
                            self._supported_climate_function_mode.api_mappings_key_rename[
                                key
                            ]
                        ] = self._attr_preset_modes_mappings[key]
                else:
                    self._attr_preset_modes.append(key)
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE

    async def async_set_preset_mode(self, preset_mode):
        """Set the climate preset mode."""
        if self._climate_function_mode_configuration is not None:
            if (
                self._attr_preset_modes_mappings is not None
                and preset_mode in self._attr_preset_modes_mappings
            ):
                converted_preset_mode = self._attr_preset_modes_mappings[preset_mode]
                await self.coordinator.stove.activateProgram(
                    self._climate_function_mode_configuration.configuration.sensor_id,
                    self._climate_function_mode_configuration.configuration_id,
                    converted_preset_mode,
                )
                await self.coordinator.update_data_after_set()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set the climate hvac mode."""
        if self._power_configuration is not None:
            if (
                self.hvac_mode is not None and self.hvac_mode is not hvac_mode
            ):  # avoid sending the same hvac mode to the API because this will result in a toggle of the power setting of the stove
                if (
                    self._power_configuration.configuration.type
                    == SensorTypeEnum.BOOLEAN.value
                ):
                    await self.coordinator.stove.activateProgram(
                        self._power_configuration.configuration.sensor_id,
                        self._power_configuration.configuration_id,
                        True,
                    )
                    await self.coordinator.update_data_after_set()
                elif (
                    self._power_configuration.configuration.type
                    == SensorTypeEnum.INT.value
                ):
                    if (
                        self._attr_hvac_modes_mappings
                        and hvac_mode in self._attr_hvac_modes_mappings
                    ):
                        await self.coordinator.stove.activateProgram(
                            self._power_configuration.configuration.sensor_id,
                            self._power_configuration.configuration_id,
                            int(self._attr_hvac_modes_mappings[hvac_mode]),
                        )
                        await self.coordinator.update_data_after_set()

    async def async_set_temperature(self, **kwargs):
        """Set the climate temperature."""
        if self._thermostat_configuration is not None:
            await self.coordinator.stove.activateProgram(
                self._thermostat_configuration.configuration.sensor_id,
                self._thermostat_configuration.configuration_id,
                float(kwargs["temperature"]),
            )
            await self.coordinator.update_data_after_set()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        # HVAC mode
        if self._supported_power_sensor is not None and hasattr(
            self.coordinator.stove.Status,
            self._supported_power_sensor.sensor_get_name,
        ):
            stato_stufa = getattr(
                self.coordinator.stove.Status,
                self._supported_power_sensor.sensor_get_name,
            )

            fase_op = getattr(
                self.coordinator.stove.Status,
                self._supported_power_sensor.fase_sensor_get_name,
            )

            if stato_stufa is not None:
                match self._supported_power_sensor.stove_model_generation:
                    case models.MczStoveModelGeneration.M1:  # M1 models
                        match stato_stufa:
                            case -1:  # disconnected
                                self._attr_hvac_action = HVACAction.OFF
                                self._attr_hvac_mode = HVACMode.OFF
                            case 0:  # off
                                self._attr_hvac_action = HVACAction.OFF
                                self._attr_hvac_mode = HVACMode.OFF
                            case 1:  # turning off ?????
                                self._attr_hvac_action = HVACAction.IDLE
                                self._attr_hvac_mode = HVACMode.OFF
                            case 3:  # turning-on (loading, start-1, start-2, stabilization, anti-condensation)
                                self._attr_hvac_action = HVACAction.PREHEATING
                                self._attr_hvac_mode = HVACMode.HEAT
                            case 40:  # turning off
                                self._attr_hvac_action = HVACAction.IDLE
                                self._attr_hvac_mode = HVACMode.OFF
                            case 41:  # cooling-down
                                self._attr_hvac_action = HVACAction.IDLE
                                self._attr_hvac_mode = HVACMode.OFF
                            case 46:  # standby
                                self._attr_hvac_action = HVACAction.IDLE
                                self._attr_hvac_mode = HVACMode.HEAT
                            case 51:  # alarm
                                self._attr_hvac_action = HVACAction.OFF
                                self._attr_hvac_mode = HVACMode.OFF
                            case _:  # default (on)
                                self._attr_hvac_action = HVACAction.HEATING
                                self._attr_hvac_mode = HVACMode.HEAT
                    case (
                        models.MczStoveModelGeneration.M2
                        | models.MczStoveModelGeneration.M3
                    ):  # M2 and M3 models
                        match stato_stufa:
                            case -1:  # disconnected
                                self._attr_hvac_action = HVACAction.OFF
                                self._attr_hvac_mode = HVACMode.OFF
                            case 0:  # off
                                self._attr_hvac_action = HVACAction.OFF
                                self._attr_hvac_mode = HVACMode.OFF
                            case 1:  # turning-off (cooling-down)
                                if fase_op is not None and fase_op == "turning-off":
                                    self._attr_hvac_action = HVACAction.IDLE
                                    self._attr_hvac_mode = HVACMode.OFF
                                else:
                                    self._attr_hvac_action = HVACAction.OFF
                                    self._attr_hvac_mode = HVACMode.OFF
                            case 2:  # standby
                                # cooling down => turning-off (turning-off 2)
                                if fase_op is not None and fase_op == "turning-off":
                                    self._attr_hvac_action = HVACAction.IDLE
                                    self._attr_hvac_mode = HVACMode.HEAT
                                else:  # really off => off (null)
                                    self._attr_hvac_action = HVACAction.IDLE
                                    self._attr_hvac_mode = HVACMode.HEAT
                            case 3:  # on
                                # starting up (preheat) => turning-on (loading, start-1, start-2, stabilization, anti-condensation)
                                if fase_op is not None and fase_op == "turning-on":
                                    self._attr_hvac_action = HVACAction.PREHEATING
                                    self._attr_hvac_mode = HVACMode.HEAT
                                else:  # on (working) => on (null)
                                    self._attr_hvac_action = HVACAction.HEATING
                                    self._attr_hvac_mode = HVACMode.HEAT
                            case _:  # default (on)
                                self._attr_hvac_action = HVACAction.HEATING
                                self._attr_hvac_mode = HVACMode.HEAT
            else:
                self._attr_hvac_action = HVACAction.OFF
                self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = None
            self._attr_hvac_action = None

        # current temp
        if hasattr(self.coordinator.stove.State, "temp_amb_install"):
            self._attr_current_temperature = (
                self.coordinator.stove.State.temp_amb_install
            )

        # target temp
        if self._supported_thermostat is not None and hasattr(
            self.coordinator.stove.State,
            self._supported_thermostat.sensor_get_name,
        ):
            self._attr_target_temperature = getattr(
                self.coordinator.stove.State,
                self._supported_thermostat.sensor_get_name,
            )
        else:
            self._attr_target_temperature = None

        # preset modes
        if self._supported_climate_function_mode is not None and hasattr(
            self.coordinator.stove.State,
            self._supported_climate_function_mode.sensor_get_name,
        ):
            preset_mode_value_raw = getattr(
                self.coordinator.stove.State,
                self._supported_climate_function_mode.sensor_get_name,
            )
            if preset_mode_value_raw is not None:
                preset_mode_value = str(preset_mode_value_raw)
                if (
                    self._supported_climate_function_mode.api_mappings_key_rename
                    is not None
                    and preset_mode_value
                    in self._supported_climate_function_mode.api_mappings_key_rename
                ):
                    self._attr_preset_mode = (
                        self._supported_climate_function_mode.api_mappings_key_rename[
                            preset_mode_value
                        ]
                    )
                else:
                    self._attr_preset_mode = preset_mode_value
        else:
            self._attr_preset_mode = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up climate entities from a config entry."""
    coordinators = entry.runtime_data
    entities = []
    for coordinator in coordinators.values():
        entities.extend(_getStoveClimateEntities(coordinator))
    async_add_entities(entities)


def _getStoveClimateEntities(
    coordinator: MczDeviceCoordinator,
) -> list[CoordinatorEntity]:
    """Get the climate entities to create for this stove."""
    entities = []
    first_supported_power_sensor = coordinator.stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
        models.supported_power_settings
    )
    if (
        first_supported_power_sensor is not None
        and first_supported_power_sensor[0] is not None
        and first_supported_power_sensor[1] is not None
    ):
        entities.append(
            MczClimateEntity(
                coordinator,
                first_supported_power_sensor[0],
                first_supported_power_sensor[1],
            )
        )
    return entities
