from dataclasses import dataclass, field
from uuid import UUID
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import TEMP_CELSIUS

@dataclass
class MczConfigItem:

    sensor_get_name: str = field(default_factory=str) #name used for getting data out of the state and status reponses
    sensor_set_name: str = field(default_factory=str) #name used for setting data trough the API (resolved in configs first)
    sensor_set_config_name: str = field(default_factory=str)

    user_friendly_name: str = field(default_factory=str)
    icon: str = field(default_factory=str)
    enabled_by_default: bool = True
    category: EntityCategory | None = None

    def __init__(self, user_friendly_name:str, sensor_get_name:str) -> None:
        self.user_friendly_name = user_friendly_name
        self.sensor_get_name = sensor_get_name

@dataclass
class PowerSettingMczConfigItem(MczConfigItem):

    def __init__(self, user_friendly_name:str,  sensor_get_name:str, sensor_set_name:str, sensor_set_config_name:str, enabled_by_default: bool):
        super().__init__(user_friendly_name, sensor_get_name)
        self.icon = "mdi:power"
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default

@dataclass
class ClimateFunctionModeMczConfigItem(MczConfigItem):
    mappings: dict[str,str] = field(default_factory=list)

    def __init__(self, user_friendly_name:str, sensor_get_name:str, sensor_set_name:str, sensor_set_config_name:str, enabled_by_default: bool, mappings: dict[str,str]):
        super().__init__(user_friendly_name, sensor_get_name)
        self.icon = "mdi:thermostat-cog"
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default
        self.mappings = mappings

@dataclass
class ThermostatMczConfigItem(MczConfigItem):

    def __init__(self, user_friendly_name:str, sensor_get_name:str, sensor_set_name:str, sensor_set_config_name:str, enabled_by_default: bool):
        super().__init__(user_friendly_name, sensor_get_name)
        self.icon = "mdi:thermostat"
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default

@dataclass
class PotMczConfigItem(MczConfigItem):

    def __init__(self, user_friendly_name:str, sensor_get_name:str, sensor_set_name:str, sensor_set_config_name:str, enabled_by_default: bool):
        super().__init__(user_friendly_name, sensor_get_name)
        self.icon = "mdi:pot"
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default

@dataclass
class SensorMczConfigItem(MczConfigItem):
    
    unit: str | None = None
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None

    def __init__(self, user_friendly_name:str, sensor_get_name:str, icon:str, unit:str|None, category: EntityCategory | None, device_class: SensorDeviceClass | None, state_class: SensorStateClass | None, enabled_by_default: bool):
        super().__init__(user_friendly_name, sensor_get_name)
        self.icon = icon
        self.unit = unit
        self.category = category
        self.device_class = device_class
        self.state_class = state_class
        self.enabled_by_default = enabled_by_default

@dataclass
class FanMczConfigItem(MczConfigItem):
    
    presets: list[str] = field(default_factory=list)

    def __init__(self, user_friendly_name:str, sensor_get_name:str, sensor_set_name:str, sensor_set_config_name:str, enabled_by_default: bool):
        super().__init__(user_friendly_name, sensor_get_name)
        self.icon = "mdi:fan"
        self.sensor_set_name = sensor_set_name
        self.sensor_set_config_name = sensor_set_config_name
        self.enabled_by_default = enabled_by_default

supported_power_settings = [
    PowerSettingMczConfigItem("Power", "fase_op", "com_on_off", "Spegnimento", True),
]

supported_climate_function_modes = [
    ClimateFunctionModeMczConfigItem("Mode", "mode", "mod_funz", "set_mod", True, {"dynamic":"auto"}),
]

supported_thermostats = [
    ThermostatMczConfigItem("Temperature", "set_amb1", "set_amb1", "Set_amb_temp", True),
]

supported_pots = [
    PotMczConfigItem("Pot", "set_pot_man", "set_pot_man", "Set_pot", True)
]

supported_sensors = [
    SensorMczConfigItem("Current State","state","mdi:power", None, EntityCategory.DIAGNOSTIC, None, None, True),
    SensorMczConfigItem("Temperature","temp_amb_install","mdi:thermometer", TEMP_CELSIUS, None, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, True),
    SensorMczConfigItem("Current Mode","mode","mdi:calendar-multiselect", None, EntityCategory.DIAGNOSTIC, None, None, True),
    SensorMczConfigItem("Exhaust Temperature","temp_fumi","mdi:thermometer", TEMP_CELSIUS, EntityCategory.DIAGNOSTIC, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, True),
    SensorMczConfigItem("Board Temperature","temp_scheda","mdi:thermometer", TEMP_CELSIUS, EntityCategory.DIAGNOSTIC, SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, True),
    SensorMczConfigItem("Exhaust Fan Speed","vel_real_ventola_fumi","mdi:fan-chevron-up", "rpm", EntityCategory.DIAGNOSTIC, None, SensorStateClass.MEASUREMENT, True),
    SensorMczConfigItem("Transport Screw Speed","vel_real_coclea","mdi:screw-lag", "rpm", EntityCategory.DIAGNOSTIC, None, SensorStateClass.MEASUREMENT, True),
]

supported_fans = [
    FanMczConfigItem("Fan 1", "set_vent_v1", "set_vent_v1", "set_v1", True),
    FanMczConfigItem("Fan 2", "set_vent_v2", "set_vent_v2", "set_v2", True),
    FanMczConfigItem("Fan 3", "set_vent_v3", "set_vent_v3", "set_v3", True),
]
