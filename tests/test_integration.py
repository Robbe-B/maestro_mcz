"""Verify real HA registration and service calls, not just entity methods."""

import json
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, EntityCategory
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import async_get_platforms
from homeassistant.helpers.translation import async_get_translations
from homeassistant.setup import async_setup_component
from homeassistant.util.unit_system import METRIC_SYSTEM, US_CUSTOMARY_SYSTEM
from pytest_homeassistant.common import MockConfigEntry

from custom_components.maestro_mcz import async_remove_config_entry_device
from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.maestro import MaestroStove
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)
from custom_components.maestro_mcz.maestro.controller.responses.consumption import (
    ConsumptionHistory,
)
from custom_components.maestro_mcz.maestro.controller.responses.counters import Counters
from custom_components.maestro_mcz.maestro.controller.responses.model import (
    Configuration,
    ModelConfiguration,
)
from custom_components.maestro_mcz.maestro.controller.responses.status import Status
from custom_components.maestro_mcz.maestro.controller.responses.stove_info import (
    StoveInfo,
)


@pytest.mark.parametrize(
    "endpoint",
    ["do_ping_for_stove", "get_stove_state_for_stove", "get_stove_status_for_stove"],
)
async def test_live_failure_isolated_to_one_stove_and_recovers(
    hass, entry, controller, stove_info_payload, caplog, endpoint
):
    """Keep the other stove updating while failed readings and cloud history stay unavailable."""
    # 1. Both stoves start with live controls, saved statistics, and yesterday's history.
    bedroom_payload = deepcopy(stove_info_payload)
    bedroom_payload["Node"].update(
        {"Id": "device-2", "UniqueCode": "SERIAL-002", "Name": "Bedroom"}
    )
    controller.retrieve_linked_stove_infos.return_value.append(
        StoveInfo(bedroom_payload)
    )
    controller.get_counters_for_stove.return_value = Counters({"num_acc": 7})
    controller.get_consumption_for_stove.side_effect = lambda _code, day: (
        ConsumptionHistory.from_response(
            {
                "Data": [{"Date": day.strftime("%Y%m%d"), "Consumption": 4.5}],
                "Total": 4.5,
            }
        )
    )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data.coordinator
    registry = er.async_get(hass)
    entity_ids = {}
    for code in ("SERIAL-001", "SERIAL-002"):
        entity_ids[code] = {
            "climate": registry.async_get_entity_id("climate", DOMAIN, code),
            "cloud": registry.async_get_entity_id(
                "binary_sensor", DOMAIN, f"{code}-Cloud_Connection_Status"
            ),
            "device": registry.async_get_entity_id(
                "binary_sensor", DOMAIN, f"{code}-Device_Connection_Status"
            ),
            "counter": registry.async_get_entity_id(
                "sensor", DOMAIN, f"{code}-num_acc"
            ),
            "history": registry.async_get_entity_id(
                "sensor", DOMAIN, f"{code}-consumption_yesterday"
            ),
        }
        for entity_id in entity_ids[code].values():
            assert entity_id is not None
            assert hass.states.get(entity_id).state != STATE_UNAVAILABLE
    failing_request = getattr(controller, endpoint)
    successful_reply = failing_request.return_value

    async def fail_living_room(device_id, _name):
        """Only the first stove's request fails; the bedroom still returns a reading."""
        if device_id == "device-1":
            raise MaestroConnectionException("temporary request failure")
        return successful_reply

    # 2. Repeat a first-stove failure while a changed bedroom temperature keeps arriving.
    caplog.set_level("INFO", logger="custom_components.maestro_mcz.maestro.account")
    caplog.clear()
    failing_request.side_effect = fail_living_room
    controller.get_stove_status_for_stove.return_value.temp_amb_install = 24
    for _ in range(2):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert coordinator.last_update_success
        assert not coordinator.stoves["SERIAL-001"].is_connected
        assert coordinator.stoves["SERIAL-002"].is_connected
        living_room = entity_ids["SERIAL-001"]
        bedroom = entity_ids["SERIAL-002"]
        assert hass.states.get(living_room["cloud"]).state == "off"
        for field in ("climate", "device", "counter", "history"):
            assert hass.states.get(living_room[field]).state == STATE_UNAVAILABLE
        assert hass.states.get(bedroom["cloud"]).state == "on"
        assert hass.states.get(bedroom["device"]).state == "on"
        bedroom_climate = hass.states.get(bedroom["climate"])
        assert bedroom_climate.attributes["current_temperature"] == 24
        assert hass.states.get(bedroom["counter"]).state == "7"
        assert hass.states.get(bedroom["history"]).state == "4.5"
    failures = [
        record
        for record in caplog.records
        if "Error refreshing stove" in record.message
    ]
    assert len(failures) == 1
    assert "Living Room" in failures[0].message

    # 3. Successful updates restore the failed stove without repeating recovery messages.
    failing_request.side_effect = None
    for _ in range(2):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert coordinator.stoves["SERIAL-001"].is_connected
    assert hass.states.get(living_room["cloud"]).state == "on"
    assert hass.states.get(living_room["device"]).state == "on"
    recovered_climate = hass.states.get(living_room["climate"])
    assert recovered_climate.attributes["current_temperature"] == 24
    assert hass.states.get(living_room["counter"]).state == "7"
    assert hass.states.get(living_room["history"]).state == "4.5"
    recoveries = [record for record in caplog.records if "recovered" in record.message]
    assert len(recoveries) == 1
    assert "Living Room" in recoveries[0].message
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("saved_metadata", [False, True])
async def test_device_metadata_updates_in_place_and_survives_missing_reports(
    hass, entry, controller, saved_metadata
):
    """Refresh the real device page without losing saved details, names, or another account's data."""
    # 1. Start without live metadata; another account may share the same stove identifier.
    controller.get_stove_status_for_stove.return_value = Status({"IsConnected": True})
    registry = dr.async_get(hass)
    if saved_metadata:
        registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, "SERIAL-001")},
            serial_number="SAVED-BOARD",
            sw_version="01.00",
        )
    other_entry = MockConfigEntry(domain=DOMAIN, unique_id="other-account")
    other_entry.add_to_hass(hass)
    other_device = registry.async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={(DOMAIN, "SERIAL-001")},
        serial_number="OTHER-BOARD",
        sw_version="Other firmware",
    )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, "SERIAL-001"), entry.entry_id
        )
        assert device.serial_number == ("SAVED-BOARD" if saved_metadata else None)
        assert device.sw_version == ("01.00" if saved_metadata else None)
        device_id = device.id
        registry.async_update_device(device_id, name_by_user="My living-room stove")
        entity_registry = er.async_get(hass)
        original_entities = {
            entity.id
            for entity in er.async_entries_for_config_entry(
                entity_registry, entry.entry_id
            )
        }
        system_info_fields = {"sm_vs_app", "nome_banca_dati_sel", "mc_vs_app"}
        coordinator = entry.runtime_data.coordinator

        # 2. Motherboard details arrive later, while all original entities remain loaded.
        controller.get_stove_status_for_stove.return_value = Status(
            {
                "IsConnected": True,
                "sm_sn": "BOARD-001",
                "sm_nome_app": "DM2.AIR",
                "sm_vs_app": "01.02.003",
                "mc_vs_app": "Panel version",
                "nome_banca_dati_sel": "Database name",
            }
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        updated_device = registry.async_get(device_id)
        assert updated_device.serial_number == "BOARD-001"
        assert updated_device.sw_version == "DM2.AIR.01.02.003"
        assert updated_device.hw_version is None

        # 3. Empty offline reports and a failed cloud request must preserve the known details.
        for missing_report in (
            Status({"IsConnected": False, "sm_sn": "", "sm_vs_app": ""}),
            None,
        ):
            controller.get_stove_status_for_stove.return_value = missing_report
            await coordinator.async_refresh()
            disconnected_device = registry.async_get(device_id)
            assert disconnected_device.serial_number == "BOARD-001"
            assert disconnected_device.sw_version == "DM2.AIR.01.02.003"
        controller.do_ping_for_stove.side_effect = MaestroConnectionException("offline")
        await coordinator.async_refresh()
        assert not coordinator.last_update_success
        assert registry.async_get(device_id).sw_version == "DM2.AIR.01.02.003"

        # 4. Reconnection supplies a changed version but no serial; only firmware changes.
        controller.do_ping_for_stove.side_effect = None
        controller.get_stove_status_for_stove.return_value = Status(
            {"IsConnected": True, "sm_vs_app": "01.02.004"}
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        reconnected_device = registry.async_get_device_by_identifier(
            (DOMAIN, "SERIAL-001"), entry.entry_id
        )
        assert reconnected_device.id == device_id
        assert reconnected_device.identifiers == {(DOMAIN, "SERIAL-001")}
        assert reconnected_device.serial_number == "BOARD-001"
        assert reconnected_device.sw_version == "DM2.AIR.01.02.004"
        assert reconnected_device.name_by_user == "My living-room stove"
        remaining_entities = {
            entity.id
            for entity in er.async_entries_for_config_entry(
                entity_registry, entry.entry_id
            )
            if entity.unique_id.removeprefix("SERIAL-001-") not in system_info_fields
        }
        assert remaining_entities == original_entities
        assert registry.async_get(other_device.id).serial_number == "OTHER-BOARD"
        assert registry.async_get(other_device.id).sw_version == "Other firmware"
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("sensor_set_type_id", "has_m1_channel", "expected_prefix", "database", "panel"),
    [
        ("sensors-1", False, "DM2.AIR", "DB-001", "00.03"),
        (
            (
                "7c201fd8-42bd-4333-914d-0f5822070757\u00a7"
                "00000000-0000-0000-0000-000000000000\u00a7"
                "314b03b8-f4ed-11eb-a33c-0242ac120003"
            ),
            True,
            "M1.Air",
            27,
            None,
        ),
        (
            (
                "7c201fd8-42bd-4333-914d-0f5822070757\u00a7"
                "2132564a-aa41-46be-a31c-7e26f94692ce\u00a7"
                "8f90d262-2818-4054-b3ec-5f71f0e90466"
            ),
            False,
            "M1.Hydro",
            "Already named",
            None,
        ),
    ],
    ids=["m2", "m1-air", "m1-hydro-without-ping"],
)
async def test_system_info_sensors_discover_once_and_follow_live_availability(
    hass,
    entry,
    controller,
    configuration,
    sensor_set_type_id,
    has_m1_channel,
    expected_prefix,
    database,
    panel,
):
    """Keep useful firmware history on the same device without guessing unsupported readings."""
    # 1. Initially the stove reports no system details, even though State has an old name.
    controller.retrieve_linked_stove_infos.return_value[
        0
    ].node.sensor_set_type_id = sensor_set_type_id
    if has_m1_channel:
        controller.get_stove_model_for_stove.return_value.model_configurations.append(
            ModelConfiguration(
                {
                    "ConfigurationName": "PING STOVE",
                    "ConfigurationId": "m1-ping",
                    "Timed": False,
                    "Limitations": None,
                    "Configurations": [
                        configuration(
                            "m1_cod_for_spe_mqtt",
                            Mappings={"C|RecuperoParametri": 0, "C|RecuperoInfo": 1},
                        )
                    ],
                }
            )
        )
    controller.get_stove_state_for_stove.return_value.nome_banca_dati_sel = "Old value"
    controller.get_stove_status_for_stove.return_value = Status({"IsConnected": True})
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
        patch(
            "custom_components.maestro_mcz.maestro.asyncio.sleep",
            new_callable=AsyncMock,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        registry = er.async_get(hass)
        fields = {"sm_vs_app", "nome_banca_dati_sel", "mc_vs_app"}
        initial_diagnostics = [
            item
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
            if item.unique_id.removeprefix("SERIAL-001-") in fields
        ]
        assert initial_diagnostics == []
        coordinator = entry.runtime_data.coordinator
        stove = coordinator.stoves["SERIAL-001"]

        # 2. Details arrive later; only newer stoves may create a panel sensor.
        controller.get_stove_status_for_stove.return_value = Status(
            {
                "IsConnected": True,
                "sm_sn": "BOARD-001",
                "sm_nome_app": "DM2.AIR",
                "sm_vs_app": "0016",
                "nome_banca_dati_sel": database,
                "mc_vs_app": "00.03",
            }
        )
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        expected_values = {
            "sm_vs_app": f"{expected_prefix}.0016",
            "nome_banca_dati_sel": "SC24-HYD" if database == 27 else database,
        }
        if panel is not None:
            expected_values["mc_vs_app"] = panel
        diagnostics = {
            item.unique_id.removeprefix("SERIAL-001-"): item
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
            if item.unique_id.removeprefix("SERIAL-001-") in fields
        }
        assert set(diagnostics) == set(expected_values)
        device_registry = dr.async_get(hass)
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, "SERIAL-001"), entry.entry_id
        )
        for field, expected_value in expected_values.items():
            entity = diagnostics[field]
            state = hass.states.get(entity.entity_id)
            assert state.state == expected_value
            assert entity.device_id == device.id
            assert entity.entity_category is EntityCategory.DIAGNOSTIC
            assert entity.disabled_by is None
            assert "unit_of_measurement" not in state.attributes
            assert "state_class" not in state.attributes
            assert "device_class" not in state.attributes
        motherboard_entity_id = diagnostics["sm_vs_app"].entity_id
        assert hass.states.get(motherboard_entity_id).state == device.sw_version
        original_entity_ids = {
            item.id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        }

        # 3. Later versions retain board type and exact text, without adding duplicates.
        controller.get_stove_status_for_stove.return_value = Status(
            {
                "IsConnected": True,
                "sm_vs_app": "0017",
                "nome_banca_dati_sel": "DB-002",
                "mc_vs_app": "00.04",
            }
        )
        await coordinator.async_refresh()
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        assert hass.states.get(motherboard_entity_id).state == f"{expected_prefix}.0017"
        assert stove.get_device_info().sw_version == f"{expected_prefix}.0017"
        database_entity_id = diagnostics["nome_banca_dati_sel"].entity_id
        assert hass.states.get(database_entity_id).state == "DB-002"
        if panel is not None:
            assert hass.states.get(diagnostics["mc_vs_app"].entity_id).state == "00.04"

        # 4. Lost connections make live diagnostics unavailable; missing readings stay unknown.
        controller.get_stove_status_for_stove.return_value = Status(
            {"IsConnected": False}
        )
        await coordinator.async_refresh()
        for entity in diagnostics.values():
            assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
        controller.get_stove_status_for_stove.return_value = Status(
            {"IsConnected": True}
        )
        await coordinator.async_refresh()
        assert hass.states.get(motherboard_entity_id).state == f"{expected_prefix}.0017"
        assert hass.states.get(database_entity_id).state == STATE_UNKNOWN
        if panel is not None:
            assert (
                hass.states.get(diagnostics["mc_vs_app"].entity_id).state
                == STATE_UNKNOWN
            )
        controller.do_ping_for_stove.side_effect = MaestroConnectionException("offline")
        if has_m1_channel:
            controller.activate_program_with_commands_for_stove.side_effect = (
                MaestroConnectionException("offline")
            )
        await coordinator.async_refresh()
        for entity in diagnostics.values():
            assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
        remaining_entity_ids = {
            item.id
            for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        }
        assert remaining_entity_ids == original_entity_ids
        assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.fixture
async def removal_account(hass, entry, controller, request):
    """Load an account normally without contacting the cloud or registering controls."""
    if getattr(request, "param", False):
        hass.config_entries.async_update_entry(
            entry, data=dict(entry.data) | {"MOCKED_FOLDER": "/synthetic"}
        )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch(
            "custom_components.maestro_mcz.MockedController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        yield entry
        if entry.state is ConfigEntryState.LOADED:
            assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "membership",
    [
        "absent",
        "empty",
        "linked",
        "offline",
        "connection",
        "auth",
        "incomplete",
        "unloaded",
    ],
)
async def test_device_removal_checks_current_account_and_preserves_other_devices(
    hass, hass_ws_client, removal_account, controller, membership
):
    """Delete only an unlinked stove, never an offline stove or another account's saved controls."""
    # 1. Two accounts share a stove identifier but keep their own devices and entity names.
    entry = removal_account
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "SERIAL-001"), ("other_integration", "SERIAL-002")},
        name="Living Room",
    )
    other_entry = MockConfigEntry(domain=DOMAIN, unique_id="other-account")
    other_entry.add_to_hass(hass)
    retained_device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "SERIAL-002")},
        name="Kitchen",
    )
    other_device = registry.async_get_or_create(
        config_entry_id=other_entry.entry_id,
        identifiers={(DOMAIN, "SERIAL-001")},
        name="Other account stove",
    )
    entities = er.async_get(hass)
    entity = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        "SERIAL-001-room",
        config_entry=entry,
        device_id=device.id,
        suggested_object_id="my_living_room",
    )
    other_entity = entities.async_get_or_create(
        "sensor",
        DOMAIN,
        "other-account-room",
        config_entry=other_entry,
        device_id=other_device.id,
        suggested_object_id="my_other_room",
    )
    other_device = registry.async_update_device(
        other_device.id, name_by_user="My stove"
    )
    known_info = controller.retrieve_linked_stove_infos.return_value[0]
    current_info = deepcopy(known_info)
    current_info.node.unique_code = "SERIAL-002"
    controller.retrieve_linked_stove_infos.reset_mock()
    if membership in {"absent", "empty", "unloaded"}:
        controller.retrieve_linked_stove_infos.return_value = (
            [current_info] if membership == "absent" else []
        )
    elif membership == "offline":
        offline_stove = entry.runtime_data.coordinator.stoves["SERIAL-001"]
        offline_stove._is_stove_connected_to_cloud = False
    elif membership == "connection":
        controller.retrieve_linked_stove_infos.side_effect = MaestroConnectionException(
            "offline"
        )
    elif membership == "auth":
        controller.retrieve_linked_stove_infos.side_effect = (
            MaestroAuthenticationException("rejected")
        )
    elif membership == "incomplete":
        current_info.node.unique_code = None
        controller.retrieve_linked_stove_infos.return_value = [current_info]
    if membership == "unloaded":
        assert await hass.config_entries.async_unload(entry.entry_id)

    # 2. Use HA's real device-page removal endpoint and its registry cleanup.
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)
    with (
        patch.object(
            hass.config_entries,
            "async_reload",
            new_callable=AsyncMock,
            return_value=True,
        ) as reload_entry,
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ) as client_factory,
    ):
        await client.send_json(
            {
                "id": 1,
                "type": "config/device_registry/remove",
                "device_id": device.id,
            }
        )
        result = await client.receive_json()
        await hass.async_block_till_done(wait_background_tasks=True)

    # 3. Fresh absence allows deletion; failures and current links preserve identities.
    removable = membership in {"absent", "empty", "unloaded"}
    assert result["success"] is removable
    controller.retrieve_linked_stove_infos.assert_awaited_once_with(
        require_unique_codes=True
    )
    if membership == "unloaded":
        client_factory.assert_called_once()
    else:
        client_factory.assert_not_called()
    if removable:
        assert registry.async_get(device.id) is None
        assert entities.async_get(entity.entity_id) is None
        reload_entry.assert_awaited_once_with(entry.entry_id)
    else:
        assert registry.async_get(device.id).id == device.id
        assert entities.async_get(entity.entity_id).id == entity.id
        reload_entry.assert_not_awaited()
    assert registry.async_get(other_device.id).name_by_user == "My stove"
    assert registry.async_get(retained_device.id).name == "Kitchen"
    assert entities.async_get(other_entity.entity_id).id == other_entity.id
    pending_flows = hass.config_entries.flow.async_progress()
    assert bool(pending_flows) is (membership == "auth")
    if membership == "auth":
        assert pending_flows[0]["context"]["entry_id"] == entry.entry_id
    if membership in {"connection", "incomplete"}:
        assert "not removed" in result["error"]["message"]
    elif membership in {"linked", "offline"}:
        assert "still linked to your Maestro account" in result["error"]["message"]
        assert "official MCZ app" in result["error"]["message"]
    elif membership == "auth":
        assert "sign in again" in result["error"]["message"]


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("removal_account", [True], indirect=True)
async def test_replay_device_removal_uses_loaded_reports_without_cloud_requests(
    hass, hass_ws_client, removal_account, controller, linked
):
    """Keep replay removal local and require reloading reports before an old device can disappear."""
    # 1. A loaded replay account knows only the stoves from its last successful load.
    entry = removal_account
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "SERIAL-001" if linked else "REMOVED-SERIAL")},
    )
    controller.reset_mock()
    assert await async_setup_component(hass, "config", {})
    client = await hass_ws_client(hass)

    # 2. Request removal from the same HA device-page endpoint as a cloud account.
    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock, return_value=True
    ) as reload_entry:
        await client.send_json(
            {
                "id": 1,
                "type": "config/device_registry/remove",
                "device_id": device.id,
            }
        )
        result = await client.receive_json()
        await hass.async_block_till_done(wait_background_tasks=True)

    # 3. Only an old replay device can be removed, without reading files or calling the cloud.
    assert result["success"] is not linked
    assert (registry.async_get(device.id) is not None) is linked
    controller.retrieve_linked_stove_infos.assert_not_awaited()
    controller.make_request.assert_not_awaited()
    if linked:
        reload_entry.assert_not_awaited()
        assert "loaded saved reports" in result["error"]["message"]
    else:
        reload_entry.assert_awaited_once_with(entry.entry_id)


@pytest.mark.parametrize("replay", [False, True])
async def test_unverifiable_device_removal_preserves_registry(
    hass, removal_account, controller, replay
):
    """Refuse removal when a device has no stove identity or its replay account is not loaded."""
    # 1. Prepare a device whose current account membership cannot be checked.
    entry = removal_account
    if replay:
        hass.config_entries.async_update_entry(
            entry, data=dict(entry.data) | {"MOCKED_FOLDER": "/synthetic"}
        )
        assert await hass.config_entries.async_unload(entry.entry_id)
    registry = dr.async_get(hass)
    device = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN if replay else "other_integration", "unknown")},
    )
    controller.reset_mock()

    # 2. Ask the removal hook without fabricating a current device list.
    with pytest.raises(HomeAssistantError) as raised:
        await async_remove_config_entry_device(hass, entry, device)
    assert raised.value.translation_key == "device_removal_cannot_verify"

    # 3. Preserve the device and avoid any cloud or replay-file requests.
    assert registry.async_get(device.id) is not None
    controller.retrieve_linked_stove_infos.assert_not_awaited()


@pytest.mark.parametrize("probe_binding", ["m1_sens_liv_pellet", "sens_liv_pellet"])
@pytest.mark.parametrize(
    "probe_state", ["enabled", "disabled", "missing", "unsupported"]
)
async def test_existing_pellet_registry_entry_keeps_identity_and_truthful_state(
    hass, entry, controller, configuration, probe_binding, probe_state
):
    """Keep saved probe identities while respecting their enabled setting and actual readings."""
    # 1. Keep a pre-migration registry entry while the model describes its actual probe.
    registry = er.async_get(hass)
    original = registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        "SERIAL-001-sens_liv_pel",
        config_entry=entry,
        suggested_object_id="existing_pellet_warning",
        original_name="Pellet Level Low",
    )
    model = controller.get_stove_model_for_stove.return_value
    state = controller.get_stove_state_for_stove.return_value
    status = controller.get_stove_status_for_stove.return_value
    state.sens_liv_pellet = probe_state != "disabled"
    status.sens_liv_pellet = probe_state != "disabled"
    status.sens_liv_pel = None if probe_state == "missing" else probe_state == "enabled"
    if probe_state != "unsupported":
        model.model_configurations.append(
            ModelConfiguration(
                {
                    "ConfigurationName": "Sensore Livello Pellet",
                    "ConfigurationId": "probe-group",
                    "Timed": False,
                    "Limitations": None,
                    "Configurations": [configuration(probe_binding)],
                }
            )
        )
    if probe_binding.startswith("m1_"):
        ping = next(
            group
            for group in model.model_configurations
            if group.configuration_name == "cod_for_spe_mqtt"
        )
        ping.configuration_name = "PING STOVE"
        ping.configurations[0].sensor_name = "m1_cod_for_spe_mqtt"

    # 2. Load real HA entities, not just constructors or the catalogue definitions.
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
        patch.object(MaestroStove, "_ping", new_callable=AsyncMock),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    registered = registry.async_get(original.entity_id)
    assert registered.id == original.id
    assert registered.unique_id == "SERIAL-001-sens_liv_pel"
    matching_entries = [
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.unique_id == registered.unique_id
    ]
    assert len(matching_entries) == 1
    binary_platform = next(
        platform
        for platform in async_get_platforms(hass, DOMAIN)
        if platform.domain == "binary_sensor"
    )

    # 3. Disabled, unsupported or unreadable probes leave saved entries, not invented readings.
    if probe_state != "enabled":
        assert original.entity_id not in binary_platform.entities
        assert registered.translation_key is None
        state = hass.states.get(original.entity_id)
        assert state is None or state.state == "unavailable"
    else:
        assert original.entity_id in binary_platform.entities
        assert registered.translation_key == "pellet_level_low"
        assert hass.states.get(original.entity_id).state == "off"
        assert (
            hass.states.get(original.entity_id).name == "Living Room Pellet level low"
        )

        # 4. Live warnings invert only genuine readings; missing readings remain unknown.
        account = entry.runtime_data.coordinator
        stove = account.stoves["SERIAL-001"]
        for reading, expected in [(False, "on"), (True, "off"), (None, "unknown")]:
            stove.Status.sens_liv_pel = reading
            account.async_set_updated_data(None)
            await hass.async_block_till_done()
            state = hass.states.get(original.entity_id)
            assert state.state == expected
            assert "icon" not in state.attributes

        # 5. A cloud failure changes availability without changing the registered identity.
        account.async_set_update_error(MaestroConnectionException("offline"))
        await hass.async_block_till_done()
        assert hass.states.get(original.entity_id).state == "unavailable"
        stove.Status.sens_liv_pel = True
        account.async_set_updated_data(None)
        await hass.async_block_till_done()
        assert hass.states.get(original.entity_id).state == "off"
        assert registry.async_get(original.entity_id).id == original.id
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("language", ["en", "nl"])
@pytest.mark.parametrize("customized", [False, True])
async def test_translated_names_preserve_registered_ids_custom_names_and_icons(
    hass, entry, controller, configuration, language, customized
):
    """Translate default names while keeping saved controls, personal names, values and icons."""
    # 1. Existing controls keep their saved IDs, whether or not the user renamed them.
    hass.config.language = language
    registry = er.async_get(hass)
    expected_names = [
        ("binary_sensor", "is_in_error", "alarm", "Alarm", "Alarm"),
        (
            "binary_sensor",
            "Cloud_Connection_Status",
            "cloud_connection",
            "Cloud connection status",
            "Cloudverbindingsstatus",
        ),
        (
            "binary_sensor",
            "Device_Connection_Status",
            "device_connection",
            "Device connection status",
            "Apparaatverbindingsstatus",
        ),
        ("button", "com_reset_allarm", "alarm_reset", "Alarm reset", "Alarm resetten"),
        (
            "button",
            "giorno",
            "system_date_time",
            "Set system date & time",
            "Systeemdatum en -tijd instellen",
        ),
        ("datetime", "giorno", "date_time", "Date & time", "Datum en tijd"),
        (
            "number",
            "rit_usc_standby",
            "ignition_delay",
            "Start / stop - delay in ignition",
            "Start / stop - vertraging bij ontsteken",
        ),
        ("select", "set_pot_man", "manual_power", "Manual power", "Handmatig vermogen"),
        ("select", "toni_buzz", "tones", "Tones", "Geluidssignalen"),
        ("sensor", "last_alarm", "last_alarm", "Last alarm code", "Laatste alarmcode"),
        ("sensor", "state", "current_state", "Current state", "Huidige status"),
        ("sensor", "mode", "current_mode", "Current mode", "Huidige modus"),
        (
            "sensor",
            "temp_amb_install",
            "ambient_temperature",
            "Ambient temperature",
            "Omgevingstemperatuur",
        ),
        (
            "sensor",
            "temp_caldaia",
            "water_temperature",
            "Water temperature",
            "Watertemperatuur",
        ),
        (
            "sensor",
            "temp_puffer",
            "puffer_temperature",
            "Buffer tank temperature",
            "Buffervattemperatuur",
        ),
        (
            "sensor",
            "sondaWifi",
            "wifi_probe_temperature",
            "Wi-Fi probe temperature",
            "Wi-Fi-sondetemperatuur",
        ),
        (
            "sensor",
            "temp_fumi",
            "exhaust_temperature",
            "Exhaust temperature",
            "Rookgastemperatuur",
        ),
        (
            "sensor",
            "temp_scheda",
            "board_temperature",
            "Board temperature",
            "Printplaattemperatuur",
        ),
        (
            "sensor",
            "vel_real_coclea",
            "transport_screw_speed",
            "Auger screw speed",
            "Snelheid toevoerschroef",
        ),
        (
            "sensor",
            "sm_vs_app",
            "motherboard_firmware",
            "Motherboard firmware",
            "Moederbordfirmware",
        ),
        (
            "sensor",
            "nome_banca_dati_sel",
            "active_database",
            "Active database",
            "Actieve database",
        ),
        ("sensor", "mc_vs_app", "panel_firmware", "Panel firmware", "Paneelfirmware"),
        ("switch", "att_eco", "start_stop", "Start / stop", "Start / stop"),
        ("fan", "set_vent_v1", "main_fan", "Fan 1", "Ventilator 1"),
        ("fan", "set_vent_v2", "main_fan", "Fan 2", "Ventilator 2"),
        ("fan", "set_vent_v3", "main_fan", "Fan 3", "Ventilator 3"),
    ]
    saved_entries = {}
    for domain, suffix, key, english, dutch in expected_names:
        original = registry.async_get_or_create(
            domain,
            DOMAIN,
            f"SERIAL-001-{suffix}",
            config_entry=entry,
            suggested_object_id=f"saved_{suffix}",
            original_name="Legacy name",
        )
        if customized:
            registry.async_update_entity(original.entity_id, name=f"My {suffix}")
        saved_entries[(domain, suffix)] = original
    climate_entry = registry.async_get_or_create(
        "climate",
        DOMAIN,
        "SERIAL-001",
        config_entry=entry,
        suggested_object_id="saved_stove",
    )
    model = controller.get_stove_model_for_stove.return_value
    manual_fans = next(
        group
        for group in model.model_configurations
        if group.configuration_name == "Manuale"
    )
    manual_fans.configurations.extend(
        Configuration(configuration(f"set_vent_v{number}")) for number in (2, 3)
    )
    state = controller.get_stove_state_for_stove.return_value
    state.state = "working"
    state.temp_caldaia = 55
    state.temp_fumi = 120
    state.temp_scheda = 30
    state.vel_real_coclea = 120
    status = controller.get_stove_status_for_stove.return_value
    status.temp_puffer = 45
    status.sondaWifi = 21
    status.set_vent_v2 = 2
    status.set_vent_v3 = 3

    # 2. Real platforms resolve distinct names in the server's selected language.
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    icons = json.loads(
        await hass.async_add_executor_job(
            Path("custom_components/maestro_mcz/icons.json").read_text, "utf-8"
        )
    )["entity"]

    for domain, suffix, key, english, dutch in expected_names:
        name = english if language == "en" else dutch
        entity_id = registry.async_get_entity_id(domain, DOMAIN, f"SERIAL-001-{suffix}")
        registered = registry.async_get(entity_id)
        original = saved_entries[(domain, suffix)]
        assert registered.id == original.id
        assert registered.entity_id == original.entity_id
        assert registered.original_name == name
        assert registered.translation_key == key
        expected_custom_name = f"My {suffix}" if customized else None
        assert registered.name == expected_custom_name
        if key in icons[domain]:
            assert icons[domain][key]["default"]
        if (state := hass.states.get(entity_id)) is not None:
            assert state.name == f"Living Room {expected_custom_name or name}"
            assert "icon" not in state.attributes
    assert hass.states.get(climate_entry.entity_id).name == "Living Room"
    assert registry.async_get(climate_entry.entity_id).original_name is None
    assert (
        hass.states.get(saved_entries[("sensor", "mode")].entity_id).state == "manual"
    )
    assert (
        hass.states.get(saved_entries[("sensor", "state")].entity_id).state == "working"
    )
    assert (
        hass.states.get(saved_entries[("sensor", "vel_real_coclea")].entity_id).state
        == "120"
    )
    assert (
        hass.states.get(saved_entries[("select", "toni_buzz")].entity_id).state
        == "normal"
    )

    # 3. Available fans use the same icon even when off; unavailable fans use fan-off.
    fan_id = registry.async_get_entity_id("fan", DOMAIN, "SERIAL-001-set_vent_v1")
    assert registry.async_get(fan_id).translation_key == "main_fan"
    fan_icons = icons["fan"]["main_fan"]
    account = entry.runtime_data.coordinator
    stove = account.stoves["SERIAL-001"]
    for value, silent, expected_state, expected_icon in [
        (3, False, "on", "mdi:fan"),
        (0, False, "off", "mdi:fan"),
        (3, True, "unavailable", "mdi:fan-off"),
        (3, False, "on", "mdi:fan"),
    ]:
        stove.Status.set_vent_v1 = value
        stove.Status.silent_enabled = silent
        account.async_set_updated_data(None)
        await hass.async_block_till_done()
        state = hass.states.get(fan_id)
        assert state.state == expected_state
        assert "icon" not in state.attributes
        assert (
            fan_icons["state"].get(state.state, fan_icons["default"]) == expected_icon
        )
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "language,mode_labels,working_label",
    [
        ("en", ["Manual", "Auto", "Overnight", "Comfort", "Turbo"], "Working"),
        (
            "nl",
            ["Manueel", "Automatisch", "Nachtmodus", "Comfortabel", "Krachtig"],
            "In bedrijf",
        ),
    ],
)
async def test_operating_labels_preserve_phase_detail_and_raw_text(
    hass, entry, controller, language, mode_labels, working_label, caplog
):
    """Translate supported phases without losing detail, original text, or unfamiliar readings."""
    # 1. Load the real sensors in the chosen language with mocked cloud responses.
    hass.config.language = language
    controller.get_stove_state_for_stove.return_value.state = "working"
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    translations = await async_get_translations(hass, language, "entity", {DOMAIN})
    registry = er.async_get(hass)
    account = entry.runtime_data.coordinator
    stove = account.stoves["SERIAL-001"]
    mode_id = registry.async_get_entity_id("sensor", DOMAIN, "SERIAL-001-mode")
    state_id = registry.async_get_entity_id("sensor", DOMAIN, "SERIAL-001-state")
    mode_entry = registry.async_get(mode_id)
    state_entry = registry.async_get(state_id)
    mode_prefix = f"component.{DOMAIN}.entity.sensor.{mode_entry.translation_key}.state"
    state_prefix = (
        f"component.{DOMAIN}.entity.sensor.{state_entry.translation_key}.state"
    )

    # 2. Established modes, including cloud aliases, keep their existing public values.
    public_modes = ["manual", "auto", "overnight", "comfort", "turbo"]
    mode_cases = list(zip(public_modes, public_modes, mode_labels, strict=True))
    mode_cases.extend(
        [("dynamic", "auto", mode_labels[1]), ("power", "turbo", mode_labels[4])]
    )
    for cloud_mode, public_mode, display_label in mode_cases:
        stove.State.mode = cloud_mode
        account.async_set_updated_data(None)
        await hass.async_block_till_done()
        reading = hass.states.get(mode_id)
        assert reading.state == public_mode
        assert translations[f"{mode_prefix}.{reading.state}"] == display_label
        preset_key = (
            f"component.{DOMAIN}.entity.climate.main_climate"
            f".state_attributes.preset_mode.state.{public_mode}"
        )
        assert translations[preset_key] == display_label
        assert "device_class" not in reading.attributes
        assert "options" not in reading.attributes

    # 3. Known status text is localized; new cloud values remain visible without guessing.
    stove.State.state = "working"
    account.async_set_updated_data(None)
    await hass.async_block_till_done()
    reading = hass.states.get(state_id)
    assert reading.state == "working"
    assert translations[f"{state_prefix}.{reading.state}"] == working_label
    assert "device_class" not in reading.attributes
    assert "options" not in reading.attributes
    state_cases = [
        ("off", "off", "Off", "Uit"),
        ("cleaning", "cleaning", "Cleaning", "Reinigen"),
        ("loading", "loading", "Loading phase", "Laadfase"),
        ("start-1", "start-1", "Startup phase 1", "Opstartfase 1"),
        ("start-2", "start-2", "Startup phase 2", "Opstartfase 2"),
        ("stabilization", "stabilization", "Stabilization", "Stabilisatie"),
        (
            "anti-condensation",
            "anti-condensation",
            "Anti-condensation phase",
            "Anticondensatiefase",
        ),
        ("on", "on", "On", "Aan"),
        ("turning-off", "turning-off", "Shutting down", "Uitschakelen"),
        ("cooling-down", "cooling-down", "Cooling down", "Afkoelen"),
        (
            "A01 - Mancata Accensione",
            "alarm-a01",
            "A01 - Ignition alarm",
            "A01 - Ontstekingsalarm",
        ),
        (
            "A21 - Allarme Pressostati (sic 3)",
            "alarm-a21",
            "A21 - Safety alarm",
            "A21 - Veiligheidsalarm",
        ),
        (
            "Attesa Allarme Sicurezze",
            "safety-alarm-wait",
            "Safety alarm wait",
            "Wachtfase veiligheidsalarm",
        ),
        ("Clean a Caldo", "cleaning-hot", "Cleaning (hot)", "Reiniging (warm)"),
        ("Clean a Freddo", "cleaning-cold", "Cleaning (cold)", "Reiniging (koud)"),
        ("Load a Caldo", "loading-hot", "Loading phase (hot)", "Laadfase (warm)"),
        ("Load a Freddo", "loading-cold", "Loading phase (cold)", "Laadfase (koud)"),
        ("Potenza 1", "power-1", "Power 1", "Vermogen 1"),
        ("Potenza 2", "power-2", "Power 2", "Vermogen 2"),
        ("Potenza 3", "power-3", "Power 3", "Vermogen 3"),
        ("Potenza 4", "power-4", "Power 4", "Vermogen 4"),
        ("Potenza 5", "power-5", "Power 5", "Vermogen 5"),
        ("Pulizia High", "cleaning-high", "Cleaning (High)", "Reiniging (High)"),
        ("Raffreddamento", "cooling-down", "Cooling down", "Afkoelen"),
        ("Spegnimento", "turning-off", "Shutting down", "Uitschakelen"),
        ("Stabilizzazione", "stabilization", "Stabilization", "Stabilisatie"),
        ("StandBy", "standby", "Standby", "Stand-by"),
        (
            "Start 1 a Caldo",
            "start-1-hot",
            "Startup phase 1 (hot)",
            "Opstartfase 1 (warm)",
        ),
        (
            "Start 1 a Freddo",
            "start-1-cold",
            "Startup phase 1 (cold)",
            "Opstartfase 1 (koud)",
        ),
        (
            "Start 2 a Freddo",
            "start-2-cold",
            "Startup phase 2 (cold)",
            "Opstartfase 2 (koud)",
        ),
        ("Stufa spenta", "off", "Off", "Uit"),
        ("turning-off-1", "turning-off-1", "Shutdown phase 1", "Uitschakelfase 1"),
        ("turning-off-2", "turning-off-2", "Shutdown phase 2", "Uitschakelfase 2"),
        (
            "hypercombustion",
            "hypercombustion",
            "Over-firing shutdown",
            "Uitschakeling wegens oververbranding",
        ),
        ("alarm", "alarm", "Alarm", "Alarm"),
        ("cold-test", "cold-test", "Cold test", "Koude test"),
        (
            "feed-screw-loading",
            "feed-screw-loading",
            "Feed screw loading",
            "Toevoerschroef laden",
        ),
        ("power-on", "power-on", "Power on", "Inschakeling"),
        (
            "A02 - No Fiamma",
            "alarm-a02",
            "A02 - Flame alarm",
            "A02 - Vlamalarm",
        ),
        (
            "A02 - New vendor text (detail 7)",
            "alarm-a02",
            "A02 - Flame alarm",
            "A02 - Vlamalarm",
        ),
        (
            "A02 -  Nieuwe tekst  ",
            "alarm-a02",
            "A02 - Flame alarm",
            "A02 - Vlamalarm",
        ),
        (
            "A08 - GUASTO MOTORE FUMI",
            "alarm-a08",
            "A08 - Flue-gas fan alarm",
            "A08 - Alarm rookgasventilator",
        ),
        (
            "A08 - GUASTO VENTILATORE FUMI",
            "alarm-a08",
            "A08 - Flue-gas fan alarm",
            "A08 - Alarm rookgasventilator",
        ),
        (
            "A11 - Defect transportschroef",
            "alarm-a11",
            "A11 - Auger alarm",
            "A11 - Alarm toevoerschroef",
        ),
        (
            "A21 - PRESSOSTATO",
            "alarm-a21",
            "A21 - Safety alarm",
            "A21 - Veiligheidsalarm",
        ),
        (
            "a21 - allarme pressostati (SIC 3)",
            "alarm-a21",
            "A21 - Safety alarm",
            "A21 - Veiligheidsalarm",
        ),
        (
            "A21 - Allarme Pressostati (sic 4)",
            "alarm-a21",
            "A21 - Safety alarm",
            "A21 - Veiligheidsalarm",
        ),
        (
            "A22 - SONDA AMBIENTE",
            "alarm-a22",
            "A22 - Room sensor alarm",
            "A22 - Alarm kamersensor",
        ),
        (
            "A22 - Guasto Sonda Ambiente",
            "alarm-a22",
            "A22 - Room sensor alarm",
            "A22 - Alarm kamersensor",
        ),
        (
            "A24 - Guasto Pompa",
            "alarm-a24",
            "A24 - Pump fault",
            "A24 - Pompstoring",
        ),
        (
            "A24 - PROBE FAILURE",
            "alarm-a24",
            "A24 - Pump fault",
            "A24 - Pompstoring",
        ),
    ]
    for raw_state, public_state, english, dutch in state_cases:
        stove.State.state = raw_state
        await account._async_update_data()
        account.async_set_updated_data(None)
        await hass.async_block_till_done()
        reading = hass.states.get(state_id)
        assert reading.state == public_state
        assert reading.attributes["raw_state"] == raw_state
        assert translations[f"{state_prefix}.{reading.state}"] == (
            english if language == "en" else dutch
        )
        assert "device_class" not in reading.attributes
        assert "options" not in reading.attributes
    assert not [
        record
        for record in caplog.records
        if record.message.startswith("Current state")
    ]

    # 4. Unfamiliar states stay intact and are reported only once, not on every update.
    stove.State.mode = "future-mode"
    stove.State.state = "future-state"
    for _ in range(3):
        await account._async_update_data()
        account.async_set_updated_data(None)
        await hass.async_block_till_done()
    for entity_id, prefix, raw_value in [
        (mode_id, mode_prefix, "future-mode"),
        (state_id, state_prefix, "future-state"),
    ]:
        reading = hass.states.get(entity_id)
        assert reading.state == raw_value
        assert f"{prefix}.{raw_value}" not in translations
    warnings = [
        record
        for record in caplog.records
        if record.message.startswith("Current state")
    ]
    assert len(warnings) == 1
    assert repr("future-state") in warnings[0].message
    assert hass.states.get(state_id).attributes["raw_state"] == "future-state"
    assert registry.async_get(mode_id).id == mode_entry.id
    assert registry.async_get(state_id).id == state_entry.id
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "language,display_labels",
    [("en", ["Silent", "Normal", "High"]), ("nl", ["Stil", "Normaal", "Hoog"])],
)
async def test_tone_options_translate_with_lowercase_values_and_unchanged_commands(
    hass, entry, controller, language, display_labels
):
    """Localize sound choices while keeping lowercase automation values and the same stove commands."""
    # 1. This stove offers all three sound levels, including the silent option.
    hass.config.language = language
    model = controller.get_stove_model_for_stove.return_value
    tone_group = next(
        group
        for group in model.model_configurations
        if group.configuration_name == "Toni"
    )
    tone_group.configurations[0].min = "0"
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    registry = er.async_get(hass)
    tone_id = registry.async_get_entity_id("select", DOMAIN, "SERIAL-001-toni_buzz")
    reading = hass.states.get(tone_id)
    assert reading.state == "normal"
    assert reading.attributes["options"] == ["silent", "normal", "high"]
    tone_entry = registry.async_get(tone_id)
    assert tone_entry.translation_key == "tones"
    translations = await async_get_translations(hass, language, "entity", {DOMAIN})
    prefix = f"component.{DOMAIN}.entity.select.{tone_entry.translation_key}.state"
    account = entry.runtime_data.coordinator
    stove = account.stoves["SERIAL-001"]

    # 2. Each lowercase choice has a localized label and sends the same numeric command.
    options = ["silent", "normal", "high"]
    for numeric_value, (raw_option, display_label) in enumerate(
        zip(options, display_labels, strict=True)
    ):
        assert translations[f"{prefix}.{raw_option}"] == display_label
        with patch.object(
            account, "update_data_after_set", new_callable=AsyncMock
        ) as refresh:
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": tone_id, "option": raw_option},
                blocking=True,
            )
            activation = controller.activate_program_with_commands_for_stove.await_args
            command = activation.args[4][0]
            assert command.SensorId == "id-toni_buzz"
            assert command.Value == numeric_value
            refresh.assert_awaited_once()

        # 3. Reading that level back preserves its lowercase state and choices.
        stove.Status.toni_buzz = numeric_value
        account.async_set_updated_data(None)
        await hass.async_block_till_done()
        reading = hass.states.get(tone_id)
        assert reading.state == raw_option
        assert reading.attributes["options"] == options
    assert registry.async_get(tone_id).id == tone_entry.id

    # 4. Old capitalized automation values must be updated, not sent as stove commands.
    controller.activate_program_with_commands_for_stove.reset_mock()
    for old_option in ["Silent", "Normal", "High"]:
        with pytest.raises(ServiceValidationError):
            await hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": tone_id, "option": old_option},
                blocking=True,
            )
    controller.activate_program_with_commands_for_stove.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "language,expected_name", [("en", "Room fan"), ("nl", "Kamerventilator")]
)
async def test_hydro_room_fan_uses_its_own_translated_name(
    hass, entry, controller, configuration, language, expected_name
):
    """Keep hydro ventilation distinct from numbered air fans without changing its identity."""
    # 1. The model exposes fixed boiler ventilation instead of mode-dependent air fans.
    hass.config.language = language
    model = controller.get_stove_model_for_stove.return_value
    model.model_configurations.append(
        ModelConfiguration(
            {
                "ConfigurationName": "BOILER",
                "ConfigurationId": "boiler-fan",
                "Timed": False,
                "Limitations": None,
                "Configurations": [configuration("set_vent_v1")],
            }
        )
    )

    # 2. Load the real fan platform with mocked cloud responses.
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    # 3. Hydro ventilation has a localized name and retains its previous unique ID.
    registry = er.async_get(hass)
    fan_id = registry.async_get_entity_id("fan", DOMAIN, "SERIAL-001-set_vent_v1")
    registered = registry.async_get(fan_id)
    assert registered.translation_key == "room_fan"
    assert registered.original_name == expected_name
    assert hass.states.get(fan_id).name == f"Living Room {expected_name}"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "unit_system,current_temperature,target_temperature,setpoint",
    [
        (METRIC_SYSTEM, 20.5, 22, 23.5),
        (US_CUSTOMARY_SYSTEM, 69, 72, 74.3),
    ],
    ids=["celsius", "fahrenheit"],
)
async def test_real_platform_setup_services_and_unload(
    hass,
    entry,
    controller,
    caplog,
    unit_system,
    current_temperature,
    target_temperature,
    setpoint,
):
    """Display temperatures in the user's units but always send Celsius settings to the stove."""
    # 1. Load the real integration, replacing only its connection to the cloud.
    hass.config.units = unit_system
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        assert setup_succeeded
        await hass.async_block_till_done()

        registry = er.async_get(hass)
        registered = er.async_entries_for_config_entry(registry, entry.entry_id)
        registered_platforms = {registered_entity.domain for registered_entity in registered}
        assert registered_platforms == {
            "binary_sensor",
            "button",
            "climate",
            "datetime",
            "fan",
            "number",
            "select",
            "sensor",
            "switch",
        }
        climate_entity_id = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
        alarm_entity_id = registry.async_get_entity_id(
            "sensor", DOMAIN, "SERIAL-001-last_alarm"
        )
        # 2. The heating control and alarm reading appear in Home Assistant.
        climate_state = hass.states.get(climate_entity_id)
        assert climate_state.state == "heat"
        assert climate_state.attributes["current_temperature"] == current_temperature
        assert climate_state.attributes["temperature"] == target_temperature
        assert not any(
            "MczClimateEntity" in record.message and "deprecated" in record.message
            for record in caplog.records
        )
        assert hass.states.get(alarm_entity_id).state == "A00"

        # 3. Change the target temperature through HA, as a user would.
        with patch.object(
            entry.runtime_data.coordinator,
            "update_data_after_set",
            new_callable=AsyncMock,
        ) as refresh:
            await hass.services.async_call(
                "climate",
                "set_temperature",
                {"entity_id": climate_entity_id, "temperature": setpoint},
                blocking=True,
            )
            activation = controller.activate_program_with_commands_for_stove.await_args
            sent_commands = activation.args[4]
            temperature_command = sent_commands[0]
            assert temperature_command.SensorId == "id-set_amb1"
            assert temperature_command.Value == pytest.approx(23.5)
            refresh.assert_awaited_once()

        # 4. Unloading removes the active integration and marks its control unavailable.
        unload_succeeded = await hass.config_entries.async_unload(entry.entry_id)
        assert unload_succeeded
        await hass.async_block_till_done()
        assert entry.state is ConfigEntryState.NOT_LOADED
        assert hass.states.get(climate_entity_id).state == "unavailable"


@pytest.mark.parametrize(
    "failure_type", [MaestroAuthenticationException, MaestroConnectionException]
)
async def test_real_service_failure_reports_error_and_starts_only_needed_reauth(
    hass, entry, controller, failure_type
):
    """Show a failed action in HA and open password recovery only when sign-in is rejected."""
    # 1. Load a working account, then make its next setting command fail.
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        assert setup_succeeded
        await hass.async_block_till_done()
    registry = er.async_get(hass)
    climate_entity_id = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
    failure = failure_type("service unavailable")
    command = controller.activate_program_with_commands_for_stove
    command.side_effect = failure

    # 2. Call HA's temperature action rather than invoking an entity method directly.
    with (
        patch.object(
            entry.runtime_data.coordinator,
            "update_data_after_set",
            new_callable=AsyncMock,
        ) as refresh,
        pytest.raises(HomeAssistantError) as raised,
    ):
        await hass.services.async_call(
            "climate",
            "set_temperature",
            {"entity_id": climate_entity_id, "temperature": 23},
            blocking=True,
        )
    await hass.async_block_till_done()

    # 3. The failure reaches the user once, without replay or removal of the account.
    assert raised.value.__cause__ is failure
    command.assert_awaited_once()
    refresh.assert_not_awaited()
    assert entry.state is ConfigEntryState.LOADED
    pending_flows = hass.config_entries.flow.async_progress()
    if failure_type is MaestroAuthenticationException:
        assert "sign in again" in str(raised.value)
        assert len(pending_flows) == 1
        assert pending_flows[0]["step_id"] == "reauth_confirm"
        assert pending_flows[0]["context"]["entry_id"] == entry.entry_id
    else:
        assert "Check the stove's state" in str(raised.value)
        assert pending_flows == []
