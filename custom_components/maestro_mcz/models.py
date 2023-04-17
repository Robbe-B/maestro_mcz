from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import TEMP_CELSIUS

#FAN [name, icon, presets, fan_number, function, enabled_by_default, category]
#SENSOR [name, unit, icon, device_class, state_class, enabled_by_default, category]

GENERIC_SENSORS = {
    "state": ["Current State", None, "mdi:power", None, None, True, EntityCategory.DIAGNOSTIC],
    "temp_amb_install": ["Temperature", TEMP_CELSIUS, "mdi:thermometer", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, True, None],
    "mode": ["Current Mode", None, "mdi:calendar-multiselect", None, None, True, EntityCategory.DIAGNOSTIC],
    "temp_fumi": ["Exhaust Temperature", TEMP_CELSIUS, "mdi:thermometer", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, True, EntityCategory.DIAGNOSTIC],
    "temp_scheda": ["Board Temperature", TEMP_CELSIUS, "mdi:thermometer", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, True, EntityCategory.DIAGNOSTIC],
    "mode": ["Current Mode", None, "mdi:calendar-multiselect", None, None, True, EntityCategory.DIAGNOSTIC],
    "vel_real_ventola_fumi": ["Exhaust Fan Speed", "rpm", "mdi:fan-chevron-up", None, SensorStateClass.MEASUREMENT, True, EntityCategory.DIAGNOSTIC],
    "vel_real_coclea": ["Transport Screw Speed", "rpm", "mdi:screw-lag", None, None, SensorStateClass.MEASUREMENT, EntityCategory.DIAGNOSTIC],
}

GENERIC_FANS = {
    "set_vent_v1": ["Fan 1", "mdi:fan", {"0", "1", "2", "3", "4", "5", "6"}, 1, "Fan", True, None]
}

models = {
    "CUTHDE08": {
        "sensor": {
            **GENERIC_SENSORS,
            **{
                # "temp_amb_install": ["Temperature", TEMP_CELSIUS, "mdi:thermometer", SensorDeviceClass.TEMPERATURE, SensorStateClass.MEASUREMENT, True, None],
            }
        },
        "fan": {
            **GENERIC_FANS,
            **{
                # "set_vent_v1": ["Fan 1", ["0", "1", "2", "3", "4", "5", "6"], 1, "Fan"]
            }
        }
    },
    "SC10": {
        "sensor": {
            **GENERIC_SENSORS,
        },
        "fan": {
            **GENERIC_FANS,
            **{
                "set_vent_v2": ["Fan 2", "mdi:fan", {"0", "1", "2", "3", "4", "5", "6"}, 2, "Fan", True, None],
                "set_vent_v3": ["Fan 3", "mdi:fan", {"0", "1", "2", "3", "4", "5", "6"}, 3, "Fan", True, None]
            }
        }
    },
    "SC12": {
        "sensor": {
            **GENERIC_SENSORS,
        },
        "fan": {
            **GENERIC_FANS,
            **{
                "set_vent_v2": ["Fan 2", "mdi:fan", {"0", "1", "2", "3", "4", "5", "6"}, 2, "Fan", True, None],
                "set_vent_v3": ["Fan 3", "mdi:fan", {"0", "1", "2", "3", "4", "5", "6"}, 3, "Fan", True, None]
            }
        }
    },
    "ST.SUITE": {
        "sensor": {
            **GENERIC_SENSORS,
            **{
            }
        },
        "fan": {
            **GENERIC_FANS,
            **{
            }
        }
    },

    "LO08": {
        "sensor": {
            **GENERIC_SENSORS,
            **{
            }
        },
        "fan": {
            **GENERIC_FANS,
            **{
            }
        }
    }
}
