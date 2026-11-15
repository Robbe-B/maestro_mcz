"""Supported MCZ counter sensors and their generation-specific units."""

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfTime
from homeassistant.helpers.entity import EntityCategory

from .models_types import CounterMczConfigItem, MczStoveModelGeneration

supported_counters = [
    CounterMczConfigItem(
        user_friendly_name="Ignition count",
        sensor_get_name="num_acc",
        translation_key="ignition_count",
        value_sources={"num_acc": 1},
        icon="mdi:fire",
        display_precision=0,
        category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    CounterMczConfigItem(
        user_friendly_name="Total operating time",
        sensor_get_name="total_operating_hours",
        translation_key="total_operating_time",
        value_sources={"cont_tot_h_lavoro": 1, "cont_tot_t_lavoro": 3600},
        icon="mdi:timer-outline",
        unit=UnitOfTime.HOURS,
        display_precision=0,
        category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    *(
        CounterMczConfigItem(
            user_friendly_name=f"Operating time at power {power}",
            sensor_get_name=f"cont_tot_t_lav{power}",
            translation_key=f"operating_time_power_{power}",
            value_sources={
                f"cont_tot_t_lav{power}": {
                    MczStoveModelGeneration.M1: 3600,
                    MczStoveModelGeneration.M2_PLUS: 1,
                }
            },
            icon="mdi:timer-outline",
            unit=UnitOfTime.HOURS,
            display_precision=0,
            category=EntityCategory.DIAGNOSTIC,
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.TOTAL_INCREASING,
        )
        for power in range(1, 6)
    ),
]
