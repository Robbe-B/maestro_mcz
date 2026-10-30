"""Protect stove identity, configuration discovery, refresh, and command routing."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from custom_components.maestro_mcz import MczAccountCoordinator
from custom_components.maestro_mcz.maestro import MaestroStove
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)
from custom_components.maestro_mcz.maestro.models import models


async def test_stove_identity_connectivity_and_device_info(stove):
    assert (stove.Id, stove.ModelId, stove.SensorSetTypeId) == (
        "device-1",
        "model-1",
        "sensors-1",
    )
    assert (stove.Name, stove.UniqueCode) == ("Living Room", "SERIAL-001")
    info = stove.get_device_info()
    assert info["identifiers"] == {("maestro_mcz", "SERIAL-001")}
    assert info["model"] == "Synthetic Air Stove"
    assert info["sw_version"] == "app.2, Panel:3, DB:database"
    stove._is_stove_connected_to_cloud = False
    assert not stove.is_connected
    assert stove.get_device_info()["sw_version"] == "Device Disconnected"


async def test_stove_refresh_and_command_contract(stove, controller):
    callback = Mock()
    await stove.activateProgram("sensor-1", "configuration-1", False, callback)
    args = controller.activate_program_with_commands_for_stove.await_args.args
    assert args[:4] == ("device-1", "model-1", "configuration-1", "sensors-1")
    assert [(command.SensorId, command.Value) for command in args[4]] == [
        ("sensor-1", False)
    ]
    assert args[5] is callback
    controller.get_stove_status_for_stove.return_value.is_connected = False
    await stove.refresh()
    assert stove.is_integration_connected_to_cloud
    assert not stove.is_stove_connected_to_cloud


@pytest.mark.parametrize(
    "error", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_ping_failure_clears_cloud_connectivity(stove, controller, error):
    controller.do_ping_for_stove.side_effect = error("offline")
    with pytest.raises(error):
        await stove.refresh()
    assert not stove.is_integration_connected_to_cloud
    assert not stove.is_connected


@pytest.mark.parametrize(
    "endpoint", ["get_stove_state_for_stove", "get_stove_status_for_stove"]
)
async def test_payload_failure_is_not_swallowed(stove, controller, endpoint):
    getattr(controller, endpoint).side_effect = MaestroConnectionException(
        "payload unavailable"
    )
    with pytest.raises(MaestroConnectionException, match="payload unavailable"):
        await stove.refresh()


def test_model_configuration_lookup_and_missing_values(stove):
    assert (
        stove.get_model_configuration_by_model_configuration_name(
            "  spegnimento "
        ).configuration_id
        == "config-Spegnimento"
    )
    assert stove.get_model_configuration_by_model_configuration_name(None) is None
    assert stove.get_model_configuration_by_model_configuration_name("missing") is None
    find = stove.get_sensor_configuration_by_model_configuration_name_and_sensor_name
    assert find("Spegnimento", "COM_ON_OFF").configuration.sensor_id == "id-com_on_off"
    assert find("missing", "com_on_off") is None
    assert find("Spegnimento", "missing") is None
    assert find("Spegnimento", None) is None


def test_generation_discovery_and_fan_mode_grouping(stove):
    first = stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name
    all_matches = stove.get_all_matching_sensor_configurations_by_model_configuration_name_and_sensor_name
    assert (
        first(models.supported_power_settings)[0].stove_model_generation
        is models.MczStoveModelGeneration.M2
    )
    assert first([]) is None
    assert all_matches([]) is None
    assert len(all_matches(models.supported_numbers)) == 1
    matches = stove.get_all_matching_sensor_for_all_configurations_by_model_mode_and_sensor_name(
        models.supported_fans
    )
    assert len(matches) == 1
    assert set(matches[0][1].mode_configurations) == {"manual", "auto"}
    assert (
        stove.get_all_matching_sensor_for_all_configurations_by_model_mode_and_sensor_name(
            []
        )
        is None
    )


def test_generation_one_configuration_aliases(stove):
    for group in stove.Model.model_configurations:
        for config in group.configurations:
            config.sensor_name = {
                "com_on_off": "m1_stato_stufa",
                "set_amb1": "m1_set_amb1",
                "mod_funz": "m1_mod_lav_att",
                "set_vent_v1": "m1_set_vent_v1",
            }.get(config.sensor_name, config.sensor_name)
    find = stove.get_first_matching_sensor_configuration_by_model_configuration_name_and_sensor_name
    assert (
        find(models.supported_power_settings)[0].stove_model_generation
        is models.MczStoveModelGeneration.M1
    )
    assert (
        find(models.supported_thermostats)[0].stove_model_generation
        is models.MczStoveModelGeneration.M1
    )


async def test_multiple_stoves_keep_identity_and_commands_separate(
    hass, entry, stove, controller
):
    info = deepcopy(controller.retrieve_linked_stove_infos.return_value[0])
    info.node.id = "device-2"
    info.node.name = "Kitchen"
    info.node.unique_code = "SERIAL-002"
    other = MaestroStove(controller, info)
    await other.async_init()
    await other.refresh()
    coordinator = MczAccountCoordinator(hass, entry, "two-stoves", [stove, other])
    assert set(coordinator.stoves) == {"SERIAL-001", "SERIAL-002"}
    assert (
        stove.get_device_info()["identifiers"] != other.get_device_info()["identifiers"]
    )
    await other.activateProgram("target", "temperature-config", 23.5)
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[0]
        == "device-2"
    )
    await stove.activateProgram("target", "temperature-config", 21.0)
    assert (
        controller.activate_program_with_commands_for_stove.await_args.args[0]
        == "device-1"
    )
