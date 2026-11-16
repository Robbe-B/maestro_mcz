"""Protect stove identity, configuration discovery, refresh, and command routing."""

from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import asdict, fields
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.maestro_mcz.coordinator import MczAccountCoordinator
from custom_components.maestro_mcz.fan import get_supported_fan_configurations
from custom_components.maestro_mcz.maestro import MaestroStove
from custom_components.maestro_mcz.maestro.account import MaestroAccount
from custom_components.maestro_mcz.maestro.controller import maestro_controller
from custom_components.maestro_mcz.maestro.controller.const import (
    ACTIVATE_PROGRAM_URL,
    PING_URL,
)
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
    MaestroController,
)
from custom_components.maestro_mcz.maestro.controller.requests.activate_program import (
    ProgramCommand,
)
from custom_components.maestro_mcz.maestro.controller.responses.model import (
    Model,
    ModelConfiguration,
)
from custom_components.maestro_mcz.maestro.model_value_reader import get_response_value
from custom_components.maestro_mcz.maestro.models import model_definitions, models_types


@pytest.mark.parametrize("unit,inverted", [(None, False), ("s", True)])
def test_model_schema_preserves_units_and_alarm_inversion(unit, inverted):
    """Keep units and alarm inversion in configuration records so settings are not lost."""
    # 1. Configure a delay's unit and whether an alarm's meaning is reversed.
    number = models_types.NumberMczConfigItem(
        "Delay",
        "rit_usc_standby",
        "rit_usc_standby",
        "Wait Standby",
        "auto",
        "ignition_delay",
        unit,
        None,
        None,
        True,
        models_types.MczStoveModelGeneration.M2_PLUS,
    )
    alarm = models_types.BinarySensorMczConfigItem(
        "Alarm", "is_in_error", "alarm", None, None, True, inverted=inverted
    )

    # 2. Inspect the declared fields and record both configurations.
    number_fields = {field.name: field for field in fields(number)}
    alarm_fields = {field.name: field for field in fields(alarm)}
    number_record = asdict(number)
    alarm_record = asdict(alarm)

    # 3. Both options belong to the schema, with neutral defaults and supplied values.
    assert number_fields["unit"].type == str | None
    assert number_fields["unit"].default is None
    assert alarm_fields["inverted"].type is bool
    assert alarm_fields["inverted"].default is False
    assert number_record["unit"] == unit
    assert alarm_record["inverted"] is inverted


def test_generic_matching_uses_common_fields_without_generation_selection(
    stove, configuration
):
    """Generic matching must use the supplied fields, not infer a generation or fan-specific map."""
    # 1. Common and generation-specific commands exist, with different groups for M1 and M2+.
    definition = models_types.FanMczConfigItem(
        "Fan",
        "set_vent_v1",
        "shared",
        {"manual": "Common"},
        None,
        True,
        None,
        "mod_lav_att",
        sensor_set_config_name="Common",
        sensor_set_name_m1="older",
        sensor_set_name_m2="newer",
        mode_to_configuration_name_mapping_m1={"dynamic": "Older"},
        mode_to_configuration_name_mapping_m2={"auto": "Newer"},
    )
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": group,
                "ConfigurationId": group,
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration(name) for name in names],
            }
        )
        for group, names in [
            ("Common", ["shared", "older", "newer"]),
            ("Older", ["older"]),
            ("Newer", ["newer"]),
        ]
    ]
    original_definition = asdict(definition)

    # 2. Call the generic methods directly without generation-specific selection.
    first = stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name(
        [definition]
    )
    matches = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name(
        [definition]
    )
    modes = stove.get_all_matching_sensor_for_all_configurations_by_model_mode_and_sensor_name(
        [definition]
    )

    # 3. Only the common control and common mode map are used; the definition stays intact.
    assert first[0] is definition
    assert first[1].configuration.sensor_name == "shared"
    assert [control.configuration.sensor_name for _, control in matches] == ["shared"]
    assert list(modes[0][1].mode_configurations) == ["manual"]
    assert (
        modes[0][1].mode_configurations["manual"].configuration.sensor_name == "shared"
    )
    assert asdict(definition) == original_definition


@pytest.mark.parametrize("missing_first", [False, True])
def test_generic_mode_matching_skips_definitions_without_modes(
    stove, configuration, missing_first
):
    """Definitions without modes must not reuse another control's matches or break discovery."""
    # 1. Only one of two definitions has a mode map, in either catalogue order.
    definition = models_types.MczConfigItem("Control", None)
    definition.sensor_set_name = "selected"
    definition.mode_to_configuration_name_mapping = {"manual": "Common"}
    missing = models_types.MczConfigItem("No modes", None)
    definitions = [missing, definition] if missing_first else [definition, missing]
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": "Common",
                "ConfigurationId": "common-group",
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration("selected")],
            }
        )
    ]
    original_definition = asdict(definition)

    # 2. Match the list through the original generic method.
    modes = stove.get_all_matching_sensor_for_all_configurations_by_model_mode_and_sensor_name(
        definitions
    )

    # 3. Only the definition with modes matches, and neither declaration is modified.
    assert len(modes) == 1
    assert modes[0][0] is definition
    assert list(modes[0][1].mode_configurations) == ["manual"]
    assert (
        modes[0][1].mode_configurations["manual"].configuration.sensor_name
        == "selected"
    )
    assert asdict(definition) == original_definition


@pytest.mark.parametrize(
    "common,m1,m2,advertised,expected",
    [
        ("shared", None, None, ["shared"], ["shared"]),
        (None, "older", None, ["older"], ["older"]),
        (None, None, "newer", ["newer"], ["newer"]),
        (None, "older", "newer", ["older", "newer"], ["newer", "older"]),
        (None, "older", "newer", ["older"], ["older"]),
        (None, "older", "newer", ["unrelated"], []),
        ("shared", "older", None, ["shared"], []),
    ],
    ids=[
        "common",
        "m1-only",
        "m2-only",
        "both",
        "only-m1-advertised",
        "neither-advertised",
        "no-common-command-fallback",
    ],
)
def test_optional_control_bindings_follow_advertised_commands(
    stove, configuration, common, m1, m2, advertised, expected
):
    """Offer only configured controls, even when the stove uses the default generation."""
    # 1. Declare any combination of bindings on a model with no ping information.
    definition = models_types.SelectMczConfigItem(
        "Tones",
        "toni_buzz",
        common,
        "Toni",
        "tones",
        None,
        True,
        value_mappings={"0": "Silent"},
        sensor_set_name_m1=m1,
        sensor_set_name_m2=m2,
    )
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": "Toni",
                "ConfigurationId": "tones-group",
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration(name) for name in advertised],
            }
        )
    ]
    assert stove.model_generation is models_types.MczStoveModelGeneration.M2_PLUS
    original_definition = asdict(definition)

    # 2. Match all advertised bindings and the first preferred binding separately.
    matches = stove.get_supported_sensor_configurations([definition]) or []
    first = stove.get_first_supported_sensor_configuration([definition])
    matched_names = [matched.configuration.sensor_name for _, matched in matches]

    # 3. Both controls retain the previous order; absent controls are never invented.
    assert matched_names == expected
    if expected:
        assert first[0] is definition
        assert first[1].configuration.sensor_id == f"id-{expected[0]}"
    else:
        assert first is None
    for config, matched in matches:
        assert isinstance(config, models_types.SelectMczConfigItem)
        assert config is definition
        assert config.value_mappings == {"0": "Silent"}
    assert asdict(definition) == original_definition
    repeated = stove.get_supported_sensor_configurations([definition]) or []
    assert [matched.configuration.sensor_name for _, matched in repeated] == expected
    assert all(config is definition for config, _ in repeated)


def test_generation_fan_groups_and_mode_names_remain_independent(stove, configuration):
    """Keep each generation's fan groups and mode names without changing their priority."""
    # 1. Both generations advertise different automatic modes and share the manual group.
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": name,
                "ConfigurationId": f"group-{name}",
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration(sensor) for sensor in sensors],
            }
        )
        for name, sensors in [
            ("Manuale", ["set_vent_v1", "m1_set_vent_v1"]),
            ("Auto", ["set_vent_v1"]),
            ("Dynamic", ["m1_set_vent_v1"]),
            ("set_mod", ["mod_funz", "m1_mod_lav_att"]),
        ]
    ]
    original_fan = asdict(model_definitions.supported_fans[0])
    original_mode = asdict(model_definitions.supported_climate_function_modes[0])

    # 2. Resolve fan groups and climate renames using the advertised control names.
    fan_matches = get_supported_fan_configurations(
        stove, model_definitions.supported_fans
    )
    mode_matches = stove.get_supported_sensor_configurations(
        model_definitions.supported_climate_function_modes
    )

    # 3. Each command keeps its own mode groups without rewriting the shared settings.
    assert len(fan_matches) == 2
    newer_fan, newer_groups = fan_matches[0]
    older_fan, older_groups = fan_matches[1]
    assert newer_fan is model_definitions.supported_fans[0]
    assert older_fan is newer_fan
    assert (
        newer_groups.mode_configurations["manual"].configuration.sensor_name
        == "set_vent_v1"
    )
    assert (
        older_groups.mode_configurations["manual"].configuration.sensor_name
        == "m1_set_vent_v1"
    )
    assert list(newer_groups.mode_configurations) == ["manual", "auto"]
    assert list(older_groups.mode_configurations) == ["manual", "dynamic"]
    assert mode_matches[0][1].configuration.sensor_name == "mod_funz"
    assert mode_matches[1][1].configuration.sensor_name == "m1_mod_lav_att"
    assert asdict(model_definitions.supported_fans[0]) == original_fan
    assert (
        asdict(model_definitions.supported_climate_function_modes[0]) == original_mode
    )


def test_generation_bindings_inherit_common_mappings_and_can_override_with_empty(
    stove, configuration
):
    """Both commands can use common fan groups without rewriting their declared overrides."""
    # 1. A shared mode map applies to both bindings, while the older rename is empty.
    fan = models_types.FanMczConfigItem(
        "Shared fan",
        "set_vent_v1",
        None,
        {"manual": "Manuale"},
        None,
        True,
        None,
        "mod_lav_att",
        sensor_set_name_m1="older",
        sensor_set_name_m2="newer",
    )
    mode = models_types.ClimateFunctionModeMczConfigItem(
        "Mode",
        "mod_lav_att",
        None,
        "Manuale",
        True,
        api_mappings_key_rename={"dynamic": "auto"},
        sensor_set_name_m1="older",
        sensor_set_name_m2="newer",
        api_mappings_key_rename_m1={},
    )
    original_mode = asdict(mode)
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": "Manuale",
                "ConfigurationId": "manual-group",
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration("older"), configuration("newer")],
            }
        )
    ]

    # 2. Discover both bindings without a generation hint.
    fans = get_supported_fan_configurations(stove, [fan])
    modes = stove.get_supported_sensor_configurations([mode])

    # 3. Shared fan groups stay available and climate overrides remain on the declaration.
    assert [list(groups.mode_configurations) for _, groups in fans] == [
        ["manual"],
        ["manual"],
    ]
    assert modes[0][0] is mode
    assert modes[1][0] is mode
    assert modes[0][1].configuration.sensor_name == "newer"
    assert modes[1][1].configuration.sensor_name == "older"
    assert asdict(mode) == original_mode


@pytest.mark.parametrize("explicit_generation", [False, True])
def test_matched_binding_does_not_change_default_response_source(
    stove, configuration, explicit_generation
):
    """An older command still works while a stove without a ping uses newer-model readings."""
    # 1. The model advertises an older control, but has no generation-identifying ping.
    definition = models_types.MczConfigItem(
        "Target", None, sensor_set_name_m1="older_target"
    )
    definition.sensor_get_name = "set_amb1"
    definition.sensor_set_config_name = "Set_amb_temp"
    definition.value_response_source = {
        models_types.MczStoveModelGeneration.M1: models_types.MczResponseSource.STATUS,
        models_types.MczStoveModelGeneration.M2_PLUS: models_types.MczResponseSource.STATE,
    }
    stove.Model.model_configurations = [
        ModelConfiguration(
            {
                "ConfigurationName": "Set_amb_temp",
                "ConfigurationId": "target-group",
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration("older_target")],
            }
        )
    ]
    stove.Status.set_amb1 = 30
    stove.State.set_amb1 = 0

    # 2. Resolve the concrete command while reading with the actual detected generation.
    resolved, matched = stove.get_first_supported_sensor_configuration([definition])
    reading = get_response_value(
        resolved,
        stove.State,
        stove.Status,
        stove.model_generation if explicit_generation else None,
    )

    # 3. The M1 command works, but the M2+ source and real zero stay intact.
    assert matched.configuration.sensor_name == "older_target"
    assert resolved is definition
    assert stove.model_generation is models_types.MczStoveModelGeneration.M2_PLUS
    assert reading == 0
    assert resolved.value_response_source == definition.value_response_source
    assert resolved.value_response_source is definition.value_response_source


def test_shared_definition_keeps_two_stove_commands_separate(
    stove, controller, configuration
):
    """Finding an older stove's control must not change a newer stove's selected command."""
    # 1. Two stove instances share one temperature definition but advertise different controls.
    definition = model_definitions.supported_thermostats[0]
    older_stove = MaestroStove(
        controller, controller.retrieve_linked_stove_infos.return_value[0]
    )
    older_stove._model = Model(
        {
            "ModelName": "Older controls",
            "ModelId": "older",
            "SensorSetTypeId": "int",
            "SensorIds": [],
            "Properties": [],
            "ModelConfigurations": [
                {
                    "ConfigurationName": "Set_amb_temp",
                    "ConfigurationId": "older-target",
                    "Timed": False,
                    "Limitations": None,
                    "Configurations": [configuration("m1_set_amb1")],
                }
            ],
        }
    )
    original_definition = asdict(definition)

    # 2. Find the newer stove's command, then the older stove's command.
    newer_settings, newer_control = stove.get_first_supported_sensor_configuration(
        [definition]
    )
    older_settings, older_control = (
        older_stove.get_first_supported_sensor_configuration([definition])
    )

    # 3. Only model controls differ; the shared declaration and earlier match stay unchanged.
    assert newer_settings is definition
    assert older_settings is definition
    assert newer_control.configuration.sensor_name == "set_amb1"
    assert older_control.configuration.sensor_name == "m1_set_amb1"
    assert newer_control.configuration_id == "config-Set_amb_temp"
    assert older_control.configuration_id == "older-target"
    assert asdict(definition) == original_definition


@pytest.fixture
def m1_ping(stove, configuration):
    """Add the M1 command channel: request parameters with 0 and information with 1."""
    group = ModelConfiguration(
        {
            "ConfigurationName": "PING STOVE",
            "ConfigurationId": "config-m1-ping",
            "Timed": False,
            "Limitations": None,
            "Configurations": [
                configuration(
                    "m1_cod_for_spe_mqtt",
                    Min="0",
                    Max="11",
                    Mappings={"C|RecuperoParametri": 0, "C|RecuperoInfo": 1},
                )
            ],
        }
    )
    stove.Model.model_configurations.append(group)
    return group.configurations[0]


@pytest.fixture
def m2_ping(stove, configuration):
    """Add the newer-model command channel with its declared ping value."""
    group = ModelConfiguration(
        {
            "ConfigurationName": "PING STOVE",
            "ConfigurationId": "config-m2-ping",
            "Timed": False,
            "Limitations": None,
            "Configurations": [
                configuration(
                    "cod_for_spe_mqtt",
                    Mappings={"Ping": 1122},
                )
            ],
        }
    )
    stove.Model.model_configurations.append(group)
    return group.configurations[0]


async def test_m1_refresh_requests_parameters_then_info(stove, controller, m1_ping):
    """Ask an M1 stove for both kinds of data in order, without changing any settings."""
    # 1. Forget the fixture's initial refresh and record reads and waits in order.
    controller.reset_mock()
    events = []

    async def record_activation(
        device_id,
        model_id,
        configuration_id,
        sensor_set_type_id,
        commands,
        callback,
    ):
        events.append(("activate", commands[0].Value))

    async def record_wait(delay):
        events.append(("sleep", delay))

    controller.activate_program_with_commands_for_stove.side_effect = record_activation
    with patch(
        "custom_components.maestro_mcz.maestro.asyncio.sleep", side_effect=record_wait
    ):
        # 2. Run one normal refresh, with the waits recorded rather than performed.
        await stove.refresh()

    # 3. Parameters come first, information second, with a one-second wait after each.
    assert events == [
        ("activate", 0),
        ("sleep", 1),
        ("activate", 1),
        ("sleep", 1),
    ]
    controller.do_ping_for_stove.assert_not_awaited()
    activation_calls = controller.activate_program_with_commands_for_stove.await_args_list
    for expected_value, activation in enumerate(activation_calls):
        device_id, model_id, configuration_id, sensor_set_id, commands, callback = (
            activation.args
        )
        assert device_id == "device-1"
        assert model_id == "model-1"
        assert configuration_id == "config-m1-ping"
        assert sensor_set_id == "sensors-1"
        assert len(commands) == 1
        assert commands[0].SensorId == "id-m1_cod_for_spe_mqtt"
        assert commands[0].Value == expected_value
        assert callback is None
    controller.get_stove_status_for_stove.assert_awaited_once()
    controller.get_stove_state_for_stove.assert_awaited_once()
    assert stove.is_connected


async def test_m1_refresh_ignores_empty_ping_and_overview_groups(
    stove, controller, m1_ping
):
    """Use M1's read group, not overview controls, so required reads still run."""
    # 1. Describe the M1 layout, including another group exposing the same sensor.
    read_group = stove.get_model_configuration_by_model_configuration_name("PING STOVE")
    read_group.configuration_id = "fbd50f73-952b-47c2-814b-2de92f434369"
    m1_ping.sensor_id = "429bb4ca-9618-4e9b-9172-1826f2b967d9"

    overview_group = deepcopy(read_group)
    overview_group.configuration_name = "PING_OVERVIEW"
    overview_group.configuration_id = "b58524dc-51f6-4a90-905d-e3824dffea96"
    overview_group.configurations[0].mappings = {"Info": 1, "Parameters": 0}

    empty_ping_group = deepcopy(read_group)
    empty_ping_group.configuration_name = "PING"
    empty_ping_group.configuration_id = "f8c0f73e-41ce-44cd-8f61-9af4bf914d68"
    empty_ping_group.configurations = []

    stove.Model.model_configurations.insert(0, overview_group)
    stove.Model.model_configurations.insert(0, empty_ping_group)
    controller.reset_mock()

    # 2. Refresh normally, recording the pauses rather than waiting in real time.
    with patch(
        "custom_components.maestro_mcz.maestro.asyncio.sleep",
        new_callable=AsyncMock,
    ) as sleep:
        await stove.refresh()

    # 3. Both reads must address PING STOVE, ignoring the groups placed before it.
    activation_calls = controller.activate_program_with_commands_for_stove.await_args_list
    assert len(activation_calls) == 2
    for expected_value, activation in enumerate(activation_calls):
        configuration_id = activation.args[2]
        commands = activation.args[4]
        assert configuration_id == read_group.configuration_id
        assert len(commands) == 1
        assert commands[0].SensorId == m1_ping.sensor_id
        assert commands[0].Value == expected_value
    assert sleep.await_args_list == [call(1), call(1)]
    controller.do_ping_for_stove.assert_not_awaited()
    controller.get_stove_status_for_stove.assert_awaited_once()
    controller.get_stove_state_for_stove.assert_awaited_once()


@pytest.mark.parametrize("accepted", [True, False])
async def test_m1_cloud_request_serialization_and_rejection(
    stove, m1_ping, accepted
):
    """Send the correct M1 cloud messages and stop immediately if a read is rejected."""
    # 1. Use the real HTTP-request builder with an accepted or rejected reply.
    api = MaestroController(Mock(), "test-user", "test-password")
    stove._controller = api
    failure = MaestroConnectionException("Read request failed")
    with (
        patch.object(
            api,
            "make_request",
            new_callable=AsyncMock,
            return_value={},
            side_effect=None if accepted else failure,
        ) as request,
        patch(
            "custom_components.maestro_mcz.maestro.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        if accepted:
            await stove._ping()
        else:
            with pytest.raises(MaestroConnectionException, match="Read request failed"):
                await stove.refresh()
            assert not stove.is_integration_connected_to_cloud
    # 2. Acceptance allows both reads; rejection stops after the first read.
    if accepted:
        expected_read_values = [0, 1]
    else:
        expected_read_values = [0]

    # 3. Check the complete messages, not just the number of requests.
    expected_requests = []
    for read_value in expected_read_values:
        expected_request = call(
            "POST",
            url=f"{ACTIVATE_PROGRAM_URL}/device-1",
            body={
                "ModelId": "model-1",
                "ConfigurationId": "config-m1-ping",
                "SensorSetTypeId": "sensors-1",
                "Commands": [{"SensorId": "id-m1_cod_for_spe_mqtt", "Value": read_value}],
            },
        )
        expected_requests.append(expected_request)
    assert request.await_args_list == expected_requests


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("sensor_id", None),
        ("enabled", False),
        ("type", "boolean"),
        ("mappings", None),
        ("mappings", []),
        ("mappings", {}),
        ("mappings", {"C|RecuperoParametri": 0, "C|RecuperoInfo": 2}),
        ("mappings", {"C|RecuperoParametri": False, "C|RecuperoInfo": True}),
        ("mappings", {"C|RecuperoParametri": 0, "C|RecuperoInfo": True}),
    ],
)
async def test_m1_invalid_ping_descriptor_fails_without_sending(
    stove, controller, m1_ping, attribute, value
):
    """Reject unsafe M1 command descriptions instead of sending a guessed stove command."""
    # 1. Damage one field in an otherwise valid M1 description.
    setattr(m1_ping, attribute, value)
    controller.reset_mock()
    # 2. Try a refresh; the invalid description must be rejected.
    with pytest.raises(MaestroConnectionException, match="Invalid M1 PING STOVE"):
        await stove.refresh()
    # 3. No command or data request should have reached the stove.
    controller.do_ping_for_stove.assert_not_awaited()
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    controller.get_stove_status_for_stove.assert_not_awaited()
    controller.get_stove_state_for_stove.assert_not_awaited()
    assert not stove.is_connected


async def test_m1_missing_ping_configuration_id_fails(stove, controller, m1_ping):
    """Do not address an M1 command when the cloud omitted its configuration ID."""
    # 1. Remove the ID that identifies the command group.
    ping_group = stove.get_model_configuration_by_model_configuration_name("PING STOVE")
    ping_group.configuration_id = None
    controller.reset_mock()
    # 2. The refresh fails before sending an unaddressed command.
    with pytest.raises(MaestroConnectionException, match="Invalid M1 PING STOVE"):
        await stove.refresh()
    controller.activate_program_with_commands_for_stove.assert_not_awaited()


@pytest.mark.parametrize("failure_index", [0, 1])
@pytest.mark.parametrize(
    "error", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_m1_ping_failure_stops_refresh(
    stove, controller, m1_ping, failure_index, error
):
    """Stop the M1 read sequence at the failed request so later reads cannot hide failure."""
    # 1. Fail either the first read or the second read.
    controller.reset_mock()
    activation_results = [error("ping rejected")]
    if failure_index == 1:
        activation_results.insert(0, None)
    controller.activate_program_with_commands_for_stove.side_effect = activation_results
    with (
        patch.object(stove, "_on_authentication_failed") as start_reauth,
        patch(
            "custom_components.maestro_mcz.maestro.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep,
        pytest.raises(error, match="ping rejected"),
    ):
        # 2. Run the sequence without actual sleeping and expect the original error.
        await stove.refresh()
    # 3. Only reads and waits before the failure are allowed to happen.
    assert controller.activate_program_with_commands_for_stove.await_count == (
        failure_index + 1
    )
    assert sleep.await_count == failure_index
    controller.get_stove_status_for_stove.assert_not_awaited()
    controller.get_stove_state_for_stove.assert_not_awaited()
    assert not stove.is_connected
    start_reauth.assert_not_called()


@pytest.mark.parametrize("group_name", ["cod_for_spe_mqtt", "PING STOVE"])
@pytest.mark.parametrize("value", [1122, 17])
@pytest.mark.parametrize(
    ("product_type", "configuration_id", "sensor_id"),
    [
        (
            "AIR",
            "8776c0fd-9b33-4a63-a66f-b10bb0fa0417",
            "07d8b37b-3723-4886-b33c-c1eba92e4c1d",
        ),
        (
            "CORE",
            "8776c0fd-9b33-4a63-a66f-b10bb0fa0417",
            "07d8b37b-3723-4886-b33c-c1eba92e4c1d",
        ),
        (
            "HYDRO",
            "b05b9997-0f7d-4406-bbc6-97182968d3be",
            "4e480199-b4fc-4cd4-a07e-6ba9aa1dfd53",
        ),
    ],
)
async def test_m2_refresh_uses_only_dedicated_ping(
    stove,
    controller,
    m2_ping,
    group_name,
    value,
    product_type,
    configuration_id,
    sensor_id,
):
    """Keep M2+ refreshes command-free regardless of product type or cloud layout."""
    # 1. Choose the cloud layout and this AIR, CORE, or HYDRO stove's own IDs.
    m2_ping.mappings["Ping"] = value
    m2_ping.sensor_id = sensor_id
    stove.Model.model_name = f"Synthetic {product_type} Stove"
    ping_group = stove.get_model_configuration_by_model_configuration_name("PING STOVE")
    ping_group.configuration_name = group_name
    ping_group.configuration_id = configuration_id
    controller.reset_mock()
    events = []

    async def record_activation(
        device_id,
        model_id,
        configuration_id,
        sensor_set_type_id,
        commands,
        callback,
    ):
        events.append(("activate", commands[0].Value))

    async def record_cloud_ping(device_id, device_name):
        events.append(("ping", device_id))

    controller.activate_program_with_commands_for_stove.side_effect = record_activation
    controller.do_ping_for_stove.side_effect = record_cloud_ping
    with patch(
        "custom_components.maestro_mcz.maestro.asyncio.sleep",
        new_callable=AsyncMock,
    ) as sleep:
        # 2. Refresh the stove and record any attempted ping operations.
        await stove.refresh()
    # 3. Use only the dedicated ping, without a configuration command or added wait.
    assert events == [("ping", "device-1")]
    sleep.assert_not_awaited()
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    controller.do_ping_for_stove.assert_awaited_once_with("device-1", "Living Room")
    controller.get_stove_status_for_stove.assert_awaited_once()
    controller.get_stove_state_for_stove.assert_awaited_once()
    assert stove.is_connected


async def test_m2_refresh_ignores_both_configuration_ping_groups(
    stove, controller, m2_ping
):
    """Avoid configuration commands even when a model advertises both ping layouts."""
    # 1. Keep the older layout and add a sensor-named group with different command IDs.
    older_group = stove.get_model_configuration_by_model_configuration_name("PING STOVE")
    sensor_named_group = deepcopy(older_group)
    sensor_named_group.configuration_name = "cod_for_spe_mqtt"
    sensor_named_group.configuration_id = "config-sensor-named-ping"
    sensor_named_ping = sensor_named_group.configurations[0]
    sensor_named_ping.sensor_id = "id-sensor-named-ping"
    sensor_named_ping.mappings = {"Ping": 17}
    stove.Model.model_configurations.append(sensor_named_group)
    controller.reset_mock()

    # 2. Run one ordinary HA refresh with both layouts advertised.
    await stove.refresh()

    # 3. Neither group sends a command; the ordinary ping and readings still run.
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    controller.do_ping_for_stove.assert_awaited_once_with("device-1", "Living Room")
    controller.get_stove_status_for_stove.assert_awaited_once()
    controller.get_stove_state_for_stove.assert_awaited_once()


@pytest.mark.parametrize("accepted", [True, False])
async def test_m2_cloud_request_serialization_and_rejection(
    stove, m2_ping, accepted
):
    """Send only the dedicated ping and report rejection instead of trying a command."""
    # 1. Accept or reject the dedicated ping through the real request builder.
    api = MaestroController(Mock(), "test-user", "test-password")
    stove._controller = api
    failure = MaestroConnectionException("Ping request failed")
    with patch.object(
        api,
        "make_request",
        new_callable=AsyncMock,
        return_value={},
        side_effect=None if accepted else failure,
    ) as request:
        # 2. Run the real cloud-message construction without using the network.
        if accepted:
            await stove._ping()
        else:
            with pytest.raises(MaestroConnectionException, match="Ping request failed"):
                await stove._ping()
    # 3. Exactly one ping request is sent, with no configuration activation.
    request.assert_awaited_once_with("POST", url=f"{PING_URL}/device-1")


@pytest.mark.parametrize("accepted", [True, False])
async def test_retained_m2_configuration_helper_serialization_and_rejection(
    stove, m2_ping, accepted, caplog
):
    """Keep the unused helper's request contract intact without enabling it in refresh."""
    # 1. Call the retained helper directly, with an accepted or rejected command.
    ping = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
        "PING STOVE", "cod_for_spe_mqtt"
    )
    api = MaestroController(Mock(), "test-user", "test-password")
    stove._controller = api
    failure = MaestroConnectionException("Ping request failed")
    with patch.object(
        api,
        "make_request",
        new_callable=AsyncMock,
        return_value={},
        side_effect=None if accepted else failure,
    ) as request:
        # 2. Exercise only the helper, not the normal HA refresh path.
        await stove._do_ping_configuration(ping)

    # 3. The retained helper sends its declared command and warns on rejection.
    request.assert_awaited_once_with(
        "POST",
        url=f"{ACTIVATE_PROGRAM_URL}/device-1",
        body={
            "ModelId": "model-1",
            "ConfigurationId": "config-m2-ping",
            "SensorSetTypeId": "sensors-1",
            "Commands": [{"SensorId": "id-cod_for_spe_mqtt", "Value": 1122}],
        },
    )
    if not accepted:
        assert "continuing with cloud refresh" in caplog.text


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("sensor_id", None),
        ("enabled", False),
        ("type", "boolean"),
        ("mappings", None),
        ("mappings", []),
        ("mappings", {}),
        ("mappings", {"Ping": True}),
        ("mappings", {"Ping": "1122"}),
        ("mappings", {"Ping": 1122.0}),
    ],
)
async def test_retained_m2_configuration_helper_rejects_invalid_descriptor(
    stove, controller, m2_ping, attribute, value, caplog
):
    """Keep the unused helper safe against invalid commands if it is called explicitly."""
    # 1. Damage one field in the retained helper's command description.
    setattr(m2_ping, attribute, value)
    ping = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
        "PING STOVE", "cod_for_spe_mqtt"
    )
    controller.reset_mock()
    # 2. Exercise the helper directly; normal refresh does not use it.
    await stove._do_ping_configuration(ping)
    # 3. Warn and skip the invalid command without issuing other cloud requests.
    assert "Invalid M2+ ping configuration" in caplog.text
    controller.do_ping_for_stove.assert_not_awaited()
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    controller.get_stove_status_for_stove.assert_not_awaited()
    controller.get_stove_state_for_stove.assert_not_awaited()


async def test_retained_m2_configuration_helper_rejects_missing_group_id(
    stove, controller, m2_ping, caplog
):
    """Prevent the unused helper from sending an incorrectly addressed command."""
    # 1. Remove the address of the retained helper's command group.
    ping_group = stove.get_model_configuration_by_model_configuration_name("PING STOVE")
    ping_group.configuration_id = None
    ping = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
        "PING STOVE", "cod_for_spe_mqtt"
    )
    controller.reset_mock()
    # 2. Call the helper explicitly, independently of HA refresh.
    await stove._do_ping_configuration(ping)
    # 3. Explain the missing address and do not send either kind of ping.
    assert "Invalid M2+ ping configuration" in caplog.text
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    controller.do_ping_for_stove.assert_not_awaited()


@pytest.mark.parametrize(
    "endpoint", ["activate_program_with_commands_for_stove", "do_ping_for_stove"]
)
@pytest.mark.parametrize(
    "error", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_m2_ping_failure_contract(
    stove, controller, m2_ping, endpoint, error, caplog
):
    """Propagate dedicated-ping failures, while never calling the disabled command path."""
    # 1. Make either the dedicated ping or the unused command reject requests.
    controller.reset_mock()
    getattr(controller, endpoint).side_effect = error("ping rejected")
    # 2. A command failure cannot affect refresh because that path is not called.
    if endpoint == "activate_program_with_commands_for_stove":
        await stove.refresh()
        controller.activate_program_with_commands_for_stove.assert_not_awaited()
        assert not caplog.records
        controller.do_ping_for_stove.assert_awaited_once()
        controller.get_stove_status_for_stove.assert_awaited_once()
        controller.get_stove_state_for_stove.assert_awaited_once()
        assert stove.is_connected
        return
    # 3. A dedicated-ping failure stops refresh and leaves the stove unavailable.
    with pytest.raises(error, match="ping rejected"):
        await stove.refresh()
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    controller.do_ping_for_stove.assert_awaited_once()
    controller.get_stove_status_for_stove.assert_not_awaited()
    controller.get_stove_state_for_stove.assert_not_awaited()
    assert not stove.is_connected


async def test_m2_dedicated_ping_runs_on_every_refresh(
    stove, controller, m2_ping
):
    """Keep every cycle up to date using only the dedicated ping, even after reloading."""
    # 1. Ignore the fixture's earlier calls and run two consecutive refreshes.
    controller.reset_mock()
    await stove.refresh()
    await stove.refresh()
    # 2. Both cycles ping and fetch readings, without sending configuration commands.
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    assert controller.do_ping_for_stove.await_count == 2
    assert controller.get_stove_status_for_stove.await_count == 2
    assert controller.get_stove_state_for_stove.await_count == 2
    # 3. Loading the model again must not change this every-cycle behavior.
    await stove.async_init()
    await stove.refresh()
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    assert controller.do_ping_for_stove.await_count == 3
    assert controller.get_stove_status_for_stove.await_count == 3
    assert controller.get_stove_state_for_stove.await_count == 3


async def test_retained_m2_configuration_helper_retries_after_rejection(
    stove, controller, m2_ping, caplog
):
    """Allow explicit helper calls to recover without enabling commands during refresh."""
    # 1. Reject the first direct helper call, then accept the next two.
    ping = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
        "PING STOVE", "cod_for_spe_mqtt"
    )
    controller.reset_mock()
    controller.activate_program_with_commands_for_stove.side_effect = [
        MaestroConnectionException("preparation failed"),
        None,
        None,
    ]
    # 2. The helper explains the rejected command without hiding the failure.
    await stove._do_ping_configuration(ping)
    assert "preparation failed" in caplog.text
    # 3. Later explicit helper calls retry, without fetching readings or cloud-pinging.
    await stove._do_ping_configuration(ping)
    await stove._do_ping_configuration(ping)
    assert controller.activate_program_with_commands_for_stove.await_count == 3
    controller.do_ping_for_stove.assert_not_awaited()
    controller.get_stove_status_for_stove.assert_not_awaited()
    controller.get_stove_state_for_stove.assert_not_awaited()


async def test_retained_m2_configuration_helper_propagates_authentication_failure(
    stove, controller, m2_ping, caplog
):
    """Keep login failures visible if the unused configuration helper is called directly."""
    # 1. Make a direct configuration request fail because the account is not authorized.
    ping = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
        "PING STOVE", "cod_for_spe_mqtt"
    )
    controller.reset_mock()
    controller.activate_program_with_commands_for_stove.side_effect = (
        MaestroAuthenticationException("authentication failed")
    )

    # 2. Call only the retained helper and expect the original login error.
    with pytest.raises(MaestroAuthenticationException, match="authentication failed"):
        await stove._do_ping_configuration(ping)

    # 3. Do not turn authentication failure into an optional warning or another request.
    controller.activate_program_with_commands_for_stove.assert_awaited_once()
    controller.do_ping_for_stove.assert_not_awaited()
    controller.get_stove_status_for_stove.assert_not_awaited()
    controller.get_stove_state_for_stove.assert_not_awaited()
    assert not caplog.records


async def test_m2_authentication_failure_recovers_on_next_refresh(
    stove, controller, m2_ping
):
    """Recover after login is repaired, without suppressing the original authentication error."""
    # 1. Make the dedicated ping reject the account's authentication.
    controller.reset_mock()
    controller.do_ping_for_stove.side_effect = (
        MaestroAuthenticationException("authentication failed")
    )
    # 2. The failed login stops the cycle before readings can be fetched.
    with pytest.raises(MaestroAuthenticationException):
        await stove.refresh()
    controller.do_ping_for_stove.assert_awaited_once()
    controller.get_stove_status_for_stove.assert_not_awaited()
    controller.get_stove_state_for_stove.assert_not_awaited()
    assert not stove.is_connected
    # 3. Repair the account; later cycles should resume normal pings and readings.
    controller.do_ping_for_stove.side_effect = None
    await stove.refresh()
    await stove.refresh()
    assert controller.do_ping_for_stove.await_count == 3
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    assert stove.is_connected


@pytest.mark.parametrize(
    "endpoint",
    ["do_ping_for_stove", "get_stove_status_for_stove", "get_stove_state_for_stove"],
)
@pytest.mark.parametrize(
    "error", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_m2_refresh_recovers_after_cloud_failure(
    stove, controller, m2_ping, endpoint, error
):
    """Resume complete refreshes after a cloud operation fails and then recovers."""
    # 1. Begin with a good cycle, then fail the selected cloud operation.
    controller.reset_mock()
    await stove.refresh()
    getattr(controller, endpoint).side_effect = error("offline")
    # 2. The failing cycle must show the stove as unavailable.
    with pytest.raises(error):
        await stove.refresh()
    assert not stove.is_connected
    # 3. Repair the cloud response; later cycles resume with only the dedicated ping.
    getattr(controller, endpoint).side_effect = None
    await stove.refresh()
    await stove.refresh()
    assert controller.do_ping_for_stove.await_count == 4
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    assert stove.is_connected


async def test_m2_pings_every_cycle_while_stove_reports_disconnected(
    stove, controller, m2_ping
):
    """Keep requesting updates while a stove is offline, so a returning stove can recover."""
    # 1. Refresh a working stove, then make it report that it is disconnected.
    controller.reset_mock()
    await stove.refresh()
    controller.get_stove_status_for_stove.return_value.is_connected = False
    await stove.refresh()
    # 2. The offline report affects availability, not whether later cycles send pings.
    assert not stove.is_connected
    # 3. Bring the stove back; all four cycles ping without configuration commands.
    controller.get_stove_status_for_stove.return_value.is_connected = True
    await stove.refresh()
    await stove.refresh()
    assert controller.do_ping_for_stove.await_count == 4
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    assert stove.is_connected


@pytest.mark.parametrize("failure_index", [0, 1])
async def test_m1_read_failure_recovers_on_next_cycle(
    stove, controller, m1_ping, failure_index
):
    """Restart the full M1 read sequence after a failure rather than skipping required reads."""
    # 1. Fail the first or second M1 read.
    activation_results = [MaestroConnectionException("read failed")]
    if failure_index == 1:
        activation_results.insert(0, None)
    controller.activate_program_with_commands_for_stove.side_effect = activation_results
    with patch(
        "custom_components.maestro_mcz.maestro.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        # 2. Observe the failure, then allow the cloud to respond normally again.
        with pytest.raises(MaestroConnectionException):
            await stove.refresh()
        controller.activate_program_with_commands_for_stove.side_effect = None
        controller.reset_mock()
        await stove.refresh()
    # 3. The recovered cycle starts over with parameters, then information.
    activation_calls = controller.activate_program_with_commands_for_stove.await_args_list
    sent_read_values = [activation.args[4][0].Value for activation in activation_calls]
    assert sent_read_values == [0, 1]
    assert stove.is_connected


async def test_missing_ping_descriptor_keeps_dedicated_endpoint(stove, controller):
    """Keep older supported cloud behavior when a model has no configuration-ping description."""
    # 1. The default model has no special ping command; refresh it normally.
    controller.reset_mock()
    await stove.refresh()
    # 2. Use the ordinary cloud ping without inventing a configuration command.
    controller.do_ping_for_stove.assert_awaited_once_with("device-1", "Living Room")
    controller.activate_program_with_commands_for_stove.assert_not_awaited()


async def test_m1_descriptor_takes_priority_over_m2(stove, controller, m1_ping, m2_ping):
    """Prefer M1's known read sequence if a description contains both kinds of command."""
    # 1. Put both command descriptions in the same group.
    group = stove.get_model_configuration_by_model_configuration_name("PING STOVE")
    group.configurations.append(m2_ping)
    controller.reset_mock()
    with patch(
        "custom_components.maestro_mcz.maestro.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        # 2. Run one refresh without waiting in real time.
        await stove.refresh()
    # 3. Only M1's two reads are sent, not the newer-model ping.
    activation_calls = controller.activate_program_with_commands_for_stove.await_args_list
    sent_read_values = [activation.args[4][0].Value for activation in activation_calls]
    assert sent_read_values == [0, 1]
    controller.do_ping_for_stove.assert_not_awaited()


@pytest.mark.parametrize("has_m2_descriptor", [False, True])
async def test_mixed_generation_account_keeps_ping_requests_separate(
    hass, entry, stove, controller, m1_ping, m2_ping, model_payload, has_m2_descriptor
):
    """Use each stove's own ping sequence when one account contains different models."""
    # 1. Add a second stove, with or without the newer-model command description.
    second_stove_info = deepcopy(controller.retrieve_linked_stove_infos.return_value[0])
    second_stove_info.node.id = "device-2"
    second_stove_info.node.unique_code = "SERIAL-002"
    second_stove = MaestroStove(controller, second_stove_info)
    second_stove._model = Model(deepcopy(model_payload))
    if has_m2_descriptor:
        second_stove._model.model_configurations.append(
            deepcopy(stove.Model.model_configurations[-1])
        )
    account = MaestroAccount(controller, [stove, second_stove])
    coordinator = MczAccountCoordinator(hass, entry, "mixed", account)
    controller.reset_mock()
    with patch(
        "custom_components.maestro_mcz.maestro.asyncio.sleep", new_callable=AsyncMock
    ) as sleep:
        # 2. Refresh both stoves through their shared account.
        await coordinator._async_update_data()
    # 3. The first stove uses M1 reads; only the second uses the ordinary ping.
    assert sleep.await_args_list == [call(1), call(1)]
    controller.do_ping_for_stove.assert_awaited_once_with("device-2", "Living Room")
    activation_calls = controller.activate_program_with_commands_for_stove.await_args_list
    addressed_device_ids = [activation.args[0] for activation in activation_calls]
    assert addressed_device_ids == ["device-1", "device-1"]


async def test_stove_identity_connectivity_and_device_info(stove):
    """Identify the correct stove in HA and report disconnection without losing its identity."""
    # 1. Check the connected living-room stove's account and model identifiers.
    assert stove.Id == "device-1"
    assert stove.ModelId == "model-1"
    assert stove.SensorSetTypeId == "sensors-1"
    assert stove.Name == "Living Room"
    assert stove.UniqueCode == "SERIAL-001"

    # 2. HA's device information should show this stove and its supplied software details.
    device_info = stove.get_device_info()
    assert device_info["identifiers"] == {("maestro_mcz", "SERIAL-001")}
    assert device_info["model"] == "Synthetic Air Stove"
    assert device_info["sw_version"] == "app.2, Panel:3, DB:database"

    # 3. A disconnected stove reports that state instead of claiming a live connection.
    stove._is_stove_connected_to_cloud = False
    assert not stove.is_connected
    assert stove.get_device_info()["sw_version"] == "Device Disconnected"


async def test_stove_refresh_and_command_contract(stove, controller):
    """Send a setting to the intended stove and keep account and stove connections distinct."""
    # 1. Send a false setting value, with a callback to run after acceptance.
    callback = Mock()
    await stove.activateProgram("sensor-1", "configuration-1", False, callback)
    activation = controller.activate_program_with_commands_for_stove.await_args
    device_id, model_id, configuration_id, sensor_set_id, commands, sent_callback = (
        activation.args
    )
    assert device_id == "device-1"
    assert model_id == "model-1"
    assert configuration_id == "configuration-1"
    assert sensor_set_id == "sensors-1"
    assert len(commands) == 1
    assert commands[0].SensorId == "sensor-1"
    assert commands[0].Value is False
    assert sent_callback is callback

    # 2. The cloud can be reachable even when the stove itself is offline.
    controller.get_stove_status_for_stove.return_value.is_connected = False
    await stove.refresh()
    assert stove.is_integration_connected_to_cloud
    assert not stove.is_stove_connected_to_cloud


@pytest.mark.parametrize("multiple_commands", [False, True])
@pytest.mark.parametrize(
    "failure_type", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_stove_user_commands_report_failures_without_replay(
    stove, controller, multiple_commands, failure_type
):
    """Keep failed commands visible to the user without replaying them or reporting success."""
    # 1. Prepare one setting or a batch, and reject it at the cloud boundary.
    commands = [ProgramCommand("power", False)]
    if multiple_commands:
        commands.append(ProgramCommand("target", 23.5))
    success_callback = Mock()
    failure = failure_type("command rejected")
    send_command = controller.activate_program_with_commands_for_stove
    send_command.side_effect = failure

    # 2. Call the stove directly, as the entity platforms do.
    with (
        patch.object(stove, "_on_authentication_failed") as start_reauth,
        pytest.raises(HomeAssistantError) as raised,
    ):
        if multiple_commands:
            await stove.activateProgramMultipleCommands(
                "config-1", commands, success_callback
            )
        else:
            await stove.activateProgram("power", "config-1", False, success_callback)

    # 3. Preserve the cause and callback, starting account recovery only for bad credentials.
    assert raised.value.__cause__ is failure
    send_command.assert_awaited_once()
    assert send_command.await_args.args[4] == commands
    assert send_command.await_args.args[5] is success_callback
    success_callback.assert_not_called()
    if failure_type is MaestroAuthenticationException:
        assert raised.value.translation_key == "command_invalid_auth"
        start_reauth.assert_called_once_with()
    else:
        assert raised.value.translation_key == "command_cannot_connect"
        assert raised.value.translation_placeholders == {"error": "command rejected"}
        start_reauth.assert_not_called()


@pytest.mark.parametrize("multiple_commands", [False, True])
async def test_stove_user_commands_preserve_success_callbacks(stove, multiple_commands):
    """Keep success callbacks working when direct stove commands are accepted by the cloud."""
    # 1. Use the real controller's acceptance handling without making an HTTP request.
    api = MaestroController(Mock(), "test-user", "test-password")
    stove._controller = api
    success_callback = Mock()
    with patch.object(
        api, "make_request", new_callable=AsyncMock, return_value={}
    ) as request:
        # 2. Send either a single setting or a batch through the stove facade.
        if multiple_commands:
            await stove.activateProgramMultipleCommands(
                "config-1",
                [ProgramCommand("power", False), ProgramCommand("target", 23.5)],
                success_callback,
            )
        else:
            await stove.activateProgram("power", "config-1", False, success_callback)
    # 3. Acceptance runs the supplied callback exactly once, without an extra command.
    success_callback.assert_called_once_with()
    request.assert_awaited_once()


async def test_stove_without_ha_callback_still_reports_auth_failure(controller):
    """Keep direct construction usable while never hiding rejected credentials from callers."""
    # 1. Create a stove without an HA recovery callback, using the original constructor.
    stove_info = controller.retrieve_linked_stove_infos.return_value[0]
    standalone_stove = MaestroStove(controller, stove_info)
    failure = MaestroAuthenticationException("credentials rejected")
    send_command = controller.activate_program_with_commands_for_stove
    send_command.side_effect = failure
    # 2. Try a setting without any HA entry to notify.
    with pytest.raises(HomeAssistantError) as raised:
        await standalone_stove.activateProgram("power", "config-1", False)
    # 3. The caller still receives the translated failure and its original cause.
    assert raised.value.translation_key == "command_invalid_auth"
    assert raised.value.__cause__ is failure
    send_command.assert_awaited_once()


@pytest.mark.parametrize(
    "commands",
    [
        [ProgramCommand("id-set_amb1", 23.5)],
        [ProgramCommand("id-com_on_off", True)],
        [ProgramCommand("custom-action", 1)],
        [ProgramCommand("id-set_amb1", 23.5), ProgramCommand("custom-action", True)],
    ],
    ids=["temperature", "power-toggle", "unknown-action", "mixed-batch"],
)
@pytest.mark.parametrize("outage_persists", [False, True])
@pytest.mark.parametrize("is_timeout", [False, True], ids=["server-error", "timeout"])
async def test_all_commands_share_transient_retries(
    stove, commands, outage_persists, is_timeout
):
    """Retry settings, toggles and custom actions alike while reporting local success only once."""
    # 1. The chosen command or batch encounters a temporary or sustained cloud outage.
    api = MaestroController(Mock(), "test-user", "test-password")
    api._token = "test-token"
    stove._controller = api
    success_callback = Mock()
    request_count = 0

    @asynccontextmanager
    async def cloud_response(*_args, **_kwargs):
        nonlocal request_count
        request_count += 1
        if is_timeout and (outage_persists or request_count == 1):
            raise TimeoutError("private transport details")
        status = 503 if outage_persists or request_count == 1 else 200
        yield Mock(status=status, headers={}, json=AsyncMock(return_value={}))

    api._session.request.side_effect = cloud_response
    with patch.object(
        maestro_controller, "_wait_before_retry", new_callable=AsyncMock
    ) as wait:
        # 2. Use the unchanged public stove API and the real controller retry policy.
        if not outage_persists:
            await stove.activateProgramMultipleCommands(
                "config-1", commands, success_callback
            )
        else:
            with pytest.raises(HomeAssistantError) as raised:
                await stove.activateProgramMultipleCommands(
                    "config-1", commands, success_callback
                )
            assert raised.value.translation_key == "command_cannot_connect"

    # 3. Every command uses the same budget; only confirmed success runs the callback.
    expected_attempts = 3 if outage_persists else 2
    assert request_count == expected_attempts
    assert wait.await_count == expected_attempts - 1
    api._session.post.assert_not_called()
    if not outage_persists:
        success_callback.assert_called_once_with()
    else:
        success_callback.assert_not_called()
    sent_requests = api._session.request.call_args_list
    original_request = sent_requests[0]
    for request in sent_requests:
        assert request == original_request


@pytest.mark.parametrize(
    "error", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_ping_failure_clears_cloud_connectivity(stove, controller, error):
    """Mark a failed cloud connection unavailable instead of displaying stale success."""
    # 1. Make the ordinary ping fail with a login or connection error.
    controller.do_ping_for_stove.side_effect = error("offline")
    # 2. A refresh exposes the error and clears the connected indication.
    with pytest.raises(error):
        await stove.refresh()
    assert not stove.is_integration_connected_to_cloud
    assert not stove.is_connected


@pytest.mark.parametrize(
    "endpoint", ["get_stove_state_for_stove", "get_stove_status_for_stove"]
)
async def test_payload_failure_is_not_swallowed(stove, controller, endpoint):
    """Expose failed data retrieval so a successful ping cannot disguise missing readings."""
    # 1. Let ping succeed, but fail one of the two reading requests.
    getattr(controller, endpoint).side_effect = MaestroConnectionException(
        "payload unavailable"
    )
    # 2. The whole refresh must report the failed reading.
    with pytest.raises(MaestroConnectionException, match="payload unavailable"):
        await stove.refresh()


def test_model_configuration_lookup_and_missing_values(stove):
    """Find controls despite harmless name differences, without guessing missing controls."""
    # 1. Group names may have different capitalization or surrounding spaces.
    power_group = stove.get_model_configuration_by_model_configuration_name(
        "  spegnimento "
    )
    assert power_group.configuration_id == "config-Spegnimento"
    assert stove.get_model_configuration_by_model_configuration_name(None) is None
    assert stove.get_model_configuration_by_model_configuration_name("missing") is None
    # 2. Sensor names also ignore capitalization; missing names yield no control.
    find_sensor = (
        stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name
    )
    power_sensor = find_sensor("Spegnimento", "COM_ON_OFF")
    assert power_sensor.configuration.sensor_id == "id-com_on_off"
    assert find_sensor("missing", "com_on_off") is None
    assert find_sensor("Spegnimento", "missing") is None
    assert find_sensor("Spegnimento", None) is None


def test_generation_discovery_and_fan_mode_grouping(stove):
    """Discover supported controls and fan modes without creating nonexistent controls."""
    # 1. Search the model for the first matching power control and all number controls.
    find_first_control = stove.get_first_supported_sensor_configuration
    find_all_controls = stove.get_supported_sensor_configurations
    power_setting, power_configuration = find_first_control(
        model_definitions.supported_power_settings
    )
    assert power_setting is model_definitions.supported_power_settings[0]
    assert power_configuration.configuration.sensor_name == "com_on_off"
    assert find_first_control([]) is None
    assert find_all_controls([]) is None
    assert len(find_all_controls(model_definitions.supported_numbers)) == 1

    # 2. One fan can belong to several modes; keep those modes grouped together.
    fan_matches = get_supported_fan_configurations(
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
    )
    assert len(fan_matches) == 1
    _fan_setting, fan_configuration = fan_matches[0]
    assert set(fan_configuration.mode_configurations) == {"manual", "auto"}
    missing_fans = get_supported_fan_configurations(stove, [])
    assert missing_fans is None


def test_generation_one_configuration_aliases(stove):
    """Recognize M1 control names so older stoves receive the correct controls."""
    # 1. Replace the example newer-model sensor names with their M1 equivalents.
    m1_sensor_names = {
        "com_on_off": "m1_stato_stufa",
        "set_amb1": "m1_set_amb1",
        "mod_funz": "m1_mod_lav_att",
        "set_vent_v1": "m1_set_vent_v1",
    }
    for group in stove.Model.model_configurations:
        for config in group.configurations:
            config.sensor_name = m1_sensor_names.get(
                config.sensor_name, config.sensor_name
            )
    # 2. Discovery should now choose M1 power and temperature controls.
    find_control = stove.get_first_supported_sensor_configuration
    power_setting, power_configuration = find_control(
        model_definitions.supported_power_settings
    )
    thermostat_setting, thermostat_configuration = find_control(
        model_definitions.supported_thermostats
    )
    assert power_setting is model_definitions.supported_power_settings[0]
    assert thermostat_setting is model_definitions.supported_thermostats[0]
    assert power_configuration.configuration.sensor_name == "m1_stato_stufa"
    assert thermostat_configuration.configuration.sensor_name == "m1_set_amb1"


@pytest.mark.parametrize(
    "ping_group,ping_sensor,power_sensor,model_name,expected_generation",
    [
        (
            "PING STOVE",
            "m1_cod_for_spe_mqtt",
            "com_on_off",
            "Newer-looking product",
            models_types.MczStoveModelGeneration.M1,
        ),
        (
            "cod_for_spe_mqtt",
            "cod_for_spe_mqtt",
            "m1_stato_stufa",
            "M1 example",
            models_types.MczStoveModelGeneration.M2_PLUS,
        ),
        (
            "PING STOVE",
            "cod_for_spe_mqtt",
            "m1_stato_stufa",
            "M3 example",
            models_types.MczStoveModelGeneration.M2_PLUS,
        ),
        (
            None,
            None,
            "m1_stato_stufa",
            "M1 example",
            models_types.MczStoveModelGeneration.M2_PLUS,
        ),
        (
            None,
            None,
            "com_on_off",
            "M2 example",
            models_types.MczStoveModelGeneration.M2_PLUS,
        ),
        (
            "unrecognized",
            "cod_for_spe_mqtt",
            "com_on_off",
            "M2 example",
            models_types.MczStoveModelGeneration.M2_PLUS,
        ),
        (
            "PING STOVE",
            "unrecognized",
            "m1_stato_stufa",
            "M1 example",
            models_types.MczStoveModelGeneration.M2_PLUS,
        ),
    ],
)
def test_model_generation_uses_only_ping_configuration(
    stove,
    configuration,
    ping_group,
    ping_sensor,
    power_sensor,
    model_name,
    expected_generation,
):
    """Recognize older ping commands and otherwise default to newer controls, regardless of product names."""
    # 1. Give the stove power controls and a name that need not match its ping.
    stove.Model.model_name = model_name
    power_configuration = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name(
        "Spegnimento", "com_on_off"
    )
    power_configuration.configuration.sensor_name = power_sensor
    stove.Model.model_configurations = [
        group for group in stove.Model.model_configurations
        if group.configuration_name not in ("cod_for_spe_mqtt", "PING STOVE")
    ]
    if ping_group is not None:
        mappings = (
            {"C|RecuperoParametri": 0, "C|RecuperoInfo": 1}
            if ping_sensor == "m1_cod_for_spe_mqtt"
            else {"Ping": 1122}
        )
        stove.Model.model_configurations.append(
            ModelConfiguration(
                {
                    "ConfigurationName": ping_group,
                    "ConfigurationId": "config-generation-ping",
                    "Timed": False,
                    "Limitations": None,
                    "Configurations": [configuration(ping_sensor, Mappings=mappings)],
                }
            )
        )

    # 2. Ask the stove for its centrally determined generation.
    detected_generation = stove.model_generation

    # 3. Only an M1 ping selects M1; absent or unfamiliar pings use M2+.
    assert detected_generation is expected_generation


def test_model_generation_before_model_is_loaded(controller):
    """Use the newer generation safely before a stove's model has been retrieved."""
    # 1. Create a stove before its controls have been retrieved.
    stove_info = controller.retrieve_linked_stove_infos.return_value[0]
    unloaded_stove = MaestroStove(controller, stove_info)

    # 2. Detection is safe before initialization.
    detected_generation = unloaded_stove.model_generation

    # 3. No model data uses the same M2+ default as an unrecognized ping.
    assert detected_generation is models_types.MczStoveModelGeneration.M2_PLUS


def test_model_generation_recognizes_m1_read_channel_without_power(stove, m1_ping):
    """Recognize M1's read channel even when its power control is missing."""
    # 1. Keep the M1 read channel but remove the known power control.
    power_group = stove.get_model_configuration_by_model_configuration_name("Spegnimento")
    stove.Model.model_configurations.remove(power_group)

    # 2. Detect the generation from the remaining known M1 marker.
    detected_generation = stove.model_generation

    # 3. Missing power controls must not cause misleading M1 consumption requests.
    assert detected_generation is models_types.MczStoveModelGeneration.M1


async def test_multiple_stoves_keep_identity_and_commands_separate(
    hass, entry, stove, controller
):
    """Keep two stoves separate so changing the kitchen cannot accidentally change the living room."""
    # 1. Add a kitchen stove to the existing living-room account.
    kitchen_info = deepcopy(controller.retrieve_linked_stove_infos.return_value[0])
    kitchen_info.node.id = "device-2"
    kitchen_info.node.name = "Kitchen"
    kitchen_info.node.unique_code = "SERIAL-002"
    kitchen_stove = MaestroStove(controller, kitchen_info)
    await kitchen_stove.async_init()
    await kitchen_stove.refresh()
    account = MaestroAccount(controller, [stove, kitchen_stove])
    coordinator = MczAccountCoordinator(hass, entry, "two-stoves", account)
    assert set(coordinator.stoves) == {"SERIAL-001", "SERIAL-002"}
    living_room_identifiers = stove.get_device_info()["identifiers"]
    kitchen_identifiers = kitchen_stove.get_device_info()["identifiers"]
    assert living_room_identifiers != kitchen_identifiers
    # 2. Change the kitchen temperature; its own device ID must be addressed.
    await kitchen_stove.activateProgram("target", "temperature-config", 23.5)
    kitchen_request = controller.activate_program_with_commands_for_stove.await_args
    assert kitchen_request.args[0] == "device-2"
    # 3. Change the living-room temperature; that request must address the other stove.
    await stove.activateProgram("target", "temperature-config", 21.0)
    living_room_request = controller.activate_program_with_commands_for_stove.await_args
    assert living_room_request.args[0] == "device-1"
