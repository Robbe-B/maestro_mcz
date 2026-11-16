"""Configuration dataclasses and enums for MCZ features."""

from dataclasses import dataclass
from enum import Enum

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.number import NumberDeviceClass, NumberMode
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import EntityCategory


class MczStoveModelGeneration(Enum):
    """Stove generations distinguished by the integration."""

    M1 = 1
    M2_PLUS = 2


class MczResponseSource(Enum):
    """Identify the response supplying a reading."""

    STATUS = 1
    STATE = 2


@dataclass
class MczConfigItem:
    """Representation of a generic MCZ config item."""

    sensor_get_name: str | None = (
        None  # name used for getting data out of the state and status reponses
    )
    sensor_set_name: str | None = (
        None  # name used for setting data trough the API (resolved in configs first)
    )
    sensor_set_config_name: str | None = None
    sensor_set_name_m1: str | None = None
    sensor_set_name_m2: str | None = None

    stove_model_generation: MczStoveModelGeneration | None = (
        None  # for sensors this will be null
    )

    # optional
    mode_to_configuration_name_mapping: dict[str, str] | None = (
        None  # key => Mode | value => Configuration Name
    )
    user_friendly_name: str | None = None
    translation_key: str | None = None
    enabled_by_default: bool = True
    category: EntityCategory | None = None
    value_response_source: (
        MczResponseSource | dict[MczStoveModelGeneration, MczResponseSource]
    ) = MczResponseSource.STATUS

    def __init__(
        self,
        user_friendly_name: str,
        stove_model_generation: MczStoveModelGeneration | None,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a generic MCZ config item."""
        self.user_friendly_name = user_friendly_name
        self.stove_model_generation = stove_model_generation
        self.sensor_set_name_m1 = sensor_set_name_m1
        self.sensor_set_name_m2 = sensor_set_name_m2


@dataclass
class PowerSettingMczConfigItem(MczConfigItem):
    """Representation of a 'Power Setting' MCZ config item."""

    value_response_source: MczResponseSource = MczResponseSource.STATUS
    bootloader_response_source: MczResponseSource = MczResponseSource.STATUS
    fase_sensor_get_name: str | None = (
        None  # name used for getting data out of the state and status reponses
    )

    sub_fase_sensor_get_name: str | None = (
        None  # name used for getting data out of the state and status reponses
    )

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str | None,
        sensor_set_config_name: str,
        fase_sensor_get_name: str,
        sub_fase_sensor_get_name: str,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration | None = None,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a 'Power Setting' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.sensor_get_name = sensor_get_name
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.fase_sensor_get_name = fase_sensor_get_name
        self.sub_fase_sensor_get_name = sub_fase_sensor_get_name
        self.enabled_by_default = enabled_by_default


@dataclass
class ClimateFunctionModeMczConfigItem(MczConfigItem):
    """Representation of a 'Climate Function Mode' MCZ config item."""

    api_mappings_key_rename: dict[str, str] | None = None
    api_mappings_key_rename_m1: dict[str, str] | None = None
    api_mappings_key_rename_m2: dict[str, str] | None = None
    value_response_source: MczResponseSource = MczResponseSource.STATUS

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str | None,
        sensor_set_config_name: str,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration | None = None,
        api_mappings_key_rename: dict[str, str] | None = None,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
        api_mappings_key_rename_m1: dict[str, str] | None = None,
        api_mappings_key_rename_m2: dict[str, str] | None = None,
    ) -> None:
        """Create a 'Climate Function Mode' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.sensor_get_name = sensor_get_name
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default
        self.api_mappings_key_rename = api_mappings_key_rename
        self.api_mappings_key_rename_m1 = api_mappings_key_rename_m1
        self.api_mappings_key_rename_m2 = api_mappings_key_rename_m2


@dataclass
class ThermostatMczConfigItem(MczConfigItem):
    """Representation of a 'Thermostat' MCZ config item."""

    current_temperature_response_source: MczResponseSource = MczResponseSource.STATUS

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str | None,
        sensor_set_config_name: str,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration | None = None,
        value_response_source: MczResponseSource = MczResponseSource.STATUS,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a 'Thermostat' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.sensor_get_name = sensor_get_name
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default
        self.value_response_source = value_response_source


@dataclass
class FanMczConfigItem(MczConfigItem):
    """Representation of a 'Fan' MCZ config item."""

    silent_enabled_get_name: str | None = None
    value_response_source: MczResponseSource = MczResponseSource.STATUS
    mode_response_source: MczResponseSource = MczResponseSource.STATUS
    mode_sensor_get_name: str = ""
    mode_to_configuration_name_mapping_m1: dict[str, str] | None = None
    mode_to_configuration_name_mapping_m2: dict[str, str] | None = None

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str | None,
        mode_to_configuration_name_mapping: dict[str, str] | None,
        silent_enabled_get_name: str | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration | None,
        mode_sensor_get_name: str,
        sensor_set_config_name: str | None = None,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
        mode_to_configuration_name_mapping_m1: dict[str, str] | None = None,
        mode_to_configuration_name_mapping_m2: dict[str, str] | None = None,
    ) -> None:
        """Create a 'Fan' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.sensor_get_name = sensor_get_name
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.mode_to_configuration_name_mapping = mode_to_configuration_name_mapping  # means we want to find the sensor name in the different mode configs
        self.silent_enabled_get_name = silent_enabled_get_name
        self.enabled_by_default = enabled_by_default
        self.mode_sensor_get_name = mode_sensor_get_name
        self.mode_to_configuration_name_mapping_m1 = (
            mode_to_configuration_name_mapping_m1
        )
        self.mode_to_configuration_name_mapping_m2 = (
            mode_to_configuration_name_mapping_m2
        )


@dataclass
class ButtonMczConfigItem(MczConfigItem):
    """Representation of a 'Button' MCZ config item."""

    def __init__(
        self,
        user_friendly_name: str,
        sensor_set_name: str | None,
        sensor_set_config_name: str,
        translation_key: str,
        category: EntityCategory | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration | None = None,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a 'Button' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.translation_key = translation_key
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.category = category
        self.enabled_by_default = enabled_by_default


@dataclass
class SwitchMczConfigItem(MczConfigItem):
    """Representation of a 'Switch' MCZ config item."""

    value_response_source: MczResponseSource = MczResponseSource.STATUS

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str | None,
        sensor_set_config_name: str,
        translation_key: str,
        category: EntityCategory | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration | None = None,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a 'Switch' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.sensor_get_name = sensor_get_name
        self.translation_key = translation_key
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.category = category
        self.enabled_by_default = enabled_by_default


@dataclass
class NumberMczConfigItem(MczConfigItem):
    """Representation of a 'Number' MCZ config item."""

    device_class: NumberDeviceClass | None = None
    unit: str | None = None
    mode: NumberMode = NumberMode.AUTO

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str | None,
        sensor_set_config_name: str,
        mode: NumberMode,
        translation_key: str,
        unit: str | None,
        category: EntityCategory | None,
        device_class: NumberDeviceClass | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration | None = None,
        value_response_source: MczResponseSource = MczResponseSource.STATUS,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a 'Number' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.sensor_get_name = sensor_get_name
        self.mode = mode
        self.translation_key = translation_key
        self.unit = unit
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.category = category
        self.device_class = device_class
        self.enabled_by_default = enabled_by_default
        self.value_response_source = value_response_source


@dataclass
class SelectMczConfigItem(MczConfigItem):
    """Representation of a 'Select' MCZ config item."""

    value_mappings: dict[str, str] | None = None
    map_back_before_sending_to_api: bool | None = (
        None  # Still needs implementation when needed
    )

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str | None,
        sensor_set_config_name: str,
        translation_key: str,
        category: EntityCategory | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration | None = None,
        value_mappings: dict[str, str] | None = None,
        value_response_source: MczResponseSource = MczResponseSource.STATUS,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a 'Select' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.sensor_get_name = sensor_get_name
        self.translation_key = translation_key
        self.category = category
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default
        self.value_mappings = value_mappings
        self.value_response_source = value_response_source


@dataclass
class DateTimeMczConfigItem(MczConfigItem):
    """Representation of a 'DateTime' MCZ config item."""

    value_response_source: MczResponseSource = MczResponseSource.STATUS
    sensor_set_name_weekday: str | None = None
    sensor_get_name_weekday: str | None = None

    sensor_set_name_year: str | None = None
    sensor_get_name_year: str | None = None

    sensor_set_name_month: str | None = None
    sensor_get_name_month: str | None = None

    sensor_set_name_day: str | None = None
    sensor_get_name_day: str | None = None

    sensor_set_name_hour: str | None = None
    sensor_get_name_hour: str | None = None

    sensor_set_name_minute: str | None = None
    sensor_get_name_minute: str | None = None

    sensor_set_name_second: str | None = None
    sensor_get_name_second: str | None = None

    sensor_set_name_am_pm: str | None = None
    sensor_get_name_am_pm: str | None = None

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str,
        sensor_get_name_weekday: str | None,
        sensor_set_name_weekday: str | None,
        sensor_get_name_year: str | None,
        sensor_set_name_year: str | None,
        sensor_get_name_month: str | None,
        sensor_set_name_month: str | None,
        sensor_get_name_day: str | None,
        sensor_set_name_day: str | None,
        sensor_get_name_hour: str | None,
        sensor_set_name_hour: str | None,
        sensor_get_name_minute: str | None,
        sensor_set_name_minute: str | None,
        sensor_get_name_second: str | None,
        sensor_set_name_second: str | None,
        sensor_get_name_am_pm: str | None,
        sensor_set_name_am_pm: str | None,
        sensor_set_config_name: str,
        translation_key: str,
        category: EntityCategory | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'DateTime' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.sensor_get_name = sensor_get_name
        self.sensor_get_name_weekday = sensor_get_name_weekday
        self.sensor_get_name_year = sensor_get_name_year
        self.sensor_get_name_month = sensor_get_name_month
        self.sensor_get_name_day = sensor_get_name_day
        self.sensor_get_name_hour = sensor_get_name_hour
        self.sensor_get_name_minute = sensor_get_name_minute
        self.sensor_get_name_second = sensor_get_name_second
        self.sensor_get_name_am_pm = sensor_get_name_am_pm
        self.translation_key = translation_key
        self.category = category
        self.sensor_set_name = sensor_set_name
        self.sensor_set_name_weekday = sensor_set_name_weekday
        self.sensor_set_name_year = sensor_set_name_year
        self.sensor_set_name_month = sensor_set_name_month
        self.sensor_set_name_day = sensor_set_name_day
        self.sensor_set_name_hour = sensor_set_name_hour
        self.sensor_set_name_minute = sensor_set_name_minute
        self.sensor_set_name_second = sensor_set_name_second
        self.sensor_set_config_name = sensor_set_config_name
        self.sensor_set_name_am_pm = sensor_set_name_am_pm
        self.enabled_by_default = enabled_by_default


@dataclass
class TimeSyncButtonMczConfigItem(DateTimeMczConfigItem):
    """Representation of a 'Time sync Button' MCZ config item."""

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str,
        sensor_get_name_weekday: str | None,
        sensor_set_name_weekday: str | None,
        sensor_get_name_year: str | None,
        sensor_set_name_year: str | None,
        sensor_get_name_month: str | None,
        sensor_set_name_month: str | None,
        sensor_get_name_day: str | None,
        sensor_set_name_day: str | None,
        sensor_get_name_hour: str | None,
        sensor_set_name_hour: str | None,
        sensor_get_name_minute: str | None,
        sensor_set_name_minute: str | None,
        sensor_get_name_second: str | None,
        sensor_set_name_second: str | None,
        sensor_get_name_am_pm: str | None,
        sensor_set_name_am_pm: str | None,
        sensor_set_config_name: str,
        translation_key: str,
        category: EntityCategory | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'Time Sync Button' MCZ config item."""
        super().__init__(
            user_friendly_name,
            sensor_get_name,
            sensor_set_name,
            sensor_get_name_weekday,
            sensor_set_name_weekday,
            sensor_get_name_year,
            sensor_set_name_year,
            sensor_get_name_month,
            sensor_set_name_month,
            sensor_get_name_day,
            sensor_set_name_day,
            sensor_get_name_hour,
            sensor_set_name_hour,
            sensor_get_name_minute,
            sensor_set_name_minute,
            sensor_get_name_second,
            sensor_set_name_second,
            sensor_get_name_am_pm,
            sensor_set_name_am_pm,
            sensor_set_config_name,
            translation_key,
            category,
            enabled_by_default,
            stove_model_generation,
        )


@dataclass
class PotMczConfigItem(SelectMczConfigItem):
    """Representation of a 'Pot' MCZ config item."""

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str | None,
        sensor_set_config_name: str,
        enabled_by_default: bool,
        translation_key: str,
        stove_model_generation: MczStoveModelGeneration | None = None,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a 'Pot' MCZ config item."""
        super().__init__(
            user_friendly_name,
            sensor_get_name,
            sensor_set_name,
            sensor_set_config_name,
            translation_key,
            None,
            enabled_by_default,
            stove_model_generation,
            None,
            sensor_set_name_m1=sensor_set_name_m1,
            sensor_set_name_m2=sensor_set_name_m2,
        )


@dataclass
class BinarySensorMczConfigItem(MczConfigItem):
    """Representation of a 'Binary Sensor' MCZ config item."""

    value_response_source: MczResponseSource = MczResponseSource.STATUS
    device_class: BinarySensorDeviceClass | None = None
    enabled_sensor_get_name: str | None = None
    inverted: bool = False

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        translation_key: str,
        category: EntityCategory | None,
        device_class: BinarySensorDeviceClass | None,
        enabled_by_default: bool,
        inverted: bool = False,
        enabled_sensor_get_name: str | None = None,
        sensor_set_name: str | None = None,
        sensor_set_config_name: str | None = None,
        stove_model_generation: MczStoveModelGeneration | None = None,
        sensor_set_name_m1: str | None = None,
        sensor_set_name_m2: str | None = None,
    ) -> None:
        """Create a 'Binary Sensor' MCZ config item."""
        super().__init__(
            user_friendly_name,
            stove_model_generation,
            sensor_set_name_m1,
            sensor_set_name_m2,
        )
        self.sensor_get_name = sensor_get_name
        self.translation_key = translation_key
        self.category = category
        self.device_class = device_class
        self.enabled_by_default = enabled_by_default
        self.inverted = inverted
        self.enabled_sensor_get_name = enabled_sensor_get_name
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.stove_model_generation = stove_model_generation


@dataclass
class SensorMczConfigItem(MczConfigItem):
    """Representation of a 'Sensor' MCZ config item."""

    unit: str | None = None
    display_precision: int | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    api_value_renames: dict[str, str] | None = None

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        translation_key: str | None,
        unit: str | None,
        display_precision: int | None,
        category: EntityCategory | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
        enabled_by_default: bool,
        api_value_renames: dict[str, str] | None = None,
        value_response_source: (
            MczResponseSource | dict[MczStoveModelGeneration, MczResponseSource]
        ) = MczResponseSource.STATE,
    ) -> None:
        """Create a 'Sensor' MCZ config item."""
        super().__init__(user_friendly_name, None)
        self.sensor_get_name = sensor_get_name
        self.translation_key = translation_key
        self.unit = unit
        self.display_precision = display_precision
        self.category = category
        self.device_class = device_class
        self.state_class = state_class
        self.enabled_by_default = enabled_by_default
        self.api_value_renames = api_value_renames
        self.value_response_source = value_response_source


@dataclass(kw_only=True)
class CounterMczConfigItem(SensorMczConfigItem):
    """Describe a counter using ordered response fields and their unit divisors."""

    value_sources: dict[str, int | dict[MczStoveModelGeneration, int]]
