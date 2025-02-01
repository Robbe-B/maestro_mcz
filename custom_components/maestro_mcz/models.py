"""Dynamic Models Config."""

from dataclasses import dataclass
from enum import Enum

from homeassistant.components.binary_sensor import BinarySensorDeviceClass
from homeassistant.components.number import NumberDeviceClass
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import REVOLUTIONS_PER_MINUTE, UnitOfTemperature, UnitOfTime
from homeassistant.helpers.entity import EntityCategory


class MczStoveModelGeneration(Enum):
    """Representation of a MCZ Stove Model Generation enum."""

    M1 = 1
    M2 = 2
    M3 = 3


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

    stove_model_generation: MczStoveModelGeneration | None = (
        None  # for sensors this will be null
    )

    # optional
    mode_to_configuration_name_mapping: dict[str, str] | None = (
        None  # key => Mode | value => Configuration Name
    )
    user_friendly_name: str | None = None
    icon: str | None = None
    unavailable_icon: str | None = None
    enabled_by_default: bool = True
    category: EntityCategory | None = None

    def __init__(
        self, user_friendly_name: str, stove_model_generation: MczStoveModelGeneration
    ) -> None:
        """Create a generic MCZ config item."""
        self.user_friendly_name = user_friendly_name
        self.stove_model_generation = stove_model_generation


@dataclass
class PowerSettingMczConfigItem(MczConfigItem):
    """Representation of a 'Power Setting' MCZ config item."""
   
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
        sensor_set_name: str,
        sensor_set_config_name: str,
        fase_sensor_get_name: str,
        sub_fase_sensor_get_name: str,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'Power Setting' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.sensor_get_name = sensor_get_name
        self.icon = "mdi:power"
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.fase_sensor_get_name = fase_sensor_get_name
        self.sub_fase_sensor_get_name = sub_fase_sensor_get_name
        self.enabled_by_default = enabled_by_default


@dataclass
class ClimateFunctionModeMczConfigItem(MczConfigItem):
    """Representation of a 'Climate Function Mode' MCZ config item."""

    api_mappings_key_rename: dict[str, str] | None = None

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str,
        sensor_set_config_name: str,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
        api_mappings_key_rename: dict[str, str] | None,
    ) -> None:
        """Create a 'Climate Function Mode' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.sensor_get_name = sensor_get_name
        self.icon = "mdi:thermostat-cog"
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default
        self.api_mappings_key_rename = api_mappings_key_rename


@dataclass
class ThermostatMczConfigItem(MczConfigItem):
    """Representation of a 'Thermostat' MCZ config item."""

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str,
        sensor_set_config_name: str,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'Thermostat' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.sensor_get_name = sensor_get_name
        self.icon = "mdi:thermostat"
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default


@dataclass
class FanMczConfigItem(MczConfigItem):
    """Representation of a 'Fan' MCZ config item."""

    silent_enabled_get_name: str | None = None

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str,
        mode_to_configuration_name_mapping: dict[str, str],
        silent_enabled_get_name: str | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'Fan' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.sensor_get_name = sensor_get_name
        self.icon = "mdi:fan"
        self.unavailable_icon = "mdi:fan-off"
        self.sensor_set_name = sensor_set_name
        self.mode_to_configuration_name_mapping = mode_to_configuration_name_mapping  # means we want to find the sensor name in the different mode configs
        self.silent_enabled_get_name = silent_enabled_get_name
        self.enabled_by_default = enabled_by_default


@dataclass
class ButtonMczConfigItem(MczConfigItem):
    """Representation of a 'Button' MCZ config item."""

    def __init__(
        self,
        user_friendly_name: str,
        sensor_set_name: str,
        sensor_set_config_name: str,
        icon: str,
        category: EntityCategory | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'Button' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.icon = icon
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.category = category
        self.enabled_by_default = enabled_by_default


@dataclass
class SwitchMczConfigItem(MczConfigItem):
    """Representation of a 'Switch' MCZ config item."""

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str,
        sensor_set_config_name: str,
        icon: str,
        category: EntityCategory | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'Switch' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.sensor_get_name = sensor_get_name
        self.icon = icon
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.category = category
        self.enabled_by_default = enabled_by_default


@dataclass
class NumberMczConfigItem(MczConfigItem):
    """Representation of a 'Number' MCZ config item."""

    device_class: NumberDeviceClass | None = None
    mode: str = "auto"  # 'box' or 'slider'

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        sensor_set_name: str,
        sensor_set_config_name: str,
        mode: str,
        icon: str,
        unit: str | None,
        category: EntityCategory | None,
        device_class: NumberDeviceClass | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'Number' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.sensor_get_name = sensor_get_name
        self.mode = mode
        self.icon = icon
        self.unit = unit
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.category = category
        self.device_class = device_class
        self.enabled_by_default = enabled_by_default


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
        sensor_set_name: str,
        sensor_set_config_name: str,
        icon: str,
        category: EntityCategory | None,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
        value_mappings: dict[str, str] | None,
    ) -> None:
        """Create a 'Select' MCZ config item."""
        super().__init__(user_friendly_name, stove_model_generation)
        self.sensor_get_name = sensor_get_name
        self.icon = icon
        self.category = category
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default
        self.value_mappings = value_mappings


@dataclass
class DateTimeMczConfigItem(MczConfigItem):
    """Representation of a 'DateTime' MCZ config item."""

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
        sensor_get_name_weekday: str,
        sensor_set_name_weekday: str,
        sensor_get_name_year: str,
        sensor_set_name_year: str,
        sensor_get_name_month: str,
        sensor_set_name_month: str,
        sensor_get_name_day: str,
        sensor_set_name_day: str,
        sensor_get_name_hour: str,
        sensor_set_name_hour: str,
        sensor_get_name_minute: str,
        sensor_set_name_minute: str,
        sensor_get_name_second: str,
        sensor_set_name_second: str,
        sensor_get_name_am_pm: str,
        sensor_set_name_am_pm: str,
        sensor_set_config_name: str,
        icon: str,
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
        self.icon = icon
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
        sensor_get_name_weekday: str,
        sensor_set_name_weekday: str,
        sensor_get_name_year: str,
        sensor_set_name_year: str,
        sensor_get_name_month: str,
        sensor_set_name_month: str,
        sensor_get_name_day: str,
        sensor_set_name_day: str,
        sensor_get_name_hour: str,
        sensor_set_name_hour: str,
        sensor_get_name_minute: str,
        sensor_set_name_minute: str,
        sensor_get_name_second: str,
        sensor_set_name_second: str,
        sensor_get_name_am_pm: str,
        sensor_set_name_am_pm: str,
        sensor_set_config_name: str,
        icon: str,
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
            icon,
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
        sensor_set_name: str,
        sensor_set_config_name: str,
        enabled_by_default: bool,
        stove_model_generation: MczStoveModelGeneration,
    ) -> None:
        """Create a 'Pot' MCZ config item."""
        super().__init__(
            user_friendly_name,
            sensor_get_name,
            sensor_set_name,
            sensor_set_config_name,
            "mdi:fire",
            None,
            enabled_by_default,
            stove_model_generation,
            None,
        )


@dataclass
class BinarySensorMczConfigItem(MczConfigItem):
    """Representation of a 'Binary Sensor' MCZ config item."""

    device_class: BinarySensorDeviceClass | None = None

    def __init__(
        self,
        user_friendly_name: str,
        sensor_get_name: str,
        icon: str,
        category: EntityCategory | None,
        device_class: BinarySensorDeviceClass | None,
        enabled_by_default: bool,
    ) -> None:
        """Create a 'Binary Sensor' MCZ config item."""
        super().__init__(user_friendly_name, None)
        self.sensor_get_name = sensor_get_name
        self.icon = icon
        self.category = category
        self.device_class = device_class
        self.enabled_by_default = enabled_by_default


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
        icon: str,
        unit: str | None,
        display_precision: int | None,
        category: EntityCategory | None,
        device_class: SensorDeviceClass | None,
        state_class: SensorStateClass | None,
        enabled_by_default: bool,
        api_value_renames: dict[str, str] | None = None,
    ) -> None:
        """Create a 'Sensor' MCZ config item."""
        super().__init__(user_friendly_name, None)
        self.sensor_get_name = sensor_get_name
        self.icon = icon
        self.unit = unit
        self.display_precision = display_precision
        self.category = category
        self.device_class = device_class
        self.state_class = state_class
        self.enabled_by_default = enabled_by_default
        self.api_value_renames = api_value_renames


supported_power_settings = [
    PowerSettingMczConfigItem(
        "Power",
        "stato_stufa",
        "com_on_off",
        "Spegnimento",
        "fase_op",
        "sub_fase_op",
        True,
        MczStoveModelGeneration.M2,
    ),
    PowerSettingMczConfigItem(
        "Power",
        "stato_stufa",
        "m1_stato_stufa",
        "Spegnimento",
        "fase_op",
        "sub_fase_op",
        True,
        MczStoveModelGeneration.M1,
    ),
]

supported_climate_function_modes = [
    ClimateFunctionModeMczConfigItem(
        "Mode",
        "mode",
        "mod_funz",
        "set_mod",
        True,
        MczStoveModelGeneration.M2,
        {"dynamic": "auto"},
    ),
    ClimateFunctionModeMczConfigItem(
        "Mode",
        "mode",
        "m1_mod_lav_att",
        "set_mod",
        True,
        MczStoveModelGeneration.M1,
        {"dynamic": "auto", "power": "turbo"},
    ),
]

supported_thermostats = [
    ThermostatMczConfigItem(
        "Ambient Temperature",
        "set_amb1",
        "set_amb1",
        "Set_amb_temp",
        True,
        MczStoveModelGeneration.M2,
    ),
    ThermostatMczConfigItem(
        "Ambient Temperature",
        "set_amb1",
        "m1_set_amb1",
        "Set_amb_temp",
        True,
        MczStoveModelGeneration.M1,
    ),
    ThermostatMczConfigItem(
        "Ambient Temperature 2",
        "set_amb2",
        "set_amb2",
        "Set_amb_temp",
        True,
        MczStoveModelGeneration.M2,
    ),
    ThermostatMczConfigItem(
        "Ambient Temperature 2",
        "set_amb2",
        "m1_set_amb2",
        "Set_amb_temp",
        True,
        MczStoveModelGeneration.M1,
    ),
    ThermostatMczConfigItem(
        "Ambient Temperature 3",
        "set_amb3",
        "set_amb3",
        "Set_amb_temp",
        True,
        MczStoveModelGeneration.M2,
    ),
    ThermostatMczConfigItem(
        "Ambient Temperature 3",
        "set_amb3",
        "m1_set_amb3",
        "Set_amb_temp",
        True,
        MczStoveModelGeneration.M1,
    ),
]

supported_pots = [
    PotMczConfigItem(
        "Manual Power",
        "set_pot_man",
        "set_pot_man",
        "Set_pot",
        True,
        MczStoveModelGeneration.M2,
    ),
    PotMczConfigItem(
        "Manual Power",
        "set_pot_man",
        "m1_potenza_att",
        "Set_pot",
        True,
        MczStoveModelGeneration.M1,
    ),
]

supported_fans = [
    FanMczConfigItem(
        "Fan 1",
        "set_vent_v1",
        "set_vent_v1",
        {
            "manual": "Manuale",
            "auto": "Auto",
            "overnight": "Overnight",
            "comfort": "Comfort",
            "turbo": "Turbo",
        },
        "silent_enabled",
        True,
        MczStoveModelGeneration.M2,
    ),
    FanMczConfigItem(
        "Fan 1",
        "set_vent_v1",
        "m1_set_vent_v1",
        {
            "manual": "Manuale",
            "dynamic": "Dynamic",
            "overnight": "Overnight",
            "comfort": "Comfort",
            "power": "Power",
        },
        "silent_enabled",
        True,
        MczStoveModelGeneration.M1,
    ),
    FanMczConfigItem(
        "Fan 2",
        "set_vent_v2",
        "set_vent_v2",
        {
            "manual": "Manuale",
            "auto": "Auto",
            "overnight": "Overnight",
            "comfort": "Comfort",
            "turbo": "Turbo",
        },
        "silent_enabled",
        True,
        MczStoveModelGeneration.M2,
    ),
    FanMczConfigItem(
        "Fan 2",
        "set_vent_v2",
        "m1_set_vent_v2",
        {
            "manual": "Manuale",
            "dynamic": "Dynamic",
            "overnight": "Overnight",
            "comfort": "Comfort",
            "power": "Power",
        },
        "silent_enabled",
        True,
        MczStoveModelGeneration.M1,
    ),
    FanMczConfigItem(
        "Fan 3",
        "set_vent_v3",
        "set_vent_v3",
        {
            "manual": "Manuale",
            "auto": "Auto",
            "overnight": "Overnight",
            "comfort": "Comfort",
            "turbo": "Turbo",
        },
        "silent_enabled",
        True,
        MczStoveModelGeneration.M2,
    ),
    FanMczConfigItem(
        "Fan 3",
        "set_vent_v3",
        "m1_set_vent_v3",
        {
            "manual": "Manuale",
            "dynamic": "Dynamic",
            "overnight": "Overnight",
            "comfort": "Comfort",
            "power": "Power",
        },
        "silent_enabled",
        True,
        MczStoveModelGeneration.M1,
    ),
]

supported_switches = [
    SwitchMczConfigItem(
        "Start / Stop",
        "att_eco",
        "att_eco",
        "Start&Stop",
        "mdi:leaf",
        None,
        True,
        MczStoveModelGeneration.M2,
    ),
    SwitchMczConfigItem(
        "Start / Stop",
        "att_eco",
        "m1_att_eco",
        "Start&Stop",
        "mdi:leaf",
        None,
        True,
        MczStoveModelGeneration.M1,
    ),
    SwitchMczConfigItem(
        "Timer",
        "crono_enabled",
        "att",
        "Crono",
        "mdi:timer",
        None,
        True,
        MczStoveModelGeneration.M2,
    ),
    SwitchMczConfigItem(
        "Timer",
        "crono_enabled",
        "m1_crono_enabled",
        "Crono",
        "mdi:timer",
        None,
        True,
        MczStoveModelGeneration.M1,
    ),
    # SwitchMczConfigItem("Silent Mode", "silent_enabled", "m1_silent_enabled", "set_v1", "mdi:fan-off", None, True),  #for first generation M1+
]

supported_numbers = [
    # start/stop
    NumberMczConfigItem(
        "Start / Stop - Delay in Ignition",
        "rit_usc_standby",
        "rit_usc_standby",
        "Start&Stop",
        "auto",
        "mdi:fire",
        UnitOfTime.SECONDS,
        EntityCategory.CONFIG,
        None,
        True,
        MczStoveModelGeneration.M2,
    ),
    NumberMczConfigItem(
        "Start / Stop - Delay in Ignition",
        "rit_usc_standby",
        "m1_rit_usc_standby",
        "Start&Stop",
        "auto",
        "mdi:fire",
        UnitOfTime.SECONDS,
        EntityCategory.CONFIG,
        None,
        True,
        MczStoveModelGeneration.M1,
    ),
    NumberMczConfigItem(
        "Start / Stop - Delay in Shutdown",
        "rit_ing_standby",
        "rit_ing_standby",
        "Start&Stop",
        "auto",
        "mdi:fire-off",
        UnitOfTime.SECONDS,
        EntityCategory.CONFIG,
        None,
        True,
        MczStoveModelGeneration.M2,
    ),
    NumberMczConfigItem(
        "Start / Stop - Delay in Shutdown",
        "rit_ing_standby",
        "m1_rit_ing_standby",
        "Start&Stop",
        "auto",
        "mdi:fire-off",
        UnitOfTime.SECONDS,
        EntityCategory.CONFIG,
        None,
        True,
        MczStoveModelGeneration.M1,
    ),
    NumberMczConfigItem(
        "Start / Stop - Negative Hysteresis",
        "ist_eco_neg_amb",
        "ist_eco_neg_amb",
        "Start&Stop",
        "auto",
        "mdi:thermometer-minus",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M2,
    ),
    NumberMczConfigItem(
        "Start / Stop - Negative Hysteresis",
        "ist_eco_neg_amb",
        "m1_ist_eco_neg_amb",
        "Start&Stop",
        "auto",
        "mdi:thermometer-minus",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M1,
    ),
    NumberMczConfigItem(
        "Start / Stop - Positive Hysteresis",
        "ist_eco_pos_amb",
        "ist_eco_pos_amb",
        "Start&Stop",
        "auto",
        "mdi:thermometer-plus",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M2,
    ),
    NumberMczConfigItem(
        "Start / Stop - Positive Hysteresis",
        "ist_eco_pos_amb",
        "m1_ist_eco_pos_amb",
        "Start&Stop",
        "auto",
        "mdi:thermometer-plus",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M1,
    ),
    # ambient
    NumberMczConfigItem(
        "Ambient - Negative Hysteresis",
        "ist_neg_amb",
        "ist_neg_amb",
        "Ambiente",
        "auto",
        "mdi:thermometer-minus",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M2,
    ),
    NumberMczConfigItem(
        "Ambient - Negative Hysteresis",
        "ist_neg_amb",
        "m1_ist_neg_amb",
        "Ambiente",
        "auto",
        "mdi:thermometer-minus",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M1,
    ),
    NumberMczConfigItem(
        "Ambient - Positive Hysteresis",
        "ist_pos_amb",
        "ist_pos_amb",
        "Ambiente",
        "auto",
        "mdi:thermometer-plus",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M2,
    ),
    NumberMczConfigItem(
        "Ambient - Positive Hysteresis",
        "ist_pos_amb",
        "m1_ist_pos_amb",
        "Ambiente",
        "auto",
        "mdi:thermometer-plus",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M1,
    ),
    # HYDRO - circulation pump
    NumberMczConfigItem(
        "Circulation Pump - On - Minimum Temperature",
        "temp_min_circ_on",
        "temp_min_circ_on",
        "temp_avanzate",
        "auto",
        "mdi:pump",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M2,
    ),
    NumberMczConfigItem(
        "Circulation Pump - On - Minimum Temperature",
        "temp_min_circ_on",
        "m1_temp_min_circ_on",
        "temp_avanzate",
        "auto",
        "mdi:pump",
        UnitOfTemperature.CELSIUS,
        EntityCategory.CONFIG,
        NumberDeviceClass.TEMPERATURE,
        True,
        MczStoveModelGeneration.M1,
    ),
]

supported_selectors = [
    SelectMczConfigItem(
        "Tones",
        "toni_buzz",
        "toni_buzz",
        "Toni",
        "mdi:volume-high",
        EntityCategory.CONFIG,
        True,
        MczStoveModelGeneration.M2,
        {"0": "Silent", "1": "Normal", "2": "High"},
    ),
    SelectMczConfigItem(
        "Tones",
        "toni_buzz",
        "m1_toni_buzz",
        "Toni",
        "mdi:volume-high",
        EntityCategory.CONFIG,
        True,
        MczStoveModelGeneration.M1,
        {"0": "Silent", "1": "Normal", "2": "High"},
    ),
]

supported_date_times = [
    DateTimeMczConfigItem(
        "Date & Time",
        "giorno",
        "giorno",
        "giorno_sett",
        "giorno_sett",
        "anno",
        "anno",
        "mese",
        "mese",
        "giorno",
        "giorno",
        "ore",
        "ore",
        "minuti",
        "minuti",
        "secondi",
        "secondi",
        "am_pm",
        "am_pm",
        "Orodatario",
        "mdi:calendar-clock",
        EntityCategory.CONFIG,
        False,
        MczStoveModelGeneration.M2,
    ),
    DateTimeMczConfigItem(
        "Date & Time",
        "giorno",
        "m1_giorno",
        None,
        None,
        "anno",
        "m1_anno",
        "mese",
        "m1_mese",
        "giorno",
        "m1_giorno",
        "ore",
        "m1_ore",
        "minuti",
        "m1_minuti",
        None,
        None,
        None,
        None,
        "Orodatario",
        "mdi:calendar-clock",
        EntityCategory.CONFIG,
        False,
        MczStoveModelGeneration.M1,
    ),
]

supported_buttons = [
    ButtonMczConfigItem(
        "Alarm Reset",
        "com_reset_allarm",
        "Reset Allarme",
        "mdi:auto-fix",
        EntityCategory.DIAGNOSTIC,
        True,
        MczStoveModelGeneration.M2,
    ),
    ButtonMczConfigItem(
        "Alarm Reset",
        "m1_com_reset_allarm",
        "Reset Allarme",
        "mdi:auto-fix",
        EntityCategory.DIAGNOSTIC,
        True,
        MczStoveModelGeneration.M1,
    ),
]

supported_time_sync_buttons = [
    TimeSyncButtonMczConfigItem(
        "Set System Date & Time",
        "giorno",
        "giorno",
        "giorno_sett",
        "giorno_sett",
        "anno",
        "anno",
        "mese",
        "mese",
        "giorno",
        "giorno",
        "ore",
        "ore",
        "minuti",
        "minuti",
        "secondi",
        "secondi",
        "am_pm",
        "am_pm",
        "Orodatario",
        "mdi:calendar-clock",
        EntityCategory.CONFIG,
        True,
        MczStoveModelGeneration.M2,
    ),
    TimeSyncButtonMczConfigItem(
        "Set System Date & Time",
        "giorno",
        "m1_giorno",
        None,
        None,
        "anno",
        "m1_anno",
        "mese",
        "m1_mese",
        "giorno",
        "m1_giorno",
        "ore",
        "m1_ore",
        "minuti",
        "m1_minuti",
        None,
        None,
        None,
        None,
        "Orodatario",
        "mdi:calendar-clock",
        EntityCategory.CONFIG,
        True,
        MczStoveModelGeneration.M1,
    ),
]

supported_binary_sensors = [
    BinarySensorMczConfigItem(
        "Alarm",
        "is_in_error",
        "mdi:alert",
        EntityCategory.DIAGNOSTIC,
        BinarySensorDeviceClass.PROBLEM,
        True,
    ),
]

supported_sensors = [
    SensorMczConfigItem(
        "Last Alarm Code",
        "last_alarm",
        "mdi:alert",
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        None,
        None,
        True,
    ),
    SensorMczConfigItem(
        "Current State",
        "state",
        "mdi:power",
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        None,
        None,
        True,
    ),
    SensorMczConfigItem(
        "Ambient Temperature",
        "temp_amb_install",
        "mdi:thermometer",
        UnitOfTemperature.CELSIUS,
        None,
        None,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        True,
    ),
    SensorMczConfigItem(
        "Water Temperature",
        "temp_caldaia",
        "mdi:water-thermometer",
        UnitOfTemperature.CELSIUS,
        None,
        None,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        True,
    ),
    SensorMczConfigItem(
        "Puffer Temperature",
        "temp_puffer",
        "mdi:water-thermometer",
        UnitOfTemperature.CELSIUS,
        None,
        None,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        True,
    ),
    SensorMczConfigItem(
        "Current Mode",
        "mode",
        "mdi:calendar-multiselect",
        None,
        None,
        EntityCategory.DIAGNOSTIC,
        None,
        None,
        True,
        {"dynamic": "auto", "power": "turbo"},
    ),  # renames are needed for first generation M1+ (for consistency in the different modes compaired to other models)
    SensorMczConfigItem(
        "Exhaust Temperature",
        "temp_fumi",
        "mdi:thermometer",
        UnitOfTemperature.CELSIUS,
        None,
        EntityCategory.DIAGNOSTIC,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        True,
    ),
    SensorMczConfigItem(
        "Board Temperature",
        "temp_scheda",
        "mdi:thermometer",
        UnitOfTemperature.CELSIUS,
        None,
        EntityCategory.DIAGNOSTIC,
        SensorDeviceClass.TEMPERATURE,
        SensorStateClass.MEASUREMENT,
        True,
    ),
    SensorMczConfigItem(
        "Exhaust Fan Speed",
        "vel_real_ventola_fumi",
        "mdi:fan-chevron-up",
        REVOLUTIONS_PER_MINUTE,
        None,
        EntityCategory.DIAGNOSTIC,
        None,
        SensorStateClass.MEASUREMENT,
        True,
    ),
    SensorMczConfigItem(
        "Transport Screw Speed",
        "vel_real_coclea",
        "mdi:screw-lag",
        REVOLUTIONS_PER_MINUTE,
        None,
        EntityCategory.DIAGNOSTIC,
        None,
        SensorStateClass.MEASUREMENT,
        True,
    ),
    SensorMczConfigItem(
        "Next Maintenance",
        "ore_prox_manut",
        "mdi:wrench-clock",
        UnitOfTime.HOURS,
        0,
        EntityCategory.DIAGNOSTIC,
        None,
        SensorStateClass.MEASUREMENT,
        True,
    ),  # SensorDeviceClass.DURATION
]
