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
    result = MockedController(str(tmp_path))
    result._mocked_stoves = {}
    return result


async def test_diagnostics_replay_round_trip(replay, tmp_path, stove):
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
    (tmp_path / "synthetic.json").write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "ignored_directory").mkdir()
    files = await replay.get_mocked_files()
    assert len(files) == 1
    found = await replay.retrieve_linked_stove_infos()
    assert len(found) == 1
    assert found[0].node.unique_code == "Living Room_device-1_model-1"
    assert replay.is_authenticated
    assert (
        await replay.get_stove_model_for_stove("model-1", "Living Room")
    ).model_name == stove.Model.model_name
    assert (
        await replay.get_stove_state_for_stove("device-1", "Living Room")
    ).temp_amb_install == 20.5
    assert (
        await replay.get_stove_status_for_stove("device-1", "Living Room")
    ).sm_sn == found[0].node.unique_code
    assert await replay.get_stove_model_for_stove("missing", "unknown") is None
    assert await replay.get_stove_state_for_stove("missing", "unknown") is None
    assert await replay.get_stove_status_for_stove("missing", "unknown") is None
    callback = Mock()
    await replay.activate_program_with_commands_for_stove(
        "device", "model", "config", "sensors", [], callback
    )
    callback.assert_called_once_with()
    await replay.activate_program_with_commands_for_stove(
        "device", "model", "config", "sensors", []
    )
    assert await replay.make_request("GET", "https://example.test") is None
    assert await replay.do_ping_for_stove("device", "Living Room") is None


async def test_invalid_replay_file_is_reported(replay, tmp_path, caplog):
    (tmp_path / "broken.json").write_text("not json", encoding="utf-8")
    assert await replay.retrieve_linked_stove_infos() == []
    assert "Mocked controller failed" in caplog.text


async def test_missing_replay_directory(replay):
    with patch(
        "custom_components.maestro_mcz.maestro.controller.mocked_controller.os.listdir",
        side_effect=OSError("missing"),
    ):
        assert await replay.get_mocked_files() is None
        assert await replay.retrieve_linked_stove_infos() == []
