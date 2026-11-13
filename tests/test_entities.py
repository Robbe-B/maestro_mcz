"""Cloud entity discovery, state, availability, IDs and commands on all platforms."""

from datetime import datetime, timezone
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.climate import HVACAction, HVACMode
from homeassistant.components.fan import FanEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.entity import EntityCategory
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
from custom_components.maestro_mcz.climate import MczClimateEntity
from custom_components.maestro_mcz.maestro.controller.responses.model import (
    Configuration,
    SensorConfiguration,
)
from custom_components.maestro_mcz.maestro.models import models


@pytest.fixture
async def entities(hass, entry, coordinator):
    """Set up each real HA platform and collect the controls it creates."""
    entities_by_platform = {}
    for platform in PLATFORMS:
        module = importlib.import_module(f"custom_components.maestro_mcz.{platform}")
        add_entities = Mock()
        await module.async_setup_entry(hass, entry, add_entities)
        add_entities.assert_called_once()
        entities_by_platform[str(platform)] = add_entities.call_args.args[0]
    return entities_by_platform


def entity(entities, platform, cls=None):
    """Find one control on a platform, optionally selecting a particular kind."""
    for candidate in entities[platform]:
        if cls is None or isinstance(candidate, cls):
            return candidate
    raise AssertionError(f"No matching entity found on the {platform} platform")


def last_sent_command(controller):
    """Read the first setting command from the controller's last recorded request."""
    activation = controller.activate_program_with_commands_for_stove.await_args
    sent_commands = activation.args[4]
    return sent_commands[0]


def test_all_platforms_discover_supported_entities_and_keep_legacy_ids(entities):
    """Keep supported controls and their existing IDs so users do not lose saved automations."""
    # 1. List the controls expected from our example stove.
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
    # 2. Each platform creates the correct controls with stable identifiers.
    for platform, expected_ids in expected.items():
        discovered_ids = {control.unique_id for control in entities[platform]}
        assert discovered_ids == expected_ids
    sensor_ids = {sensor.unique_id for sensor in entities["sensor"]}
    assert sensor_ids >= {
        "SERIAL-001-temp_amb_install",
        "SERIAL-001-last_alarm",
        "SERIAL-001-mode",
    }
    # 3. All controls belong to the same physical stove in HA.
    for platform_entities in entities.values():
        for item in platform_entities:
            assert item.device_info["identifiers"] == {("maestro_mcz", "SERIAL-001")}


@pytest.mark.parametrize("prop,value", [("state", "working"), ("mode", "manual")])
async def test_operating_sensors_are_regular_entities(
    hass, entry, coordinator, stove, prop, value
):
    """Show everyday operating readings as regular sensors without changing their IDs or values."""
    # 1. Give the stove an operating reading to discover.
    setattr(stove.Status, prop, value)
    module = importlib.import_module("custom_components.maestro_mcz.sensor")
    # 2. Discover the sensors through the Home Assistant platform.
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    discovered_sensors = add_entities.call_args.args[0]
    operating_sensor = next(
        sensor for sensor in discovered_sensors if sensor._prop == prop
    )
    # 3. Keep the reading enabled with its existing ID, outside diagnostics.
    assert operating_sensor.entity_category is None
    assert operating_sensor.unique_id == f"SERIAL-001-{prop}"
    assert operating_sensor.entity_registry_enabled_default is True
    assert operating_sensor.native_value == value


@pytest.mark.parametrize("command_name", ["com_reset_allarm", "m1_com_reset_allarm"])
async def test_alarm_reset_is_a_configuration_button(
    hass, entry, coordinator, stove, controller, configuration, command_name
):
    """Put alarm reset under Configuration on both stove families without changing its command."""
    # 1. Give the stove the alarm-reset command used by this family.
    reset_group = next(
        group
        for group in stove.Model.model_configurations
        if group.configuration_name == "Reset Allarme"
    )
    reset_group.configurations = [Configuration(configuration(command_name, "boolean"))]
    if command_name == "m1_com_reset_allarm":
        ping_group = stove.get_model_configuration_by_model_configuration_name(
            "cod_for_spe_mqtt"
        )
        ping_group.configuration_name = "PING STOVE"
        ping_sensor = ping_group.configurations[0]
        ping_sensor.sensor_name = "m1_cod_for_spe_mqtt"
        ping_sensor.mappings = {"C|RecuperoParametri": 0, "C|RecuperoInfo": 1}
    module = importlib.import_module("custom_components.maestro_mcz.button")
    # 2. Discover the reset button through the Home Assistant platform.
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    discovered_buttons = add_entities.call_args.args[0]
    reset_button = next(
        button for button in discovered_buttons if button._prop == command_name
    )
    # 3. Keep the button enabled with its existing ID and reset behavior.
    assert reset_button.entity_category is EntityCategory.CONFIG
    assert reset_button.unique_id == f"SERIAL-001-{command_name}"
    assert reset_button.entity_registry_enabled_default is True
    await reset_button.async_press()
    command = last_sent_command(controller)
    assert command.SensorId == f"id-{command_name}"
    assert command.Value is True
    activation = controller.activate_program_with_commands_for_stove.await_args
    assert activation.args[2] == "config-Reset Allarme"
    coordinator.update_data_after_set.assert_awaited_once()


@pytest.mark.parametrize("platform", [str(platform) for platform in PLATFORMS])
async def test_empty_model_does_not_invent_controls(
    hass, entry, coordinator, stove, platform
):
    """Avoid showing controls a stove does not support, while retaining connection indicators."""
    # 1. Remove all supported controls and available readings from the model.
    stove.Model.model_configurations = []
    stove._state = SimpleNamespace()
    stove._status = SimpleNamespace()
    stove._is_stove_connected_to_cloud = False
    module = importlib.import_module(f"custom_components.maestro_mcz.{platform}")
    # 2. Set up the selected HA platform for this empty model.
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    discovered_entities = add_entities.call_args.args[0]
    # 3. Only the two connection indicators may exist without model data.
    if platform == "binary_sensor":
        assert len(discovered_entities) == 2
    else:
        assert len(discovered_entities) == 0


@pytest.mark.parametrize("platform", [str(platform) for platform in PLATFORMS])
def test_regular_entities_require_coordinator_and_stove_connectivity(
    entities, coordinator, stove, platform
):
    """Make controls unavailable when either HA, the cloud, or the stove cannot communicate."""
    # 1. Exclude connection indicators; they explain failures rather than control the stove.
    regular_controls = [
        control
        for control in entities[platform]
        if not isinstance(
            control, (MczCloudStatusBinarySensorEntity, MczStoveStatusBinarySensorEntity)
        )
    ]
    assert regular_controls
    for item in regular_controls:
        assert item.available
    # 2. Break each communication link in turn.
    for coordinator_ok, cloud_ok, device_ok in (
        (False, True, True),
        (True, False, True),
        (True, True, False),
    ):
        coordinator.last_update_success = coordinator_ok
        stove._is_integration_connected_to_cloud = cloud_ok
        stove._is_stove_connected_to_cloud = device_ok
        # 3. None of the ordinary controls should claim to be usable.
        for item in regular_controls:
            if platform == "fan":
                item._handle_coordinator_update_internal()
            assert not item.available


@pytest.mark.parametrize("platform", [str(platform) for platform in PLATFORMS])
def test_coordinator_updates_write_entity_state(entities, platform):
    """Publish refreshed values to HA so users actually see new readings."""
    # 1. Record whether each control publishes its changed state.
    for item in entities[platform]:
        with patch.object(item, "async_write_ha_state") as write:
            # 2. Notify the control that new stove data has arrived.
            item._handle_coordinator_update()
        # 3. It should publish exactly once.
        write.assert_called_once()


def test_connectivity_diagnostics_are_independent(entities, coordinator, stove):
    """Keep connection indicators informative even when ordinary controls are unavailable."""
    # 1. Select the indicators for HA-to-cloud and stove-to-cloud communication.
    cloud = entity(entities, "binary_sensor", MczCloudStatusBinarySensorEntity)
    device = entity(entities, "binary_sensor", MczStoveStatusBinarySensorEntity)
    # 2. Try a working stove, an offline stove, and an unreachable cloud.
    for cloud_ok, device_ok in ((True, True), (True, False), (False, False)):
        coordinator.last_update_success = False
        stove._is_integration_connected_to_cloud = cloud_ok
        stove._is_stove_connected_to_cloud = device_ok
        cloud._handle_coordinator_update_internal()
        device._handle_coordinator_update_internal()
        # 3. The indicators should explain which link is still reachable.
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
    """Prefer status readings, fall back to state readings, and never invent missing values."""
    # 1. Give status and state different values for the same stove field.
    item = next(
        control for control in entities[platform] if getattr(control, "_prop", None) == prop
    )
    stove._status = SimpleNamespace(**{prop: value})
    stove._state = SimpleNamespace(**{prop: "fallback"})
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) == value
    # 2. Without a status reading, use the available state reading.
    stove._status = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) == "fallback"
    # 3. Without either reading, show no value instead of an old or guessed value.
    stove._state = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) is None


@pytest.mark.parametrize(
    "raw,expected",
    [("dynamic", "auto"), ("power", "turbo"), ("manual", "manual"), (None, None)],
)
def test_sensor_mode_aliases(entities, stove, raw, expected):
    """Translate cloud mode names to familiar HA names without inventing a missing mode."""
    # 1. Give the stove the cloud mode chosen by this case.
    item = next(sensor for sensor in entities["sensor"] if sensor._prop == "mode")
    stove.State.mode = raw
    # 2. Refresh the sensor; it should display the corresponding HA mode.
    item._handle_coordinator_update_internal()
    assert item.native_value == expected


@pytest.mark.parametrize("value", [0.0, 17.9])
async def test_number_int_commands_are_converted_and_refreshed(
    entities, controller, coordinator, value
):
    """Send whole-number settings as integers and then request updated readings."""
    # 1. Choose a numeric control whose stove command requires a whole number.
    await entity(entities, "number").async_set_native_value(value)
    # 2. Inspect the command rather than assuming the input's original type was correct.
    activation = controller.activate_program_with_commands_for_stove.await_args
    sent_commands = activation.args[4]
    assert activation.args[2] == "config-Start&Stop"
    assert len(sent_commands) == 1
    command = sent_commands[0]
    assert command.SensorId == "id-rit_usc_standby"
    assert command.Value == int(value)
    assert type(command.Value) is int
    # 3. HA should read back the changed setting.
    coordinator.update_data_after_set.assert_awaited_once()


async def test_number_double_command_and_bounds(entities, controller):
    """Preserve fractional settings and show the model's allowed adjustment range."""
    # 1. Describe this number control as accepting fractional values.
    item = entity(entities, "number")
    item._number_configuration.configuration.type = "double"
    assert item.native_min_value == 0
    assert item.native_max_value == 120
    assert item.native_step == 1
    # 2. Enter a fractional value; it must not be rounded to a whole number.
    await item.async_set_native_value(17.5)
    command = last_sent_command(controller)
    assert command.Value == 17.5


@pytest.mark.parametrize("enabled", [False, True])
async def test_switch_commands_are_boolean(entities, controller, coordinator, enabled):
    """Send a real yes/no switch value so the stove cannot confuse it with another command."""
    # 1. Select the switch and perform the on or off action chosen by this case.
    item = entity(entities, "switch")
    if enabled:
        await item.async_turn_on()
    else:
        await item.async_turn_off()
    # 2. The command keeps both its correct sensor ID and boolean value.
    command = last_sent_command(controller)
    assert command.SensorId == "id-att_eco"
    assert command.Value is enabled
    coordinator.update_data_after_set.assert_awaited_once()


async def test_select_options_round_trip(entities, controller, coordinator, stove):
    """Turn a readable dropdown choice into a stove value and display the returned choice."""
    # 1. The tone dropdown starts on its normal setting.
    item = next(selector for selector in entities["select"] if selector._prop == "toni_buzz")
    assert item.options == ["Normal", "High"]
    assert item.current_option == "Normal"
    # 2. Choosing High sends the model's value 2 and requests an updated reading.
    await item.async_select_option("High")
    command = last_sent_command(controller)
    assert command.SensorId == "id-toni_buzz"
    assert command.Value == 2
    coordinator.update_data_after_set.assert_awaited_once()
    # 3. When the stove reports value 2, HA displays High again.
    stove.Status.toni_buzz = 2
    item._handle_coordinator_update_internal()
    assert item.current_option == "High"


async def test_manual_power_selector_is_numeric(entities, controller):
    """Present power levels as readable choices but send the selected level as a number."""
    # 1. The stove supports five power levels and currently reports level three.
    item = next(selector for selector in entities["select"] if selector._prop == "set_pot_man")
    assert item.options == ["1", "2", "3", "4", "5"]
    assert item.current_option == "3"
    # 2. Selecting the text label "5" sends numeric power level 5.
    await item.async_select_option("5")
    command = last_sent_command(controller)
    assert command.Value == 5


@pytest.mark.parametrize("kind,value", [("boolean", True), ("int", 7)])
async def test_alarm_button_commands(entities, controller, configuration, kind, value):
    """Reset alarms using the value type the model expects, rather than a guessed button value."""
    # 1. Describe an alarm-reset button with either a boolean or integer command.
    item = entity(entities, "button", MczButtonEntity)
    reset_description = configuration(
        "reset", kind, Variants=["reset"], Mappings={"reset": 7}
    )
    reset_sensor = Configuration(reset_description)
    reset_configuration = SensorConfiguration(reset_sensor, "reset-config")
    item._set_button_configuration(reset_configuration)
    # 2. Press the button and inspect the command sent to the stove.
    await item.async_press()
    command = last_sent_command(controller)
    assert command.SensorId == "id-reset"
    assert command.Value == value
    assert type(command.Value) is type(value)


async def test_command_failures_do_not_trigger_success_refresh(
    entities, controller, coordinator
):
    """Do not run success-only follow-up work when the stove rejected a setting change."""
    # 1. Make a setting command fail.
    controller.activate_program_with_commands_for_stove.side_effect = RuntimeError(
        "command failed"
    )
    # 2. Attempt the change; the error must reach the caller.
    with pytest.raises(RuntimeError, match="command failed"):
        await entity(entities, "number").async_set_native_value(20)
    # 3. A success refresh must not disguise the failed command.
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
    """Show the correct heating activity for each model, avoiding misleading on/off indications."""
    # 1. Describe the model's ping protocol and reported operating state.
    item = entity(entities, "climate")
    stove.Model.model_name = f"M{generation} example"
    if generation == 1:
        ping_group = stove.get_model_configuration_by_model_configuration_name(
            "cod_for_spe_mqtt"
        )
        ping_group.configuration_name = "PING STOVE"
        ping_sensor = ping_group.configurations[0]
        ping_sensor.sensor_name = "m1_cod_for_spe_mqtt"
        ping_sensor.mappings = {"C|RecuperoParametri": 0, "C|RecuperoInfo": 1}
    stove.Status.stato_stufa = state
    stove.Status.fase_op = phase
    # 2. Translate that report into HA's heating mode and current activity.
    item._handle_coordinator_update_internal()
    # 3. Both the requested mode and actual activity must match the scenario.
    assert item.hvac_mode == mode
    assert item.hvac_action == action


def test_climate_does_not_guess_an_unknown_control_family(entities, stove):
    """Clear old heating activity when controls are no longer recognized."""
    # 1. A previously recognized stove now exposes an unfamiliar control layout.
    item = entity(entities, "climate")
    assert item.hvac_action == HVACAction.HEATING
    stove.Model.model_configurations.clear()

    # 2. Process the same readings without a known interpretation.
    item._handle_coordinator_update_internal()

    # 3. Do not retain the old heating indication or guess a newer generation.
    assert item.hvac_mode is None
    assert item.hvac_action is None


async def test_climate_targets_presets_and_toggle_guard(
    entities, controller, coordinator, stove
):
    """Respect existing heating state and send only valid changes to temperature and mode."""
    # 1. Check the initial temperatures, available modes, and allowed range.
    item = entity(entities, "climate")
    assert item.native_current_temperature == 20.5
    assert item.native_target_temperature == 22
    assert item.hvac_modes == [HVACMode.OFF, HVACMode.HEAT]
    assert item.preset_modes == ["manual", "auto", "comfort"]
    assert item.min_temp == 5
    assert item.max_temp == 35
    # 2. Asking an already-heating stove to heat must not toggle its power.
    await item.async_set_hvac_mode(HVACMode.HEAT)
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    await item.async_set_hvac_mode(HVACMode.OFF)
    command = last_sent_command(controller)
    assert command.SensorId == "id-com_on_off"
    assert command.Value is True
    # 3. Temperature and preset changes send their correct stove values.
    await item.async_set_temperature(temperature=23.5)
    assert last_sent_command(controller).Value == 23.5
    await item.async_set_preset_mode("auto")
    assert last_sent_command(controller).Value == 1
    # 4. Ignore an unknown preset; translate a returned cloud mode back to Auto.
    previous_command_count = controller.activate_program_with_commands_for_stove.await_count
    await item.async_set_preset_mode("invalid")
    assert controller.activate_program_with_commands_for_stove.await_count == previous_command_count
    stove.State.mode = "dynamic"
    item._handle_coordinator_update_internal()
    assert item.preset_mode == "auto"


@pytest.mark.parametrize("current,target", [(18.5, 23.5), (0, 0), (None, None)])
def test_climate_temperature_updates_use_core_api(entities, stove, current, target):
    """Keep temperatures fresh in HA, including zero and unknown readings."""
    # 1. Read the initial temperatures before the stove sends a changed report.
    item = entity(entities, "climate")
    assert item.native_current_temperature == 20.5
    assert item.native_target_temperature == 22

    # 2. Refresh the control with the new room temperature and heating target.
    stove.State.temp_amb_install = current
    stove.State.set_amb1 = target
    item._handle_coordinator_update_internal()

    # 3. HA must read the new values in Celsius, not cached values or a different unit.
    assert item.native_current_temperature == current
    assert item.native_target_temperature == target
    assert item.native_temperature_unit == UnitOfTemperature.CELSIUS


def test_climate_does_not_override_deprecated_temperature_properties():
    """Let HA handle display units without deprecated temperature overrides."""
    # 1. Inspect only the integration's own members, not Core's compatibility aliases.
    own_members = vars(MczClimateEntity)

    # 2. The integration must not define deprecated properties or store legacy values.
    for property_name in (
        "current_temperature",
        "target_temperature",
        "temperature_unit",
    ):
        assert property_name not in own_members
        assert f"_attr_{property_name}" not in own_members


async def test_climate_integer_power_mapping(entities, controller, configuration):
    """Use the older model's explicit off value rather than the newer boolean power command."""
    # 1. Describe a power control that uses numeric on/off values.
    item = entity(entities, "climate")
    power_description = configuration(
        "m1_stato_stufa",
        "int",
        Variants=["on", "off"],
        Mappings={"on": 1, "off": 0},
    )
    power_sensor = Configuration(power_description)
    power_configuration = SensorConfiguration(power_sensor, "power-config")
    item._set_power_configuration(power_configuration)
    # 2. Turn heating off; this model expects value 0 on its own sensor.
    await item.async_set_hvac_mode(HVACMode.OFF)
    command = last_sent_command(controller)
    assert command.SensorId == "id-m1_stato_stufa"
    assert command.Value == 0


def test_climate_missing_values_clear_state(entities, stove):
    """Clear missing heating information so old temperatures or modes are not shown as current."""
    # 1. Remove both sources of stove readings.
    item = entity(entities, "climate")
    stove._state = SimpleNamespace()
    stove._status = SimpleNamespace()
    # 2. Refresh the control; each missing value should be empty.
    item._handle_coordinator_update_internal()
    assert item.hvac_mode is None
    assert item.hvac_action is None
    assert item.native_target_temperature is None
    assert item.preset_mode is None


@pytest.mark.parametrize(
    "value,on,percentage",
    [(0, False, None), (1, True, 20), (3, True, 60), (5, True, 100)],
)
def test_fan_speed_conversion(entities, stove, value, on, percentage):
    """Convert stove fan levels into the on/off state and percentage users see in HA."""
    # 1. Give the stove one of its reported fan speed levels.
    item = entity(entities, "fan")
    stove.Status.set_vent_v1 = value
    # 2. Refresh the fan control and check its readable speed.
    item._handle_coordinator_update_internal()
    assert item.is_on == on
    assert item.percentage == percentage
    assert item.speed_count == 5
    assert item.supported_features & FanEntityFeature.SET_SPEED


@pytest.mark.parametrize("percentage,expected", [(1, 1), (20, 1), (60, 3), (100, 5)])
async def test_fan_percentage_commands(entities, controller, percentage, expected):
    """Convert a requested fan percentage to a supported stove level."""
    # 1. Request the percentage selected by this test case.
    await entity(entities, "fan").async_set_percentage(percentage)
    # 2. The stove receives its numeric speed level, not the raw percentage.
    command = last_sent_command(controller)
    assert command.SensorId == "id-set_vent_v1"
    assert command.Value == expected


async def test_fan_turn_on_off_and_presets(entities, controller):
    """Keep fan on/off, percentage, and preset actions consistent with the stove's controls."""
    # 1. Without a requested speed, turning on selects the maximum level.
    item = entity(entities, "fan")
    await item.async_turn_on()
    assert last_sent_command(controller).Value == 5
    # 2. An explicit percentage changes the level; turning off sends zero.
    await item.async_turn_on(percentage=40)
    assert last_sent_command(controller).Value == 2
    await item.async_turn_off()
    assert last_sent_command(controller).Value == 0
    # 3. Add supported presets and verify that an unknown preset sends nothing.
    config = item._current_fan_configuration.configuration
    config.variants = ["auto", "silent"]
    config.mappings = {"auto": 6, "silent": 7}
    item._update_features_based_on_current_stove_mode()
    assert item.preset_modes == ["auto", "silent"]
    await item.async_turn_on(preset_mode="auto")
    assert last_sent_command(controller).Value == "auto"
    previous_command_count = controller.activate_program_with_commands_for_stove.await_count
    await item.async_set_preset_mode("invalid")
    assert controller.activate_program_with_commands_for_stove.await_count == previous_command_count


def test_fan_mode_changes_and_silent_disable_availability(entities, stove):
    """Disable unavailable fan controls when silent mode or the operating mode forbids them."""
    # 1. A manual-mode fan starts available with its normal icon.
    item = entity(entities, "fan")
    assert item.available
    assert item.icon == "mdi:fan"
    # 2. Silent mode makes manual fan adjustment unavailable.
    stove.Status.silent_enabled = True
    item._handle_coordinator_update_internal()
    assert not item.available
    assert item.icon == "mdi:fan-off"
    # 3. Automatic or unknown operating modes must not invent manual fan controls.
    stove.Status.silent_enabled = False
    stove.State.mode = "auto"
    item._update_features_based_on_current_stove_mode()
    item._handle_coordinator_update_internal()
    assert not item.available
    assert item.speed_count == 0
    stove.State.mode = "unknown"
    item._update_features_based_on_current_stove_mode()
    assert item._current_fan_configuration is None
    # 4. Returning to manual mode restores the supported control.
    stove.State.mode = "manual"
    item._update_features_based_on_current_stove_mode()
    item._handle_coordinator_update_internal()
    assert item.available


def test_date_time_reading_and_invalid_date(entities, stove):
    """Display a valid stove clock but reject impossible dates instead of guessing a date."""
    # 1. The initial stove report contains a valid date and time.
    item = entity(entities, "datetime")
    assert item.native_value == datetime(
        2026, 10, 30, 14, 20, 10, tzinfo=dt_util.DEFAULT_TIME_ZONE
    )
    assert item.weekday == 4
    assert item.am_pm is True
    # 2. Month 13 and month 0 are both invalid; neither should display a clock value.
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
    """Set the stove clock in the user's local time, including dates crossing New Year."""
    # 1. Select UTC or Brussels as HA's local time zone.
    item = entity(entities, "datetime")
    with patch.object(dt_util, "DEFAULT_TIME_ZONE", ZoneInfo(time_zone)):
        await item.async_set_value(
            datetime(2026, 12, 31, 23, 58, 57, tzinfo=timezone.utc)
        )
    # 2. The single clock command includes all converted date and time parts.
    activation = controller.activate_program_with_commands_for_stove.await_args
    sent_commands = activation.args[4]
    clock_values = [(command.SensorId, command.Value) for command in sent_commands]
    assert activation.args[2] == "config-Orodatario"
    assert clock_values[:7] == [
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
    """Make the sync button use the current time rather than a stored or guessed time."""
    # 1. Fix "now" to an example time so the expected result is predictable.
    item = entity(entities, "button", MczTimeSyncButtonEntity)
    now = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    with (
        patch("custom_components.maestro_mcz.button.dt_util.utcnow", return_value=now),
        patch.object(
            item._mcz_date_time_entity, "async_set_value", new_callable=AsyncMock
        ) as set_value,
    ):
        # 2. Press the clock-sync button.
        await item.async_press()
    # 3. The clock setter receives that exact time and schedules a reading refresh.
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
    """Display a known fan preset from its reported value without guessing unknown presets."""
    # 1. Two names share value 6; the first declared name should win.
    item = entity(entities, "fan")
    item._current_fan_configuration.configuration.mappings = {
        "auto": 6,
        "boost": 7,
        "alternate_auto": 6,
    }
    # 2. Give the fan a numeric, text, unknown, or missing value from the test table.
    stove.Status.set_vent_v1 = value
    item._handle_coordinator_update_internal()
    assert item.preset_mode == expected


@pytest.mark.parametrize("flag", [False, True])
async def test_date_time_command_preserves_am_pm_flag(entities, controller, flag):
    """Preserve the stove's AM/PM flag as a boolean when setting its clock."""
    # 1. Choose the flag the stove should receive.
    item = entity(entities, "datetime")
    item._attr_am_pm = flag
    await item.async_set_value(datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc))
    # 2. Read the AM/PM command from the outgoing clock update.
    activation = controller.activate_program_with_commands_for_stove.await_args
    commands = activation.args[4]
    am_pm_command = next(command for command in commands if command.SensorId == "id-am_pm")
    assert am_pm_command.Value is flag


async def test_generation_one_date_time_optional_components(
    coordinator, stove, controller
):
    """Set an older stove's clock even when weekday, seconds, and AM/PM controls are absent."""
    from custom_components.maestro_mcz.datetime import MczDateTimeEntity

    # 1. Describe an M1 clock without its optional components.
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
    # 2. Reading the clock should leave unsupported parts empty.
    assert item.native_value.second == 0
    assert item.weekday is None
    assert item.am_pm is None
    # 3. Setting the clock must send only the components this model supports.
    await item.async_set_value(datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc))
    activation = controller.activate_program_with_commands_for_stove.await_args
    commands = activation.args[4]
    assert {command.SensorId for command in commands} == {
        "id-anno",
        "id-mese",
        "id-giorno",
        "id-ore",
        "id-minuti",
    }


async def test_date_time_missing_fields_and_configuration(entities, stove, controller):
    """Clear an unreadable clock and avoid setting it without a valid command description."""
    # 1. Remove the stove's clock readings.
    item = entity(entities, "datetime")
    stove._status = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert item.native_value is None
    assert item.weekday is None
    assert item.am_pm is None

    # 2. Remove the clock's command description before trying to set a new time.
    item._date_time_configuration = None
    await item.async_set_value(datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc))
    # 3. No unaddressed clock command may be sent.
    controller.activate_program_with_commands_for_stove.assert_not_awaited()


def test_fan_string_preset_state_fallback_and_missing_value(entities, stove):
    """Read a fan preset from fallback data, but clear it when that reading disappears."""
    # 1. Remove status data and put a preset in the alternate state response.
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
    # 2. Remove the fan reading; the previous preset must not remain on screen.
    stove._state = SimpleNamespace(mode="manual")
    item._handle_coordinator_update_internal()
    assert item.is_on is False
    assert item.preset_mode is None
    assert item.percentage is None


def test_selector_state_fallback_and_missing_value(entities, stove):
    """Use fallback power readings and clear a dropdown choice when no valid reading exists."""
    # 1. Supply a power level only in the alternate state response.
    item = next(selector for selector in entities["select"] if selector._prop == "set_pot_man")
    stove._status = SimpleNamespace()
    stove._state = SimpleNamespace(set_pot_man=4)
    item._handle_coordinator_update_internal()
    assert item.current_option == "4"
    # 2. Remove that reading, then also try an unsupported value type.
    stove._state = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert item.current_option is None
    item._selector_configuration.configuration.type = "string"
    item._handle_coordinator_update_internal()
    assert item.current_option is None


async def test_controls_without_configuration_do_not_send_commands(
    entities, controller
):
    """Do nothing safely when control descriptions are missing, avoiding guessed stove commands."""
    # 1. Remove each control's model description before asking it to act.
    number_control = entity(entities, "number")
    number_control._number_configuration = None
    await number_control.async_set_native_value(10)

    selector = entity(entities, "select")
    selector._selector_configuration = None
    await selector.async_select_option("3")

    switch = entity(entities, "switch")
    switch._switch_configuration = None
    await switch.async_turn_on()
    await switch.async_turn_off()

    alarm_button = entity(entities, "button", MczButtonEntity)
    alarm_button._button_configuration = None
    await alarm_button.async_press()

    time_sync_button = entity(entities, "button", MczTimeSyncButtonEntity)
    time_sync_button._time_sync_button_configuration = None
    await time_sync_button.async_press()

    heating_control = entity(entities, "climate")
    heating_control._power_configuration = None
    heating_control._thermostat_configuration = None
    heating_control._climate_function_mode_configuration = None
    await heating_control.async_set_hvac_mode(HVACMode.OFF)
    await heating_control.async_set_temperature(temperature=22)
    await heating_control.async_set_preset_mode("auto")

    fan_control = entity(entities, "fan")
    fan_control._current_fan_configuration = None
    fan_control._attr_speed_count = 0
    await fan_control.async_turn_on()
    await fan_control.async_turn_off()
    await fan_control.async_set_percentage(100)
    await fan_control.async_set_preset_mode("auto")
    # 2. None of these actions may send a command without its required description.
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
    """Use a genuine alternate reading when status explicitly reports no value."""
    # 1. The status field is empty while the state field contains a reading.
    assert getattr(stove.Status, prop) is None
    assert getattr(stove.State, prop) == expected
    item = next(
        control for control in entities[platform] if getattr(control, "_prop", None) == prop
    )
    assert getattr(item, value_property) == expected
    # 2. If the alternate reading also disappears, the displayed value must clear.
    setattr(stove.State, prop, None)
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) is None


async def setup_binary_sensors(hass, entry):
    """Set up the binary sensor platform and return the controls it creates."""
    module = importlib.import_module("custom_components.maestro_mcz.binary_sensor")
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    return add_entities.call_args.args[0]


@pytest.mark.parametrize("probe_reading", [True, False])
async def test_pellet_level_low_appears_only_when_stove_reports_its_probe(
    hass, entry, coordinator, stove, probe_reading
):
    """Show the pellet warning only on stoves that send a probe reading, not on every stove."""
    # 1. Our example stove sends no pellet probe reading.
    assert stove.Status.sens_liv_pel is None
    controls_without_probe = await setup_binary_sensors(hass, entry)
    ids_without_probe = {control.unique_id for control in controls_without_probe}
    assert "SERIAL-001-sens_liv_pel" not in ids_without_probe
    # 2. The stove now sends a reading from its pellet level probe.
    stove.Status.sens_liv_pel = probe_reading
    controls_with_probe = await setup_binary_sensors(hass, entry)
    ids_with_probe = {control.unique_id for control in controls_with_probe}
    # 3. The pellet warning appears, and the existing alarm keeps its ID.
    assert "SERIAL-001-sens_liv_pel" in ids_with_probe
    assert "SERIAL-001-is_in_error" in ids_with_probe


@pytest.mark.parametrize(
    "probe_reading,expected_warning",
    [
        (True, False),  # enough pellets: no warning
        (False, True),  # reserve reached: the stove beeps, so warn
        (None, None),  # no reading: unknown, never a guessed warning
    ],
)
async def test_pellet_level_low_turns_on_when_the_reserve_is_reached(
    hass, entry, coordinator, stove, probe_reading, expected_warning
):
    """Turn the warning on exactly when the probe reports that pellets are running out."""
    # 1. Start with a stove that has a pellet level probe.
    stove.Status.sens_liv_pel = True
    controls = await setup_binary_sensors(hass, entry)
    pellet_warning = next(
        control for control in controls if getattr(control, "_prop", None) == "sens_liv_pel"
    )
    # 2. The probe sends a new reading (or none at all).
    stove.Status.sens_liv_pel = probe_reading
    pellet_warning._handle_coordinator_update_internal()
    # 3. The warning follows the probe, inverted: False from the probe means "low".
    assert pellet_warning.is_on is expected_warning
