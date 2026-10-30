"""Cloud entity discovery, state, availability, IDs and commands on all platforms."""

from copy import deepcopy
from datetime import datetime, timezone
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.components.fan import FanEntityFeature
from homeassistant.util import dt as dt_util

from custom_components.maestro_mcz import PLATFORMS
from custom_components.maestro_mcz.binary_sensor import (
    MczCloudStatusBinarySensorEntity,
    MczStoveStatusBinarySensorEntity,
)
from custom_components.maestro_mcz.button import (
    MczButtonEntity,
    MczTimeSyncButtonEntity,
)
from custom_components.maestro_mcz.maestro.controller.responses.model import (
    Configuration,
    SensorConfiguration,
)
from custom_components.maestro_mcz.maestro.models import models


@pytest.fixture
async def entities(hass, entry, coordinator):
    result = {}
    for platform in PLATFORMS:
        module = importlib.import_module(f"custom_components.maestro_mcz.{platform}")
        add_entities = Mock()
        await module.async_setup_entry(hass, entry, add_entities)
        add_entities.assert_called_once()
        result[str(platform)] = add_entities.call_args.args[0]
    return result


def entity(entities, platform, cls=None):
    return next(e for e in entities[platform] if cls is None or isinstance(e, cls))


def test_all_platforms_discover_supported_entities_and_keep_legacy_ids(entities):
    expected = {
        "climate": {"SERIAL-001"},
        "fan": {"SERIAL-001-set_vent_v1"},
        "number": {"SERIAL-001-rit_usc_standby"},
        "select": {"SERIAL-001-set_pot_man", "SERIAL-001-toni_buzz"},
        "switch": {"SERIAL-001-att_eco"},
        "button": {"SERIAL-001-com_reset_allarm", "SERIAL-001-giorno"},
        "datetime": {"SERIAL-001-giorno"},
        "binary_sensor": {
            "SERIAL-001-is_in_error",
            "SERIAL-001-Cloud_Connection_Status",
            "SERIAL-001-Device_Connection_Status",
        },
    }
    for platform, ids in expected.items():
        assert {e.unique_id for e in entities[platform]} == ids
    assert {e.unique_id for e in entities["sensor"]} >= {
        "SERIAL-001-temp_amb_install",
        "SERIAL-001-last_alarm",
        "SERIAL-001-mode",
    }
    for values in entities.values():
        for item in values:
            assert item.device_info["identifiers"] == {("maestro_mcz", "SERIAL-001")}


@pytest.mark.parametrize("platform", [str(platform) for platform in PLATFORMS])
async def test_empty_model_does_not_invent_controls(
    hass, entry, coordinator, stove, platform
):
    stove.Model.model_configurations = []
    stove._state = SimpleNamespace()
    stove._status = SimpleNamespace()
    stove._is_stove_connected_to_cloud = False
    module = importlib.import_module(f"custom_components.maestro_mcz.{platform}")
    add = Mock()
    await module.async_setup_entry(hass, entry, add)
    found = add.call_args.args[0]
    assert len(found) == (2 if platform == "binary_sensor" else 0)


@pytest.mark.parametrize("platform", [str(platform) for platform in PLATFORMS])
def test_regular_entities_require_coordinator_and_stove_connectivity(
    entities, coordinator, stove, platform
):
    values = [
        e
        for e in entities[platform]
        if not isinstance(
            e, (MczCloudStatusBinarySensorEntity, MczStoveStatusBinarySensorEntity)
        )
    ]
    assert values
    for item in values:
        assert item.available
    for coordinator_ok, cloud_ok, device_ok in (
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ):
        coordinator.last_update_success = coordinator_ok
        stove._is_integration_connected_to_cloud = cloud_ok
        stove._is_stove_connected_to_cloud = device_ok
        for item in values:
            if platform == "fan":
                item._handle_coordinator_update_internal()
            assert not item.available


@pytest.mark.parametrize("platform", [str(platform) for platform in PLATFORMS])
def test_coordinator_updates_write_entity_state(entities, platform):
    for item in entities[platform]:
        with patch.object(item, "async_write_ha_state") as write:
            item._handle_coordinator_update()
        write.assert_called_once()


def test_connectivity_diagnostics_are_independent(entities, coordinator, stove):
    cloud = entity(entities, "binary_sensor", MczCloudStatusBinarySensorEntity)
    device = entity(entities, "binary_sensor", MczStoveStatusBinarySensorEntity)
    for cloud_ok, device_ok in ((True, True), (True, False), (False, False)):
        coordinator.last_update_success = False
        stove._is_integration_connected_to_cloud = cloud_ok
        stove._is_stove_connected_to_cloud = device_ok
        cloud._handle_coordinator_update_internal()
        device._handle_coordinator_update_internal()
        assert cloud.available
        assert cloud.is_on is cloud_ok
        assert device.available is cloud_ok
        assert device.is_on is device_ok


@pytest.mark.parametrize(
    "platform,prop,value_property,value",
    [
        ("sensor", "temp_amb_install", "native_value", 19.25),
        ("sensor", "temp_amb_install", "native_value", 0),
        ("number", "rit_usc_standby", "native_value", 0),
        ("switch", "att_eco", "is_on", False),
        ("binary_sensor", "is_in_error", "is_on", True),
        ("binary_sensor", "is_in_error", "is_on", False),
    ],
)
def test_state_precedence_fallback_and_missing(
    entities, stove, platform, prop, value_property, value
):
    item = next(e for e in entities[platform] if getattr(e, "_prop", None) == prop)
    stove._status = SimpleNamespace(**{prop: value})
    stove._state = SimpleNamespace(**{prop: "fallback"})
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) == value
    stove._status = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) == "fallback"
    stove._state = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) is None


@pytest.mark.parametrize(
    "raw,expected",
    [("dynamic", "auto"), ("power", "turbo"), ("manual", "manual"), (None, None)],
)
def test_sensor_mode_aliases(entities, stove, raw, expected):
    item = next(e for e in entities["sensor"] if e._prop == "mode")
    stove.State.mode = raw
    item._handle_coordinator_update_internal()
    assert item.native_value == expected


@pytest.mark.parametrize("value", [0.0, 17.9])
async def test_number_int_commands_are_converted_and_refreshed(
    entities, controller, coordinator, value
):
    await entity(entities, "number").async_set_native_value(value)
    args = controller.activate_program_with_commands_for_stove.await_args.args
    assert args[2] == "config-Start&Stop"
    assert [(c.SensorId, c.Value) for c in args[4]] == [
        ("id-rit_usc_standby", int(value))
    ]
    assert type(args[4][0].Value) is int
    coordinator.update_data_after_set.assert_awaited_once()


async def test_number_double_command_and_bounds(entities, controller):
    item = entity(entities, "number")
    item._number_configuration.configuration.type = "double"
    assert (item.native_min_value, item.native_max_value, item.native_step) == (
        0,
        120,
        1,
    )
    await item.async_set_native_value(17.5)
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[4][0].Value
        == 17.5
    )


@pytest.mark.parametrize("enabled", [False, True])
async def test_switch_commands_are_boolean(entities, controller, coordinator, enabled):
    item = entity(entities, "switch")
    await (item.async_turn_on() if enabled else item.async_turn_off())
    command = controller.activate_program_with_commands_for_stove.await_args.args[4][0]
    assert command.SensorId == "id-att_eco"
    assert command.Value is enabled
    coordinator.update_data_after_set.assert_awaited_once()


async def test_select_options_round_trip(entities, controller, coordinator, stove):
    item = next(e for e in entities["select"] if e._prop == "toni_buzz")
    assert item.options == ["Normal", "High"]
    assert item.current_option == "Normal"
    await item.async_select_option("High")
    command = controller.activate_program_with_commands_for_stove.await_args.args[4][0]
    assert (command.SensorId, command.Value) == ("id-toni_buzz", 2)
    coordinator.update_data_after_set.assert_awaited_once()
    stove.Status.toni_buzz = 2
    item._handle_coordinator_update_internal()
    assert item.current_option == "High"


async def test_manual_power_selector_is_numeric(entities, controller):
    item = next(e for e in entities["select"] if e._prop == "set_pot_man")
    assert item.options == ["1", "2", "3", "4", "5"]
    assert item.current_option == "3"
    await item.async_select_option("5")
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[4][0].Value
        == 5
    )


@pytest.mark.parametrize("kind,value", [("boolean", True), ("int", 7)])
async def test_alarm_button_commands(entities, controller, configuration, kind, value):
    item = entity(entities, "button", MczButtonEntity)
    item._set_button_configuration(
        SensorConfiguration(
            Configuration(
                configuration("reset", kind, Variants=["reset"], Mappings={"reset": 7})
            ),
            "reset-config",
        )
    )
    await item.async_press()
    command = controller.activate_program_with_commands_for_stove.await_args.args[4][0]
    assert command.SensorId == "id-reset"
    assert command.Value == value
    assert type(command.Value) is type(value)


async def test_command_failures_do_not_trigger_success_refresh(
    entities, controller, coordinator
):
    controller.activate_program_with_commands_for_stove.side_effect = RuntimeError(
        "command failed"
    )
    with pytest.raises(RuntimeError, match="command failed"):
        await entity(entities, "number").async_set_native_value(20)
    coordinator.update_data_after_set.assert_not_awaited()


@pytest.mark.parametrize(
    "generation,state,phase,mode,action",
    [
        (1, -1, None, HVACMode.OFF, HVACAction.OFF),
        (1, 0, None, HVACMode.OFF, HVACAction.OFF),
        (1, 1, None, HVACMode.OFF, HVACAction.IDLE),
        (1, 3, None, HVACMode.HEAT, HVACAction.PREHEATING),
        (1, 40, None, HVACMode.OFF, HVACAction.IDLE),
        (1, 41, None, HVACMode.OFF, HVACAction.IDLE),
        (1, 46, None, HVACMode.HEAT, HVACAction.IDLE),
        (1, 51, None, HVACMode.OFF, HVACAction.OFF),
        (1, 9, None, HVACMode.HEAT, HVACAction.HEATING),
        (2, -1, None, HVACMode.OFF, HVACAction.OFF),
        (2, 0, None, HVACMode.OFF, HVACAction.OFF),
        (2, 1, "turning-off", HVACMode.OFF, HVACAction.IDLE),
        (2, 1, None, HVACMode.OFF, HVACAction.OFF),
        (2, 2, "turning-off", HVACMode.HEAT, HVACAction.IDLE),
        (2, 2, None, HVACMode.HEAT, HVACAction.IDLE),
        (2, 3, "turning-on", HVACMode.HEAT, HVACAction.PREHEATING),
        (2, 3, "working", HVACMode.HEAT, HVACAction.HEATING),
        (2, 99, None, HVACMode.HEAT, HVACAction.HEATING),
        (3, 3, "working", HVACMode.HEAT, HVACAction.HEATING),
        (2, None, None, HVACMode.OFF, HVACAction.OFF),
    ],
)
def test_climate_generation_state_machine(
    entities, stove, generation, state, phase, mode, action
):
    item = entity(entities, "climate")
    item._supported_power_sensor = deepcopy(item._supported_power_sensor)
    item._supported_power_sensor.stove_model_generation = (
        models.MczStoveModelGeneration(generation)
    )
    stove.Status.stato_stufa = state
    stove.Status.fase_op = phase
    item._handle_coordinator_update_internal()
    assert (item.hvac_mode, item.hvac_action) == (mode, action)


async def test_climate_targets_presets_and_toggle_guard(
    entities, controller, coordinator, stove
):
    item = entity(entities, "climate")
    assert (item.current_temperature, item.target_temperature) == (20.5, 22)
    assert item.hvac_modes == [HVACMode.OFF, HVACMode.HEAT]
    assert item.preset_modes == ["manual", "auto", "comfort"]
    assert (item.min_temp, item.max_temp) == (5, 35)
    await item.async_set_hvac_mode(HVACMode.HEAT)
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    await item.async_set_hvac_mode(HVACMode.OFF)
    command = controller.activate_program_with_commands_for_stove.await_args.args[4][0]
    assert (command.SensorId, command.Value) == ("id-com_on_off", True)
    await item.async_set_temperature(temperature=23.5)
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[4][0].Value
        == 23.5
    )
    await item.async_set_preset_mode("auto")
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[4][0].Value
        == 1
    )
    before = controller.activate_program_with_commands_for_stove.await_count
    await item.async_set_preset_mode("invalid")
    assert controller.activate_program_with_commands_for_stove.await_count == before
    stove.State.mode = "dynamic"
    item._handle_coordinator_update_internal()
    assert item.preset_mode == "auto"


async def test_climate_integer_power_mapping(entities, controller, configuration):
    item = entity(entities, "climate")
    item._set_power_configuration(
        SensorConfiguration(
            Configuration(
                configuration(
                    "m1_stato_stufa",
                    "int",
                    Variants=["on", "off"],
                    Mappings={"on": 1, "off": 0},
                )
            ),
            "power-config",
        )
    )
    await item.async_set_hvac_mode(HVACMode.OFF)
    command = controller.activate_program_with_commands_for_stove.await_args.args[4][0]
    assert (command.SensorId, command.Value) == ("id-m1_stato_stufa", 0)


def test_climate_missing_values_clear_state(entities, stove):
    item = entity(entities, "climate")
    stove._state = SimpleNamespace()
    stove._status = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert (
        item.hvac_mode
        is item.hvac_action
        is item.target_temperature
        is item.preset_mode
        is None
    )


@pytest.mark.parametrize(
    "value,on,percentage",
    [(0, False, None), (1, True, 20), (3, True, 60), (5, True, 100)],
)
def test_fan_speed_conversion(entities, stove, value, on, percentage):
    item = entity(entities, "fan")
    stove.Status.set_vent_v1 = value
    item._handle_coordinator_update_internal()
    assert (item.is_on, item.percentage) == (on, percentage)
    assert item.speed_count == 5
    assert item.supported_features & FanEntityFeature.SET_SPEED


@pytest.mark.parametrize("percentage,expected", [(1, 1), (20, 1), (60, 3), (100, 5)])
async def test_fan_percentage_commands(entities, controller, percentage, expected):
    await entity(entities, "fan").async_set_percentage(percentage)
    command = controller.activate_program_with_commands_for_stove.await_args.args[4][0]
    assert (command.SensorId, command.Value) == ("id-set_vent_v1", expected)


async def test_fan_turn_on_off_and_presets(entities, controller):
    item = entity(entities, "fan")
    await item.async_turn_on()
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[4][0].Value
        == 5
    )
    await item.async_turn_on(percentage=40)
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[4][0].Value
        == 2
    )
    await item.async_turn_off()
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[4][0].Value
        == 0
    )
    config = item._current_fan_configuration.configuration
    config.variants = ["auto", "silent"]
    config.mappings = {"auto": 6, "silent": 7}
    item._update_features_based_on_current_stove_mode()
    assert item.preset_modes == ["auto", "silent"]
    await item.async_turn_on(preset_mode="auto")
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[4][0].Value
        == "auto"
    )
    before = controller.activate_program_with_commands_for_stove.await_count
    await item.async_set_preset_mode("invalid")
    assert controller.activate_program_with_commands_for_stove.await_count == before


def test_fan_mode_changes_and_silent_disable_availability(entities, stove):
    item = entity(entities, "fan")
    assert item.available
    assert item.icon == "mdi:fan"
    stove.Status.silent_enabled = True
    item._handle_coordinator_update_internal()
    assert not item.available
    assert item.icon == "mdi:fan-off"
    stove.Status.silent_enabled = False
    stove.State.mode = "auto"
    item._update_features_based_on_current_stove_mode()
    item._handle_coordinator_update_internal()
    assert not item.available
    assert item.speed_count == 0
    stove.State.mode = "unknown"
    item._update_features_based_on_current_stove_mode()
    assert item._current_fan_configuration is None
    stove.State.mode = "manual"
    item._update_features_based_on_current_stove_mode()
    item._handle_coordinator_update_internal()
    assert item.available


def test_date_time_reading_and_invalid_date(entities, stove):
    item = entity(entities, "datetime")
    assert item.native_value == datetime(
        2026, 10, 30, 14, 20, 10, tzinfo=dt_util.DEFAULT_TIME_ZONE
    )
    assert item.weekday == 4
    assert item.am_pm is True
    stove.Status.mese = 13
    item._handle_coordinator_update_internal()
    assert item.native_value is None
    stove.Status.mese = 0
    item._handle_coordinator_update_internal()
    assert item.native_value is None


@pytest.mark.parametrize(
    "time_zone,year,month,day,hour,weekday",
    [("UTC", 2026, 12, 31, 23, 3), ("Europe/Brussels", 2027, 1, 1, 0, 4)],
)
async def test_date_time_command_batch_and_time_zone(
    entities, controller, coordinator, time_zone, year, month, day, hour, weekday
):
    item = entity(entities, "datetime")
    with patch.object(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo(time_zone)):
        await item.async_set_value(
            datetime(2026, 12, 31, 23, 58, 57, tzinfo=timezone.utc)
        )
    args = controller.activate_program_with_commands_for_stove.await_args.args
    assert args[2] == "config-Orodatario"
    assert [(c.SensorId, c.Value) for c in args[4]][:7] == [
        ("id-giorno_sett", weekday),
        ("id-anno", year),
        ("id-mese", month),
        ("id-giorno", day),
        ("id-ore", hour),
        ("id-minuti", 58),
        ("id-secondi", 57),
    ]
    coordinator.update_data_after_set.assert_awaited_once()


async def test_time_sync_delegates_current_utc_time(entities, coordinator):
    item = entity(entities, "button", MczTimeSyncButtonEntity)
    now = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    with (
        patch("custom_components.maestro_mcz.button.dt_util.utcnow", return_value=now),
        patch.object(
            item._mcz_date_time_entity, "async_set_value", new_callable=AsyncMock
        ) as set_value,
    ):
        await item.async_press()
    set_value.assert_awaited_once_with(now)
    coordinator.update_data_after_set.assert_awaited_once()


@pytest.mark.parametrize(
    "value,expected",
    [
        (6, "auto"),
        ("6", "auto"),
        (7, "boost"),
        ("7", "boost"),
        (3, None),
        (0, None),
        ("0", None),
        (None, None),
    ],
)
def test_fan_numeric_preset_reverse_lookup(entities, stove, value, expected):
    item = entity(entities, "fan")
    item._current_fan_configuration.configuration.mappings = {
        "auto": 6,
        "boost": 7,
        "alternate_auto": 6,
    }
    stove.Status.set_vent_v1 = value
    item._handle_coordinator_update_internal()
    assert item.preset_mode == expected


@pytest.mark.parametrize("flag", [False, True])
async def test_date_time_command_preserves_am_pm_flag(entities, controller, flag):
    item = entity(entities, "datetime")
    item._attr_am_pm = flag
    await item.async_set_value(datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc))
    commands = controller.activate_program_with_commands_for_stove.await_args.args[4]
    assert next(c.Value for c in commands if c.SensorId == "id-am_pm") is flag


async def test_generation_one_date_time_optional_components(
    coordinator, stove, controller
):
    from custom_components.maestro_mcz.datetime import MczDateTimeEntity

    group = stove.get_model_configuration_by_model_configuration_name("Orodatario")
    group.configurations = [
        config
        for config in group.configurations
        if config.sensor_name not in {"giorno_sett", "secondi", "am_pm"}
    ]
    for config in group.configurations:
        config.sensor_name = f"m1_{config.sensor_name}"
    date_config = (
        stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
            "Orodatario", "m1_giorno"
        )
    )
    item = MczDateTimeEntity(
        coordinator, stove.UniqueCode, models.supported_date_times[1], date_config
    )
    assert item.native_value.second == 0
    assert item.weekday is item.am_pm is None
    await item.async_set_value(datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc))
    commands = controller.activate_program_with_commands_for_stove.await_args.args[4]
    assert {command.SensorId for command in commands} == {
        "id-anno",
        "id-mese",
        "id-giorno",
        "id-ore",
        "id-minuti",
    }


async def test_date_time_missing_fields_and_configuration(entities, stove, controller):
    item = entity(entities, "datetime")
    stove._status = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert item.native_value is item.weekday is item.am_pm is None
    item._date_time_configuration = None
    await item.async_set_value(datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc))
    controller.activate_program_with_commands_for_stove.assert_not_awaited()


def test_fan_string_preset_state_fallback_and_missing_value(entities, stove):
    item = entity(entities, "fan")
    item._current_fan_configuration.configuration.mappings = {"auto": 6}
    stove._status = SimpleNamespace()
    stove.State.silent_enabled = False
    stove.State.set_vent_v1 = "auto"
    item._handle_coordinator_update_internal()
    assert item.available
    assert item.is_on
    assert item.preset_mode == "auto"
    assert item.percentage is None
    stove._state = SimpleNamespace(mode="manual")
    item._handle_coordinator_update_internal()
    assert item.is_on is False
    assert item.preset_mode is item.percentage is None


def test_selector_state_fallback_and_missing_value(entities, stove):
    item = next(e for e in entities["select"] if e._prop == "set_pot_man")
    stove._status = SimpleNamespace()
    stove._state = SimpleNamespace(set_pot_man=4)
    item._handle_coordinator_update_internal()
    assert item.current_option == "4"
    stove._state = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert item.current_option is None
    item._selector_configuration.configuration.type = "string"
    item._handle_coordinator_update_internal()
    assert item.current_option is None


async def test_controls_without_configuration_do_not_send_commands(
    entities, controller
):
    item = entity(entities, "number")
    item._number_configuration = None
    await item.async_set_native_value(10)
    item = entity(entities, "select")
    item._selector_configuration = None
    await item.async_select_option("3")
    item = entity(entities, "switch")
    item._switch_configuration = None
    await item.async_turn_on()
    await item.async_turn_off()
    item = entity(entities, "button", MczButtonEntity)
    item._button_configuration = None
    await item.async_press()
    item = entity(entities, "button", MczTimeSyncButtonEntity)
    item._time_sync_button_configuration = None
    await item.async_press()
    item = entity(entities, "climate")
    item._power_configuration = item._thermostat_configuration = (
        item._climate_function_mode_configuration
    ) = None
    await item.async_set_hvac_mode(HVACMode.OFF)
    await item.async_set_temperature(temperature=22)
    await item.async_set_preset_mode("auto")
    item = entity(entities, "fan")
    item._current_fan_configuration = None
    item._attr_speed_count = 0
    await item.async_turn_on()
    await item.async_turn_off()
    await item.async_set_percentage(100)
    await item.async_set_preset_mode("auto")
    controller.activate_program_with_commands_for_stove.assert_not_awaited()


@pytest.mark.parametrize(
    "platform,prop,value_property,expected",
    [
        ("sensor", "temp_amb_install", "native_value", 20.5),
        ("binary_sensor", "is_in_error", "is_on", False),
    ],
)
def test_sensor_falls_back_to_state_when_status_is_null(
    entities, stove, platform, prop, value_property, expected
):
    assert getattr(stove.Status, prop) is None
    assert getattr(stove.State, prop) == expected
    item = next(e for e in entities[platform] if getattr(e, "_prop", None) == prop)
    assert getattr(item, value_property) == expected
    setattr(stove.State, prop, None)
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) is None
