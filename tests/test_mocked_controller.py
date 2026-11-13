"""Protect the diagnostics replay path used to reproduce cloud stove reports."""

from dataclasses import asdict
from datetime import date
import json
import os
from unittest.mock import Mock, patch

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.maestro import MaestroStove
from custom_components.maestro_mcz.maestro.controller.mocked_controller import (
    MockedController,
)


@pytest.fixture
def replay(tmp_path):
    """Start a replay controller with an empty folder, not a real cloud account."""
    replay_controller = MockedController(str(tmp_path))
    return replay_controller


@pytest.mark.parametrize(
    "consumption,expected_value",
    [({"value": 12.5}, 12.5), ({"value": 0}, 0), ({"value": None}, None), (None, None)],
    ids=["recorded", "zero", "no-reading", "older-report"],
)
async def test_diagnostics_replay_round_trip(
    hass, entry, replay, tmp_path, stove, consumption, expected_value
):
    """Reproduce a reported stove problem without needing the owner's physical stove."""
    # 1. Save an example stove report and a directory that should be ignored.
    payload = {
        "data": {
            "devices": {
                "Living Room": {
                    "coordinator.stove_data": {
                        "Id": stove.Id,
                        "Name": stove.Name,
                        "ModelId": stove.ModelId,
                        "SensorSetTypeId": stove.SensorSetTypeId,
                        "Model": asdict(stove.Model),
                        "State": asdict(stove.State),
                        "Status": asdict(stove.Status),
                    },
                }
            }
        }
    }
    if consumption is not None:
        payload["data"]["devices"]["Living Room"]["consumption"] = consumption
    report_file = tmp_path / "synthetic.json"
    report_file.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "ignored_directory").mkdir()
    # 2. Replay finds one report and reconstructs the stove it describes.
    report_files = await replay.get_mocked_files()
    assert len(report_files) == 1
    discovered_stoves = await replay.retrieve_linked_stove_infos()
    assert len(discovered_stoves) == 1
    replayed_stove = discovered_stoves[0]
    assert replayed_stove.node.unique_code == "Living Room_device-1_model-1"
    assert replay.is_authenticated
    # 3. Replayed readings match the report; an unknown stove has no readings.
    replayed_model = await replay.get_stove_model_for_stove("model-1", "Living Room")
    replayed_state = await replay.get_stove_state_for_stove("device-1", "Living Room")
    replayed_status = await replay.get_stove_status_for_stove("device-1", "Living Room")
    assert replayed_model.model_name == stove.Model.model_name
    assert replayed_state.temp_amb_install == 20.5
    assert replayed_status.sm_sn == replayed_stove.node.unique_code
    missing_model = await replay.get_stove_model_for_stove("missing", "unknown")
    missing_state = await replay.get_stove_state_for_stove("missing", "unknown")
    missing_status = await replay.get_stove_status_for_stove("missing", "unknown")
    assert missing_model is None
    assert missing_state is None
    assert missing_status is None
    requested_day = date(2026, 11, 12)
    replayed_consumption = await replay.get_consumption_for_stove(
        replayed_stove.node.unique_code, requested_day
    )
    unknown_consumption = await replay.get_consumption_for_stove("missing", requested_day)
    assert replayed_consumption.consumption_for_date(requested_day) == expected_value
    assert unknown_consumption.days == ()

    # 4. Commands can exercise callbacks, but replay never sends real requests.
    callback = Mock()
    await replay.activate_program_with_commands_for_stove(
        "device", "model", "config", "sensors", [], callback
    )
    callback.assert_called_once_with()
    await replay.activate_program_with_commands_for_stove(
        "device", "model", "config", "sensors", []
    )
    request_result = await replay.make_request("GET", "https://example.test")
    ping_result = await replay.do_ping_for_stove("device", "Living Room")
    assert request_result is None
    assert ping_result is None

    # 5. Real platform setup shows the saved value without creating a cloud client.
    hass.config_entries.async_update_entry(
        entry, data=dict(entry.data) | {"MOCKED_FOLDER": str(tmp_path)}
    )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController",
            side_effect=AssertionError("Replay must not create a cloud client"),
        ) as live_controller,
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert setup_succeeded
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{replayed_stove.node.unique_code}-consumption_yesterday"
    )
    if expected_value is None:
        assert entity_id is None
    else:
        assert hass.states.get(entity_id).state == str(float(expected_value))
    live_controller.assert_not_called()
    await hass.config_entries.async_unload(entry.entry_id)

    # 6. Another replay cannot borrow reports that it has not loaded itself.
    separate_replay = MockedController(str(tmp_path))
    unloaded_state = await separate_replay.get_stove_state_for_stove(
        "device-1", "Living Room"
    )
    assert unloaded_state is None


async def test_invalid_replay_file_is_reported(replay, tmp_path, caplog):
    """Explain a broken report instead of making replay look successful."""
    # 1. Put unreadable contents in what should be a JSON report.
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")
    # 2. Replay reports the problem instead of inventing a stove.
    discovered_stoves = await replay.retrieve_linked_stove_infos()
    assert discovered_stoves == []
    assert "Mocked controller failed" in caplog.text


async def test_missing_replay_directory(replay):
    """Handle a missing report folder without pretending there are available stoves."""
    # 1. Pretend the report directory cannot be opened.
    with patch(
        "custom_components.maestro_mcz.maestro.controller.mocked_controller.os.listdir",
        side_effect=OSError("missing"),
    ):
        # 2. There are no files or stoves to replay.
        report_files = await replay.get_mocked_files()
        discovered_stoves = await replay.retrieve_linked_stove_infos()
    assert report_files is None
    assert discovered_stoves == []


@pytest.mark.parametrize("current_first", [True, False])
async def test_renamed_reports_keep_their_own_readings(replay, tmp_path, stove, current_first):
    """Keep renamed reports separate so an older disconnected snapshot cannot disable another."""
    # 1. Two reports share physical IDs, but have different names and saved readings.
    snapshots = [
        ("Current snapshot", True, 20.5, 12.5),
        ("Earlier snapshot", False, 18.0, 0),
    ]
    report_files = []
    expected_readings = {}
    for number, (name, connected, temperature, consumption) in enumerate(snapshots):
        model = asdict(stove.Model)
        model["model_name"] = f"{name} model"
        state = asdict(stove.State)
        state["temp_amb_install"] = temperature
        status = asdict(stove.Status)
        status["is_connected"] = connected
        report = {
            "data": {
                "devices": {
                    name: {
                        "coordinator.stove_data": {
                            "Id": stove.Id,
                            "Name": name,
                            "ModelId": stove.ModelId,
                            "SensorSetTypeId": stove.SensorSetTypeId,
                            "Model": model,
                            "State": state,
                            "Status": status,
                        },
                        "consumption": {"value": consumption},
                    }
                }
            }
        }
        report_file = tmp_path / f"snapshot-{number}.json"
        report_file.write_text(json.dumps(report), encoding="utf-8")
        report_files.append(str(report_file))
        expected_readings[name] = (connected, temperature, consumption)
    if not current_first:
        report_files.reverse()

    # 2. Replay both files in either order, then refresh each virtual stove.
    with patch.object(replay, "get_mocked_files", return_value=report_files):
        stove_infos = await replay.retrieve_linked_stove_infos()
    assert len(stove_infos) == 2
    for info in stove_infos:
        replayed_stove = MaestroStove(replay, info)
        await replayed_stove.async_init()
        await replayed_stove.refresh()
        connected, temperature, consumption = expected_readings[info.node.name]
        history_day = date(2026, 11, 12)
        history = await replay.get_consumption_for_stove(info.node.unique_code, history_day)

        # 3. Each keeps its own model, availability, temperature, and consumption.
        assert replayed_stove.Model.model_name == f"{info.node.name} model"
        assert replayed_stove.is_connected is connected
        assert replayed_stove.State.temp_amb_install == temperature
        assert history.consumption_for_date(history_day) == consumption


@pytest.mark.parametrize("newest_connected", [True, False])
@pytest.mark.parametrize("newest_first", [True, False])
async def test_duplicate_reports_use_the_newest_file(
    replay, tmp_path, stove, newest_connected, newest_first
):
    """Use the newest snapshot so directory order cannot invent a disconnected stove."""
    # 1. Save older and newer reports with identical stove IDs and names.
    device = {
        "coordinator.stove_data": {
            "Id": stove.Id,
            "Name": stove.Name,
            "ModelId": stove.ModelId,
            "SensorSetTypeId": stove.SensorSetTypeId,
            "Model": asdict(stove.Model),
            "State": asdict(stove.State),
            "Status": asdict(stove.Status),
        },
        "consumption": {"value": 12.5},
    }
    data = device["coordinator.stove_data"]
    data["Status"]["is_connected"] = not newest_connected
    report = {"data": {"devices": {stove.Name: device}}}
    old_file = tmp_path / "z-older.json"
    old_file.write_text(json.dumps(report), encoding="utf-8")
    os.utime(old_file, (100, 100))
    data["Status"]["is_connected"] = newest_connected
    data["State"]["temp_amb_install"] = 19.0
    data["Model"]["model_name"] = "Latest snapshot model"
    device["consumption"]["value"] = 0
    new_file = tmp_path / "a-newer.json"
    new_file.write_text(json.dumps(report), encoding="utf-8")
    os.utime(new_file, (200, 200))
    directory_order = [new_file.name, old_file.name]
    if not newest_first:
        directory_order.reverse()

    # 2. Load files in either directory order and refresh the single virtual stove.
    with patch(
        "custom_components.maestro_mcz.maestro.controller.mocked_controller.os.listdir",
        return_value=directory_order,
    ):
        stove_infos = await replay.retrieve_linked_stove_infos()
    assert len(stove_infos) == 1
    replayed_stove = MaestroStove(replay, stove_infos[0])
    await replayed_stove.async_init()
    await replayed_stove.refresh()
    day = date(2026, 11, 12)
    history = await replay.get_consumption_for_stove(replayed_stove.UniqueCode, day)

    # 3. Use all saved values from the newest file, even if it records disconnection.
    assert replayed_stove.is_connected is newest_connected
    assert replayed_stove.State.temp_amb_install == 19.0
    assert replayed_stove.Model.model_name == "Latest snapshot model"
    assert history.consumption_for_date(day) == 0
