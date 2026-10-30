"""Shared synthetic cloud fixtures using real Home Assistant classes."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.maestro_mcz import MczAccountCoordinator
from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.maestro import MaestroStove
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroController,
)
from custom_components.maestro_mcz.maestro.controller.responses.model import Model
from custom_components.maestro_mcz.maestro.controller.responses.state import State
from custom_components.maestro_mcz.maestro.controller.responses.status import Status
from custom_components.maestro_mcz.maestro.controller.responses.stove_info import (
    StoveInfo,
)
from custom_components.maestro_mcz.maestro.types.enums import SensorTypeEnum


@pytest.fixture(autouse=True)
def custom_integration(enable_custom_integrations):
    """Make the custom integration available to the HA test harness."""


@pytest.fixture
def entry(hass):
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-user",
        data={"username": "test-user", "password": "test-password"},
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def stove_info_payload():
    return {
        "Node": {
            "Id": "device-1",
            "Name": "Living Room",
            "UniqueCode": "SERIAL-001",
            "ModelId": "model-1",
            "SensorSetTypeId": "sensors-1",
        },
        "AccessControl": {},
    }


@pytest.fixture
def configuration():
    """Build raw API configurations, not objects replacing production parsers."""

    def build(name, kind=SensorTypeEnum.INT.value, **overrides):
        return {
            "SensorName": name,
            "SensorId": f"id-{name}",
            "Type": kind,
            "Visible": True,
            "Enabled": True,
            "Min": "1",
            "Max": "5",
            "Variants": [],
            "Mappings": {},
        } | overrides

    return build


@pytest.fixture
def model_payload(configuration):
    def group(name, configs):
        return {
            "ConfigurationName": name,
            "ConfigurationId": f"config-{name}",
            "Timed": False,
            "Limitations": None,
            "Configurations": configs,
        }

    return {
        "ModelName": "Synthetic Air Stove",
        "ModelId": "model-1",
        "SensorSetTypeId": "sensors-1",
        "SensorIds": [],
        "Properties": [],
        "ModelConfigurations": [
            group(
                "Spegnimento",
                [configuration("com_on_off", SensorTypeEnum.BOOLEAN.value)],
            ),
            group(
                "Set_amb_temp",
                [
                    configuration(
                        "set_amb1", SensorTypeEnum.DOUBLE.value, Min="5", Max="35"
                    ),
                ],
            ),
            group(
                "set_mod",
                [
                    configuration(
                        "mod_funz",
                        Variants=["manual", "dynamic", "comfort"],
                        Mappings={"manual": 0, "dynamic": 1, "comfort": 2},
                    ),
                ],
            ),
            group("Manuale", [configuration("set_vent_v1")]),
            group("Auto", [configuration("set_vent_v1", Enabled=False)]),
            group("Set_pot", [configuration("set_pot_man")]),
            group(
                "Start&Stop",
                [
                    configuration("att_eco", SensorTypeEnum.BOOLEAN.value),
                    configuration("rit_usc_standby", Min="0", Max="120"),
                ],
            ),
            group("Toni", [configuration("toni_buzz", Min="1", Max="2")]),
            group(
                "Reset Allarme",
                [
                    configuration("com_reset_allarm", SensorTypeEnum.BOOLEAN.value),
                ],
            ),
            group(
                "Orodatario",
                [
                    configuration(
                        name,
                        SensorTypeEnum.BOOLEAN.value
                        if name == "am_pm"
                        else SensorTypeEnum.INT.value,
                    )
                    for name in (
                        "giorno_sett",
                        "anno",
                        "mese",
                        "giorno",
                        "ore",
                        "minuti",
                        "secondi",
                        "am_pm",
                    )
                ],
            ),
        ],
    }


@pytest.fixture
def controller(stove_info_payload, model_payload):
    result = AsyncMock(spec=MaestroController)
    result.is_authenticated = True
    result.retrieve_linked_stove_infos.return_value = [
        StoveInfo(deepcopy(stove_info_payload))
    ]
    result.get_stove_model_for_stove.return_value = Model(deepcopy(model_payload))
    result.get_stove_state_for_stove.return_value = State(
        {
            "temp_amb_install": 20.5,
            "set_amb1": 22.0,
            "mod_lav_att": "manual",
            "IsInError": False,
            "last_alarm": "A00",
        }
    )
    result.get_stove_status_for_stove.return_value = Status(
        {
            "IsConnected": True,
            "stato_stufa": 3,
            "fase_op": "working",
            "set_vent_v1": 3,
            "silent_enabled": False,
            "set_pot_man": 3,
            "rit_usc_standby": 15,
            "att_eco": True,
            "toni_buzz": 1,
            "anno": 2026,
            "mese": 10,
            "giorno": 30,
            "ore": 14,
            "minuti": 20,
            "secondi": 10,
            "giorno_sett": 4,
            "am_pm": True,
            "sm_nome_app": "app",
            "sm_vs_app": 2,
            "mc_vs_app": "3",
            "nome_banca_dati_sel": "database",
        }
    )
    return result


@pytest.fixture
async def stove(controller):
    result = MaestroStove(
        controller, controller.retrieve_linked_stove_infos.return_value[0]
    )
    await result.async_init()
    await result.refresh()
    return result


@pytest.fixture
def coordinator(hass, entry, stove):
    result = MczAccountCoordinator(hass, entry, "test-account", [stove])
    result.last_update_success = True
    result.update_data_after_set = AsyncMock()
    entry.runtime_data = result
    return result
