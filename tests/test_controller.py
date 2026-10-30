"""Cloud wire protocol, authentication, retries, and command regression tests."""

import json
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

import aiohttp
import pytest

from custom_components.maestro_mcz.maestro.controller.const import (
    ACTIVATE_PROGRAM_URL,
    APPLIANCE_URL,
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
from custom_components.maestro_mcz.maestro.controller.responses.model import Model
from custom_components.maestro_mcz.maestro.controller.responses.state import State
from custom_components.maestro_mcz.maestro.controller.responses.status import Status


def response(status=200, payload=None, error=None):
    context = MagicMock()
    context.__aenter__ = AsyncMock(side_effect=error)
    context.__aexit__ = AsyncMock(return_value=False)
    context.__aenter__.return_value = Mock(
        status=status, reason="synthetic response", json=AsyncMock(return_value=payload)
    )
    return context


@pytest.fixture
def api():
    return MaestroController(
        MagicMock(spec=aiohttp.ClientSession), "test-user", "test-password"
    )


async def test_login_sends_credentials_and_keeps_token(api):
    api._session.post.return_value = response(payload={"Token": "test-token"})
    assert not api.is_authenticated
    assert await api._login()
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
    api._session.post.return_value = context
    if raise_errors:
        with pytest.raises(exception):
            await api._login(True)
    else:
        assert await api._login() is False
        assert "Failed to" in caplog.text
    assert not api.is_authenticated


async def test_request_serialization_and_headers(api):
    api._token = "test-token"
    api._session.request.return_value = response(payload={"ok": True})
    assert await api.make_request(
        "POST", "https://example.test/api", body={"value": "é"}
    ) == {"ok": True}
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
    api._token = "expired-test-token"
    api._session.request.side_effect = [
        response(status=status),
        response(payload={"ok": 1}),
    ]
    api._session.post.return_value = response(payload={"Token": "renewed-test-token"})
    assert await api.make_request("GET", "https://example.test") == {"ok": 1}
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
    api._token = "test-token"
    api._session.request.side_effect = [failure, response(payload=42)]
    with patch.object(api, "_backoff", new_callable=AsyncMock) as backoff:
        assert await api.make_request("GET", "https://example.test") == 42
    backoff.assert_awaited_once_with(0)


@pytest.mark.parametrize("avoid_retries,attempts", [(False, 3), (True, 1)])
async def test_request_retry_budget(api, avoid_retries, attempts):
    api._token = "test-token"
    api._session.request.return_value = response(status=503)
    with patch.object(api, "_backoff", new_callable=AsyncMock) as backoff:
        assert (
            await api.make_request(
                "GET", "https://example.test", avoid_retries=avoid_retries
            )
            is None
        )
    assert api._session.request.call_count == attempts
    assert backoff.await_args_list == [call(i) for i in range(attempts)]


async def test_login_failure_exhausts_retry_budget_without_request(api):
    with (
        patch.object(
            api, "_login", new_callable=AsyncMock, return_value=False
        ) as login,
        patch.object(api, "_backoff", new_callable=AsyncMock) as backoff,
    ):
        assert await api.make_request("GET", "https://example.test") is None
    assert login.await_count == backoff.await_count == 3
    api._session.request.assert_not_called()


async def test_invalid_json_is_not_reported_as_success(api):
    api._token = "test-token"
    context = response()
    context.__aenter__.return_value.json.side_effect = ValueError("invalid JSON")
    api._session.request.return_value = context
    with pytest.raises(ValueError, match="invalid JSON"):
        await api.make_request("GET", "https://example.test")


@pytest.mark.parametrize("status", [400, 404, 429])
async def test_non_success_client_status_is_not_retried(api, status):
    api._token = "test-token"
    api._session.request.return_value = response(status=status)
    with patch.object(api, "_backoff", new_callable=AsyncMock) as backoff:
        assert await api.make_request("GET", "https://example.test") is None
    api._session.request.assert_called_once()
    backoff.assert_not_awaited()


async def test_backoff_is_deterministic_without_sleeping(api):
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
        await api._backoff(2)
    sleep.assert_awaited_once_with(1.25)


@pytest.mark.parametrize("missing", [None, []])
async def test_account_without_devices(api, missing):
    with (
        patch.object(api, "_login", new_callable=AsyncMock) as login,
        patch.object(
            api, "make_request", new_callable=AsyncMock, return_value=missing
        ) as request,
    ):
        assert await api.retrieve_linked_stove_infos() == []
    login.assert_awaited_once_with(True)
    request.assert_awaited_once_with("POST", STOVE_INFO_URL, body={})


async def test_account_filters_devices_without_serial(api, stove_info_payload):
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
        stoves = await api.retrieve_linked_stove_infos()
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
    if method == "get_stove_model_for_stove":
        payload = model_payload
    with patch.object(
        api, "make_request", new_callable=AsyncMock, return_value=payload
    ) as request:
        result = await getattr(api, method)(*args)
        assert isinstance(result, result_type)
        assert request.await_args.args[0] == verb
        assert (
            request.await_args.kwargs.get("url") or request.await_args.args[1]
        ) == url
        request.return_value = None
        with pytest.raises(MaestroConnectionException, match="Living Room"):
            await getattr(api, method)(*args)


@pytest.mark.parametrize("success", [None, {}, {"accepted": True}])
async def test_activate_program_preserves_command_values_and_callback(api, success):
    callback = Mock()
    with patch.object(
        api, "make_request", new_callable=AsyncMock, return_value=success
    ) as request:
        await api.activate_program_with_commands_for_stove(
            "device-1",
            "model-1",
            "config-1",
            "sensors-1",
            [ProgramCommand("power", True), ProgramCommand("target", 22.5)],
            callback,
        )
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
    assert callback.call_count == (success is not None)
