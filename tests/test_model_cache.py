"""Saving model definitions must not change how cloud-connected stoves work."""

import json
from copy import deepcopy
from dataclasses import asdict
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store, _FileStoreIO
from homeassistant.util import dt as dt_util
from homeassistant.util.file import WriteError
from homeassistant.util.json import SerializationError

from custom_components.maestro_mcz.maestro.account import MaestroAccount
from custom_components.maestro_mcz.maestro.cloud.controller.controller import (
    MaestroConnectionException,
)
from custom_components.maestro_mcz.maestro.cloud.responses.model import Model
from custom_components.maestro_mcz.model_cache import ModelCache


def saved_models(hass_storage):
    """Select only stove model files, ignoring HA's unrelated registry storage."""
    return {
        key: envelope
        for key, envelope in hass_storage.items()
        if key.startswith("maestro_mcz.model_definition.")
    }


async def test_save_reload_complete_model(hass, hass_storage, model_payload):
    """Keep every advertised rule so saving does not simplify a stove's capabilities."""
    # 1. Include timed groups, mode-specific limits and both kinds of raw mappings.
    model_payload["SensorIds"] = ["fan", "temperature"]
    model_payload["Properties"] = ["air", "timed"]
    manual_group = model_payload["ModelConfigurations"][3]
    manual_group["Timed"] = True
    manual_group["Limitations"] = "manual mode only"
    manual_control = manual_group["Configurations"][0]
    manual_control["Variants"] = ["Auto", "Silent", "1"]
    manual_control["Mappings"] = {"Auto": "auto", "Silent": 0, "1": "1"}
    manual_control["Visible"] = False
    model = Model(model_payload)
    earliest_fetch = dt_util.utcnow()

    # 2. Save and reload through a fresh HA Store, not the in-memory model.
    await ModelCache(hass).async_save_model("SERIAL-001", "model-1", "sensors-1", model)
    files = saved_models(hass_storage)
    assert len(files) == 1
    storage_key, envelope = next(iter(files.items()))
    reloaded = await Store(hass, 1, storage_key).async_load()

    # 3. The versioned snapshot retains identity and all nested metadata, not readings.
    assert envelope["version"] == 1
    assert reloaded["unique_code"] == "SERIAL-001"
    assert reloaded["model_id"] == "model-1"
    assert reloaded["sensor_set_type_id"] == "sensors-1"
    fetch_time = dt_util.parse_datetime(reloaded["fetched_at"])
    assert fetch_time is not None
    assert fetch_time >= earliest_fetch
    assert fetch_time <= dt_util.utcnow()
    assert reloaded["model"] == asdict(model)
    restored_model = Model(reloaded["model"], from_mocked_response=True)
    assert restored_model == model
    restored_manual_control = restored_model.model_configurations[3].configurations[0]
    restored_auto_control = restored_model.model_configurations[4].configurations[0]
    assert restored_manual_control.mappings == {
        "Auto": "auto",
        "Silent": 0,
        "1": "1",
    }
    assert restored_auto_control.enabled is False
    assert set(reloaded) == {
        "unique_code",
        "model_id",
        "sensor_set_type_id",
        "fetched_at",
        "model",
    }


async def test_distinct_stoves_and_replacement(hass, hass_storage, model_payload):
    """Keep stoves separate even when they share a model, and replace only a fresh snapshot."""
    # 1. Two physical stoves share a model but have different sensor sets.
    cache = ModelCache(hass)
    model = Model(model_payload)
    await cache.async_save_model("SERIAL-001", "model-1", "sensors-1", model)
    await cache.async_save_model("SERIAL-002", "model-1", "sensors-2", model)
    original_files = deepcopy(saved_models(hass_storage))

    # 2. A new cloud definition changes only the first stove.
    model.model_name = "Updated model"
    await cache.async_save_model("SERIAL-001", "model-1", "sensors-1", model)

    # 3. Both associations survive and the second stove's file remains untouched.
    files = saved_models(hass_storage)
    assert len(files) == 2
    by_serial = {
        envelope["data"]["unique_code"]: (key, envelope)
        for key, envelope in files.items()
    }
    first_key, first_snapshot = by_serial["SERIAL-001"]
    second_key, second_snapshot = by_serial["SERIAL-002"]
    assert first_key != second_key
    assert first_snapshot["data"]["model"]["model_name"] == "Updated model"
    assert second_snapshot == original_files[second_key]
    assert second_snapshot["data"]["sensor_set_type_id"] == "sensors-2"


@pytest.mark.parametrize("failure_stage", ["replacement", "serialization"])
async def test_failed_save_preserves_disk_snapshot(
    hass, tmp_path, model_payload, caplog, failure_stage
):
    """A failed save must leave the last usable definition intact on disk."""
    # 1. Use real storage in a temporary installation, with a confirmed first save.
    hass.config.config_dir = str(tmp_path)
    cache = ModelCache(hass)
    model = Model(model_payload)
    with patch("homeassistant.helpers.storage._FileStoreIO", _FileStoreIO):
        await cache.async_save_model("SERIAL-001", "model-1", "sensors-1", model)
        paths = await hass.async_add_executor_job(
            lambda: list((tmp_path / ".storage").glob("maestro_mcz.model_definition.*"))
        )
        assert len(paths) == 1
        storage_path = paths[0]
        original_content = await hass.async_add_executor_job(storage_path.read_text)

        # 2. Fail serialization or atomic replacement of an updated definition.
        model.model_name = "New definition"
        if failure_stage == "replacement":
            failing_operation = "homeassistant.util.file.AtomicWriter.commit"
            failure = OSError("Disk unavailable")
        else:
            failing_operation = (
                "homeassistant.helpers.storage.json_helper.prepare_save_json"
            )
            failure = SerializationError("Cannot serialize definition")
        with patch(failing_operation, side_effect=failure):
            await cache.async_save_model("SERIAL-001", "model-1", "sensors-1", model)

        # 3. A fresh reader sees the old file, and HA reports the save failure.
        current_content = await hass.async_add_executor_job(storage_path.read_text)
        assert current_content == original_content
        envelope = json.loads(current_content)
        reloaded = await Store(hass, 1, envelope["key"]).async_load()
        assert reloaded["model"]["model_name"] == model_payload["ModelName"]
        storage_errors = [
            record
            for record in caplog.records
            if record.name == "homeassistant.helpers.storage"
            and record.levelname == "ERROR"
        ]
        assert len(storage_errors) == 1
        assert "Error writing config" in storage_errors[0].message
        assert not any(
            record.name == "custom_components.maestro_mcz.model_cache"
            for record in caplog.records
        )


@pytest.mark.parametrize("replay", [False, True])
async def test_setup_captures_only_live_models(
    hass, entry, controller, hass_storage, replay
):
    """Save normal cloud models but never let replayed reports overwrite live definitions."""
    # 1. Choose a live account or a replay account using the same example responses.
    if replay:
        hass.config_entries.async_update_entry(
            entry, data=dict(entry.data) | {"MOCKED_FOLDER": "synthetic"}
        )
    original_entry_data = dict(entry.data)
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch(
            "custom_components.maestro_mcz.MockedController", return_value=controller
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Run the existing setup and first refresh.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # 3. Runtime still uses the fetched model, and only live accounts write a snapshot.
    assert setup_succeeded
    stove = entry.runtime_data.account.stoves["SERIAL-001"]
    assert stove.Model is controller.get_stove_model_for_stove.return_value
    assert entry.data == original_entry_data
    files = saved_models(hass_storage)
    assert len(files) == (0 if replay else 1)
    if not replay:
        snapshot = next(iter(files.values()))["data"]
        assert snapshot["unique_code"] == stove.UniqueCode
        assert snapshot["model"] == asdict(stove.Model)


async def test_capture_precedes_failed_live_refresh(
    hass, entry, controller, hass_storage
):
    """Keep a successfully fetched model even if later stove readings prevent startup."""
    # 1. Model fetching works, but the first request for live readings fails.
    controller.do_ping_for_stove.side_effect = MaestroConnectionException("Unavailable")
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Existing cloud startup must still report its failure.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # 3. Model persistence already completed before that failure occurred.
    assert not setup_succeeded
    assert entry.state is ConfigEntryState.SETUP_RETRY
    files = saved_models(hass_storage)
    assert len(files) == 1
    snapshot = next(iter(files.values()))["data"]
    assert snapshot["model"] == asdict(
        controller.get_stove_model_for_stove.return_value
    )


@pytest.mark.parametrize(
    "save_error",
    [
        WriteError("Storage unavailable"),
        OSError("Storage unavailable"),
        HomeAssistantError("Storage unavailable"),
    ],
)
async def test_failed_save_does_not_block_setup(
    hass, entry, controller, caplog, save_error
):
    """Keep cloud controls working when storage is unavailable."""
    # 1. The cloud is healthy, but the snapshot writer cannot save its data.
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
        patch(
            "homeassistant.helpers.storage._FileStoreIO.async_write",
            side_effect=save_error,
        ),
    ):
        # 2. Set up the account normally.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # 3. The stove still has its cloud model and readings, with an explicit error log.
    assert setup_succeeded
    stove = entry.runtime_data.account.stoves["SERIAL-001"]
    assert stove.Model is controller.get_stove_model_for_stove.return_value
    assert stove.is_connected
    error_loggers = {
        "homeassistant.helpers.storage",
        "custom_components.maestro_mcz.model_cache",
    }
    storage_errors = [
        record
        for record in caplog.records
        if record.name in error_loggers and record.levelname == "ERROR"
    ]
    assert len(storage_errors) == 1
    assert "Storage unavailable" in storage_errors[0].message


async def test_failed_fetch_never_uses_or_replaces_snapshot(
    hass, controller, hass_storage
):
    """A saved definition must not hide a cloud failure before fallback is implemented."""
    # 1. Save a previous model, then make the next model request fail.
    cache = ModelCache(hass)
    await cache.async_save_model(
        "SERIAL-001",
        "model-1",
        "sensors-1",
        controller.get_stove_model_for_stove.return_value,
    )
    original_files = deepcopy(saved_models(hass_storage))
    controller.get_stove_model_for_stove.side_effect = MaestroConnectionException(
        "Offline"
    )
    account = MaestroAccount(controller, on_model_fetched=cache.async_save_model)
    await account.async_load_stoves()

    # 2. Initializing still requires a successful cloud model fetch.
    with pytest.raises(MaestroConnectionException, match="Offline"):
        await account.async_initialize()

    # 3. The old snapshot survives, but runtime does not use it as a fallback.
    assert saved_models(hass_storage) == original_files
    assert account.stoves["SERIAL-001"].Model is None


async def test_replay_account_disables_capture(controller):
    """Protect live storage even if a caller accidentally offers replay a save callback."""
    # 1. Attach a recording callback to an explicitly replayed account.
    capture = AsyncMock()
    account = MaestroAccount(controller, replay=True, on_model_fetched=capture)
    await account.async_load_stoves()

    # 2. Load the replayed model normally.
    await account.async_initialize()

    # 3. Reports are usable for reproduction without being saved as live metadata.
    assert account.stoves["SERIAL-001"].Model is not None
    capture.assert_not_awaited()


async def test_missing_model_is_not_captured(controller):
    """Do not record an empty response as a successfully fetched model definition."""
    # 1. The controller has no model to return for this stove.
    controller.get_stove_model_for_stove.return_value = None
    capture = AsyncMock()
    account = MaestroAccount(controller, on_model_fetched=capture)
    await account.async_load_stoves()

    # 2. Preserve the existing initialization behavior for missing metadata.
    await account.async_initialize()

    # 3. There is no usable definition to persist.
    assert account.stoves["SERIAL-001"].Model is None
    capture.assert_not_awaited()
