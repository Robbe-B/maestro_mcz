from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
)

from homeassistant.helpers.entity import EntityCategory
from homeassistant.const import TEMP_CELSIUS

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
    "set_vent_v1": ["Fan 1", "mdi:fan", {"0", "1", "2", "3", "4", "5", "6"}, 1, "Fan", True, EntityCategory.CONFIG]
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
    "SC12": {
        "sensor": {
            **GENERIC_SENSORS,
        },
        "fan": {
            **GENERIC_FANS,
        }
    },
}
