"""Setup, coordinator lifecycle, and error propagation regression coverage."""

import asyncio
from contextlib import suppress
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from threading import get_ident
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.translation import async_get_translations
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant.common import MockConfigEntry

from custom_components.maestro_mcz import (
    PLATFORMS,
    _has_mocked_folder,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.coordinator import (
    MczAccountCoordinator,
    MczConsumptionCoordinator,
    MczCountersCoordinator,
    MczRuntimeData,
)
from custom_components.maestro_mcz.maestro import MaestroStove
from custom_components.maestro_mcz.maestro.account import MaestroAccount
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
    MaestroController,
)


async def test_setup_without_mocked_folder(hass):
    """Start normally without replay files, so ordinary installations need no extra folder."""
    # 1. Pretend there are no saved reports to replay.
    with patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None):
        # 2. Basic integration setup should still succeed.
        setup_succeeded = await async_setup(hass, {})
    assert setup_succeeded


async def test_setup_starts_mock_import(hass):
    """Discover replay files automatically, making reported stove problems reproducible."""
    # 1. Provide a replay folder and record the request to create a replay account.
    with (
        patch(
            "custom_components.maestro_mcz._has_mocked_folder",
            return_value="/synthetic",
        ),
        patch.object(
            hass.config_entries.flow, "async_init", new_callable=AsyncMock
        ) as flow,
    ):
        # 2. Run setup and let HA finish its background work.
        setup_succeeded = await async_setup(hass, {})
        assert setup_succeeded
        await hass.async_block_till_done()
    # 3. The new account should import reports from the folder we supplied.
    assert flow.await_args.args == ("maestro_mcz",)
    assert flow.await_args.kwargs["context"] == {"source": "import"}
    assert flow.await_args.kwargs["data"]["MOCKED_FOLDER"] == "/synthetic"


@pytest.mark.parametrize("exists", [False, True])
async def test_mock_folder_detection(hass, tmp_path, monkeypatch, exists):
    """Find existing replay folders without making HA wait for filesystem checks."""
    # 1. Prepare an isolated installation with or without the expected replay folder.
    replay_path = Path("config/custom_components/maestro_mcz/mocked")

    def prepare_folder():
        monkeypatch.chdir(tmp_path)
        if exists:
            replay_path.mkdir(parents=True)

    await hass.async_add_executor_job(prepare_folder)
    event_loop_thread = get_ident()
    checking_threads = []
    original_is_dir = Path.is_dir

    def check_directory(folder):
        checking_threads.append(get_ident())
        return original_is_dir(folder)

    # 2. Detect the real folder and record which thread performs its filesystem check.
    with patch(
        "custom_components.maestro_mcz.Path.is_dir",
        autospec=True,
        side_effect=check_directory,
    ) as directory_check:
        detected_folder = await _has_mocked_folder(hass)

    # 3. Preserve the detected path while keeping the check off HA's event-loop thread.
    expected_folder = str(replay_path) if exists else None
    assert detected_folder == expected_folder
    directory_check.assert_called_once_with(replay_path)
    assert len(checking_threads) == 1
    assert checking_threads[0] != event_loop_thread


@pytest.mark.parametrize("mocked", [False, True])
@pytest.mark.parametrize("polling_interval", [None, 10, 30, 120])
async def test_setup_entry_initializes_coordinator_and_platforms(
    hass, entry, controller, mocked, polling_interval
):
    """Use ten-second live updates even when an older installation saved another interval."""
    # 1. Prepare any old refresh setting and choose live cloud data or offline replay.
    if polling_interval is not None:
        hass.config_entries.async_update_entry(
            entry, options={"polling_interval": polling_interval}
        )
    if mocked:
        hass.config_entries.async_update_entry(
            entry, data=dict(entry.data) | {"MOCKED_FOLDER": "/synthetic"}
        )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ) as live_controller_factory,
        patch(
            "custom_components.maestro_mcz.MockedController", return_value=controller
        ) as replay_controller_factory,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ) as setup_platforms,
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Let HA set up the account and its controls.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        assert setup_succeeded
        await hass.async_block_till_done()
    # 3. Only the chosen data source should be used.
    if mocked:
        replay_controller_factory.assert_called_once()
        live_controller_factory.assert_not_called()
    else:
        live_controller_factory.assert_called_once()
        replay_controller_factory.assert_not_called()
    assert isinstance(entry.runtime_data, MczRuntimeData)
    assert isinstance(entry.runtime_data.account, MaestroAccount)
    account = entry.runtime_data.coordinator
    assert isinstance(account, MczAccountCoordinator)
    assert list(account.stoves) == ["SERIAL-001"]
    assert (
        account.stoves["SERIAL-001"] is entry.runtime_data.account.stoves["SERIAL-001"]
    )
    assert account.update_interval == timedelta(seconds=10)
    counters = account.counters_coordinators["SERIAL-001"]
    consumption = account.consumption_coordinators["SERIAL-001"]
    assert counters.update_interval == timedelta(hours=1)
    assert consumption.update_interval == timedelta(hours=1)
    setup_platforms.assert_awaited_once_with(entry, PLATFORMS)
    controller.get_stove_model_for_stove.assert_awaited_once_with(
        "model-1", "Living Room"
    )
    controller.do_ping_for_stove.assert_awaited_once_with("device-1", "Living Room")


async def test_account_logs_distinguish_configured_entries(
    hass, entry, controller, caplog
):
    """Keep cloud failure and recovery logs identifiable when two accounts use the same stove name."""
    # 1. Two saved accounts have distinct user-facing labels, not raw login details.
    hass.config_entries.async_update_entry(entry, title="Downstairs account")
    second_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Upstairs account",
        unique_id="private-second-account",
        data={"username": "private-login", "password": "private-password"},
    )
    second_entry.add_to_hass(hass)
    entries = (entry, second_entry)
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        for configured_entry in entries:
            assert configured_entry.state is ConfigEntryState.LOADED

    # 2. Let HA report a normal polling failure for each configured account.
    hass.config.components.add(DOMAIN)
    await async_get_translations(hass, "en", "exceptions", {DOMAIN})
    caplog.clear()
    controller.do_ping_for_stove.side_effect = MaestroConnectionException(
        "Ping for 'Living Room': Maestro request timed out"
    )
    for configured_entry in entries:
        account = configured_entry.runtime_data.coordinator
        assert account.name == configured_entry.title
        counters = account.counters_coordinators["SERIAL-001"]
        history = account.consumption_coordinators["SERIAL-001"]
        assert counters.name == f"{configured_entry.title} / Living Room counters"
        assert history.name == f"{configured_entry.title} / Living Room consumption"
        await account.async_refresh()

    # 3. Logs identify both accounts and the stove without adding duplicate controller errors.
    messages = [record.getMessage() for record in caplog.records]
    failures = [message for message in messages if "Error fetching" in message]
    assert len(failures) == 2
    for configured_entry in entries:
        assert any(
            f"Error fetching {configured_entry.title} data:" in message
            and "Ping for 'Living Room'" in message
            for message in failures
        )
    assert "private" not in caplog.text

    # 4. HA's recovery messages use those same labels, rather than the literal 'username'.
    controller.do_ping_for_stove.side_effect = None
    for configured_entry in entries:
        await configured_entry.runtime_data.coordinator.async_refresh()
    messages = [record.getMessage() for record in caplog.records]
    for configured_entry in entries:
        assert f"Fetching {configured_entry.title} data recovered" in messages
        assert await hass.config_entries.async_unload(configured_entry.entry_id)


async def test_accounts_own_separate_clients_stoves_and_membership(
    hass, entry, controller
):
    """Keep two accounts independent even when their stove serial numbers match."""
    # 1. Each configured account has its own authenticated client and stove objects.
    second_entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="second-account",
        data={"username": "second-user", "password": "second-password"},
    )
    second_entry.add_to_hass(hass)
    second_client = Mock(spec=MaestroController)
    second_client.is_authenticated = True
    for method in (
        "retrieve_linked_stove_infos",
        "get_stove_model_for_stove",
        "get_stove_state_for_stove",
        "get_stove_status_for_stove",
    ):
        getattr(second_client, method).return_value = deepcopy(
            getattr(controller, method).return_value
        )
    clients = {entry.data["username"]: controller, "second-user": second_client}
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController",
            side_effect=lambda session, username, password: clients[username],
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    first_account = entry.runtime_data.account
    second_account = second_entry.runtime_data.account
    assert first_account is not second_account
    assert first_account.stoves["SERIAL-001"] is not second_account.stoves["SERIAL-001"]

    # 2. A fresh removal check on one account must not replace either loaded stove map.
    controller.retrieve_linked_stove_infos.reset_mock()
    second_client.retrieve_linked_stove_infos.reset_mock()
    controller.retrieve_linked_stove_infos.return_value = []
    assert not await first_account.async_has_linked_stove({"SERIAL-001"})
    assert await second_account.async_has_linked_stove({"SERIAL-001"})
    controller.retrieve_linked_stove_infos.assert_awaited_once_with(
        require_unique_codes=True
    )
    second_client.retrieve_linked_stove_infos.assert_awaited_once_with(
        require_unique_codes=True
    )
    assert list(first_account.stoves) == ["SERIAL-001"]
    assert list(second_account.stoves) == ["SERIAL-001"]

    # 3. One account's failed polling must not use or change the other's client.
    controller.do_ping_for_stove.side_effect = MaestroConnectionException("offline")
    await entry.runtime_data.coordinator.async_refresh()
    await second_entry.runtime_data.coordinator.async_refresh()
    assert not entry.runtime_data.coordinator.last_update_success
    assert second_entry.runtime_data.coordinator.last_update_success
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_unload(second_entry.entry_id)


@pytest.mark.parametrize(
    ("error", "expected", "expected_key", "expected_messages"),
    [
        (
            MaestroAuthenticationException,
            ConfigEntryAuthFailed,
            "account_invalid_auth",
            {
                "en": "The Maestro account needs to sign in again.",
                "nl": "Meld je opnieuw aan bij het Maestro-account.",
            },
        ),
        (
            MaestroConnectionException,
            ConfigEntryNotReady,
            "account_cannot_connect",
            {
                "en": "Could not connect to the Maestro cloud: unavailable",
                "nl": "Er kon geen verbinding worden gemaakt met de Maestro-cloud: unavailable",
            },
        ),
    ],
)
@pytest.mark.parametrize("language", ["en", "nl"])
async def test_setup_account_failure(
    hass, entry, controller, error, expected, expected_key, expected_messages, language
):
    """Distinguish a rejected account from an outage so HA offers the right recovery."""
    # 1. Make account discovery fail before any controls are created.
    failure = error("unavailable")
    controller.retrieve_linked_stove_infos.side_effect = failure
    # HA includes translations in exception logs only for loaded integrations.
    hass.config.components.add(DOMAIN)
    await async_get_translations(hass, "en", "exceptions", {DOMAIN})
    translations = await async_get_translations(hass, language, "exceptions", {DOMAIN})
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ) as forward,
        pytest.raises(expected) as raised,
    ):
        # 2. Try setting up the account.
        await async_setup_entry(hass, entry)
    # 3. Setup must fail without loading empty or misleading controls.
    reported_error = raised.value
    assert reported_error.__cause__ is failure
    assert reported_error.translation_domain == DOMAIN
    assert reported_error.translation_key == expected_key
    expected_placeholders = (
        None if error is MaestroAuthenticationException else {"error": "unavailable"}
    )
    assert reported_error.translation_placeholders == expected_placeholders
    message_template = translations[
        f"component.{DOMAIN}.exceptions.{expected_key}.message"
    ]
    rendered_message = message_template.format(**(expected_placeholders or {}))
    assert rendered_message == expected_messages[language]
    assert str(reported_error) == expected_messages["en"].rstrip(".")
    forward.assert_not_awaited()


async def test_setup_connection_failure_waits_for_retry(hass, entry, controller):
    """Retry a temporary cloud outage automatically without asking for a new password."""
    # 1. The account's discovery request fails because the cloud cannot be reached.
    controller.retrieve_linked_stove_infos.side_effect = MaestroConnectionException(
        "cloud is offline"
    )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ) as forward,
    ):
        # 2. Let HA handle setup normally, including scheduling its next attempt.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    # 3. HA waits to retry and does not request new credentials or create controls.
    assert setup_succeeded is False
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert hass.config_entries.flow.async_progress() == []
    forward.assert_not_awaited()


async def test_setup_preserves_server_requested_retry_delay(hass, entry, controller):
    """Let HA wait as requested by the cloud instead of retrying an overloaded login early."""
    # 1. Discovery is temporarily blocked by a server-requested pause.
    failure = MaestroConnectionException(
        "Maestro login failed (HTTP 503)", retry_after=120
    )
    controller.retrieve_linked_stove_infos.side_effect = failure
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        pytest.raises(ConfigEntryNotReady) as raised,
    ):
        # 2. Try setup through its real Home Assistant exception boundary.
        await async_setup_entry(hass, entry)
    # 3. HA receives the original requested delay and its cause.
    assert raised.value.retry_after == 120
    assert raised.value.__cause__ is failure
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "account_cannot_connect"
    assert raised.value.translation_placeholders == {"error": str(failure)}


@pytest.mark.parametrize(
    ("data_source", "expected_key"),
    [
        ("model", "account_cannot_connect"),
        ("live", "account_cannot_connect"),
        ("statistics", "counters_cannot_connect"),
        ("consumption", "consumption_cannot_connect"),
    ],
)
async def test_coordinators_preserve_server_requested_retry_delay(
    hass, entry, coordinator, stove, controller, data_source, expected_key
):
    """Preserve server-requested pauses for setup and every independently scheduled reading."""
    # 1. The selected cloud operation asks HA to pause before its next update.
    updates = {
        "model": (coordinator, controller.get_stove_model_for_stove),
        "live": (coordinator, controller.do_ping_for_stove),
        "statistics": (
            MczCountersCoordinator(hass, entry, controller, stove),
            controller.get_counters_for_stove,
        ),
        "consumption": (
            MczConsumptionCoordinator(hass, entry, controller, stove),
            controller.get_consumption_for_stove,
        ),
    }
    update_coordinator, request = updates[data_source]
    failure = MaestroConnectionException("Maestro service is busy", retry_after=120)
    request.side_effect = failure
    # 2. Let the coordinator translate the failure for HA's scheduler.
    with pytest.raises(UpdateFailed) as raised:
        if data_source == "model":
            await update_coordinator._async_setup()
        else:
            await update_coordinator._async_update_data()
    # 3. No layer discards the pause or turns overload into a password prompt.
    assert raised.value.retry_after == 120
    assert raised.value.__cause__ is failure
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == expected_key
    assert raised.value.translation_placeholders == {"error": str(failure)}
    assert hass.config_entries.flow.async_progress() == []
    await update_coordinator.async_shutdown()


@pytest.mark.parametrize(
    "failing_request",
    [
        "retrieve_linked_stove_infos",
        "get_stove_model_for_stove",
        "do_ping_for_stove",
    ],
)
async def test_setup_authentication_starts_reauth(
    hass, entry, controller, failing_request
):
    """Show HA's password recovery prompt wherever setup discovers expired credentials."""
    # 1. Reject the account during discovery, model loading, or its first live update.
    getattr(controller, failing_request).side_effect = MaestroAuthenticationException(
        "password changed"
    )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Let HA handle setup normally, including authentication errors.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    # 3. Setup stops and offers recovery for the existing account.
    assert setup_succeeded is False
    pending_flows = hass.config_entries.flow.async_progress()
    assert len(pending_flows) == 1
    recovery_flow = pending_flows[0]
    assert recovery_flow["step_id"] == "reauth_confirm"
    assert recovery_flow["context"]["source"] == "reauth"
    assert recovery_flow["context"]["entry_id"] == entry.entry_id


@pytest.mark.parametrize("data_source", ["live", "statistics", "consumption"])
@pytest.mark.parametrize("authentication_failed", [False, True])
async def test_update_authentication_starts_reauth(
    hass, entry, coordinator, stove, controller, data_source, authentication_failed
):
    """Offer sign-in recovery for rejected live or history requests, not network outages."""
    # 1. Fail one kind of update with expired credentials or a temporary outage.
    updates = {
        "live": (coordinator, controller.do_ping_for_stove),
        "statistics": (
            MczCountersCoordinator(hass, entry, controller, stove),
            controller.get_counters_for_stove,
        ),
        "consumption": (
            MczConsumptionCoordinator(hass, entry, controller, stove),
            controller.get_consumption_for_stove,
        ),
    }
    update_coordinator, request = updates[data_source]
    failure = (
        MaestroAuthenticationException
        if authentication_failed
        else MaestroConnectionException
    )
    request.side_effect = failure("unavailable")

    # 2. Let HA handle the failed scheduled update.
    await update_coordinator.async_refresh()
    await hass.async_block_till_done()

    # 3. Only authentication failures start recovery, always for the same account.
    assert not update_coordinator.last_update_success
    pending_flows = hass.config_entries.flow.async_progress()
    if authentication_failed:
        assert len(pending_flows) == 1
        assert pending_flows[0]["step_id"] == "reauth_confirm"
        assert pending_flows[0]["context"]["entry_id"] == entry.entry_id
    else:
        assert pending_flows == []
    await update_coordinator.async_shutdown()


@pytest.mark.parametrize("result", [False, True])
async def test_unload_platforms(hass, entry, result):
    """Report whether controls unloaded successfully so HA knows the account's state."""
    # 1. Let platform unloading succeed or fail for this account.
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new_callable=AsyncMock,
        return_value=result,
    ) as unload:
        # 2. Ask the integration to unload its controls.
        unload_result = await async_unload_entry(hass, entry)
    # 3. Pass the result back to HA without hiding an unload failure.
    assert unload_result is result
    unload.assert_awaited_once_with(entry, PLATFORMS)


@pytest.mark.parametrize(
    ("language", "expected_message"),
    [
        ("en", "No stoves were found for this Maestro account."),
        ("nl", "Er zijn geen kachels gevonden voor dit Maestro-account."),
    ],
)
async def test_coordinator_empty_account(
    hass, entry, controller, language, expected_message
):
    """Report an account with no stoves instead of pretending a refresh succeeded."""
    # 1. Start with a refresh manager that has no stoves.
    coordinator = MczAccountCoordinator(
        hass, entry, "empty", MaestroAccount(controller)
    )
    translations = await async_get_translations(hass, language, "exceptions", {DOMAIN})
    # 2. Both its first setup and later refreshes must explain the missing stove.
    for method in (coordinator._async_setup, coordinator._async_update_data):
        with pytest.raises(UpdateFailed) as raised:
            await method()
        # 3. Either failure explains the empty account in the user's language.
        assert raised.value.translation_domain == DOMAIN
        assert raised.value.translation_key == "account_no_stoves"
        assert raised.value.translation_placeholders is None
        assert raised.value.__cause__ is None
        translated_message = translations[
            f"component.{DOMAIN}.exceptions.account_no_stoves.message"
        ]
        assert translated_message == expected_message


async def test_coordinator_model_failure(coordinator, stove, controller):
    """Stop setup if the stove's supported controls cannot be loaded."""
    # 1. Pretend the cloud cannot return the stove model.
    controller.get_stove_model_for_stove.side_effect = MaestroConnectionException(
        "offline"
    )
    # 2. The refresh manager should tell HA that setup failed.
    with pytest.raises(UpdateFailed) as raised:
        await coordinator._async_setup()
    assert raised.value.translation_key == "account_cannot_connect"
    assert raised.value.translation_placeholders == {"error": "offline"}


@pytest.mark.parametrize(
    ("error", "expected", "expected_key"),
    [
        (MaestroAuthenticationException, ConfigEntryAuthFailed, "account_invalid_auth"),
        (MaestroConnectionException, UpdateFailed, "account_cannot_connect"),
    ],
)
@pytest.mark.parametrize("during_setup", [False, True])
async def test_coordinator_maps_update_failures(
    coordinator, controller, error, expected, expected_key, during_setup
):
    """Distinguish expired login from connection trouble so HA can respond appropriately."""
    # 1. Make model loading or a live update fail with an account or connection error.
    failure = error("offline")
    if during_setup:
        controller.get_stove_model_for_stove.side_effect = failure
    else:
        controller.do_ping_for_stove.side_effect = failure
    # 2. HA receives the matching kind of failure, not a generic success.
    with pytest.raises(expected) as raised:
        if during_setup:
            await coordinator._async_setup()
        else:
            await coordinator._async_update_data()
    # 3. The translated failure retains its cause without exposing sign-in details.
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == expected_key
    assert raised.value.__cause__ is failure
    expected_placeholders = (
        None if error is MaestroAuthenticationException else {"error": "offline"}
    )
    assert raised.value.translation_placeholders == expected_placeholders


@pytest.mark.parametrize(
    "failure_kind", ["connection", "authentication", "backoff", "zero-backoff"]
)
@pytest.mark.parametrize("failing_device", ["device-1", "device-2"])
async def test_multi_stove_account_failure_scope(
    hass, entry, stove, controller, failure_kind, failing_device
):
    """Try every stove during an outage, but stop the account for rejected login or server delays."""
    # 1. Three already-working stoves let us observe both earlier successes and skipped requests.
    stoves = [stove]
    for number in (2, 3):
        info = deepcopy(controller.retrieve_linked_stove_infos.return_value[0])
        info.node.id = f"device-{number}"
        info.node.unique_code = f"SERIAL-00{number}"
        info.node.name = f"Room {number}"
        next_stove = MaestroStove(controller, info)
        await next_stove.async_init()
        await next_stove.refresh()
        stoves.append(next_stove)
    account = MaestroAccount(controller, stoves)
    coordinator = MczAccountCoordinator(hass, entry, "test-account", account)
    if failure_kind == "authentication":
        failure = MaestroAuthenticationException("sign in again")
        expected = ConfigEntryAuthFailed
    elif failure_kind == "connection":
        failure = MaestroConnectionException("unreachable")
        expected = UpdateFailed
    else:
        delay = 0 if failure_kind == "zero-backoff" else 120
        failure = MaestroConnectionException("wait for cloud", retry_after=delay)
        expected = UpdateFailed

    async def fail_request(device_id, _name):
        """A general outage fails every stove; account-wide errors stop at the chosen stove."""
        if failure_kind == "connection" or device_id == failing_device:
            raise failure

    controller.do_ping_for_stove.reset_mock()
    controller.do_ping_for_stove.side_effect = fail_request

    # 2. Refresh the account and retain the original cause and requested delay.
    with pytest.raises(expected) as raised:
        await coordinator._async_update_data()
    assert raised.value.__cause__ is failure
    if failure_kind != "authentication":
        assert raised.value.retry_after == failure.retry_after

    # 3. Ordinary failures visit every stove; account-wide failures never contact the next stove.
    visited_devices = [
        request.args[0] for request in controller.do_ping_for_stove.await_args_list
    ]
    if failure_kind == "connection":
        assert visited_devices == ["device-1", "device-2", "device-3"]
        for failed_stove in stoves:
            assert not failed_stove.is_connected
    else:
        expected_devices = ["device-1"]
        if failing_device == "device-2":
            expected_devices.append("device-2")
        assert visited_devices == expected_devices


async def test_coordinator_delayed_refresh_contract(coordinator):
    """Wait for a changed setting to reach the cloud before reading it back twice."""
    # 1. Record waits and refreshes without actually delaying the test.
    with (
        patch(
            "custom_components.maestro_mcz.coordinator.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep,
        patch.object(coordinator, "async_refresh", new_callable=AsyncMock) as refresh,
    ):
        # 2. Request the normal follow-up after changing a stove setting.
        await MczAccountCoordinator.update_data_after_set(coordinator)
    # 3. Both follow-up reads retain their three-second settling delay.
    assert [args.args for args in sleep.await_args_list] == [(3,), (3,)]
    assert refresh.await_count == 2


async def test_overlapping_commands_share_refreshes(coordinator):
    """Share follow-up reads without delaying commands or multiplying cloud requests."""
    # 1. Hold the first cloud read open while another command requests updates.
    refresh_started = asyncio.Event()
    release_refresh = asyncio.Event()

    async def read_cloud():
        refresh_started.set()
        await release_refresh.wait()

    with (
        patch(
            "custom_components.maestro_mcz.coordinator.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep,
        patch.object(coordinator, "async_refresh", side_effect=read_cloud) as refresh,
    ):
        first_caller = asyncio.create_task(
            MczAccountCoordinator.update_data_after_set(coordinator)
        )
        await refresh_started.wait()
        # 2. Join the running sequence rather than starting another pair of reads.
        second_caller = asyncio.create_task(
            MczAccountCoordinator.update_data_after_set(coordinator)
        )
        release_refresh.set()
        await asyncio.gather(first_caller, second_caller)

        # 3. Both callers share two reads; a later command gets a fresh sequence.
        assert refresh.await_count == 2
        assert [call.args for call in sleep.await_args_list] == [(3,), (3,)]
        await MczAccountCoordinator.update_data_after_set(coordinator)
        assert refresh.await_count == 4
        assert coordinator._command_refresh_task is None


async def test_cancelled_caller_does_not_cancel_shared_refreshes(coordinator):
    """Keep refreshing for another command when one service caller goes away."""
    # 1. Pause a shared cloud read so one caller can be cancelled midway.
    refresh_started = asyncio.Event()
    release_refresh = asyncio.Event()

    async def read_cloud():
        refresh_started.set()
        await release_refresh.wait()

    with (
        patch(
            "custom_components.maestro_mcz.coordinator.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch.object(coordinator, "async_refresh", side_effect=read_cloud) as refresh,
    ):
        first_caller = asyncio.create_task(
            MczAccountCoordinator.update_data_after_set(coordinator)
        )
        await refresh_started.wait()
        second_caller = asyncio.create_task(
            MczAccountCoordinator.update_data_after_set(coordinator)
        )
        # 2. Cancelling one caller must not cancel the shared work.
        first_caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first_caller
        release_refresh.set()
        await second_caller

    # 3. The other caller still receives both scheduled reads.
    assert refresh.await_count == 2
    assert coordinator._command_refresh_task is None


@pytest.mark.parametrize("during_refresh", [False, True])
async def test_shared_refreshes_stop_on_unload(coordinator, during_refresh):
    """Stop pending waits and active reads on unload, with no follow-up work afterward."""
    # 1. Pause either the propagation wait or the cloud read.
    work_started = asyncio.Event()
    never_released = asyncio.Event()

    async def pause_work(*_args):
        work_started.set()
        await never_released.wait()

    with (
        patch(
            "custom_components.maestro_mcz.coordinator.asyncio.sleep",
            side_effect=None if during_refresh else pause_work,
            new_callable=AsyncMock,
        ),
        patch.object(
            coordinator,
            "async_refresh",
            side_effect=pause_work if during_refresh else None,
            new_callable=AsyncMock,
        ) as refresh,
    ):
        caller = asyncio.create_task(
            MczAccountCoordinator.update_data_after_set(coordinator)
        )
        await work_started.wait()
        # 2. Unload the coordinator while the shared sequence is still running.
        await coordinator.async_shutdown()
        with suppress(asyncio.CancelledError):
            await caller
        await MczAccountCoordinator.update_data_after_set(coordinator)

    # 3. No second read or new sequence may survive unload.
    assert refresh.await_count == int(during_refresh)
    assert coordinator._command_refresh_task is None
