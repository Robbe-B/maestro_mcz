"""Cloud requests, bounded authentication recovery, and command regression tests."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

import aiohttp
import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.loader import async_get_integration

from custom_components.maestro_mcz.maestro.controller import maestro_controller
from custom_components.maestro_mcz.maestro.controller.const import (
    ACTIVATE_PROGRAM_URL,
    APPLIANCE_URL,
    CONSUMPTION_URL,
    CONTENT_TYPE,
    LOGIN_URL,
    PING_URL,
    STOVE_INFO_URL,
    STOVE_MODEL_URL,
    TENTANT_ID,
)
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
    MaestroController,
)
from custom_components.maestro_mcz.maestro.controller.requests.activate_program import (
    ProgramCommand,
)
from custom_components.maestro_mcz.maestro.controller.responses.counters import Counters
from custom_components.maestro_mcz.maestro.controller.responses.model import Model
from custom_components.maestro_mcz.maestro.controller.responses.state import State
from custom_components.maestro_mcz.maestro.controller.responses.status import Status


def response(status=200, payload=None, error=None, headers=None):
    """Build a pretend HTTP reply usable by the controller's real request code."""
    http_reply = Mock(
        status=status,
        reason="synthetic response",
        headers=headers or {},
        json=AsyncMock(return_value=payload),
    )
    # aiohttp opens replies with "async with"; an error happens while opening.
    request_context = MagicMock()
    request_context.__aenter__ = AsyncMock(return_value=http_reply, side_effect=error)
    request_context.__aexit__ = AsyncMock(return_value=False)
    return request_context


@pytest.fixture
def api():
    """Create a real controller whose network session only records calls."""
    return MaestroController(
        MagicMock(spec=aiohttp.ClientSession), "test-user", "test-password"
    )


async def test_login_sends_credentials_and_keeps_token(api):
    """Send the supplied login details and keep the returned token for later requests."""
    # 1. Make login return a known token; the controller starts logged out.
    api._session.post.return_value = response(payload={"Token": "test-token"})
    assert not api.is_authenticated
    # 2. Log in through the real controller code.
    await api._login()
    # 3. The account is authenticated and the request contains the expected details.
    assert api.is_authenticated
    api._session.post.assert_called_once_with(
        LOGIN_URL,
        json={"username": "test-user", "password": "test-password"},
        headers={"content-type": CONTENT_TYPE, "tenantid": TENTANT_ID},
        timeout=api._timeout,
    )
    assert api._timeout.total == 10


@pytest.mark.parametrize(
    ("context", "exception", "attempts"),
    [
        (response(status=400), MaestroAuthenticationException, 1),
        (response(status=401), MaestroAuthenticationException, 1),
        (response(status=403), MaestroAuthenticationException, 1),
        (response(status=500), MaestroConnectionException, 3),
        (response(status=429), MaestroConnectionException, 1),
        (response(error=TimeoutError()), MaestroConnectionException, 3),
        (response(error=aiohttp.ClientError("offline")), MaestroConnectionException, 1),
        (
            response(error=aiohttp.ClientConnectionError()),
            MaestroConnectionException,
            3,
        ),
    ],
)
async def test_login_failure_contract(api, context, exception, attempts, caplog):
    """Expose login failures so callers cannot mistake a bad account for a connected stove."""
    # 1. Supply the failed cloud reply chosen by this case.
    api._token = "stale-test-token"
    api._session.post.return_value = context
    # 2. Every failure raises the appropriate exception for HA to handle.
    with (
        patch.object(
            maestro_controller, "_wait_before_retry", new_callable=AsyncMock
        ) as wait,
        pytest.raises(exception),
    ):
        await api._login()
    # 3. No stale token or duplicate error log disguises the failed sign-in.
    assert not api.is_authenticated
    assert api._session.post.call_count == attempts
    assert wait.await_count == attempts - 1
    assert not [
        record for record in caplog.records if record.levelno >= logging.WARNING
    ]


async def test_request_serialization_and_headers(api):
    """Send text and authentication details correctly so the cloud understands the command."""
    # 1. Start with a logged-in account and a successful cloud reply.
    api._token = "test-token"
    api._session.request.return_value = response(payload={"ok": True})
    supplied_headers = {"accept": "application/json", "auth-token": "stale-token"}
    # 2. Send text containing an accented character, not just plain ASCII.
    request_result = await api.make_request(
        "POST",
        "https://example.test/api",
        headers=supplied_headers,
        body={"value": "é"},
    )
    # 3. The reply is returned and the outgoing JSON/header details stay correct.
    assert request_result == {"ok": True}
    api._session.request.assert_called_once_with(
        "POST",
        "https://example.test/api",
        data=json.dumps({"value": "é"}, ensure_ascii=False),
        headers={
            "accept": "application/json",
            "auth-token": "test-token",
            "content-type": CONTENT_TYPE,
            "tenantid": TENTANT_ID,
        },
        timeout=api._timeout,
    )
    assert supplied_headers == {
        "accept": "application/json",
        "auth-token": "stale-token",
    }


@pytest.mark.parametrize("status", [401, 403])
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_expired_token_reauthenticates_and_retries(api, status, method, caplog):
    """Renew an expired login automatically so a temporary expiry does not stop updates."""
    # 1. Reject the old token, then accept a replacement token and a retried request.
    api._token = "expired-test-token"
    api._session.request.side_effect = [
        response(status=status),
        response(payload={"ok": 1}),
    ]
    api._session.post.return_value = response(payload={"Token": "renewed-test-token"})
    # 2. Make the request using the expired login.
    request_result = await api.make_request(
        method, "https://example.test", body={"value": False}
    )
    # 3. One new login and one retry should recover the original request.
    assert request_result == {"ok": 1}
    assert api._token == "renewed-test-token"
    assert api._session.request.call_count == 2
    api._session.post.assert_called_once()
    original_request, recovered_request = api._session.request.call_args_list
    assert original_request.kwargs["headers"]["auth-token"] == "expired-test-token"
    assert recovered_request.kwargs["headers"]["auth-token"] == "renewed-test-token"
    assert original_request.kwargs["data"] == recovered_request.kwargs["data"]
    assert original_request.args == recovered_request.args
    assert "Maestro request attempt 1/3 rejected authentication" in caplog.text
    assert "Renewing authentication once" in caplog.text
    assert "expired-test-token" not in caplog.text
    assert "renewed-test-token" not in caplog.text


@pytest.mark.parametrize(
    "failure,expected_attempts",
    [
        (response(status=500), 3),
        (response(error=TimeoutError()), 3),
        (response(error=aiohttp.ClientError()), 1),
        (response(error=aiohttp.ClientConnectionError()), 3),
        (response(error=aiohttp.ClientPayloadError()), 3),
        (response(error=ValueError("invalid response")), 1),
        (response(), 1),
    ],
    ids=[
        "server-error",
        "timeout",
        "client-error",
        "network-error",
        "interrupted-response",
        "invalid-response",
        "empty-response",
    ],
)
@pytest.mark.parametrize("after_renewal", [False, True])
async def test_command_failures_obey_shared_retry_budget(
    api, failure, expected_attempts, after_renewal
):
    """Retry temporary command failures within one budget, never invalid data or permanent failures."""
    # 1. Fail a command, optionally after its old token was explicitly rejected.
    api._token = "test-token"
    request_results = [failure] * expected_attempts
    if after_renewal:
        request_results.insert(0, response(status=401))
    api._session.request.side_effect = request_results
    api._session.post.return_value = response(payload={"Token": "renewed-token"})
    callback = Mock()
    # 2. Try the setting through the real command and HTTP code.
    with (
        patch.object(
            maestro_controller, "_wait_before_retry", new_callable=AsyncMock
        ) as wait,
        pytest.raises(MaestroConnectionException),
    ):
        await api.activate_program_with_commands_for_stove(
            "device-1",
            "model-1",
            "config-1",
            "sensors-1",
            [ProgramCommand("target", 22.5)],
            callback,
        )
    # 3. Renewal shares the three-attempt budget and failure never calls back as success.
    total_attempts = min(3, expected_attempts + int(after_renewal))
    assert api._session.request.call_count == total_attempts
    assert wait.await_count == total_attempts - 1 - int(after_renewal)
    assert api._session.post.call_count == int(after_renewal)
    callback.assert_not_called()
    assert api.is_authenticated


@pytest.mark.parametrize("expired_token", [False, True])
async def test_login_connection_failure_propagates_without_retry(api, expired_token):
    """Leave a login outage to HA recovery rather than retrying or demanding a new password."""
    # 1. Login is unreachable, either initially or after a token expires.
    if expired_token:
        api._token = "expired-test-token"
        api._session.request.return_value = response(status=401)
    failure = MaestroConnectionException("login service unavailable")
    with (
        patch.object(
            api,
            "_login",
            new_callable=AsyncMock,
            side_effect=failure,
        ) as login,
    ):
        # 2. Ask for data and preserve the original login failure.
        with pytest.raises(MaestroConnectionException) as raised:
            await api.make_request("GET", "https://example.test")
    # 3. No repeated login or unauthenticated data request hides the outage.
    assert raised.value is failure
    login.assert_awaited_once_with()
    assert api._session.request.call_count == int(expired_token)


@pytest.mark.parametrize("expired_token", [False, True])
@pytest.mark.parametrize("login_status", [400, 401, 403])
async def test_rejected_password_propagates_during_requests(
    api, expired_token, login_status
):
    """Tell HA the password must change even when failure happens during token renewal."""
    # 1. Start logged out, or with a token that the service will reject.
    if expired_token:
        api._token = "expired-test-token"
        api._session.request.return_value = response(status=401)
    api._session.post.return_value = response(status=login_status)
    # 2. Request an update using the old saved password.
    with pytest.raises(MaestroAuthenticationException):
        await api.make_request("GET", "https://example.test")
    # 3. A rejected password is not swallowed or retried as a network outage.
    assert not api.is_authenticated
    api._session.post.assert_called_once()
    assert api._session.request.call_count == int(expired_token)


async def test_rejected_login_400_starts_automatic_setup_reauth(api, hass, entry):
    """Ask for the changed password automatically instead of repeatedly retrying setup."""
    # 1. The cloud rejects the saved password with HTTP 400 during real account login.
    api._session.post.return_value = response(status=400)
    saved_account_data = dict(entry.data)
    with (
        patch("custom_components.maestro_mcz.MaestroController", return_value=api),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Let Home Assistant set up the account without a manual recovery trigger.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # 3. Recovery targets the same account and leaves its saved credentials unchanged.
    assert setup_succeeded is False
    pending_flows = hass.config_entries.flow.async_progress()
    assert len(pending_flows) == 1
    recovery_flow = pending_flows[0]
    assert recovery_flow["step_id"] == "reauth_confirm"
    assert recovery_flow["context"]["source"] == "reauth"
    assert recovery_flow["context"]["entry_id"] == entry.entry_id
    assert entry.data == saved_account_data
    api._session.post.assert_called_once()
    api._session.request.assert_not_called()


@pytest.mark.parametrize("already_authenticated", [False, True])
async def test_new_token_rejected_by_service_requires_reauth(
    api, already_authenticated
):
    """Stop repeated token renewal when the service rejects a newly issued login."""
    # 1. Login succeeds, but the service rejects the fresh token.
    if already_authenticated:
        api._token = "expired-test-token"
    api._session.post.return_value = response(payload={"Token": "new-test-token"})
    api._session.request.return_value = response(status=403)
    # 2. Request an update rather than renewing the same rejected token forever.
    with pytest.raises(MaestroAuthenticationException):
        await api.make_request("GET", "https://example.test")
    # 3. One renewal and one replay are the absolute limit, even with bad fresh tokens.
    assert not api.is_authenticated
    assert api._session.post.call_count == 2 - int(already_authenticated)
    assert api._session.request.call_count == 2


@pytest.mark.parametrize("payload", [{}, {"Token": ""}, {"Token": 12}, []])
async def test_login_without_valid_token_is_a_service_error(api, payload):
    """Do not ask for a new password or claim success when a login reply is malformed."""
    # 1. The login endpoint responds successfully but omits a usable token.
    api._token = "old-test-token"
    api._session.post.return_value = response(payload=payload)
    # 2. Validate the response through the actual login path.
    with pytest.raises(MaestroConnectionException, match="no valid token"):
        await api._login()
    # 3. No stale token should remain usable after the failed login.
    assert not api.is_authenticated


@pytest.mark.parametrize("during_login", [False, True])
@pytest.mark.parametrize(
    "failure",
    [
        ValueError("private response body"),
        aiohttp.ContentTypeError(
            Mock(), (), status=200, message="private response body"
        ),
        aiohttp.ClientError("private network address"),
        TimeoutError("private network address"),
    ],
)
async def test_response_failures_keep_safe_details_and_cause(
    api, during_login, failure, caplog
):
    """Classify unreadable or unreachable replies without exposing their private contents."""
    # 1. Make reading the response fail after a login or ordinary request.
    api._token = "test-token"
    context = response()
    context.__aenter__.return_value.json.side_effect = failure
    api._session.request.return_value = context
    api._session.post.return_value = context
    # 2. Preserve the underlying cause while raising a useful, safe connection error.
    with (
        patch.object(maestro_controller, "_wait_before_retry", new_callable=AsyncMock),
        pytest.raises(MaestroConnectionException) as raised,
    ):
        if during_login:
            await api._login()
        else:
            await api.make_request("GET", "https://example.test/private-device")
    # 3. Neither a service error nor its body becomes an auth failure or duplicate log.
    request_failure = raised.value.__cause__
    if isinstance(failure, TimeoutError):
        assert isinstance(request_failure, MaestroConnectionException)
        assert request_failure.__cause__ is failure
    else:
        assert request_failure is failure
    assert "private" not in str(raised.value)
    assert "Maestro" in str(raised.value)
    assert not [
        record for record in caplog.records if record.levelno >= logging.WARNING
    ]
    expected_attempts = 3 if isinstance(failure, TimeoutError) else 1
    assert api._session.request.call_count == expected_attempts * int(not during_login)
    assert api._session.post.call_count == expected_attempts * int(during_login)


@pytest.mark.parametrize(
    "status,expected_attempts", [(400, 1), (404, 1), (429, 1), (500, 3), (503, 3)]
)
async def test_http_status_selects_bounded_recovery(api, status, expected_attempts):
    """Retry temporary server failures but leave permanent rejection to the caller."""
    # 1. Return the same HTTP status for each attempt.
    api._token = "test-token"
    api._session.request.return_value = response(status=status)
    # 2. Exhaust the relevant budget while keeping the original HTTP explanation.
    with (
        patch.object(
            maestro_controller, "_wait_before_retry", new_callable=AsyncMock
        ) as wait,
        pytest.raises(MaestroConnectionException, match=f"HTTP {status}"),
    ):
        await api.make_request("GET", "https://example.test")
    # 3. HA can recover later without an unnecessary password prompt or final wait.
    assert api._session.request.call_count == expected_attempts
    assert wait.await_count == expected_attempts - 1
    api._session.post.assert_not_called()


@pytest.mark.parametrize("expired_token", [False, True])
async def test_simultaneous_requests_share_login_and_renewal(api, expired_token):
    """Share one sign-in for simultaneous readings so requests do not invalidate each other."""
    # 1. Start logged out or force both readings to send the same expired token.
    if expired_token:
        api._token = "expired-token"
    both_old_requests_started = asyncio.Event()
    old_request_count = 0
    login_reply = Mock(
        status=200, json=AsyncMock(return_value={"Token": "fresh-token"})
    )

    async def open_login():
        # Give the other reading time to reach the login that is already in progress.
        await asyncio.sleep(0)
        return login_reply

    login_context = response()
    login_context.__aenter__.side_effect = open_login
    api._session.post.return_value = login_context

    @asynccontextmanager
    async def reading_response(_method, _url, *, headers, **_request_options):
        nonlocal old_request_count
        if headers["auth-token"] == "expired-token":
            old_request_count += 1
            if old_request_count == 2:
                both_old_requests_started.set()
            await both_old_requests_started.wait()
            yield Mock(status=401)
        else:
            yield Mock(status=200, json=AsyncMock(return_value={"ok": True}))

    api._session.request.side_effect = reading_response
    # 2. Fetch State and Status concurrently, as a normal stove update does.
    results = await asyncio.wait_for(
        asyncio.gather(
            api.make_request("GET", "https://example.test/State"),
            api.make_request("GET", "https://example.test/Status"),
        ),
        timeout=2,
    )
    # 3. Both readings recover, with only one shared login and no lost token.
    assert results == [{"ok": True}, {"ok": True}]
    api._session.post.assert_called_once()
    assert api._session.request.call_count == 2 + 2 * int(expired_token)
    assert api._token == "fresh-token"


async def test_late_rejection_does_not_clear_a_newer_token(api):
    """Keep a working replacement token when an older in-flight request is rejected late."""
    # 1. Delay one retried reading while another request renews its token again.
    api._token = "expired-token"
    api._session.post.side_effect = [
        response(payload={"Token": "first-new-token"}),
        response(payload={"Token": "second-new-token"}),
    ]
    slow_retry_started = asyncio.Event()
    finish_slow_retry = asyncio.Event()

    @asynccontextmanager
    async def reading_response(_method, url, *, headers, **_request_options):
        token = headers["auth-token"]
        if url.endswith("/slow") and token == "first-new-token":
            slow_retry_started.set()
            await finish_slow_retry.wait()
        if token == "second-new-token":
            yield Mock(status=200, json=AsyncMock(return_value={"ok": True}))
        else:
            yield Mock(status=401)

    api._session.request.side_effect = reading_response
    slow_reading = asyncio.create_task(
        api.make_request("GET", "https://example.test/slow")
    )
    await asyncio.wait_for(slow_retry_started.wait(), timeout=2)
    # 2. Complete another renewal, then let the older retry report its rejection.
    fast_result = await api.make_request("GET", "https://example.test/fast")
    finish_slow_retry.set()
    with pytest.raises(
        MaestroConnectionException, match="superseded authentication token"
    ) as raised:
        await slow_reading
    # 3. The late reply stays a visible temporary failure, not a bad-password signal.
    assert isinstance(raised.value.__cause__, MaestroAuthenticationException)
    assert fast_result == {"ok": True}
    assert api._token == "second-new-token"
    assert api._session.post.call_count == 2
    assert api._session.request.call_count == 4

    # 4. A later update uses the working token without another login or hidden replay.
    next_result = await api.make_request("GET", "https://example.test/next")
    assert next_result == {"ok": True}
    assert api._session.post.call_count == 2
    assert api._session.request.call_count == 5
    next_request = api._session.request.call_args
    assert next_request.kwargs["headers"]["auth-token"] == "second-new-token"


@pytest.mark.parametrize("token_state", ["current", "superseded", "cleared"])
@pytest.mark.parametrize("user_command", [False, True], ids=["polling", "command"])
async def test_replayed_token_rejection_starts_only_needed_ha_reauth(
    api, hass, entry, stove, coordinator, token_state, user_command
):
    """Ask for a password only when the rejected token is still current, not replaced."""
    # 1. Reject a replay while another request may have replaced or invalidated its token.
    integration = await async_get_integration(hass, "maestro_mcz")
    await integration.async_get_platform("config_flow")
    stove._controller = api
    api._token = "expired-token"
    api._session.post.return_value = response(payload={"Token": "renewed-token"})
    rejection = MaestroAuthenticationException("Maestro authentication rejected")

    async def reject_request(_method, _url, token, _headers, _body):
        if token == "renewed-token" and token_state != "current":
            async with api._authentication_lock:
                api._token = (
                    "newer-working-token" if token_state == "superseded" else None
                )
        raise rejection

    with patch.object(
        api, "_request_once", new_callable=AsyncMock, side_effect=reject_request
    ) as request:
        # 2. Let the real stove or polling boundary handle the controller's classification.
        if user_command:
            with pytest.raises(HomeAssistantError) as raised:
                await stove.activateProgram("power", "config-1", False)
            reported_error = raised.value
        else:
            await coordinator.async_refresh()
            reported_error = coordinator.last_exception
            assert not coordinator.last_update_success
        await hass.async_block_till_done()

        # 3. No extra replay occurs; only a genuinely rejected current token starts recovery.
        assert request.await_count == 2
        api._session.post.assert_called_once()
        pending_flows = hass.config_entries.flow.async_progress()
        if token_state == "superseded":
            failure = reported_error.__cause__
            assert isinstance(failure, MaestroConnectionException)
            request_failure = failure.__cause__
            assert isinstance(request_failure, MaestroConnectionException)
            assert request_failure.__cause__ is rejection
            assert api._token == "newer-working-token"
            assert pending_flows == []
            if user_command:
                assert reported_error.translation_key == "command_cannot_connect"
            else:
                assert isinstance(reported_error, UpdateFailed)
        else:
            assert reported_error.__cause__ is rejection
            assert not api.is_authenticated
            assert len(pending_flows) == 1
            assert pending_flows[0]["step_id"] == "reauth_confirm"
            assert pending_flows[0]["context"]["entry_id"] == entry.entry_id
            if user_command:
                assert reported_error.translation_key == "command_invalid_auth"
            else:
                assert isinstance(reported_error, ConfigEntryAuthFailed)


@pytest.mark.parametrize("missing", [None, [], {}])
async def test_account_without_devices_or_response(api, missing):
    """Distinguish an empty account from a failed discovery request during sign-in."""
    # 1. Log in successfully, then receive an empty list or no response at all.
    api._session.post.return_value = response(payload={"Token": "test-token"})
    api._session.request.return_value = response(payload=missing)
    # 2. Ask the controller which stoves belong to the account.
    if missing == []:
        linked_stoves = await api.retrieve_linked_stove_infos()
        assert linked_stoves == []
    else:
        with pytest.raises(MaestroConnectionException):
            await api.retrieve_linked_stove_infos()
    # 3. Both outcomes follow a real login and account-discovery attempt.
    api._session.post.assert_called_once()
    api._session.request.assert_called_once()
    assert api._session.request.call_args.args == ("POST", STOVE_INFO_URL)
    assert api._session.request.call_args.kwargs["data"] == "{}"


@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("get_stove_model_for_stove", ("model-id", "Living Room")),
        ("get_stove_state_for_stove", ("device-id", "Living Room")),
        ("get_stove_status_for_stove", ("device-id", "Living Room")),
    ],
)
async def test_reading_requires_a_json_object(api, method, args):
    """Reject the wrong reply shape instead of presenting it as valid stove readings."""
    # 1. The cloud returns a list where this reading needs named fields.
    api._token = "test-token"
    api._session.request.return_value = response(payload=["private reply"])

    # 2. Reading the result fails at the JSON boundary without exposing its contents.
    with pytest.raises(TypeError, match="JSON response must be an object") as error:
        await getattr(api, method)(*args)

    # 3. A malformed reply is not a transient failure and is not requested again.
    api._session.request.assert_called_once()
    assert "private reply" not in str(error.value)


@pytest.mark.parametrize("during_login", [False, True])
async def test_timeout_diagnostics_identify_stove_action_and_actual_budget(
    api, during_login, caplog
):
    """Explain which stove action exhausted its budget without leaking private request details."""
    # 1. A timeout contains private transport details that must never appear in messages.
    failure = TimeoutError("https://private-host/private-device?token=private-token")
    if during_login:
        api._session.post.return_value = response(error=failure)
    else:
        api._token = "private-token"
        api._session.request.return_value = response(error=failure)

    # 2. Run the real retry loop through a named stove action, skipping only the waits.
    with (
        patch.object(maestro_controller, "_wait_before_retry", new_callable=AsyncMock),
        pytest.raises(MaestroConnectionException) as raised,
    ):
        await api.get_stove_state_for_stove("private-device", "Living Room")

    # 3. Report the correct budget, per-attempt timeout and cause, not a guessed total duration.
    budget = "login" if during_login else "request"
    message = str(raised.value)
    assert message == (
        "State for 'Living Room': Maestro "
        f"{budget} timed out (10 s per-attempt timeout) after 3 {budget} attempts"
    )
    exhausted_failure = raised.value.__cause__
    attempt_failure = exhausted_failure.__cause__
    assert attempt_failure.__cause__ is failure
    expected_requests = 0 if during_login else 3
    expected_logins = 3 if during_login else 0
    assert api._session.request.call_count == expected_requests
    assert api._session.post.call_count == expected_logins
    assert f"Maestro {budget} attempt 1/3 failed" in caplog.text
    assert f"Maestro {budget} attempt 2/3 failed" in caplog.text
    assert "private" not in message
    assert "private" not in caplog.text
    assert "test-user" not in caplog.text
    assert "test-password" not in caplog.text
    assert not [
        record for record in caplog.records if record.levelno >= logging.WARNING
    ]


@pytest.mark.parametrize(("status", "retry_after"), [(404, None), (429, 90)])
async def test_stove_http_diagnostics_preserve_server_delay(
    api, caplog, status, retry_after
):
    """Identify a rejected stove request while leaving the server's retry delay to HA."""
    # 1. The server asks for a pause rather than allowing immediate local retries.
    api._token = "private-token"
    api._session.request.return_value = response(
        status=status,
        headers={"Retry-After": str(retry_after)} if retry_after is not None else {},
    )

    # 2. Ping the named stove through the ordinary HTTP and exception boundaries.
    with pytest.raises(MaestroConnectionException) as raised:
        await api.do_ping_for_stove("private-device", "Living Room")

    # 3. Both the HTTP reason and delay survive, without claiming an exhausted budget.
    expected_message = f"Ping for 'Living Room': Maestro request failed (HTTP {status})"
    if retry_after is not None:
        expected_message += f"; server requested a retry after {retry_after} seconds"
    assert str(raised.value) == expected_message
    assert raised.value.retry_after == retry_after
    assert raised.value.__cause__.retry_after == retry_after
    api._session.request.assert_called_once()
    assert "private" not in caplog.text
    assert not [
        record for record in caplog.records if record.levelno >= logging.WARNING
    ]


@pytest.mark.parametrize("require_unique_codes", [False, True])
async def test_account_filters_devices_without_serial(
    api, stove_info_payload, require_unique_codes
):
    """Skip unidentified stoves during setup, but never let that filtering authorize removal."""
    # 1. Include one valid stove and one device without a serial number.
    without_serial = {"Node": {"Id": "no-serial"}, "AccessControl": {}}
    with patch.object(
        api,
        "make_request",
        new_callable=AsyncMock,
        return_value=[stove_info_payload, without_serial],
    ):
        # 2. Removal must not confuse an unidentified linked stove with an absent one.
        if require_unique_codes:
            with pytest.raises(MaestroConnectionException, match="missing serial"):
                await api.retrieve_linked_stove_infos(require_unique_codes=True)
        else:
            stoves = await api.retrieve_linked_stove_infos()
            # 3. Ordinary setup still keeps only stoves with stable serial numbers.
            assert [stove.node.unique_code for stove in stoves] == ["SERIAL-001"]


@pytest.mark.parametrize(
    "stove_payload",
    [
        {},
        {"Node": None},
        {"Node": {"UniqueCode": None}},
        {"Node": {"UniqueCode": " "}},
        {"Node": {"UniqueCode": 12}},
    ],
)
async def test_device_removal_rejects_unidentifiable_linked_stoves(api, stove_payload):
    """Never mistake an incomplete account list for proof that an old stove has gone."""
    # 1. A successful cloud response contains a stove that cannot be identified safely.
    with (
        patch.object(
            api, "make_request", new_callable=AsyncMock, return_value=[stove_payload]
        ) as discover,
        pytest.raises(MaestroConnectionException),
    ):
        # 2. Read the list for a removal decision rather than ordinary setup.
        await api.retrieve_linked_stove_infos(require_unique_codes=True)
    # 3. The invalid response never becomes an empty list authorizing deletion.
    discover.assert_awaited_once()


@pytest.mark.parametrize(
    ("method", "args", "verb", "url", "payload", "result_type"),
    [
        (
            "do_ping_for_stove",
            ("device-1", "Living Room"),
            "POST",
            f"{PING_URL}/device-1",
            {},
            type(None),
        ),
        (
            "get_stove_state_for_stove",
            ("device-1", "Living Room"),
            "GET",
            f"{APPLIANCE_URL}/device-1/State",
            {"temp_amb_install": 20},
            State,
        ),
        (
            "get_stove_status_for_stove",
            ("device-1", "Living Room"),
            "GET",
            f"{APPLIANCE_URL}/device-1/Status",
            {"IsConnected": True},
            Status,
        ),
        (
            "get_stove_model_for_stove",
            ("model-1", "Living Room"),
            "GET",
            f"{STOVE_MODEL_URL}/model-1",
            None,
            Model,
        ),
        (
            "get_counters_for_stove",
            ("device-1", "Living Room"),
            "GET",
            f"{APPLIANCE_URL}/device-1/Counters",
            {"num_acc": 0},
            Counters,
        ),
    ],
)
async def test_endpoint_routing_and_failure(
    api, model_payload, method, args, verb, url, payload, result_type
):
    """Use the right cloud address for each reading and preserve the original failure."""
    # 1. Provide a valid reply for the operation chosen by this case.
    if method == "get_stove_model_for_stove":
        payload = model_payload
    with patch.object(
        api, "make_request", new_callable=AsyncMock, return_value=payload
    ) as request:
        requested_operation = getattr(api, method)
        # 2. Call that operation and check both its result and destination.
        result = await requested_operation(*args)
        assert isinstance(result, result_type)
        request.assert_awaited_once()
        sent_request = request.await_args
        assert sent_request.args[0] == verb
        # Existing methods pass the URL either by name or as the second argument.
        requested_url = sent_request.kwargs.get("url")
        if not requested_url:
            requested_url = sent_request.args[1]
        assert requested_url == url

        # 3. A later failed request must retain its useful explanation and original cause.
        failure = MaestroConnectionException("Maestro request failed (HTTP 503)")
        request.side_effect = failure
        with pytest.raises(MaestroConnectionException) as raised:
            await requested_operation(*args)
        assert raised.value.__cause__ is failure
        assert args[1] in str(raised.value)
        assert str(failure) in str(raised.value)


@pytest.mark.parametrize("payload", [[], {"num_acc": "bad"}])
async def test_counters_reject_malformed_responses(api, payload):
    """Expose invalid statistics rather than inventing a usable counter reading."""
    # 1. The endpoint responds, but its data cannot represent valid counters.
    with patch.object(
        api, "make_request", new_callable=AsyncMock, return_value=payload
    ):
        # 2. Request counters using the real controller and response parser.
        with pytest.raises((TypeError, ValueError)):
            await api.get_counters_for_stove("device-1", "Living Room")


@pytest.mark.parametrize("success", [False, {}, {"accepted": True}])
async def test_activate_program_preserves_command_values_and_callback(api, success):
    """Send the exact requested settings and report success only after the cloud accepts them."""
    # 1. Prepare a yes/no power value and a fractional temperature.
    callback = Mock()
    commands = [ProgramCommand("power", True), ProgramCommand("target", 22.5)]
    with patch.object(
        api, "make_request", new_callable=AsyncMock, return_value=success
    ) as request:
        if success is False:
            request.side_effect = MaestroConnectionException(
                "Maestro request timed out"
            )
        # 2. Send the settings with this case's accepted or rejected cloud reply.
        activation = api.activate_program_with_commands_for_stove(
            "device-1", "model-1", "config-1", "sensors-1", commands, callback
        )
        if success is False:
            with pytest.raises(MaestroConnectionException, match="timed out"):
                await activation
        else:
            await activation
    # 3. Values and IDs are unchanged, including booleans and fractional numbers.
    request.assert_awaited_once_with(
        "POST",
        url=f"{ACTIVATE_PROGRAM_URL}/device-1",
        body={
            "ModelId": "model-1",
            "ConfigurationId": "config-1",
            "SensorSetTypeId": "sensors-1",
            "Commands": [
                {"SensorId": "power", "Value": True},
                {"SensorId": "target", "Value": 22.5},
            ],
        },
    )
    # An empty dictionary still counts as acceptance; an exception prevents the callback.
    if success is False:
        callback.assert_not_called()
    else:
        callback.assert_called_once()


async def test_consumption_request_uses_serial_and_preserves_zero(api):
    """Fetch the right stove's dated history without mistaking zero use for missing data."""
    # 1. The account is logged in and the service reports no use on the requested day.
    api._token = "test-token"
    api._session.request.return_value = response(
        payload={
            "Data": [{"Date": "20261112", "Consumption": 0}],
            "Total": 0,
            "VsPreviousInterval": -100,
        }
    )

    # 2. Request the stove's history for the selected date.
    history = await api.get_consumption_for_stove("SERIAL-001", date(2026, 11, 12))

    # 3. The serial, date, and exact zero reading survive the real HTTP/parsing path.
    request_arguments = api._session.request.call_args
    assert request_arguments.args[0] == "GET"
    assert request_arguments.args[1] == f"{CONSUMPTION_URL}/SERIAL-001/week/20261112"
    assert request_arguments.kwargs["headers"]["auth-token"] == "test-token"
    assert request_arguments.kwargs["data"] == "null"
    assert history.consumption_for_date(date(2026, 11, 12)) == 0
    assert history.consumption_for_date(date(2026, 11, 11)) is None


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [
        (MaestroConnectionException("service unavailable"), MaestroConnectionException),
        ({}, ValueError),
    ],
    ids=["request-failed", "invalid-history"],
)
async def test_consumption_classifies_failure_after_normal_request(
    api, payload, expected_error
):
    """Keep request failures separate from malformed history without changing other endpoints."""
    # 1. The shared request handler returns a failure or an invalid history response.
    with patch.object(
        api, "make_request", new_callable=AsyncMock, return_value=payload
    ) as request:
        if isinstance(payload, MaestroConnectionException):
            request.side_effect = payload
        # 2. Let the consumption endpoint interpret the result.
        with pytest.raises(expected_error):
            await api.get_consumption_for_stove("SERIAL-001", date(2026, 11, 12))

    # 3. Consumption uses the same default request behavior as other readings.
    request.assert_awaited_once_with(
        "GET", f"{CONSUMPTION_URL}/SERIAL-001/week/20261112"
    )


@pytest.mark.parametrize(
    ("status", "expected_error", "expected_attempts"),
    [
        (400, MaestroConnectionException, 1),
        (401, MaestroAuthenticationException, 2),
        (403, MaestroAuthenticationException, 2),
        (404, MaestroConnectionException, 1),
        (429, MaestroConnectionException, 1),
        (503, MaestroConnectionException, 3),
    ],
)
async def test_consumption_http_failure_is_classified(
    api, status, expected_error, expected_attempts
):
    """Request sign-in recovery for rejected history credentials, not service failures."""
    # 1. Every request is rejected, even if an expired token is renewed.
    api._token = "test-token"
    api._session.request.return_value = response(status=status)
    api._session.post.return_value = response(payload={"Token": "renewed-token"})
    # 2. Ask for optional history through the real request handler.
    with (
        patch.object(
            maestro_controller, "_wait_before_retry", new_callable=AsyncMock
        ) as wait,
        pytest.raises(expected_error),
    ):
        await api.get_consumption_for_stove("private-serial", date(2026, 11, 12))

    # 3. Renew authentication once, or retry a temporary read failure within its budget.
    assert api._session.request.call_count == expected_attempts
    assert wait.await_count == (2 if status == 503 else 0)


@pytest.mark.parametrize(
    "failure", [TimeoutError(), aiohttp.ClientConnectionError("offline")]
)
async def test_consumption_network_failure_is_not_empty_history(api, failure):
    """Report unreachable history as a failure, never as a successful zero-consumption day."""
    # 1. A history request fails before an HTTP response is received.
    api._token = "test-token"
    api._session.request.return_value = response(error=failure)
    # 2. Try a short recovery before leaving a sustained outage to Home Assistant.
    with (
        patch.object(
            maestro_controller, "_wait_before_retry", new_callable=AsyncMock
        ) as wait,
        pytest.raises(MaestroConnectionException) as raised,
    ):
        await api.get_consumption_for_stove("SERIAL-001", date(2026, 11, 12))

    # 3. The original cause survives and a failed fetch is not empty history.
    request_failure = raised.value.__cause__
    exhausted_failure = request_failure.__cause__
    assert exhausted_failure.__cause__ is failure
    assert api._session.request.call_count == 3
    assert wait.await_count == 2


async def test_consumption_login_failure_requires_reauth(api):
    """Request a new password when history cannot log in, rather than retrying bad credentials."""
    # 1. The account has no usable token and its credentials are rejected.
    api._session.post.return_value = response(status=401)

    # 2. Ask for consumption history using the real login path.
    with pytest.raises(MaestroAuthenticationException, match="Failed to login"):
        await api.get_consumption_for_stove("SERIAL-001", date(2026, 11, 12))

    # 3. No history request is sent without a valid login.
    api._session.request.assert_not_called()
    api._session.post.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        response(status=408),
        response(status=500),
        response(status=502),
        response(status=503),
        response(status=504),
        response(error=TimeoutError()),
        response(error=aiohttp.ClientConnectionError("offline")),
        response(error=aiohttp.ClientPayloadError("incomplete transfer")),
    ],
)
async def test_read_recovers_after_brief_outage(api, failure):
    """Keep a brief cloud outage from interrupting readings when a short retry succeeds."""
    # 1. Fail one read, then return a recognizable stove reading.
    api._token = "test-token"
    api._session.request.side_effect = [
        failure,
        response(payload={"temp_amb_install": 20}),
    ]
    with patch.object(
        maestro_controller, "_wait_before_retry", new_callable=AsyncMock
    ) as wait:
        # 2. Fetch a real read-only endpoint.
        state = await api.get_stove_state_for_stove("device-1", "Living Room")
    # 3. One short wait recovers the reading, without another login.
    assert state.temp_amb_install == 20
    assert api._session.request.call_count == 2
    api._session.post.assert_not_called()
    wait.assert_awaited_once_with(0)


async def test_post_discovery_and_ping_share_transient_retries(api):
    """Recover discovery and ping outages through the same bounded request handling."""
    # 1. Account discovery and the following ping each briefly fail.
    api._token = "test-token"
    api._session.request.side_effect = [
        response(status=503),
        response(payload=[]),
        response(status=503),
        response(payload={}),
    ]
    with patch.object(
        maestro_controller, "_wait_before_retry", new_callable=AsyncMock
    ) as wait:
        # 2. Read the stove list, then try the separate ping operation.
        stoves = await api.retrieve_linked_stove_infos()
        await api.do_ping_for_stove("device-1", "Living Room")
    # 3. Both POST operations recover after a short wait.
    assert stoves == []
    sent_requests = api._session.request.call_args_list
    assert sent_requests[0].args == ("POST", STOVE_INFO_URL)
    assert sent_requests[1].args == ("POST", STOVE_INFO_URL)
    assert sent_requests[2].args == ("POST", f"{PING_URL}/device-1")
    assert sent_requests[3].args == ("POST", f"{PING_URL}/device-1")
    assert len(sent_requests) == 4
    assert wait.await_args_list == [call(0), call(0)]


@pytest.mark.parametrize(
    "failure",
    [
        response(status=503),
        response(error=TimeoutError()),
        response(error=aiohttp.ClientConnectionError("offline")),
        response(error=aiohttp.ClientPayloadError("incomplete transfer")),
    ],
)
async def test_transient_login_recovers_before_discovery(api, failure):
    """Recover a brief sign-in outage without asking the user to replace a working password."""
    # 1. Sign-in briefly fails, then supplies a valid token.
    api._session.post.side_effect = [failure, response(payload={"Token": "good-token"})]
    api._session.request.return_value = response(payload=[])
    with patch.object(
        maestro_controller, "_wait_before_retry", new_callable=AsyncMock
    ) as wait:
        # 2. Discover stoves through the real sign-in path.
        stoves = await api.retrieve_linked_stove_infos()
    # 3. Sign-in recovers before discovery starts.
    assert stoves == []
    assert api._token == "good-token"
    assert api._session.post.call_count == 2
    api._session.request.assert_called_once()
    wait.assert_awaited_once_with(0)


@pytest.mark.parametrize("operation_name", ["login", "read", "command"])
@pytest.mark.parametrize("failed_attempts", [1, 2, 3])
async def test_retry_backoff_grows_and_never_sleeps_after_last_attempt(
    api, operation_name, failed_attempts
):
    """Space retries without hammering the cloud or wasting time after the last failure."""
    # 1. Fail one, two, or all three attempts, with a fixed amount of jitter.
    api._token = "test-token"
    during_login = operation_name == "login"
    replies = [response(status=503) for _ in range(failed_attempts)]
    replies.append(response(payload={"Token": "good-token"} if during_login else {}))
    operation = api._session.post if during_login else api._session.request
    operation.side_effect = replies
    with (
        patch.object(maestro_controller.random, "uniform", return_value=0.25) as jitter,
        patch.object(
            maestro_controller.asyncio, "sleep", new_callable=AsyncMock
        ) as sleep,
    ):
        # 2. Attempt sign-in, a reading, or a command without waiting in real time.
        if during_login:
            request = api._login()
        elif operation_name == "command":
            request = api.activate_program_with_commands_for_stove(
                "device-1",
                "model-1",
                "config-1",
                "sensors-1",
                [ProgramCommand("power", True)],
            )
        else:
            request = api.get_stove_state_for_stove("device-1", "Living Room")
        if failed_attempts == 3:
            with pytest.raises(MaestroConnectionException):
                await request
        else:
            await request
    # 3. There are at most three attempts and only the waits preceding an actual retry.
    waits = min(failed_attempts, 2)
    assert operation.call_count == min(failed_attempts + 1, 3)
    assert sleep.await_args_list == [call(1.25), call(2.25)][:waits]
    assert jitter.call_args_list == [call(0, 0.5)] * waits


@pytest.mark.parametrize(
    "statuses,expected_error,expected_logins,expected_waits",
    [
        ([503, 401, 200], None, 1, [0]),
        ([401, 503, 200], None, 1, [1]),
        ([503, 503, 401], MaestroConnectionException, 0, [0, 1]),
        ([401, 503, 503], MaestroConnectionException, 1, [1]),
        ([401, 403], MaestroAuthenticationException, 1, []),
    ],
)
@pytest.mark.parametrize("is_command", [False, True], ids=["read", "command"])
async def test_operation_and_authentication_share_one_request_budget(
    api, statuses, expected_error, expected_logins, expected_waits, is_command
):
    """Prevent cloud outages combined with token expiry from multiplying request attempts."""
    # 1. Interleave temporary service failures with an expired or rejected token.
    api._token = "old-token"
    api._session.post.return_value = response(payload={"Token": "renewed-token"})
    api._session.request.side_effect = [
        response(status=status, payload={}) for status in statuses
    ]
    with patch.object(
        maestro_controller, "_wait_before_retry", new_callable=AsyncMock
    ) as wait:
        operation = (
            api.activate_program_with_commands_for_stove(
                "device-1",
                "model-1",
                "config-1",
                "sensors-1",
                [ProgramCommand("target", 23.5)],
            )
            if is_command
            else api.get_stove_state_for_stove("device-1", "Living Room")
        )
        # 2. Run either operation with its shared three-request budget.
        if expected_error is None:
            result = await operation
            if is_command:
                assert result is None
            else:
                assert isinstance(result, State)
        else:
            with pytest.raises(expected_error):
                await operation
    # 3. Authentication has at most one renewal and cannot add a fourth request.
    assert api._session.request.call_count == len(statuses)
    assert api._session.post.call_count == expected_logins
    assert wait.await_args_list == [call(attempt) for attempt in expected_waits]


async def test_login_and_operation_budgets_are_bounded_together(api):
    """Recover login and token expiry without multiplying each request into another retry loop."""
    # 1. Both required sign-ins recover on their third attempt, while the read also needs recovery.
    api._session.post.side_effect = [
        response(status=503),
        response(status=503),
        response(payload={"Token": "first-token"}),
        response(status=503),
        response(status=503),
        response(payload={"Token": "renewed-token"}),
    ]
    api._session.request.side_effect = [
        response(status=503),
        response(status=401),
        response(payload={}),
    ]
    with patch.object(
        maestro_controller, "_wait_before_retry", new_callable=AsyncMock
    ) as wait:
        # 2. Fetch a reading through both bounded sign-ins.
        state = await api.get_stove_state_for_stove("device-1", "Living Room")
    # 3. There are at most six login attempts and three operation attempts, never nine reads.
    assert isinstance(state, State)
    assert api._session.post.call_count == 6
    assert api._session.request.call_count == 3
    assert wait.await_args_list == [call(0), call(1), call(0), call(0), call(1)]


@pytest.mark.parametrize("status", [400, 404, 429, 501, 505])
@pytest.mark.parametrize("is_command", [False, True], ids=["read", "command"])
async def test_permanent_status_is_not_retried(api, status, is_command):
    """Do not retry permanent failures or turn rate limiting into a burst of commands or reads."""
    # 1. A request gets a response that short local retries should not repeat.
    api._token = "test-token"
    api._session.request.return_value = response(status=status)
    with patch.object(
        maestro_controller, "_wait_before_retry", new_callable=AsyncMock
    ) as wait:
        # 2. Return the original HTTP failure.
        with pytest.raises(MaestroConnectionException, match=f"HTTP {status}"):
            if is_command:
                await api.activate_program_with_commands_for_stove(
                    "device-1",
                    "model-1",
                    "config-1",
                    "sensors-1",
                    [ProgramCommand("power", True)],
                )
            else:
                await api.get_stove_state_for_stove("device-1", "Living Room")
    # 3. Neither another request nor an unnecessary login follows.
    api._session.request.assert_called_once()
    api._session.post.assert_not_called()
    wait.assert_not_awaited()


@pytest.mark.parametrize(
    "payload,parse_failure",
    [
        (None, None),
        ({}, ValueError("private malformed JSON")),
        ({}, aiohttp.ContentTypeError(Mock(), (), message="invalid content type")),
    ],
)
@pytest.mark.parametrize("is_command", [False, True], ids=["read", "command"])
async def test_invalid_response_is_not_retried(api, payload, parse_failure, is_command):
    """Report malformed replies rather than retrying commands or readings on invalid data."""
    # 1. The endpoint returns empty data or an unreadable response.
    api._token = "test-token"
    reply = response(payload=payload)
    reply.__aenter__.return_value.json.side_effect = parse_failure
    api._session.request.return_value = reply
    with patch.object(
        maestro_controller, "_wait_before_retry", new_callable=AsyncMock
    ) as wait:
        # 2. Attempt the operation through its real parsing boundary.
        with pytest.raises(MaestroConnectionException):
            if is_command:
                await api.activate_program_with_commands_for_stove(
                    "device-1",
                    "model-1",
                    "config-1",
                    "sensors-1",
                    [ProgramCommand("power", True)],
                )
            else:
                await api.get_stove_state_for_stove("device-1", "Living Room")
    # 3. Invalid data does not become an outage retry or an authentication prompt.
    api._session.request.assert_called_once()
    wait.assert_not_awaited()


@pytest.mark.parametrize("during_login", [False, True])
@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize(
    "header,expected_delay",
    [
        ("120", 120),
        ("Mon, 16 Nov 2026 10:02:00 GMT", 120),
        ("Mon, 16 Nov 2026 09:59:00 GMT", 0),
    ],
)
async def test_server_retry_after_defers_to_ha_without_local_retry(
    api, during_login, status, header, expected_delay
):
    """Respect the cloud's requested wait instead of hammering an overloaded service."""
    # 1. The cloud supplies a delay in seconds or as an HTTP date.
    api._token = "test-token"
    reply = response(status=status, headers={"Retry-After": header})
    operation = api._session.post if during_login else api._session.request
    operation.return_value = reply
    with (
        patch.object(
            maestro_controller, "_wait_before_retry", new_callable=AsyncMock
        ) as wait,
        patch.object(maestro_controller, "datetime", wraps=datetime) as clock,
    ):
        clock.now.return_value = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
        # 2. Ask for sign-in or a reading without locally waiting out the server delay.
        with pytest.raises(MaestroConnectionException) as raised:
            if during_login:
                await api._login()
            else:
                await api.get_stove_state_for_stove("device-1", "Living Room")
    # 3. HA receives the delay; a server-requested pause consumes no local retries.
    assert raised.value.retry_after == expected_delay
    assert f"HTTP {status}" in str(raised.value)
    operation.assert_called_once()
    wait.assert_not_awaited()


@pytest.mark.parametrize("header", ["invalid", "Mon, 16 Nov 2026 10:02:00"])
async def test_invalid_server_delay_preserves_the_original_failure(api, header):
    """Do not hide a rate-limit failure when the server sends an unusable wait hint."""
    # 1. The rate-limited endpoint includes a malformed or timezone-less delay.
    api._token = "test-token"
    api._session.request.return_value = response(
        status=429, headers={"Retry-After": header}
    )
    # 2. Report the HTTP error rather than a date-parser failure.
    with pytest.raises(MaestroConnectionException, match="HTTP 429") as raised:
        await api.get_stove_state_for_stove("device-1", "Living Room")
    # 3. There is no invented server delay and no tight local retry loop.
    assert raised.value.retry_after is None
    api._session.request.assert_called_once()
