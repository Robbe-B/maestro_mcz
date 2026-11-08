"""Protect the diagnostics replay path used to reproduce cloud stove reports."""

from dataclasses import asdict
import json
from unittest.mock import Mock, patch

import pytest

from custom_components.maestro_mcz.maestro.controller.mocked_controller import (
    MockedController,
)


@pytest.fixture
def replay(tmp_path):
    """Start a replay controller with an empty folder, not a real cloud account."""
    replay_controller = MockedController(str(tmp_path))
    replay_controller._mocked_stoves = {}
    return replay_controller


async def test_diagnostics_replay_round_trip(replay, tmp_path, stove):
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
                    }
                }
            }
        }
    }
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
