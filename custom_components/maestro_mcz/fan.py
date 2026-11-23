"""Platform for Fan integration."""

import contextlib
import logging
import math
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .coordinator import MczAccountCoordinator, MczConfigEntry
from .maestro import MaestroStove, get_control_names
from .maestro.controller.responses.model import (
    SensorConfiguration,
    SensorConfigurationMultipleModes,
)
from .maestro.model_value_reader import get_response_value, read_response_value
from .maestro.models import model_definitions, models_types
from .maestro.types.enums import SensorTypeEnum

_LOGGER = logging.getLogger(__name__)


class MczFanEntity(CoordinatorEntity[MczAccountCoordinator], FanEntity):
    """Adapt advertised, mode-dependent fan controls to HA presets/percentages.

    Derive features from cached configuration and dispatch through the stove;
    do not own account polling or rewrite raw mode/response values.
    """

    _attr_has_entity_name = True
    _attr_available: bool = True

    _attr_is_on: bool | None = None
    _attr_percentage: int | None = None
    _attr_preset_mode: str | None = None
    _attr_preset_modes: list[str] | None = None
    _attr_speed_count: int = 0
    _attr_translation_key: str = "main_fan"

    _supported_fan: models_types.FanMczConfigItem
    _fan_configuration: SensorConfigurationMultipleModes | None = None
    _current_fan_configuration: SensorConfiguration | None = None

    def __init__(
        self,
        coordinator: MczAccountCoordinator,
        stove_unique_code: str,
        supported_fan: models_types.FanMczConfigItem,
        matching_fan_configuration: SensorConfigurationMultipleModes | None,
        fixed_fan_configuration: SensorConfiguration | None = None,
    ) -> None:
        """Initialize the fan entity."""
        super().__init__(coordinator)
        self.coordinator: MczAccountCoordinator = coordinator
        self._stove: MaestroStove = coordinator.stoves[stove_unique_code]
        if supported_fan.translation_key is None:
            self._attr_name = supported_fan.user_friendly_name
        else:
            self._attr_translation_key = supported_fan.translation_key
        self._attr_translation_placeholders = (
            supported_fan.translation_placeholders or {}
        )
        self._attr_unique_id = f"{stove_unique_code}-{supported_fan.sensor_get_name}"
        self._attr_device_info = self._stove.get_device_info()
        self._prop = supported_fan.sensor_get_name
        self.entity_registry_enabled_default = supported_fan.enabled_by_default
        self.entity_category = supported_fan.category
        self._supported_fan = supported_fan
        self._fan_configuration = matching_fan_configuration
        self._fixed_fan_configuration = fixed_fan_configuration

        self._update_features_based_on_current_stove_mode()  # each mode of the stove has other fan settings, so we need to update this accordingly

        self._handle_coordinator_update_internal()  # getting the initial update directly without delay

    @property
    def available(self) -> bool:
        return self._attr_available

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
        if (
            self._current_fan_configuration is not None
            and self._current_fan_configuration.configuration is not None
            and self._current_fan_configuration.configuration.mappings is not None
            and len(self._current_fan_configuration.configuration.mappings) > 0
            and preset_mode in self._current_fan_configuration.configuration.mappings
        ):
            await self._stove.activateProgram(
                self._current_fan_configuration.configuration.sensor_id,
                self._current_fan_configuration.configuration_id,
                preset_mode,
            )
            await self.coordinator.update_data_after_set()

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if self._current_fan_configuration is not None:
            if preset_mode is not None:
                await self.async_set_preset_mode(preset_mode)
            elif percentage is not None:
                await self.async_set_percentage(percentage)
            else:
                await self.async_set_percentage(100)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        if self._current_fan_configuration is not None:
            await self._stove.activateProgram(
                self._current_fan_configuration.configuration.sensor_id,
                self._current_fan_configuration.configuration_id,
                0,
            )  # '0' means off
            await self.coordinator.update_data_after_set()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if self._attr_speed_count > 1:
            value_in_range = math.ceil(
                percentage_to_ranged_value((1, self._attr_speed_count), percentage)
            )
            if self._current_fan_configuration is not None:
                await self._stove.activateProgram(
                    self._current_fan_configuration.configuration.sensor_id,
                    self._current_fan_configuration.configuration_id,
                    value_in_range,
                )
                await self.coordinator.update_data_after_set()

    def _get_configuration_for_current_stove_mode(self) -> SensorConfiguration | None:
        """Get the correct sensor configuration for the current mode that the stove is in."""
        if (
            self._stove.State is not None
            and self._stove.State.mode is not None
            and self._fan_configuration is not None
            and self._stove.State.mode in self._fan_configuration.mode_configurations
        ):
            return self._fan_configuration.mode_configurations[self._stove.State.mode]
        return None

    def _update_features_based_on_current_stove_mode(self) -> None:
        """Refresh all fan features that are applicable for the current mode that the stove is in."""
        if self._fixed_fan_configuration is not None:
            self._current_fan_configuration = self._fixed_fan_configuration
        else:
            current_mode = read_response_value(
                self._supported_fan.mode_response_source,
                self._stove.State,
                self._stove.Status,
                self._supported_fan.mode_sensor_get_name,
            )
            self._current_fan_configuration = (
                self._fan_configuration.mode_configurations.get(current_mode)
                if self._fan_configuration is not None and isinstance(current_mode, str)
                else None
            )

        self._attr_supported_features = FanEntityFeature(0)  # resetting the features
        self._attr_preset_modes = None
        self._attr_speed_count = 0
        self._set_available_internal(False)

        if (
            self._current_fan_configuration is not None
            and self._current_fan_configuration.configuration is not None
            and self._current_fan_configuration.configuration.enabled
        ):
            self._set_available_internal(True)
            if (
                self._current_fan_configuration.configuration.type
                == SensorTypeEnum.INT.value
            ):
                # on/off
                self._attr_supported_features |= (
                    FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
                )

                # speed
                assert self._current_fan_configuration.configuration.max is not None
                self._attr_speed_count = int(
                    self._current_fan_configuration.configuration.max
                )
                self._attr_supported_features |= FanEntityFeature.SET_SPEED

                # preset
                if (
                    self._current_fan_configuration.configuration.variants is not None
                    and len(self._current_fan_configuration.configuration.variants) > 0
                ):
                    self._attr_preset_modes = []
                    assert (
                        self._current_fan_configuration.configuration.mappings
                        is not None
                    )
                    for key in self._current_fan_configuration.configuration.variants:
                        if (
                            key
                            in self._current_fan_configuration.configuration.mappings
                        ):
                            self._attr_preset_modes.append(key)
                    self._attr_supported_features |= FanEntityFeature.PRESET_MODE

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates."""
        self._update_features_based_on_current_stove_mode()
        self._handle_coordinator_update_internal()
        self.async_write_ha_state()

    def _handle_coordinator_update_internal(self) -> None:
        """Handle coordinator updates for this fan."""

        # determine if the fan is enabled
        if (
            self._current_fan_configuration is not None
            and self._current_fan_configuration.configuration is not None
            and self._current_fan_configuration.configuration.enabled
        ):
            self._set_available_internal(True)
        else:
            self._set_available_internal(False)
            return  # we can return here since the fan is disabled in the config and we don't need to update values

        # determine silent mode is enabled
        if (
            self._supported_fan is not None
            and self._supported_fan.silent_enabled_get_name is not None
        ):
            silent_enabled = get_response_value(
                self._supported_fan,
                self._stove.State,
                self._stove.Status,
                self._stove.model_generation,
                self._supported_fan.silent_enabled_get_name,
            )

            if silent_enabled is not None and silent_enabled:
                self._set_available_internal(False)
                return  # we can return here since the rest doesn't matter anymore when the fan is not available

        # determine the fan value
        value = get_response_value(
            self._supported_fan,
            self._stove.State,
            self._stove.Status,
            self._stove.model_generation,
        )
        fan_value: str | int | None = str(value) if value is not None else None

        with contextlib.suppress(Exception):
            assert fan_value is not None
            fan_value = int(fan_value)  # fan_value can be a string

        # on/off
        if (
            self._current_fan_configuration is not None
            and fan_value is not None
            and (type(fan_value) is str or (type(fan_value) is int and fan_value != 0))
        ):
            self._attr_is_on = True
        else:
            self._attr_is_on = False

        # presets
        if (
            self._current_fan_configuration is not None
            and self._current_fan_configuration.configuration.mappings is not None
            and len(self._current_fan_configuration.configuration.mappings) > 0
            and fan_value is not None
            and (
                (
                    type(fan_value) is str
                    and fan_value
                    in self._current_fan_configuration.configuration.mappings
                )
                or (
                    type(fan_value) is int
                    and fan_value
                    in self._current_fan_configuration.configuration.mappings.values()
                    and fan_value != 0
                )
            )
        ):
            if type(fan_value) is str:
                self._attr_preset_mode = fan_value
            elif type(fan_value) is int:
                self._attr_preset_mode = next(
                    (
                        key
                        for key, mapped in self._current_fan_configuration.configuration.mappings.items()
                        if mapped == fan_value
                    ),
                    None,
                )
        else:
            self._attr_preset_mode = None

        # speed
        if (
            self._current_fan_configuration is not None
            and self._current_fan_configuration.configuration.min is not None
            and self._current_fan_configuration.configuration.max is not None
            and fan_value is not None
            and type(fan_value) is int
            and self._attr_speed_count >= 1
            and int(self._current_fan_configuration.configuration.min)
            <= fan_value
            <= int(self._current_fan_configuration.configuration.max)
            and fan_value != 0
        ):
            self._attr_percentage = ranged_value_to_percentage(
                (1, self._attr_speed_count), fan_value
            )
        else:
            self._attr_percentage = None

    def _set_available_internal(self, available: bool) -> None:
        """Set the availability of the fan."""
        self._attr_available = (
            super().available and self._stove.is_connected and available
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MczConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up fan entities from a config entry."""
    coordinator: MczAccountCoordinator = entry.runtime_data.coordinator
    entities = []
    for stove in coordinator.stoves.values():
        entities.extend(_getStoveFanEntities(coordinator, stove))
    async_add_entities(entities)


def get_supported_fan_configurations(
    stove: MaestroStove, fans: list[models_types.FanMczConfigItem]
) -> (
    list[tuple[models_types.FanMczConfigItem, SensorConfigurationMultipleModes]] | None
):
    """Select each fan's generation-specific mode groups before model matching."""
    matches = []
    for fan in fans:
        for sensor_name in get_control_names(fan):
            mode_groups = fan.mode_to_configuration_name_mapping
            if sensor_name == fan.sensor_set_name_m2:
                generation_groups = fan.mode_to_configuration_name_mapping_m2
            elif sensor_name == fan.sensor_set_name_m1:
                generation_groups = fan.mode_to_configuration_name_mapping_m1
            else:
                generation_groups = None
            if generation_groups is not None:
                mode_groups = generation_groups
            if mode_groups is None:
                continue
            mode_configurations: dict[str, SensorConfiguration] = {}
            for mode, group in mode_groups.items():
                configuration = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
                    group, sensor_name
                )
                if configuration is not None:
                    mode_configurations[mode] = configuration
            if mode_configurations:
                matches.append(
                    (fan, SensorConfigurationMultipleModes(mode_configurations))
                )
    return matches or None


def _getStoveFanEntities(
    coordinator: MczAccountCoordinator, stove: MaestroStove
) -> list[CoordinatorEntity[MczAccountCoordinator]]:
    """Get the fan entities to create for this stove."""
    entities: list[CoordinatorEntity[MczAccountCoordinator]] = []
    fixed_fans = {
        fan.sensor_get_name: (fan, configuration)
        for fan, configuration in (
            stove.get_supported_sensor_configurations(model_definitions.supported_fans)
            or []
        )
        if configuration.configuration is not None
        and configuration.configuration.enabled
    }
    supported_fans = get_supported_fan_configurations(
        stove,
        [
            fan
            for fan in model_definitions.supported_fans
            if (
                fan.mode_to_configuration_name_mapping is not None
                or fan.mode_to_configuration_name_mapping_m1 is not None
                or fan.mode_to_configuration_name_mapping_m2 is not None
            )
            and fan.sensor_get_name not in fixed_fans
        ],
    )

    if supported_fans is not None:
        entities.extend(
            [
                MczFanEntity(
                    coordinator, stove.UniqueCode, supported_fan[0], supported_fan[1]
                )
                for supported_fan in supported_fans
                if supported_fan[0] is not None and supported_fan[1] is not None
            ]
        )
    entities.extend(
        MczFanEntity(coordinator, stove.UniqueCode, fan, None, configuration)
        for fan, configuration in fixed_fans.values()
    )
    return entities
