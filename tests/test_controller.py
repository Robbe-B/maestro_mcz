"""Cloud wire protocol, authentication, retries, and command regression tests."""

from datetime import date
import json
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

import aiohttp
import pytest

from custom_components.maestro_mcz.maestro.controller.const import (
    ACTIVATE_PROGRAM_URL,
    APPLIANCE_URL,
    CONTENT_TYPE,
    CONSUMPTION_URL,
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
from custom_components.maestro_mcz.maestro.controller.responses.model import Model
from custom_components.maestro_mcz.maestro.controller.responses.state import State
from custom_components.maestro_mcz.maestro.controller.responses.status import Status


def response(status=200, payload=None, error=None):
    """Build a pretend HTTP reply usable by the controller's real request code."""
    http_reply = Mock(
        status=status, reason="synthetic response", json=AsyncMock(return_value=payload)
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
    login_succeeded = await api._login()
    assert login_succeeded
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
    ("context", "exception"),
    [
        (response(status=401), MaestroAuthenticationException),
        (response(status=500), MaestroAuthenticationException),
        (response(error=TimeoutError()), MaestroConnectionException),
        (response(error=aiohttp.ClientError("offline")), MaestroConnectionException),
    ],
)
@pytest.mark.parametrize("raise_errors", [False, True])
async def test_login_failure_contract(api, context, exception, raise_errors, caplog):
    """Expose login failures so callers cannot mistake a bad account for a connected stove."""
    # 1. Supply the failed cloud reply chosen by this case.
    api._session.post.return_value = context
    # 2. Some callers request an exception; others request a logged failure result.
    if raise_errors:
        with pytest.raises(exception):
            await api._login(True)
    else:
        login_succeeded = await api._login()
        assert login_succeeded is False
        assert "Failed to" in caplog.text
    # 3. Neither failure-handling mode should leave the account logged in.
    assert not api.is_authenticated


async def test_request_serialization_and_headers(api):
    """Send text and authentication details correctly so the cloud understands the command."""
    # 1. Start with a logged-in account and a successful cloud reply.
    api._token = "test-token"
    api._session.request.return_value = response(payload={"ok": True})
    # 2. Send text containing an accented character, not just plain ASCII.
    request_result = await api.make_request(
        "POST", "https://example.test/api", body={"value": "é"}
    )
    # 3. The reply is returned and the outgoing JSON/header details stay correct.
    assert request_result == {"ok": True}
    api._session.request.assert_called_once_with(
        "POST",
        "https://example.test/api",
        data=json.dumps({"value": "é"}, ensure_ascii=False),
        headers={
            "auth-token": "test-token",
            "content-type": CONTENT_TYPE,
            "tenantid": TENTANT_ID,
        },
        timeout=api._timeout,
    )


@pytest.mark.parametrize("status", [401, 403])
async def test_expired_token_reauthenticates_and_retries(api, status):
    """Renew an expired login automatically so a temporary expiry does not stop updates."""
    # 1. Reject the old token, then accept a replacement token and a retried request.
    api._token = "expired-test-token"
    api._session.request.side_effect = [
        response(status=status),
        response(payload={"ok": 1}),
    ]
    api._session.post.return_value = response(payload={"Token": "renewed-test-token"})
    # 2. Make the request using the expired login.
    request_result = await api.make_request("GET", "https://example.test")
    # 3. One new login and one retry should recover the original request.
    assert request_result == {"ok": 1}
    assert api._token == "renewed-test-token"
    assert api._session.request.call_count == 2
    api._session.post.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        response(status=500),
        response(error=TimeoutError()),
        response(error=aiohttp.ClientError()),
    ],
)
async def test_transient_request_failure_recovers(api, failure):
    """Retry a temporary network problem so a single glitch does not lose a reading."""
    # 1. Make the first request fail and the second return a recognizable value.
    api._token = "test-token"
    api._session.request.side_effect = [failure, response(payload=42)]
    with patch.object(api, "_backoff", new_callable=AsyncMock) as backoff:
        # 2. Ask for data without waiting through real retry delays.
        request_result = await api.make_request("GET", "https://example.test")
    # 3. The first retry recovers the reading.
    assert request_result == 42
    backoff.assert_awaited_once_with(0)


@pytest.mark.parametrize("avoid_retries,attempts", [(False, 3), (True, 1)])
async def test_request_retry_budget(api, avoid_retries, attempts):
    """Limit repeated failures so an unreachable cloud cannot cause endless requests."""
    # 1. Make every request fail.
    api._token = "test-token"
    api._session.request.return_value = response(status=503)
    with patch.object(api, "_backoff", new_callable=AsyncMock) as backoff:
        # 2. Use either the normal retry budget or the explicitly single-attempt mode.
        request_result = await api.make_request(
            "GET", "https://example.test", avoid_retries=avoid_retries
        )
    # 3. Failure is explicit, with exactly the allowed number of attempts and waits.
    assert request_result is None
    assert api._session.request.call_count == attempts
    expected_retry_waits = [call(attempt_number) for attempt_number in range(attempts)]
    assert backoff.await_args_list == expected_retry_waits


async def test_login_failure_exhausts_retry_budget_without_request(api):
    """Stop after repeated login failures without sending unauthenticated data requests."""
    # 1. Make login fail on every attempt.
    with (
        patch.object(
            api, "_login", new_callable=AsyncMock, return_value=False
        ) as login,
        patch.object(api, "_backoff", new_callable=AsyncMock) as backoff,
    ):
        # 2. Ask for data; the controller must try to log in first.
        request_result = await api.make_request("GET", "https://example.test")
    # 3. It stops after three login attempts and never sends the data request.
    assert request_result is None
    assert login.await_count == 3
    assert backoff.await_count == 3
    api._session.request.assert_not_called()


async def test_invalid_json_is_not_reported_as_success(api):
    """Reject an unreadable cloud reply instead of treating malformed data as a good reading."""
    # 1. Make the response body fail JSON parsing.
    api._token = "test-token"
    context = response()
    context.__aenter__.return_value.json.side_effect = ValueError("invalid JSON")
    api._session.request.return_value = context
    # 2. The caller must see the parsing error.
    with pytest.raises(ValueError, match="invalid JSON"):
        await api.make_request("GET", "https://example.test")


@pytest.mark.parametrize("status", [400, 404, 429])
async def test_non_success_client_status_is_not_retried(api, status):
    """Do not repeatedly send a request the cloud has explicitly rejected."""
    # 1. Return the non-retryable HTTP status chosen by this case.
    api._token = "test-token"
    api._session.request.return_value = response(status=status)
    with patch.object(api, "_backoff", new_callable=AsyncMock) as backoff:
        # 2. Make the rejected request.
        request_result = await api.make_request("GET", "https://example.test")
    # 3. Failure is returned after one attempt, without a retry wait.
    assert request_result is None
    api._session.request.assert_called_once()
    backoff.assert_not_awaited()


async def test_backoff_is_deterministic_without_sleeping(api):
    """Calculate the retry delay predictably without making the test wait in real time."""
    # 1. Replace the random delay addition and actual sleeping with recorded values.
    with (
        patch(
            "custom_components.maestro_mcz.maestro.controller.maestro_controller.random.uniform",
            return_value=0.25,
        ),
        patch(
            "custom_components.maestro_mcz.maestro.controller.maestro_controller.asyncio.sleep",
            new_callable=AsyncMock,
        ) as sleep,
    ):
        # 2. Calculate the delay for the third attempt (numbered from zero).
        await api._backoff(2)
    # 3. The resulting wait is the base delay plus the fixed random addition.
    sleep.assert_awaited_once_with(1.25)


@pytest.mark.parametrize("missing", [None, []])
async def test_account_without_devices(api, missing):
    """Return no stoves for an empty account instead of inventing a controllable device."""
    # 1. Log in successfully but receive no linked stoves.
    with (
        patch.object(api, "_login", new_callable=AsyncMock) as login,
        patch.object(
            api, "make_request", new_callable=AsyncMock, return_value=missing
        ) as request,
    ):
        # 2. Ask the controller which stoves belong to the account.
        linked_stoves = await api.retrieve_linked_stove_infos()
    # 3. The account was queried, and the stove list is genuinely empty.
    assert linked_stoves == []
    login.assert_awaited_once_with(True)
    request.assert_awaited_once_with("POST", STOVE_INFO_URL, body={})


async def test_account_filters_devices_without_serial(api, stove_info_payload):
    """Ignore devices without a stable identity so HA does not create unreliable entities."""
    # 1. Include one valid stove and one device without a serial number.
    without_serial = {"Node": {"Id": "no-serial"}, "AccessControl": {}}
    with (
        patch.object(api, "_login", new_callable=AsyncMock),
        patch.object(
            api,
            "make_request",
            new_callable=AsyncMock,
            return_value=[stove_info_payload, without_serial],
        ),
    ):
        # 2. Discover the account's stoves.
        stoves = await api.retrieve_linked_stove_infos()
    # 3. Only the stove with a stable serial number is kept.
    assert [stove.node.unique_code for stove in stoves] == ["SERIAL-001"]


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
    ],
)
async def test_endpoint_routing_and_failure(
    api, model_payload, method, args, verb, url, payload, result_type
):
    """Use the right cloud address for each reading and expose a missing response."""
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
        sent_request = request.await_args
        assert sent_request.args[0] == verb
        # Existing methods pass the URL either by name or as the second argument.
        requested_url = sent_request.kwargs.get("url")
        if not requested_url:
            requested_url = sent_request.args[1]
        assert requested_url == url

        # 3. A later missing reply must raise an error naming the affected stove.
        request.return_value = None
        with pytest.raises(MaestroConnectionException, match="Living Room"):
            await requested_operation(*args)


@pytest.mark.parametrize("success", [None, {}, {"accepted": True}])
async def test_activate_program_preserves_command_values_and_callback(api, success):
    """Send the exact requested settings and report success only after the cloud accepts them."""
    # 1. Prepare a yes/no power value and a fractional temperature.
    callback = Mock()
    commands = [ProgramCommand("power", True), ProgramCommand("target", 22.5)]
    with patch.object(
        api, "make_request", new_callable=AsyncMock, return_value=success
    ) as request:
        # 2. Send the settings with this case's accepted or rejected cloud reply.
        activation = api.activate_program_with_commands_for_stove(
            "device-1", "model-1", "config-1", "sensors-1", commands, callback
        )
        if success is None:
            with pytest.raises(MaestroConnectionException, match="device-1"):
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
    # An empty dictionary still counts as acceptance; only None means failure.
    if success is None:
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
    assert request_arguments.args[1] == (
        f"{CONSUMPTION_URL}/SERIAL-001/week/20261112"
    )
    assert request_arguments.kwargs["headers"]["auth-token"] == "test-token"
    assert request_arguments.kwargs["data"] == "null"
    assert history.consumption_for_date(date(2026, 11, 12)) == 0
    assert history.consumption_for_date(date(2026, 11, 11)) is None


@pytest.mark.parametrize(
    ("payload", "expected_error"),
    [(None, MaestroConnectionException), ({}, ValueError)],
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
        # 2. Let the consumption endpoint interpret the result.
        with pytest.raises(expected_error):
            await api.get_consumption_for_stove("SERIAL-001", date(2026, 11, 12))

    # 3. Consumption uses the same default request behavior as other readings.
    request.assert_awaited_once_with(
        "GET", f"{CONSUMPTION_URL}/SERIAL-001/week/20261112"
    )


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 503])
async def test_consumption_http_failure_uses_existing_request_contract(api, status):
    """Treat rejected history as unavailable while keeping the usual request retries."""
    # 1. Every request is rejected, even if an expired token is renewed.
    api._token = "test-token"
    api._session.request.return_value = response(status=status)
    api._session.post.return_value = response(payload={"Token": "renewed-token"})
    with patch.object(api, "_backoff", new_callable=AsyncMock):
        # 2. Ask for optional history through the real request handler.
        with pytest.raises(
            MaestroConnectionException, match="Failed to retrieve consumption history"
        ):
            await api.get_consumption_for_stove("private-serial", date(2026, 11, 12))

    # 3. Existing retry rules apply; a rejected response does not imply no support.
    expected_attempts = 3 if status in (401, 403, 503) else 1
    assert api._session.request.call_count == expected_attempts


@pytest.mark.parametrize("failure", [TimeoutError(), aiohttp.ClientError("offline")])
async def test_consumption_network_failure_is_not_empty_history(api, failure):
    """Report unreachable history as a failure, never as a successful zero-consumption day."""
    # 1. Every attempt fails before an HTTP response is received.
    api._token = "test-token"
    api._session.request.return_value = response(error=failure)
    with patch.object(api, "_backoff", new_callable=AsyncMock):
        # 2. Retry within the existing request budget.
        with pytest.raises(
            MaestroConnectionException, match="Failed to retrieve consumption history"
        ):
            await api.get_consumption_for_stove("SERIAL-001", date(2026, 11, 12))

    # 3. The failure is bounded, rather than retrying indefinitely.
    assert api._session.request.call_count == 3


async def test_consumption_login_failure_uses_existing_request_contract(api):
    """Keep failed login retries unchanged and mark optional history unavailable."""
    # 1. The account has no usable token and its credentials are rejected.
    api._session.post.return_value = response(status=401)

    # 2. Ask for consumption history using the real login path.
    with patch.object(api, "_backoff", new_callable=AsyncMock) as backoff:
        with pytest.raises(
            MaestroConnectionException, match="Failed to retrieve consumption history"
        ):
            await api.get_consumption_for_stove("SERIAL-001", date(2026, 11, 12))

    # 3. No history request is sent without a valid login.
    api._session.request.assert_not_called()
    assert api._session.post.call_count == 3
    assert backoff.await_count == 3
