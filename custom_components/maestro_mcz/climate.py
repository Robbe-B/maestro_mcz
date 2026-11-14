"""Platform for Climate integration."""

from __future__ import annotations

import logging
import re

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import MczAccountCoordinator
from .maestro import MaestroStove
from .maestro.controller.responses.model import SensorConfiguration
from .maestro.models import models
from .maestro.types.enums import SensorTypeEnum

_LOGGER = logging.getLogger(__name__)


class MczClimateEntity(CoordinatorEntity, ClimateEntity):
    """Representation of a MCZ climate entity."""

    _attr_has_entity_name = True
    _attr_hvac_mode: HVACMode | None = None
    _attr_hvac_action: HVACAction | None = None
    _attr_native_current_temperature: float | None = None
    _attr_native_target_temperature: float | None = None
    _attr_preset_mode = None
    _attr_preset_modes: list[str] | None = None
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
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_power_sensor: models.PowerSettingMczConfigItem,
        matching_power_configuration: SensorConfiguration,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        self._legacy_preset_commands: dict[
            str, tuple[SensorConfiguration, bool | int]
        ] = {}

        # general
        self._attr_name = None
        self._attr_unique_id = f"{stove_unique_code}"
        self._attr_icon = "mdi:stove"
        self._attr_device_info = self._stove.get_device_info()

        # set power on/off config
        self._supported_power_sensor = supported_power_sensor
        self._set_power_configuration(matching_power_configuration)

        # set thermostat config
        first_supported_thermostat = self._stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
            models.supported_thermostats
        )
        if (
            first_supported_thermostat is not None
            and first_supported_thermostat[0] is not None
            and first_supported_thermostat[1] is not None
        ):
            self._supported_thermostat = first_supported_thermostat[0]
            self.entity_registry_enabled_default = (
                self._supported_thermostat.enabled_by_default
            )
            self.entity_category = self._supported_thermostat.category
            self._set_thermostat_configuration(first_supported_thermostat[1])

        # Standard metadata defines the advertised presets and their readback names.
        # Choosing a compatibility command must not hide those presets.
        first_supported_climate_function_mode = self._stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
            models.supported_climate_function_modes
        )
        if self._uses_legacy_mode_commands():
            legacy_mode = self._set_legacy_preset_commands()
            # Only fall back to a two-preset list when no standard list exists.
            if first_supported_climate_function_mode is None:
                first_supported_climate_function_mode = legacy_mode
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
    def available(self) -> bool:
        """Check availability based on coordinator and stove connection."""
        # Check 1: coordinator is available
        if not super().available:
            return False
        # Check 2: is the stove connected
        return self._stove.is_connected

    @property
    def hvac_mode(self):
        return self._attr_hvac_mode

    @property
    def hvac_action(self):
        return self._attr_hvac_action

    @property
    def preset_mode(self):
        return self._attr_preset_mode

    def _uses_legacy_mode_commands(self) -> bool:
        """Check command compatibility without inferring the stove's mode count."""
        if self._stove.model_generation != models.MczStoveModelGeneration.M1:
            return False

        bootloader = getattr(self._stove.Status, "sm_vs_bootloader", None)
        version = (
            re.fullmatch(r"([0-9]+)\.([0-9]+)(?:\.[0-9]+)*", bootloader)
            if isinstance(bootloader, str)
            else None
        )
        if version is None:
            # Unknown versions must not opt into an older command format.
            _LOGGER.warning(
                "Cannot determine bootloader version for '%s'; retaining standard mode commands",
                self._stove.Name,
            )
            return False

        # Compare numbers, not text: 1.10 is newer than 1.3. This threshold only
        # selects command format; it does not prove that a stove has two modes.
        return (int(version[1]), int(version[2])) < (1, 3)

    def _get_legacy_mode_configuration(
        self,
        mode: models.ClimateFunctionModeMczConfigItem,
        expected_type: SensorTypeEnum,
    ) -> SensorConfiguration | None:
        """Resolve a usable legacy control, or keep the standard command."""
        match = self._stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
            [mode]
        )
        configuration = match[1] if match is not None else None
        sensor = configuration.configuration if configuration is not None else None

        # Both legacy controls need the same checks. A matching name is not
        # enough: disabled controls, missing IDs or a wrong value type are unsafe.
        if (
            configuration is None
            or sensor is None
            or not sensor.enabled
            or sensor.type != expected_type.value
            or not sensor.sensor_id
            or not configuration.configuration_id
        ):
            _LOGGER.warning(
                "Legacy %s command is missing or invalid for '%s'; retaining standard mode commands",
                mode.sensor_set_config_name,
                self._stove.Name,
            )
            return None
        return configuration

    def _set_legacy_preset_commands(
        self,
    ) -> tuple[models.ClimateFunctionModeMczConfigItem, SensorConfiguration] | None:
        """Build command overrides and return the optional two-mode fallback."""
        mode = models.legacy_climate_function_modes[0]
        mode_configuration = self._get_legacy_mode_configuration(
            mode, SensorTypeEnum.BOOLEAN
        )
        if mode_configuration is not None:
            # Manual/Auto need actual booleans, not the standard integer values.
            self._legacy_preset_commands["manual"] = (mode_configuration, False)
            self._legacy_preset_commands["auto"] = (mode_configuration, True)

        recipe = models.legacy_climate_recipe_modes[0]
        recipe_configuration = self._get_legacy_mode_configuration(
            recipe, SensorTypeEnum.INT
        )
        if recipe_configuration is not None:
            recipe_sensor = recipe_configuration.configuration
            assert recipe_sensor is not None  # Validated by the shared lookup.
            preset_names = recipe.api_mappings_key_rename or {}
            for name in ("overnight", "comfort", "power"):
                mappings = recipe_sensor.mappings
                # Each recipe preset is independent. A bad or absent mapping
                # must not disable the other presets or replace their commands.
                if (
                    recipe_sensor.variants is None
                    or name not in recipe_sensor.variants
                    or not isinstance(mappings, dict)
                    or type(mappings.get(name)) is not int
                ):
                    _LOGGER.warning(
                        "Legacy preset '%s' is missing or invalid for '%s'; retaining standard preset command",
                        name,
                        self._stove.Name,
                    )
                    continue
                # Keep the model's values and IDs; only rename power to Turbo.
                preset = preset_names.get(name, name)
                self._legacy_preset_commands[preset] = (
                    recipe_configuration,
                    mappings[name],
                )

        # This fallback exposes Manual/Auto only if no standard mode list exists.
        if mode_configuration is not None:
            return mode, mode_configuration
        return None

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
            self._attr_native_temperature_unit = UnitOfTemperature.CELSIUS
            self._attr_supported_features |= ClimateEntityFeature.TARGET_TEMPERATURE

    def _set_climate_function_mode_configuration(
        self, matching_climate_function_mode_configuration: SensorConfiguration
    ):
        self._climate_function_mode_configuration = (
            matching_climate_function_mode_configuration
        )
        if (
            matching_climate_function_mode_configuration.configuration.type
            == SensorTypeEnum.BOOLEAN.value
        ):
            self._attr_preset_modes = ["manual", "auto"]
            self._attr_preset_modes_mappings = {"manual": False, "auto": True}
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
        elif (
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
        if self._climate_function_mode_configuration is None:
            return
        if (
            self._attr_preset_modes_mappings is None
            or preset_mode not in self._attr_preset_modes_mappings
        ):
            return

        # Validate against the normal preset mappings first. Compatibility
        # overrides change how a preset is sent, not which presets are offered.
        mode_configuration, value = self._legacy_preset_commands.get(
            preset_mode,
            (
                self._climate_function_mode_configuration,
                self._attr_preset_modes_mappings[preset_mode],
            ),
        )
        await self._stove.activateProgram(
            mode_configuration.configuration.sensor_id,
            mode_configuration.configuration_id,
            value,
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
                    await self._stove.activateProgram(
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
                        await self._stove.activateProgram(
                            self._power_configuration.configuration.sensor_id,
                            self._power_configuration.configuration_id,
                            int(self._attr_hvac_modes_mappings[hvac_mode]),
                        )
                        await self.coordinator.update_data_after_set()

    async def async_set_temperature(self, **kwargs):
        """Set the climate temperature."""
        if self._thermostat_configuration is not None:
            await self._stove.activateProgram(
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
            self._stove.Status,
            self._supported_power_sensor.sensor_get_name,
        ):
            stato_stufa = getattr(
                self._stove.Status,
                self._supported_power_sensor.sensor_get_name,
            )

            fase_op = getattr(
                self._stove.Status,
                self._supported_power_sensor.fase_sensor_get_name,
            )

            if stato_stufa is not None:
                match self._stove.model_generation:
                    case models.MczStoveModelGeneration.M1:
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
                    case models.MczStoveModelGeneration.M2_PLUS:
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
                    case _:
                        self._attr_hvac_action = None
                        self._attr_hvac_mode = None
            else:
                self._attr_hvac_action = HVACAction.OFF
                self._attr_hvac_mode = HVACMode.OFF
        else:
            self._attr_hvac_mode = None
            self._attr_hvac_action = None

        # current temp
        if hasattr(self._stove.State, "temp_amb_install"):
            self._attr_native_current_temperature = self._stove.State.temp_amb_install

        # target temp
        if self._supported_thermostat is not None and hasattr(
            self._stove.State,
            self._supported_thermostat.sensor_get_name,
        ):
            self._attr_native_target_temperature = getattr(
                self._stove.State,
                self._supported_thermostat.sensor_get_name,
            )
        else:
            self._attr_native_target_temperature = None

        # preset modes
        if self._supported_climate_function_mode is not None and hasattr(
            self._stove.State,
            self._supported_climate_function_mode.sensor_get_name,
        ):
            preset_mode_value_raw = getattr(
                self._stove.State,
                self._supported_climate_function_mode.sensor_get_name,
            )
            if preset_mode_value_raw is not None:
                preset_mode_value = str(preset_mode_value_raw)
                # Rename dynamic to auto only for display. Keep the shared raw
                # state unchanged because fan controls select commands by that mode.
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
    coordinator: MczAccountCoordinator = entry.runtime_data
    entities = []
    for stove in coordinator.stoves.values():
        entities.extend(_getStoveClimateEntities(coordinator, stove))
    async_add_entities(entities)


def _getStoveClimateEntities(
    coordinator: MczAccountCoordinator, stove: MaestroStove
) -> list[CoordinatorEntity]:
    """Get the climate entities to create for this stove."""
    entities = []
    first_supported_power_sensor = stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
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
                stove.UniqueCode,
                first_supported_power_sensor[0],
                first_supported_power_sensor[1],
            )
        )
    return entities
