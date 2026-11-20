"""Cloud entity discovery, state, availability, IDs and commands on all platforms."""

import importlib
import json
from dataclasses import asdict
from datetime import UTC, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.climate import ClimateEntityFeature, HVACAction, HVACMode
from homeassistant.components.fan import FanEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.exceptions import HomeAssistantError
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
from custom_components.maestro_mcz.fan import (
    MczFanEntity,
    get_supported_fan_configurations,
)
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)
from custom_components.maestro_mcz.maestro.controller.responses.model import (
    Configuration,
    ModelConfiguration,
    SensorConfiguration,
)
from custom_components.maestro_mcz.maestro.controller.responses.state import State
from custom_components.maestro_mcz.maestro.controller.responses.status import Status
from custom_components.maestro_mcz.maestro.model_value_reader import (
    get_response_value,
    read_response_value,
)
from custom_components.maestro_mcz.maestro.models import model_definitions, models_types
from custom_components.maestro_mcz.maestro.types.enums import SensorTypeEnum


@pytest.mark.parametrize("uppercase", [False, True])
async def test_both_advertised_button_bindings_preserve_ids_and_commands(
    hass, entry, coordinator, stove, configuration, controller, uppercase
):
    """Keep both advertised reset controls distinct, even with the default generation."""
    # 1. A model without a ping advertises both concrete reset command names.
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": "Reset Allarme",
                "ConfigurationId": "reset-group",
                "Timed": False,
                "Limitations": None,
                "Configurations": [
                    configuration(
                        name,
                        SensorTypeEnum.BOOLEAN.value,
                        SensorName=name.upper() if uppercase else name,
                    )
                    for name in ["m1_com_reset_allarm", "com_reset_allarm"]
                ],
            }
        )
    ]
    assert stove.model_generation is models_types.MczStoveModelGeneration.M2_PLUS

    # 2. Discover buttons from the one shared definition, then press each one.
    module = importlib.import_module("custom_components.maestro_mcz.button")
    added = Mock()
    await module.async_setup_entry(hass, entry, added)
    buttons = [
        entity for entity in added.call_args.args[0] if entity.name == "Alarm Reset"
    ]
    commands = []
    for button in buttons:
        controller.activate_program_with_commands_for_stove.reset_mock()
        await button.async_press()
        activation = controller.activate_program_with_commands_for_stove.await_args
        command = activation.args[4][0]
        commands.append((activation.args[2], command.SensorId, command.Value))

    # 3. Preserve M2-first ordering, concrete unique IDs and both exact command routes.
    assert [button.unique_id for button in buttons] == [
        f"{stove.UniqueCode}-com_reset_allarm",
        f"{stove.UniqueCode}-m1_com_reset_allarm",
    ]
    assert commands == [
        ("reset-group", "id-com_reset_allarm", True),
        ("reset-group", "id-m1_com_reset_allarm", True),
    ]


@pytest.mark.parametrize(
    "control_name,older_names,expected",
    [
        ("newer", None, "auto"),
        ("older", None, "auto"),
        ("older", {}, "dynamic"),
        ("OLDER", {"dynamic": "turbo"}, "turbo"),
    ],
)
async def test_shared_climate_definition_uses_matched_command_names(
    coordinator,
    stove,
    configuration,
    controller,
    monkeypatch,
    control_name,
    older_names,
    expected,
):
    """Use each stove's display names without rewriting settings shared with other stoves."""
    # 1. Both generations share names unless the older control explicitly overrides them.
    power = stove.get_first_supported_sensor_configuration(
        model_definitions.supported_power_settings
    )
    definition = models_types.ClimateFunctionModeMczConfigItem(
        "Mode",
        "mod_lav_att",
        None,
        "set_mod",
        True,
        api_mappings_key_rename={"dynamic": "auto"},
        sensor_set_name_m1="older",
        sensor_set_name_m2="newer",
        api_mappings_key_rename_m1=older_names,
    )
    original_definition = asdict(definition)
    monkeypatch.setattr(
        model_definitions, "supported_climate_function_modes", [definition]
    )
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": "set_mod",
                "ConfigurationId": "mode-group",
                "Timed": False,
                "Limitations": None,
                "Configurations": [
                    configuration(
                        control_name,
                        Variants=["manual", "dynamic"],
                        Mappings={"manual": 0, "dynamic": 1},
                    )
                ],
            }
        )
    ]
    stove.Status.mod_lav_att = "dynamic"

    # 2. Create the heating control and select the mode shown to this stove's user.
    climate = MczClimateEntity(coordinator, stove.UniqueCode, *power)
    await climate.async_set_preset_mode(expected)
    command = last_sent_command(controller)

    # 3. Labels, reading and command agree, while the shared declaration is unchanged.
    assert climate.preset_modes == ["manual", expected]
    assert climate.preset_mode == expected
    assert command.SensorId == f"id-{control_name}"
    assert command.Value == 1
    assert asdict(definition) == original_definition


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


@pytest.fixture
def m1_mode_stove(stove, configuration):
    """Provide an M1 stove exposing both mode commands, as the affected cloud model does."""
    sensor_names = {
        "com_on_off": "m1_stato_stufa",
        "mod_funz": "m1_mod_lav_att",
        "set_vent_v1": "m1_set_vent_v1",
        "cod_for_spe_mqtt": "m1_cod_for_spe_mqtt",
    }
    for group in stove.Model.model_configurations:
        if group.configuration_name == "cod_for_spe_mqtt":
            group.configuration_name = "PING STOVE"
            group.configurations[0].mappings = {
                "C|RecuperoParametri": 0,
                "C|RecuperoInfo": 1,
            }
        elif group.configuration_name == "Auto":
            group.configuration_name = "Dynamic"
            group.configurations[0].enabled = True
        elif group.configuration_name == "set_mod":
            group.configurations[0].variants.extend(["overnight", "power"])
            group.configurations[0].mappings.update({"overnight": 3, "power": 4})
        for sensor in group.configurations:
            if sensor.sensor_name in sensor_names:
                sensor.sensor_name = sensor_names[sensor.sensor_name]
                sensor.sensor_id = f"id-{sensor.sensor_name}"
    stove.Model.model_configurations.append(
        ModelConfiguration(
            {
                "ConfigurationName": "Cambio_mod_2MOD",
                "ConfigurationId": "legacy-mode-config",
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration("m1_automode", "boolean")],
            }
        )
    )
    stove.Model.model_configurations.append(
        ModelConfiguration(
            {
                "ConfigurationName": "Ricetta Pellet",
                "ConfigurationId": "legacy-recipe-config",
                "Timed": False,
                "Limitations": None,
                "Configurations": [
                    configuration(
                        "m1_mod_lav_att",
                        Variants=["manual", "dynamic", "overnight", "comfort", "power"],
                        Mappings={
                            "manual": 10,
                            "dynamic": 11,
                            "overnight": 12,
                            "comfort": 13,
                            "power": 14,
                        },
                    )
                ],
            }
        )
    )
    stove.Status.sm_vs_bootloader = "1.2"
    return stove


@pytest.fixture(
    params=[
        models_types.MczStoveModelGeneration.M1,
        models_types.MczStoveModelGeneration.M2_PLUS,
    ],
    ids=["older", "newer"],
)
def hydro_stove(stove, configuration, request):
    """Describe a hydro stove whose room fan appears in several control groups.

    The direct room-fan group lacks presets, while the boiler group exposes
    Auto and Silent. Distinct command IDs reveal which group receives changes.
    """
    fan_sensor_name = "set_vent_v1"
    if request.param is models_types.MczStoveModelGeneration.M1:
        fan_sensor_name = "m1_set_vent_v1"
    stove.Model.model_name = "Synthetic Hydro Stove - 1 Fan"
    stove.State.mode = None
    stove.Status.mod_lav_att = None
    stove.State.conf_imp = 1
    stove.Model.model_configurations = [
        group
        for group in stove.Model.model_configurations
        if group.configuration_name not in {"Manuale", "Auto", "set_mod"}
    ]
    for group_name in (
        "PUFFER",
        "BOILER",
        "ACQUA_SANITARIA",
        "CALDAIA_STUFA",
        "set_vent_room",
    ):
        variants = ["auto", "silent"]
        mappings = {"auto": 6, "silent": -1}
        if group_name == "set_vent_room":
            variants = []
            mappings = {}
        stove.Model.model_configurations.append(
            ModelConfiguration(
                {
                    "ConfigurationName": group_name,
                    "ConfigurationId": f"config-{group_name}",
                    "Timed": False,
                    "Limitations": None,
                    "Configurations": [
                        configuration(
                            fan_sensor_name,
                            SensorId=f"fan-sensor-{group_name}",
                            Min="0",
                            Max="5",
                            Variants=variants,
                            Mappings=mappings,
                        )
                    ],
                }
            )
        )
    return stove


@pytest.fixture
async def hydro_fans(hass, entry, coordinator, hydro_stove):
    """Discover hydro ventilation through the real Home Assistant fan platform."""
    module = importlib.import_module("custom_components.maestro_mcz.fan")
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    return add_entities.call_args.args[0]


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
            assert item.device_info.identifiers == {("maestro_mcz", "SERIAL-001")}


def test_catalogue_icons_cover_every_custom_entity_and_temperature_defaults():
    """Keep every catalogue variant linked to an icon or its unchanged temperature default."""
    # 1. Load the frontend icons alongside every catalogue that creates entities.
    icons = json.loads(
        Path("custom_components/maestro_mcz/icons.json").read_text(encoding="utf-8")
    )["entity"]
    catalogues = {
        "binary_sensor": model_definitions.supported_binary_sensors,
        "button": [
            *model_definitions.supported_buttons,
            *model_definitions.supported_time_sync_buttons,
        ],
        "datetime": model_definitions.supported_date_times,
        "number": model_definitions.supported_numbers,
        "select": [
            *model_definitions.supported_selectors,
            *model_definitions.supported_pots,
        ],
        "sensor": [
            *model_definitions.supported_sensors,
            *model_definitions.supported_system_info_sensors,
            *model_definitions.supported_counters,
        ],
        "switch": model_definitions.supported_switches,
    }

    # 2. Each custom icon is reachable; ordinary temperature readings retain HA defaults.
    for domain, definitions in catalogues.items():
        for definition in definitions:
            if definition.translation_key is None:
                assert domain == "sensor"
                assert definition.device_class == "temperature"
            else:
                assert icons[domain][definition.translation_key]["default"]
            assert not hasattr(definition, "icon")
            assert not hasattr(definition, "unavailable_icon")

    # 3. Shared fan/climate icons retain their presets without backend icon fields.
    for definition in model_definitions.supported_fans:
        assert not hasattr(definition, "icon")
        assert not hasattr(definition, "unavailable_icon")
    climate_presets = icons["climate"]["main_climate"]["state_attributes"][
        "preset_mode"
    ]
    assert set(climate_presets["state"]) == {
        "manual",
        "auto",
        "overnight",
        "comfort",
        "turbo",
    }
    fan_presets = icons["fan"]["main_fan"]["state_attributes"]["preset_mode"]
    assert set(fan_presets["state"]) == {"auto", "silent"}


@pytest.mark.parametrize("prop,value", [("state", "working"), ("mode", "manual")])
async def test_operating_sensors_are_regular_entities(
    hass, entry, coordinator, stove, prop, value
):
    """Show everyday operating readings as regular sensors without changing their IDs or values."""
    # 1. Give the information response an operating reading to discover.
    setattr(stove.State, prop, value)
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
    """Put alarm reset under Configuration on both stove generations without changing its command."""
    # 1. Give the stove the alarm-reset command used by this generation.
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
    """Avoid unsupported controls while retaining connection indicators and known firmware."""
    # 1. Remove all supported controls and available readings from the model.
    stove.Model.model_configurations = []
    stove._state = SimpleNamespace()
    stove._status = SimpleNamespace()
    stove.device_metadata.update_from_status(
        None, stove.SensorSetTypeId, stove.model_generation
    )
    stove._is_stove_connected_to_cloud = False
    module = importlib.import_module(f"custom_components.maestro_mcz.{platform}")
    # 2. Set up the selected HA platform for this empty model.
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    discovered_entities = add_entities.call_args.args[0]
    # 3. Connection indicators and already known firmware do not invent new readings.
    if platform == "binary_sensor":
        assert len(discovered_entities) == 2
    elif platform == "sensor":
        assert len(discovered_entities) == 1
        firmware_sensor = discovered_entities[0]
        assert firmware_sensor.unique_id == "SERIAL-001-sm_vs_app"
        assert firmware_sensor.native_value == "DM2.AIR.01.02.003"
        assert not firmware_sensor.available
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
            control,
            (MczCloudStatusBinarySensorEntity, MczStoveStatusBinarySensorEntity),
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
def test_declared_response_and_missing_values(
    entities, stove, platform, prop, value_property, value
):
    """Use each control's declared response, preserving zero and False without guessing."""
    # 1. Give the preferred response a reading and the other response a different one.
    item = next(
        control
        for control in entities[platform]
        if getattr(control, "_prop", None) == prop
    )
    primary = "_state" if platform == "sensor" else "_status"
    secondary = "_status" if platform == "sensor" else "_state"
    setattr(stove, primary, SimpleNamespace(**{prop: value}))
    setattr(stove, secondary, SimpleNamespace(**{prop: "other response"}))
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) == value
    # 2. A missing preferred reading must not substitute an unrelated response.
    setattr(stove, primary, SimpleNamespace())
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) is None
    # 3. Without either reading, show no value instead of an old or guessed value.
    setattr(stove, secondary, SimpleNamespace())
    item._handle_coordinator_update_internal()
    assert getattr(item, value_property) is None


@pytest.mark.parametrize(
    "source,state_value,status_value,expected",
    [
        (models_types.MczResponseSource.STATUS, 12, 0, 0),
        (models_types.MczResponseSource.STATE, 0, 12, 0),
        (models_types.MczResponseSource.STATUS, True, False, False),
        (models_types.MczResponseSource.STATE, False, True, False),
        (models_types.MczResponseSource.STATUS, None, None, None),
        (models_types.MczResponseSource.STATUS, 12, None, None),
        (models_types.MczResponseSource.STATE, None, 12, None),
    ],
)
def test_response_source_preserves_values_without_fallback(
    source, state_value, status_value, expected
):
    """Read only the chosen response, preserving zero, false and missing readings."""
    # 1. Parse simultaneous endpoint replies with deliberately different readings.
    sensor_name = "att_eco" if isinstance(status_value, bool) else "set_amb1"
    state = State({sensor_name: state_value})
    status = Status({sensor_name: status_value})

    # 2. Read the setting from the one declared response.
    reading = read_response_value(source, state, status, sensor_name)

    # 3. Preserve the chosen value rather than substituting a truthy alternative.
    assert reading == expected
    assert type(reading) is type(expected)


@pytest.mark.parametrize("source", list(models_types.MczResponseSource))
def test_response_policy_handles_absent_endpoint_caches(source):
    """An absent response must not produce a made-up setting or a stale reading."""
    # 1. Neither endpoint has supplied a response.
    state = None
    status = None

    # 2. Read the setting with each supported source policy.
    reading = read_response_value(source, state, status, "set_vent_v1")

    # 3. Missing caches remain unknown rather than becoming display strings.
    assert reading is None


@pytest.mark.parametrize(
    "status_present,status_value,state_value,expected",
    [(False, None, 0, None), (True, None, 2, None), (True, False, 2, False)],
)
def test_older_tones_do_not_stringify_null_or_use_another_response(
    status_present, status_value, state_value, expected
):
    """Leave missing tones unknown rather than showing another reply or the word None."""
    # 1. Supply conflicting replies with missing or empty tone settings.
    state = SimpleNamespace(toni_buzz=state_value)
    status = SimpleNamespace()
    if status_present:
        status.toni_buzz = status_value
    tones = next(
        item
        for item in model_definitions.supported_selectors
        if item.sensor_get_name == "toni_buzz"
    )

    # 2. Resolve the control's single declared response.
    reading = get_response_value(
        tones, state, status, models_types.MczStoveModelGeneration.M1
    )

    # 3. Keep False as a reading, while absent and null values stay unknown.
    assert reading == expected
    assert type(reading) is type(expected)


def test_unconfigured_response_name_is_not_guessed():
    """Reject an incomplete control definition instead of displaying another setting."""
    # 1. A definition has no response property to identify its reading.
    control = models_types.MczConfigItem(
        "Incomplete control", models_types.MczStoveModelGeneration.M1
    )
    state = State({"set_amb1": 18})
    status = Status({"set_amb1": 22})

    # 2. Reading it must report the configuration error rather than inventing a source.
    with pytest.raises(ValueError, match="requires a sensor name"):
        get_response_value(control, state, status)


@pytest.mark.parametrize("value", [0, None])
async def test_current_control_and_information_temperatures_have_distinct_sources(
    hass, entry, coordinator, hydro_stove, value
):
    """Use current readings for heating and the generation-specific source for information."""
    # 1. Discover controls while both endpoint replies contain different temperatures.
    hydro_stove.State.temp_amb_install = 17
    hydro_stove.Status.temp_amb_install = 20
    sensor_module = importlib.import_module("custom_components.maestro_mcz.sensor")
    climate_module = importlib.import_module("custom_components.maestro_mcz.climate")
    add_sensors = Mock()
    add_climates = Mock()
    await sensor_module.async_setup_entry(hass, entry, add_sensors)
    await climate_module.async_setup_entry(hass, entry, add_climates)
    ambient = next(
        sensor
        for sensor in add_sensors.call_args.args[0]
        if sensor._prop == "temp_amb_install"
    )
    heating = add_climates.call_args.args[0][0]

    # 2. Update the current reading and target, leaving the information reply distinct.
    hydro_stove.Status.temp_amb_install = value
    hydro_stove.Status.set_amb1 = 25
    hydro_stove.State.set_amb1 = 29
    ambient._handle_coordinator_update_internal()
    heating._handle_coordinator_update_internal()

    # 3. Heating uses Status; the older information view does too, unlike the newer one.
    expected_information = 17
    if hydro_stove.model_generation is models_types.MczStoveModelGeneration.M1:
        expected_information = value
    assert ambient.native_value == expected_information
    assert heating.native_current_temperature == value
    assert heating.native_target_temperature == 25


@pytest.mark.parametrize("mode_field", ["mod_lav_att", "configured_mode"])
def test_fan_uses_status_mode_without_rewriting_information_or_original_helper(
    entities, stove, monkeypatch, mode_field
):
    """Use the fan's configured mode field without mutating the separate information reply."""
    # 1. Only the configured field reports Manual; other replies are unfamiliar.
    fan = entity(entities, "fan")
    monkeypatch.setattr(fan._supported_fan, "mode_sensor_get_name", mode_field)
    stove.State.mode = "unrecognized"
    stove.Status.mod_lav_att = "unrecognized"
    setattr(stove.Status, mode_field, "manual")

    # 2. Refresh through the audited caller, retaining the original helper unchanged.
    with patch.object(fan, "async_write_ha_state"):
        fan._handle_coordinator_update()

    # 3. Use Manual's settings without rewriting State or changing the helper's result.
    assert fan.available
    assert fan.speed_count == 5
    assert stove.State.mode == "unrecognized"
    assert fan._get_configuration_for_current_stove_mode() is None

    # 4. Missing current mode does not substitute the information response.
    setattr(stove.Status, mode_field, None)
    stove.State.mode = "manual"
    with patch.object(fan, "async_write_ha_state"):
        fan._handle_coordinator_update()
    assert not fan.available
    assert fan._get_configuration_for_current_stove_mode() is not None


def test_fan_missing_reading_and_silent_flag_do_not_use_information_fallback(
    entities, stove
):
    """Do not mistake missing fan data for an enabled fan or another reply's silent setting."""
    # 1. Information disagrees with the current response about silence and speed.
    fan = entity(entities, "fan")
    stove.State.silent_enabled = True
    stove.State.set_vent_v1 = 5
    stove.Status.silent_enabled = False
    stove.Status.set_vent_v1 = 0

    # 2. Refresh the fan using current control data.
    fan._handle_coordinator_update_internal()

    # 3. False and zero remain genuine readings rather than falling through.
    assert fan.available
    assert fan.is_on is False
    stove.Status.set_vent_v1 = None
    fan._handle_coordinator_update_internal()
    assert fan.is_on is False
    assert fan.preset_mode is None


@pytest.mark.parametrize("generation", list(models_types.MczStoveModelGeneration))
def test_probe_and_maintenance_do_not_substitute_another_response(generation):
    """Keep missing selected readings unknown instead of using another response's values."""
    # 1. Only the other response supplies these synthetic information readings.
    state = SimpleNamespace(sondaWifi=0, ore_prox_manut=0)
    status = SimpleNamespace(sondaWifi=None, ore_prox_manut=None)
    probe = next(
        item
        for item in model_definitions.supported_sensors
        if item.sensor_get_name == "sondaWifi"
    )
    maintenance = next(
        item
        for item in model_definitions.supported_sensors
        if item.sensor_get_name == "ore_prox_manut"
    )

    # 2. Read each existing entity's declared generation-specific policy.
    probe_value = get_response_value(probe, state, status, generation)
    maintenance_value = get_response_value(maintenance, state, status, generation)

    # 3. An empty selected response does not fall back to the other response.
    assert probe_value is None
    assert maintenance_value is None
    # 4. Genuine selected zero readings remain visible.
    status.sondaWifi = 0
    status.ore_prox_manut = 0
    assert get_response_value(probe, state, status, generation) == 0
    assert get_response_value(maintenance, state, status, generation) == 0


@pytest.mark.parametrize(
    "generation,status_values,state_values,expected_readings",
    [
        (
            models_types.MczStoveModelGeneration.M1,
            {
                "mod_lav_att": "manual",
                "set_amb1": 22,
                "set_amb2": None,
                "set_amb3": None,
                "set_vent_v1": "auto",
                "temp_min_circ_on": None,
                "toni_buzz": 0,
                "sondaWifi": 255,
                "ore_prox_manut": 937,
                "temp_caldaia": None,
                "temp_puffer": None,
            },
            {"mod_lav_att": "manual", "set_amb1": 22, "last_alarm": None},
            {
                "last_alarm": None,
                "sondaWifi": 255,
                "ore_prox_manut": 937,
                "temp_caldaia": None,
                "temp_puffer": None,
            },
        ),
        (
            models_types.MczStoveModelGeneration.M2_PLUS,
            {
                "mod_lav_att": None,
                "set_amb1": 25,
                "set_amb2": None,
                "set_amb3": None,
                "set_vent_v1": 5,
                "temp_min_circ_on": 45,
                "toni_buzz": 2,
                "sondaWifi": None,
                "ore_prox_manut": 1302,
                "temp_caldaia": 34.7,
                "temp_puffer": 0,
            },
            {
                "mod_lav_att": None,
                "set_amb1": 25,
                "last_alarm": "A99",
                "temp_caldaia": 34.7,
                "temp_puffer": 0,
            },
            {
                "last_alarm": "A99",
                "sondaWifi": None,
                "ore_prox_manut": 1302,
                "temp_caldaia": 34.7,
                "temp_puffer": 0,
            },
        ),
    ],
    ids=["older-air-diagnostic", "newer-hydro-diagnostic"],
)
def test_diagnostic_readings_use_their_declared_response(
    generation, status_values, state_values, expected_readings
):
    """Keep the supplied diagnostic readings intact without treating null fields as values."""
    # 1. Reconstruct a small non-identifying subset of the paired diagnostic replies.
    # The diagnostic's normalized State mode is represented by its original wire name.
    state = State(state_values)
    status = Status(status_values)

    # 2. Read existing controls using their declared response, not field presence alone.
    for sensor_name, expected in expected_readings.items():
        sensor = next(
            item
            for item in model_definitions.supported_sensors
            if item.sensor_get_name == sensor_name
        )
        reading = get_response_value(sensor, state, status, generation)
        assert reading == expected
    tones = next(
        item
        for item in model_definitions.supported_selectors
        if item.sensor_get_name == "toni_buzz"
    )
    pump = next(
        item
        for item in model_definitions.supported_numbers
        if item.sensor_get_name == "temp_min_circ_on"
    )

    # 3. Keep the older zero tones and newer pump value; older absent pump stays unknown.
    assert (
        get_response_value(tones, state, status, generation)
        == status_values["toni_buzz"]
    )
    assert (
        get_response_value(pump, state, status, generation)
        == status_values["temp_min_circ_on"]
    )
    assert state.unknown_fields is None
    assert status.unknown_fields is None


@pytest.mark.parametrize(
    "generation",
    [
        models_types.MczStoveModelGeneration.M1,
        models_types.MczStoveModelGeneration.M2_PLUS,
    ],
)
@pytest.mark.parametrize("sensor_name", ["set_amb2", "set_amb3"])
def test_additional_thermostat_targets_do_not_use_saved_information_values(
    generation, sensor_name
):
    """Keep unused targets unknown until current data supplies a real reading."""
    # 1. Both diagnostics have null current targets and no corresponding State fields.
    status = Status({sensor_name: None})
    state = State({sensor_name: 28}, True)
    thermostat = next(
        item
        for item in model_definitions.supported_thermostats
        if item.sensor_get_name == sensor_name
    )

    # 2. An old saved information value cannot substitute for the absent current target.
    assert get_response_value(thermostat, state, status, generation) is None

    # 3. A synthetic future current reading, including zero, uses the declared field.
    setattr(status, sensor_name, 0)
    assert get_response_value(thermostat, state, status, generation) == 0


async def test_three_fan_capture_targets_do_not_advertise_extra_thermostats(
    hass, entry, coordinator, stove
):
    """Do not infer adjustable extra thermostats from reported default temperatures alone."""
    # 1. Original three-fan captures report 20 for extra targets but configure only target 1.
    stove.Model.model_name = "Air Stove - 3 Fan"
    stove.Status.set_amb2 = 20
    stove.Status.set_amb3 = 20
    assert not hasattr(stove.State, "set_amb2")
    assert not hasattr(stove.State, "set_amb3")

    # 2. Discover climate using the existing enabled model descriptors.
    module = importlib.import_module("custom_components.maestro_mcz.climate")
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    climates = add_entities.call_args.args[0]
    extra_targets = [
        item
        for item in model_definitions.supported_thermostats
        if item.sensor_get_name in {"set_amb2", "set_amb3"}
    ]
    matching_extra_targets = stove.get_supported_sensor_configurations(extra_targets)

    # 3. The configured thermostat remains target 1; reported values are not capabilities.
    assert len(climates) == 1
    assert climates[0]._supported_thermostat.sensor_get_name == "set_amb1"
    assert matching_extra_targets is None


@pytest.mark.parametrize(
    "fan_value,silent_enabled,available",
    [("auto", False, True), (1, True, False)],
    ids=["reported-auto", "whole-stove-silent"],
)
async def test_original_m1_hydro_boiler_descriptor_routes_room_fan(
    hass,
    entry,
    coordinator,
    stove,
    configuration,
    controller,
    fan_value,
    silent_enabled,
    available,
):
    """Use the captured older boiler fan descriptor without inventing mode or ping metadata."""
    # 1. Both original older hydro models have this descriptor and no populated stove ping.
    stove.Model.model_name = "Hydro Stove - 1 Fan"
    stove.Status.sm_vs_bootloader = "1.3"
    stove.Status.mod_lav_att = None
    stove.State.mode = None
    stove.Status.set_vent_v1 = fan_value
    stove.Status.silent_enabled = silent_enabled
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": "BOILER",
                "ConfigurationId": "captured-boiler-test",
                "Timed": False,
                "Limitations": None,
                "Configurations": [
                    configuration(
                        "m1_set_vent_v1",
                        Enabled=True,
                        Min="0",
                        Max="5",
                        Variants=["auto", "silent"],
                        Mappings={"auto": 6, "silent": -1},
                    )
                ],
            }
        )
    ]

    # 2. Discover the fixed fan from its actual sensor and group, not inferred generation.
    module = importlib.import_module("custom_components.maestro_mcz.fan")
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    fans = add_entities.call_args.args[0]
    assert stove.model_generation is models_types.MczStoveModelGeneration.M2_PLUS
    assert len(fans) == 1
    room_fan = fans[0]

    # 3. Preserve advertised bounds/presets, and respect the separate whole-stove silent flag.
    assert (
        room_fan._fixed_fan_configuration.configuration.sensor_name == "m1_set_vent_v1"
    )
    assert room_fan.name == "Room Fan"
    assert room_fan.speed_count == 5
    assert room_fan.preset_modes == ["auto", "silent"]
    assert room_fan.available is available
    if available:
        assert room_fan.preset_mode == "auto"
        # 4. Send the advertised preset name through the existing path, not a guessed numeric command.
        await room_fan.async_set_preset_mode("silent")
        command = last_sent_command(controller)
        activation = controller.activate_program_with_commands_for_stove.await_args
        assert command.SensorId == "id-m1_set_vent_v1"
        assert command.Value == "silent"
        assert (
            room_fan._current_fan_configuration.configuration.mappings["silent"] == -1
        )
        assert activation.args[2] == "captured-boiler-test"


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


@pytest.mark.parametrize(
    "sensor_name",
    ["m1_temp_min_circ_on", "temp_min_circ_on"],
    ids=["older", "newer"],
)
@pytest.mark.parametrize(
    "status_payload,state_value,expected",
    [
        (None, 45, None),
        ({}, 45, None),
        ({"temp_min_circ_on": None}, 45, None),
        ({"temp_min_circ_on": 55}, 45, 55),
        ({"temp_min_circ_on": 0}, 45, 0),
        ({}, 0, None),
        ({}, None, None),
        (None, None, None),
    ],
    ids=[
        "missing-status",
        "missing-status-reading",
        "null-status-reading",
        "status-priority",
        "zero-status-priority",
        "zero-state-does-not-substitute",
        "neither-reading",
        "neither-response-reading",
    ],
)
async def test_pump_activation_temperature_readback(
    hass,
    entry,
    coordinator,
    stove,
    configuration,
    sensor_name,
    status_payload,
    state_value,
    expected,
):
    """Read each generation's pump setting from Status and never substitute information data."""
    # 1. The stove exposes its pump threshold as an adjustable number.
    expected_generation = models_types.MczStoveModelGeneration.M2_PLUS
    if sensor_name == "m1_temp_min_circ_on":
        expected_generation = models_types.MczStoveModelGeneration.M1
        ping = next(
            group
            for group in stove.Model.model_configurations
            if group.configuration_name == "cod_for_spe_mqtt"
        )
        ping.configuration_name = "PING STOVE"
        ping.configurations[0].sensor_name = "m1_cod_for_spe_mqtt"
    stove.Status.temp_min_circ_on = 60
    stove.Model.model_configurations.append(
        ModelConfiguration(
            {
                "ConfigurationName": "temp_avanzate",
                "ConfigurationId": "config-pump-temperature",
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration(sensor_name, Min="0", Max="80")],
            }
        )
    )
    module = importlib.import_module("custom_components.maestro_mcz.number")
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    discovered_numbers = add_entities.call_args.args[0]
    pump_temperature = next(
        number for number in discovered_numbers if number._prop == "temp_min_circ_on"
    )
    assert stove.model_generation is expected_generation
    assert pump_temperature.native_value == 60
    # 2. Parse the cloud readings and refresh the displayed pump threshold.
    stove._status = Status(status_payload) if status_payload is not None else None
    stove._state = State({"temp_min_circ_on": state_value})
    pump_temperature._handle_coordinator_update_internal()
    # 3. Keep a genuine Status zero, but clear a missing current reading.
    assert pump_temperature.native_value == expected
    # 4. Even an old saved State reading must not restore the unsupported fallback.
    stove._state = State({"temp_min_circ_on": state_value}, True)
    pump_temperature._handle_coordinator_update_internal()
    assert pump_temperature.native_value == expected


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
    """Keep recognizable power choices and send the selected power level as a number."""
    # 1. The stove supports five power levels and currently reports level three.
    item = next(selector for selector in entities["select"] if selector._prop == "set_pot_man")
    assert item.options == ["1", "2", "3", "4", "5"]
    assert item.current_option == "3"
    # 2. Selecting the text label "5" sends numeric power level 5.
    await item.async_select_option("5")
    command = last_sent_command(controller)
    # 3. The stove receives a number and the control points to its frontend icons.
    assert command.Value == 5
    assert item.translation_key == "manual_power"
    assert item.icon is None


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
    "platform,action,arguments",
    [
        ("climate", "async_set_temperature", {"temperature": 23}),
        ("climate", "async_set_hvac_mode", {"hvac_mode": HVACMode.OFF}),
        ("climate", "async_set_preset_mode", {"preset_mode": "auto"}),
        ("fan", "async_turn_on", {}),
        ("fan", "async_turn_off", {}),
        ("fan", "async_set_percentage", {"percentage": 40}),
        ("fan", "async_set_preset_mode", {"preset_mode": "auto"}),
        ("number", "async_set_native_value", {"value": 20}),
        ("switch", "async_turn_on", {}),
        ("switch", "async_turn_off", {}),
        ("select", "async_select_option", {"option": "High"}),
        ("button", "async_press", {}),
        (
            "datetime",
            "async_set_value",
            {
                "value": datetime(2026, 12, 31, 23, 58, tzinfo=UTC),
            },
        ),
    ],
)
@pytest.mark.parametrize(
    "failure_type", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_user_commands_report_terminal_ha_errors(
    entities, controller, coordinator, entry, platform, action, arguments, failure_type
):
    """Explain failed controls in HA and request a new password only for rejected credentials."""
    # 1. Select a usable control whose controller has already reported final failure.
    item = entity(entities, platform)
    if platform == "button":
        item = entity(entities, platform, MczButtonEntity)
    if platform == "select":
        item = next(
            control for control in entities[platform] if control._prop == "toni_buzz"
        )
    if platform == "fan" and action == "async_set_preset_mode":
        fan_configuration = item._current_fan_configuration.configuration
        fan_configuration.variants = ["auto"]
        fan_configuration.mappings = {"auto": 6}
        item._update_features_based_on_current_stove_mode()
    failure = failure_type("service unavailable")
    command = controller.activate_program_with_commands_for_stove
    command.side_effect = failure

    # 2. Try the setting as a user would, without launching a real sign-in flow.
    with (
        patch.object(type(entry), "async_start_reauth") as start_reauth,
        pytest.raises(HomeAssistantError) as raised,
    ):
        await getattr(item, action)(**arguments)

    # 3. Platforms translate the final failure without adding retries or a success refresh.
    reported_error = raised.value
    assert reported_error.__cause__ is failure
    assert reported_error.translation_domain == "maestro_mcz"
    if failure_type is MaestroAuthenticationException:
        assert reported_error.translation_key == "command_invalid_auth"
        start_reauth.assert_called_once_with(coordinator.hass)
    else:
        assert reported_error.translation_key == "command_cannot_connect"
        assert reported_error.translation_placeholders == {
            "error": "service unavailable"
        }
        start_reauth.assert_not_called()
    command.assert_awaited_once()
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


def test_climate_uses_default_generation_without_ping_controls(entities, stove):
    """Continue interpreting newer-model readings when no identifying controls are available."""
    # 1. A previously recognized stove now exposes an unfamiliar control layout.
    item = entity(entities, "climate")
    assert item.hvac_action == HVACAction.HEATING
    stove.Model.model_configurations.clear()

    # 2. Process the same readings using the default generation.
    item._handle_coordinator_update_internal()

    # 3. Missing ping information still uses the M2+ heating interpretation.
    assert stove.model_generation is models_types.MczStoveModelGeneration.M2_PLUS
    assert item.hvac_mode == HVACMode.HEAT
    assert item.hvac_action == HVACAction.HEATING


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
    stove.Status.mod_lav_att = "dynamic"
    item._handle_coordinator_update_internal()
    assert item.preset_mode == "auto"


@pytest.mark.parametrize(
    "bootloader,legacy",
    [
        ("1.2", True),
        ("1.2.9", True),
        ("1.3", False),
        ("1.10", False),
        ("2.0", False),
        (None, False),
        ("", False),
        ("unknown", False),
        ("1", False),
        ("1.2beta", False),
    ],
)
async def test_m1_mode_commands_follow_bootloader(
    m1_mode_stove, coordinator, controller, bootloader, legacy, caplog
):
    """Keep all advertised modes and send each through the control supported by its stove version."""
    # 1. Standard and older controls exist, and the cloud advertises five modes.
    stove = m1_mode_stove
    stove.Status.sm_vs_bootloader = bootloader
    power = stove.get_first_supported_sensor_configuration(
        model_definitions.supported_power_settings
    )

    # 2. Create the heating control and switch in both directions.
    item = MczClimateEntity(coordinator, stove.UniqueCode, *power)
    assert item.supported_features & ClimateEntityFeature.PRESET_MODE
    assert item.preset_modes == ["manual", "auto", "comfort", "overnight", "turbo"]
    if legacy:
        expected_sensor = "id-m1_automode"
        expected_configuration = "legacy-mode-config"
        expected_values = [True, False]
    else:
        expected_sensor = "id-m1_mod_lav_att"
        expected_configuration = "config-set_mod"
        expected_values = [1, 0]
    for preset, expected_value in zip(("auto", "manual"), expected_values):
        await item.async_set_preset_mode(preset)

        # 3. Send the correct sensor, group and exact value type to the cloud.
        command = last_sent_command(controller)
        assert command.SensorId == expected_sensor
        assert command.Value == expected_value
        assert type(command.Value) is type(expected_value)
        activation = controller.activate_program_with_commands_for_stove.await_args
        assert activation.args[2] == expected_configuration
    for preset, reported_mode, standard_value, legacy_value in (
        ("comfort", "comfort", 2, 13),
        ("overnight", "overnight", 3, 12),
        ("turbo", "power", 4, 14),
    ):
        await item.async_set_preset_mode(preset)
        command = last_sent_command(controller)
        assert command.SensorId == "id-m1_mod_lav_att"
        expected_value = legacy_value if legacy else standard_value
        assert command.Value == expected_value
        assert type(command.Value) is int
        activation = controller.activate_program_with_commands_for_stove.await_args
        expected_configuration = "legacy-recipe-config" if legacy else "config-set_mod"
        assert activation.args[2] == expected_configuration
        stove.State.mode = reported_mode
        stove.Status.mod_lav_att = reported_mode
        item._handle_coordinator_update_internal()
        assert item.preset_mode == preset
        assert stove.State.mode == reported_mode
    assert coordinator.update_data_after_set.await_count == 5
    if bootloader in (None, "", "unknown", "1", "1.2beta"):
        assert "retaining standard mode commands" in caplog.text


async def test_legacy_mode_switch_preserves_mode_based_fans(
    m1_mode_stove, coordinator, controller
):
    """Keep fan commands attached to the reported mode when an older stove switches to automatic."""
    # 1. An older stove starts in manual mode with its ordinary M1 fan controls.
    stove = m1_mode_stove
    power = stove.get_first_supported_sensor_configuration(
        model_definitions.supported_power_settings
    )
    climate = MczClimateEntity(coordinator, stove.UniqueCode, *power)
    fan_configuration = get_supported_fan_configurations(
        stove,
        [
            fan
            for fan in model_definitions.supported_fans
            if (
                fan.mode_to_configuration_name_mapping is not None
                or fan.mode_to_configuration_name_mapping_m1 is not None
                or fan.mode_to_configuration_name_mapping_m2 is not None
            )
        ],
    )[0]
    fan = MczFanEntity(coordinator, stove.UniqueCode, *fan_configuration)
    await fan.async_set_percentage(50)
    manual_activation = controller.activate_program_with_commands_for_stove.await_args
    assert manual_activation.args[2] == "config-Manuale"

    # 2. Switch the stove to auto; its next report still calls that mode dynamic.
    await climate.async_set_preset_mode("auto")
    assert last_sent_command(controller).Value is True
    stove.State.mode = "dynamic"
    stove.Status.mod_lav_att = "dynamic"
    climate._handle_coordinator_update_internal()
    fan._update_features_based_on_current_stove_mode()
    fan._handle_coordinator_update_internal()
    await fan.async_set_percentage(50)

    # 3. Display Auto without changing the raw mode or the numeric fan command.
    assert climate.preset_mode == "auto"
    assert stove.State.mode == "dynamic"
    assert fan.available is True
    dynamic_activation = controller.activate_program_with_commands_for_stove.await_args
    assert dynamic_activation.args[2] == "config-Auto"
    command = last_sent_command(controller)
    assert command.SensorId == "id-m1_set_vent_v1"
    assert command.Value == 3
    assert type(command.Value) is int


@pytest.mark.parametrize(
    "legacy_problem",
    ["missing", "disabled", "wrong_type", "missing_sensor_id", "missing_group_id"],
)
async def test_legacy_mode_without_valid_command_keeps_standard_commands(
    m1_mode_stove, coordinator, controller, caplog, legacy_problem
):
    """Keep existing controls working when the cloud omits or cannot use the older command."""
    # 1. The cloud still advertises standard modes, but its older command is unusable.
    stove = m1_mode_stove
    legacy_group = stove.get_model_configuration_by_model_configuration_name(
        "Cambio_mod_2MOD"
    )
    if legacy_problem == "missing":
        stove.Model.model_configurations.remove(legacy_group)
    elif legacy_problem == "disabled":
        legacy_group.configurations[0].enabled = False
    elif legacy_problem == "wrong_type":
        legacy_group.configurations[0].type = "int"
    elif legacy_problem == "missing_sensor_id":
        legacy_group.configurations[0].sensor_id = None
    else:
        legacy_group.configuration_id = None
    power = stove.get_first_supported_sensor_configuration(
        model_definitions.supported_power_settings
    )

    # 2. Create the heating control and switch between automatic and manual.
    item = MczClimateEntity(coordinator, stove.UniqueCode, *power)
    for preset, expected_value in (("auto", 1), ("manual", 0)):
        await item.async_set_preset_mode(preset)

        # 3. Keep all advertised presets and send the standard numeric command.
        command = last_sent_command(controller)
        assert command.SensorId == "id-m1_mod_lav_att"
        assert command.Value == expected_value
        assert type(command.Value) is int
        activation = controller.activate_program_with_commands_for_stove.await_args
        assert activation.args[2] == "config-set_mod"
    assert item.preset_modes == ["manual", "auto", "comfort", "overnight", "turbo"]
    assert item.supported_features & ClimateEntityFeature.PRESET_MODE
    assert "retaining standard mode commands" in caplog.text
    await item.async_set_preset_mode("comfort")
    assert last_sent_command(controller).Value == 13
    recipe_activation = controller.activate_program_with_commands_for_stove.await_args
    assert recipe_activation.args[2] == "legacy-recipe-config"


@pytest.mark.parametrize(
    "recipe_problem",
    [
        "missing",
        "disabled",
        "wrong_type",
        "missing_sensor_id",
        "missing_group_id",
        "missing_mapping",
        "missing_mappings",
        "boolean_mapping",
        "missing_variant",
        "missing_variants",
    ],
)
async def test_legacy_recipe_without_valid_command_keeps_standard_commands(
    m1_mode_stove, coordinator, controller, caplog, recipe_problem
):
    """Keep presets usable when an older stove's alternate preset command cannot be used safely."""
    # 1. The ordinary controls work, but the older recipe control has a problem.
    stove = m1_mode_stove
    recipe_group = stove.get_model_configuration_by_model_configuration_name(
        "Ricetta Pellet"
    )
    recipe_sensor = recipe_group.configurations[0]
    if recipe_problem == "missing":
        stove.Model.model_configurations.remove(recipe_group)
    elif recipe_problem == "disabled":
        recipe_sensor.enabled = False
    elif recipe_problem == "wrong_type":
        recipe_sensor.type = "boolean"
    elif recipe_problem == "missing_sensor_id":
        recipe_sensor.sensor_id = None
    elif recipe_problem == "missing_group_id":
        recipe_group.configuration_id = None
    elif recipe_problem == "missing_mapping":
        del recipe_sensor.mappings["comfort"]
    elif recipe_problem == "missing_mappings":
        recipe_sensor.mappings = None
    elif recipe_problem == "boolean_mapping":
        recipe_sensor.mappings["comfort"] = True
    elif recipe_problem == "missing_variants":
        recipe_sensor.variants = None
    else:
        recipe_sensor.variants.remove("comfort")
    power = stove.get_first_supported_sensor_configuration(
        model_definitions.supported_power_settings
    )

    # 2. Request a preset whose older command is unavailable or invalid.
    item = MczClimateEntity(coordinator, stove.UniqueCode, *power)
    await item.async_set_preset_mode("comfort")

    # 3. Use its standard command without hiding modes or breaking Manual/Auto.
    command = last_sent_command(controller)
    assert command.SensorId == "id-m1_mod_lav_att"
    assert command.Value == 2
    assert type(command.Value) is int
    activation = controller.activate_program_with_commands_for_stove.await_args
    assert activation.args[2] == "config-set_mod"
    assert item.preset_modes == ["manual", "auto", "comfort", "overnight", "turbo"]
    assert "retaining standard" in caplog.text
    await item.async_set_preset_mode("auto")
    assert last_sent_command(controller).Value is True
    auto_activation = controller.activate_program_with_commands_for_stove.await_args
    assert auto_activation.args[2] == "legacy-mode-config"
    if recipe_problem in ("missing_mapping", "boolean_mapping", "missing_variant"):
        await item.async_set_preset_mode("turbo")
        assert last_sent_command(controller).Value == 14
        turbo_activation = controller.activate_program_with_commands_for_stove.await_args
        assert turbo_activation.args[2] == "legacy-recipe-config"


async def test_legacy_recipe_uses_model_mapping_values(
    m1_mode_stove, coordinator, controller
):
    """Follow the stove's own preset values instead of assuming every older model uses the same numbers."""
    # 1. This model assigns Comfort a different value in its older control.
    stove = m1_mode_stove
    recipe_group = stove.get_model_configuration_by_model_configuration_name(
        "Ricetta Pellet"
    )
    recipe_group.configurations[0].mappings["comfort"] = 23
    power = stove.get_first_supported_sensor_configuration(
        model_definitions.supported_power_settings
    )

    # 2. Create the heating control and choose Comfort.
    item = MczClimateEntity(coordinator, stove.UniqueCode, *power)
    await item.async_set_preset_mode("comfort")

    # 3. Send this model's value, not a fixed number or the standard mapping.
    command = last_sent_command(controller)
    assert command.SensorId == "id-m1_mod_lav_att"
    assert command.Value == 23
    assert type(command.Value) is int
    activation = controller.activate_program_with_commands_for_stove.await_args
    assert activation.args[2] == "legacy-recipe-config"


@pytest.mark.parametrize("legacy_enabled", [True, False])
async def test_legacy_only_mode_configuration(
    m1_mode_stove, coordinator, controller, legacy_enabled
):
    """Offer two presets only when the cloud's sole mode control is a usable older command."""
    # 1. No standard mode control exists, and the older command may be disabled.
    stove = m1_mode_stove
    stove.Model.model_configurations = [
        group
        for group in stove.Model.model_configurations
        if group.configuration_name != "set_mod"
    ]
    legacy_group = stove.get_model_configuration_by_model_configuration_name(
        "Cambio_mod_2MOD"
    )
    legacy_group.configurations[0].enabled = legacy_enabled
    power = stove.get_first_supported_sensor_configuration(
        model_definitions.supported_power_settings
    )

    # 2. Create the heating control and request each basic mode.
    item = MczClimateEntity(coordinator, stove.UniqueCode, *power)
    for preset, expected_value in (("auto", True), ("manual", False)):
        await item.async_set_preset_mode(preset)

        # 3. Send boolean values only if the sole command is enabled.
        if legacy_enabled:
            assert item.preset_modes == ["manual", "auto"]
            command = last_sent_command(controller)
            assert command.SensorId == "id-m1_automode"
            assert command.Value is expected_value
            activation = controller.activate_program_with_commands_for_stove.await_args
            assert activation.args[2] == "legacy-mode-config"
        else:
            assert item.preset_modes is None
            assert not item.supported_features & ClimateEntityFeature.PRESET_MODE
            controller.activate_program_with_commands_for_stove.assert_not_awaited()
    previous_command_count = controller.activate_program_with_commands_for_stove.await_count
    await item.async_set_preset_mode("comfort")
    assert controller.activate_program_with_commands_for_stove.await_count == previous_command_count


@pytest.mark.parametrize("current,target", [(18.5, 23.5), (0, 0), (None, None)])
def test_climate_temperature_updates_use_core_api(entities, stove, current, target):
    """Keep temperatures fresh in HA, including zero and unknown readings."""
    # 1. Read the initial temperatures before the stove sends a changed report.
    item = entity(entities, "climate")
    assert item.native_current_temperature == 20.5
    assert item.native_target_temperature == 22

    # 2. Refresh the control with the new room temperature and heating target.
    stove.Status.temp_amb_install = current
    stove.Status.set_amb1 = target
    stove.State.temp_amb_install = 10
    stove.State.set_amb1 = 15
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
    # 3. Losing the thermostat definition also clears its previously shown target.
    item._attr_native_target_temperature = 22
    item._supported_thermostat = None
    item._handle_coordinator_update_internal()
    assert item.native_target_temperature is None


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
    # 1. A manual-mode fan starts available with frontend-managed icons.
    item = entity(entities, "fan")
    assert item.available
    assert item.translation_key == "main_fan"
    assert item.icon is None
    # 2. Silent mode makes manual fan adjustment unavailable.
    stove.Status.silent_enabled = True
    item._handle_coordinator_update_internal()
    assert not item.available
    assert item.icon is None
    # 3. Automatic or unknown operating modes must not invent manual fan controls.
    stove.Status.silent_enabled = False
    stove.State.mode = "auto"
    stove.Status.mod_lav_att = "auto"
    item._update_features_based_on_current_stove_mode()
    item._handle_coordinator_update_internal()
    assert not item.available
    assert item.speed_count == 0
    stove.State.mode = "unknown"
    stove.Status.mod_lav_att = "unknown"
    item._update_features_based_on_current_stove_mode()
    assert item._current_fan_configuration is None
    # 4. Returning to manual mode restores the supported control.
    stove.State.mode = "manual"
    stove.Status.mod_lav_att = "manual"
    item._update_features_based_on_current_stove_mode()
    item._handle_coordinator_update_internal()
    assert item.available


@pytest.mark.parametrize("mode", [None, "manual", "auto", "unknown"])
def test_hydro_room_fan_does_not_require_an_operating_mode(
    hydro_fans, hydro_stove, mode
):
    """Keep one hydro room-fan control usable without relying on air-stove presets."""
    # 1. A hydro stove starts without a reported operating mode.
    assert len(hydro_fans) == 1
    room_fan = hydro_fans[0]
    assert room_fan.available is True
    assert room_fan.name == "Room Fan"
    assert room_fan.unique_id == "SERIAL-001-set_vent_v1"
    # 2. Change the reported mode without changing the stove's fan controls.
    hydro_stove.State.mode = mode
    hydro_stove.Status.mod_lav_att = mode
    room_fan._update_features_based_on_current_stove_mode()
    room_fan._handle_coordinator_update_internal()
    # 3. The same boiler-backed fan retains its speeds and fan presets.
    assert room_fan.available is True
    assert room_fan.speed_count == 5
    assert room_fan.preset_modes == ["auto", "silent"]
    assert room_fan.supported_features & FanEntityFeature.SET_SPEED
    assert room_fan.supported_features & FanEntityFeature.PRESET_MODE
    assert room_fan._current_fan_configuration.configuration_id == "config-BOILER"


async def test_hydro_room_fan_speed_and_power_commands(hydro_fans, controller):
    """Send hydro speed and off requests to the boiler control, not another fan group."""
    # 1. Turning on without a speed requests the highest supported level.
    room_fan = hydro_fans[0]
    await room_fan.async_turn_on()
    on_command = last_sent_command(controller)
    assert on_command.Value == 5
    assert on_command.SensorId == "fan-sensor-BOILER"
    on_activation = controller.activate_program_with_commands_for_stove.await_args
    assert on_activation.args[2] == "config-BOILER"
    # 2. A lower percentage uses the same control and its numeric speed range.
    await room_fan.async_set_percentage(40)
    speed_command = last_sent_command(controller)
    assert speed_command.Value == 2
    assert speed_command.SensorId == "fan-sensor-BOILER"
    speed_activation = controller.activate_program_with_commands_for_stove.await_args
    assert speed_activation.args[2] == "config-BOILER"
    # 3. Turning the room fan off sends zero to that same control.
    await room_fan.async_turn_off()
    off_command = last_sent_command(controller)
    assert off_command.Value == 0
    assert off_command.SensorId == "fan-sensor-BOILER"
    off_activation = controller.activate_program_with_commands_for_stove.await_args
    assert off_activation.args[2] == "config-BOILER"


@pytest.mark.parametrize("preset", ["auto", "silent"])
async def test_hydro_room_fan_preset_commands(
    hydro_fans, controller, coordinator, preset
):
    """Preserve the hydro fan's Auto and Silent options when sending a change."""
    # 1. The stove exposes fan presets even though it has no climate presets.
    room_fan = hydro_fans[0]
    assert room_fan.preset_modes == ["auto", "silent"]
    # 2. Select a supported fan preset.
    await room_fan.async_set_preset_mode(preset)
    # 3. Send the preset through the boiler group and request fresh readings.
    command = last_sent_command(controller)
    assert command.SensorId == "fan-sensor-BOILER"
    assert command.Value == preset
    activation = controller.activate_program_with_commands_for_stove.await_args
    assert activation.args[2] == "config-BOILER"
    coordinator.update_data_after_set.assert_awaited_once()


@pytest.mark.parametrize(
    "value,on,percentage,preset",
    [
        (0, False, None, None),
        (3, True, 60, None),
        (6, True, None, "auto"),
        (-1, True, None, "silent"),
    ],
)
def test_hydro_room_fan_readings(
    hydro_fans, hydro_stove, value, on, percentage, preset
):
    """Display hydro fan levels and special settings without inventing a speed."""
    # 1. The room-fan control is present without an operating mode.
    room_fan = hydro_fans[0]
    # 2. Refresh after the stove reports a new room-fan setting.
    hydro_stove.Status.set_vent_v1 = value
    room_fan._handle_coordinator_update_internal()
    # 3. Auto and Silent are shown as presets, not ordinary speed percentages.
    assert room_fan.is_on is on
    assert room_fan.percentage == percentage
    assert room_fan.preset_mode == preset


@pytest.mark.parametrize("missing_capability", ["group", "sensor", "disabled"])
async def test_hydro_room_fan_requires_enabled_boiler_control(
    hass, entry, coordinator, hydro_stove, missing_capability
):
    """Do not invent a hydro room fan from another group when its boiler control is absent."""
    # 1. Remove or disable the boiler fan while leaving the other groups intact.
    boiler_group = hydro_stove.get_model_configuration_by_model_configuration_name(
        "BOILER"
    )
    if missing_capability == "group":
        hydro_stove.Model.model_configurations.remove(boiler_group)
    elif missing_capability == "sensor":
        boiler_group.configurations.clear()
    else:
        boiler_group.configurations[0].enabled = False
    # 2. Discover the stove's available fan controls.
    module = importlib.import_module("custom_components.maestro_mcz.fan")
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    # 3. Other hydro groups must not create a guessed fan or lose its presets.
    assert add_entities.call_args.args[0] == []


@pytest.mark.parametrize("boiler_enabled", [True, False])
async def test_hydro_room_fan_shares_one_id_with_mode_based_ventilation(
    hass, entry, coordinator, hydro_stove, configuration, controller, boiler_enabled
):
    """Keep one fan control when boiler and operating-mode groups describe the same fan."""
    # 1. The stove exposes the same room fan through boiler and manual controls.
    boiler_group = hydro_stove.get_model_configuration_by_model_configuration_name(
        "BOILER"
    )
    boiler_sensor = boiler_group.configurations[0]
    boiler_sensor.enabled = boiler_enabled
    hydro_stove.Model.model_configurations.append(
        ModelConfiguration(
            {
                "ConfigurationName": "Manuale",
                "ConfigurationId": "config-Manuale",
                "Timed": False,
                "Limitations": None,
                "Configurations": [
                    configuration(
                        boiler_sensor.sensor_name,
                        SensorId="fan-sensor-Manuale",
                    )
                ],
            }
        )
    )
    hydro_stove.State.mode = "manual"
    hydro_stove.Status.mod_lav_att = "manual"
    # 2. Discover ventilation and send a speed request through the single control.
    module = importlib.import_module("custom_components.maestro_mcz.fan")
    add_entities = Mock()
    await module.async_setup_entry(hass, entry, add_entities)
    discovered_fans = add_entities.call_args.args[0]
    assert len(discovered_fans) == 1
    room_fan = discovered_fans[0]
    await room_fan.async_set_percentage(40)
    # 3. Prefer enabled boiler ventilation; otherwise retain the ordinary air-fan control.
    assert room_fan.unique_id == "SERIAL-001-set_vent_v1"
    expected_name = "Room Fan" if boiler_enabled else "Fan 1"
    expected_group = "BOILER" if boiler_enabled else "Manuale"
    assert room_fan.name == expected_name
    command = last_sent_command(controller)
    activation = controller.activate_program_with_commands_for_stove.await_args
    assert command.SensorId == f"fan-sensor-{expected_group}"
    assert activation.args[2] == f"config-{expected_group}"
    assert command.Value == 2


def test_hydro_room_fan_becomes_unavailable_when_disabled(hydro_fans, hydro_stove):
    """Respect disabled hydro ventilation even when its fixed control remains discoverable."""
    # 1. The room fan starts enabled and connected.
    room_fan = hydro_fans[0]
    assert room_fan.available is True
    boiler_group = hydro_stove.get_model_configuration_by_model_configuration_name(
        "BOILER"
    )
    # 2. The stove disables its boiler fan control.
    boiler_group.configurations[0].enabled = False
    room_fan._update_features_based_on_current_stove_mode()
    room_fan._handle_coordinator_update_internal()
    # 3. Home Assistant no longer offers speed or preset adjustments.
    assert room_fan.available is False
    assert room_fan.speed_count == 0
    assert room_fan.preset_modes is None


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
        coordinator,
        stove.UniqueCode,
        model_definitions.supported_date_times[1],
        date_config,
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


def test_fan_string_preset_uses_current_response_and_clears_missing_value(
    entities, stove
):
    """Read a current fan preset and clear it without using a different response."""
    # 1. Put different presets in current and information replies.
    item = entity(entities, "fan")
    item._current_fan_configuration.configuration.mappings = {"auto": 6}
    stove._status = SimpleNamespace(set_vent_v1="auto")
    stove.State.silent_enabled = False
    stove.State.set_vent_v1 = "silent"
    item._handle_coordinator_update_internal()
    assert item.available
    assert item.is_on
    assert item.preset_mode == "auto"
    assert item.percentage is None
    # 2. Remove the fan reading; the previous preset must not remain on screen.
    stove._status = SimpleNamespace()
    item._handle_coordinator_update_internal()
    assert item.is_on is False
    assert item.preset_mode is None
    assert item.percentage is None


def test_selector_uses_current_response_and_clears_missing_value(entities, stove):
    """Read current power and clear its choice without substituting information data."""
    # 1. Supply different power levels in the two responses.
    item = next(
        selector for selector in entities["select"] if selector._prop == "set_pot_man"
    )
    stove._status = SimpleNamespace(set_pot_man=4)
    stove._state = SimpleNamespace(set_pot_man=5)
    item._handle_coordinator_update_internal()
    assert item.current_option == "4"
    # 2. Remove that reading, then also try an unsupported value type.
    stove._status = SimpleNamespace()
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
    "platform,prop,value_property,state_value,expected",
    [
        ("sensor", "temp_amb_install", "native_value", 20.5, 20.5),
        ("binary_sensor", "is_in_error", "is_on", False, None),
    ],
)
def test_sensor_declared_source_when_status_is_null(
    entities, stove, platform, prop, value_property, state_value, expected
):
    """Keep information readings separate from current alarm data when Status is empty."""
    # 1. The status field is empty while the state field contains a reading.
    setattr(stove.Status, prop, None)
    assert getattr(stove.State, prop) == state_value
    item = next(
        control
        for control in entities[platform]
        if getattr(control, "_prop", None) == prop
    )
    item._handle_coordinator_update_internal()
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


@pytest.fixture(params=["sens_liv_pellet", "m1_sens_liv_pellet"])
def pellet_probe_configuration(stove, configuration, request):
    """Describe the optional probe setting for each stove generation, not a physical probe."""
    probe_group = ModelConfiguration(
        {
            "ConfigurationName": "Sensore Livello Pellet",
            "ConfigurationId": "config-pellet-probe",
            "Timed": False,
            "Limitations": None,
            "Configurations": [configuration(request.param)],
        }
    )
    stove.Model.model_configurations.append(probe_group)
    return probe_group


@pytest.mark.parametrize("probe_reading", [True, False])
async def test_pellet_level_low_appears_only_when_stove_reports_its_probe(
    hass, entry, coordinator, stove, pellet_probe_configuration, probe_reading
):
    """Show the pellet warning only when an enabled probe supplies a reading."""
    # 1. The probe is enabled, but the stove has not sent a reading yet.
    stove.Status.sens_liv_pellet = True
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
    "status_enabled,state_enabled,expected_sensor",
    [
        (False, False, False),
        (False, True, False),
        (None, False, False),
        (None, None, False),
        (True, False, True),
        (None, True, False),
    ],
)
async def test_pellet_probe_setting_controls_discovery(
    hass,
    entry,
    coordinator,
    stove,
    pellet_probe_configuration,
    status_enabled,
    state_enabled,
    expected_sensor,
):
    """Avoid false low-pellet warnings when a stove without an enabled probe still reports false."""
    # 1. Like the supplied M1 and M2 reports, the stove sends a false probe reading.
    stove.Status.sens_liv_pel = False
    stove.Status.sens_liv_pellet = status_enabled
    stove.State.sens_liv_pellet = state_enabled
    # 2. Discover controls only when the current response confirms an enabled probe.
    controls = await setup_binary_sensors(hass, entry)
    discovered_ids = {control.unique_id for control in controls}
    # 3. Only a confirmed enabled probe gets a warning entity; the alarm stays intact.
    has_pellet_sensor = "SERIAL-001-sens_liv_pel" in discovered_ids
    assert has_pellet_sensor is expected_sensor
    assert "SERIAL-001-is_in_error" in discovered_ids


async def test_pellet_sensor_requires_a_supported_probe_configuration(
    hass, entry, coordinator, stove, pellet_probe_configuration
):
    """Do not offer a pellet warning when the model has no matching probe configuration."""
    # 1. Readings alone suggest a working probe, but its model configuration is absent.
    stove.Status.sens_liv_pellet = True
    stove.Status.sens_liv_pel = False
    stove.Model.model_configurations.remove(pellet_probe_configuration)
    # 2. Discover the stove's supported binary sensors.
    controls = await setup_binary_sensors(hass, entry)
    discovered_ids = {control.unique_id for control in controls}
    # 3. Omit the unsupported pellet sensor without removing the normal alarm.
    assert "SERIAL-001-sens_liv_pel" not in discovered_ids
    assert "SERIAL-001-is_in_error" in discovered_ids


@pytest.mark.parametrize(
    "probe_reading,expected_warning",
    [
        (True, False),  # enough pellets: no warning
        (False, True),  # reserve reached: the stove beeps, so warn
        (None, None),  # no reading: unknown, never a guessed warning
    ],
)
async def test_pellet_level_low_turns_on_when_the_reserve_is_reached(
    hass,
    entry,
    coordinator,
    stove,
    pellet_probe_configuration,
    probe_reading,
    expected_warning,
):
    """Turn the warning on exactly when the probe reports that pellets are running out."""
    # 1. Start with a stove that has a pellet level probe.
    stove.Status.sens_liv_pellet = True
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


@pytest.mark.parametrize("enabled", [False, None])
async def test_pellet_warning_clears_when_probe_is_no_longer_enabled(
    hass, entry, coordinator, stove, pellet_probe_configuration, enabled
):
    """Stop showing a low-pellet warning if an existing probe is disabled or its setting is missing."""
    # 1. An enabled probe reports low pellets.
    stove.Status.sens_liv_pellet = True
    stove.Status.sens_liv_pel = False
    controls = await setup_binary_sensors(hass, entry)
    pellet_warning = next(
        control for control in controls if getattr(control, "_prop", None) == "sens_liv_pel"
    )
    assert pellet_warning.is_on is True
    # 2. The enable setting disappears or is turned off, but the raw reading stays false.
    stove.Status.sens_liv_pellet = enabled
    pellet_warning._handle_coordinator_update_internal()
    # 3. Show no reading until the stove confirms the probe is enabled again.
    assert pellet_warning.is_on is None
    stove.Status.sens_liv_pellet = True
    pellet_warning._handle_coordinator_update_internal()
    assert pellet_warning.is_on is True
