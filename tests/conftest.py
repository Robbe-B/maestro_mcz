"""Reusable starting points: one account, one stove, and example cloud replies.

The stove starts connected, heating normally, with a room temperature of
20.5 degrees. Tests change only the details needed for their own story.
No fixture contacts a real stove or cloud account.
"""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.coordinator import MczAccountCoordinator
from custom_components.maestro_mcz.maestro import MaestroStove
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroController,
)
from custom_components.maestro_mcz.maestro.controller.responses.consumption import (
    ConsumptionHistory,
)
from custom_components.maestro_mcz.maestro.controller.responses.model import Model
from custom_components.maestro_mcz.maestro.controller.responses.state import State
from custom_components.maestro_mcz.maestro.controller.responses.status import Status
from custom_components.maestro_mcz.maestro.controller.responses.stove_info import (
    StoveInfo,
)
from custom_components.maestro_mcz.maestro.types.enums import SensorTypeEnum


@pytest.fixture
def entry(hass):
    """Register a pretend account with Home Assistant."""
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="test-user",
        data={"username": "test-user", "password": "test-password"},
    )
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def stove_info_payload():
    """Describe the living-room stove and the IDs used to address it."""
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
    """Build a sensor description, allowing a test to change specific details."""

    def build(name, kind=SensorTypeEnum.INT.value, **overrides):
        sensor_description = {
            "SensorName": name,
            "SensorId": f"id-{name}",
            "Type": kind,
            "Visible": True,
            "Enabled": True,
            "Min": "1",
            "Max": "5",
            "Variants": [],
            "Mappings": {},
        }
        sensor_description.update(overrides)
        return sensor_description

    return build


@pytest.fixture
def model_payload(configuration):
    """Describe our pretend stove's controls and newer-model ping protocol."""

    def group(name, configs):
        """Keep related controls together, just as the cloud response does."""
        return {
            "ConfigurationName": name,
            "ConfigurationId": f"config-{name}",
            "Timed": False,
            "Limitations": None,
            "Configurations": configs,
        }

    # Most clock fields are numbers; the AM/PM flag is a yes/no value.
    clock_configurations = []
    for sensor_name in (
        "giorno_sett",
        "anno",
        "mese",
        "giorno",
        "ore",
        "minuti",
        "secondi",
        "am_pm",
    ):
        if sensor_name == "am_pm":
            sensor_type = SensorTypeEnum.BOOLEAN.value
        else:
            sensor_type = SensorTypeEnum.INT.value
        clock_configurations.append(configuration(sensor_name, sensor_type))

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
            group("Orodatario", clock_configurations),
            group(
                "cod_for_spe_mqtt",
                [configuration("cod_for_spe_mqtt", Mappings={"Ping": 1122})],
            ),
        ],
    }


@pytest.fixture
def controller(stove_info_payload, model_payload):
    """Stand in for the cloud while keeping the real response-parsing code."""
    mocked_controller = AsyncMock(spec=MaestroController)
    mocked_controller.is_authenticated = True
    mocked_controller.get_consumption_for_stove.return_value = ConsumptionHistory(
        days=(), total=0, vs_previous_interval=None
    )
    mocked_controller.retrieve_linked_stove_infos.return_value = [
        StoveInfo(deepcopy(stove_info_payload))
    ]
    mocked_controller.get_stove_model_for_stove.return_value = Model(deepcopy(model_payload))
    mocked_controller.get_stove_state_for_stove.return_value = State(
        {
            "temp_amb_install": 20.5,
            "set_amb1": 22.0,
            "mod_lav_att": "manual",
            "IsInError": False,
            "last_alarm": "A00",
        }
    )
    mocked_controller.get_stove_status_for_stove.return_value = Status(
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
    return mocked_controller


@pytest.fixture
async def stove(controller):
    """Load and refresh the stove, so tests start with known readings.

    Tests checking request counts reset the controller's recorded calls first:
    this initial refresh has already made requests.
    """
    stove_info = controller.retrieve_linked_stove_infos.return_value[0]
    living_room_stove = MaestroStove(controller, stove_info)
    await living_room_stove.async_init()
    await living_room_stove.refresh()
    return living_room_stove


@pytest.fixture
def coordinator(hass, entry, stove):
    """Connect the stove to HA's refresh manager without waiting after commands."""
    account_coordinator = MczAccountCoordinator(hass, entry, "test-account", [stove])
    account_coordinator.last_update_success = True
    account_coordinator.update_data_after_set = AsyncMock()
    entry.runtime_data = account_coordinator
    return account_coordinator
