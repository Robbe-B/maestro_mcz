"""Representation of a MaestroController."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime

import aiohttp

from .const import (
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
from .controller_interface import MaestroControllerInterface
from .requests.activate_program import ActivateProgramRequest, ProgramCommand
from .response_types import require_json_object
from .responses.consumption import ConsumptionHistory
from .responses.counters import Counters
from .responses.model import Model
from .responses.state import State
from .responses.status import Status
from .responses.stove_info import StoveInfo

_LOGGER = logging.getLogger(__name__)

SINGLE_REQUEST_TIMEOUT: float = 10  # Seconds
MAX_ATTEMPTS = 3
BACKOFF_BASE_SECONDS = 1.0
MAX_JITTER_SECONDS = 0.5
TRANSIENT_HTTP_STATUSES = {408, 500, 502, 503, 504}


async def _wait_before_retry(attempt: int) -> None:
    """Space retries by one then two seconds, plus bounded jitter."""
    delay = BACKOFF_BASE_SECONDS * 2**attempt + random.uniform(0, MAX_JITTER_SECONDS)
    _LOGGER.debug("Waiting %.2f seconds before the next attempt", delay)
    await asyncio.sleep(delay)


@contextmanager
def _request_context(description: str) -> Iterator[None]:
    """Add the human-readable action only after the shared retry loop finishes."""
    _LOGGER.debug("Starting %s", description)
    try:
        yield
    except MaestroConnectionException as err:
        raise type(err)(f"{description}: {err}", retry_after=err.retry_after) from err


def _connection_failure(
    response: aiohttp.ClientResponse, operation: str
) -> MaestroConnectionException:
    """Respect server delays rather than retrying an overloaded service locally."""
    retry_after = None
    header = response.headers.get("Retry-After")
    if header:
        try:
            retry_after = float(max(0, int(header)))
        except (ValueError, OverflowError):
            try:
                retry_time = parsedate_to_datetime(header)
                if retry_time.tzinfo is not None:
                    retry_after = max(
                        0, (retry_time - datetime.now(UTC)).total_seconds()
                    )
            except (TypeError, ValueError, OverflowError):
                pass  # An invalid server hint must not hide the original HTTP failure.

    message = f"{operation} failed (HTTP {response.status})"
    if retry_after is not None:
        message += f"; server requested a retry after {retry_after:g} seconds"
        return MaestroConnectionException(message, retry_after=retry_after)
    if response.status in TRANSIENT_HTTP_STATUSES:
        return _MaestroTransientConnectionException(message)
    return MaestroConnectionException(message)


class MaestroController(MaestroControllerInterface):
    """Own one account's HTTP authentication, retries and endpoint parsing.

    Borrow the caller's ClientSession; do not close it or own stove caches,
    Home Assistant polling, entity labels or feature-selection policy.
    """

    def __init__(
        self, client_session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        """Initialize MaestroController."""
        self._username = username
        self._password = password
        self._token: str | None = None
        self._authentication_lock = asyncio.Lock()
        self._session = client_session
        self._timeout = aiohttp.ClientTimeout(total=SINGLE_REQUEST_TIMEOUT)

    @property
    def is_authenticated(self) -> bool:
        """Returns the current authentication state."""
        return self._token is not None

    async def _login(self) -> None:
        """Allow at most three login attempts, never retrying rejected credentials."""
        for attempt in range(MAX_ATTEMPTS):
            try:
                await self._login_once()
                return
            except _MaestroTransientConnectionException as err:
                if attempt == MAX_ATTEMPTS - 1:
                    raise _MaestroTransientConnectionException(
                        f"{err} after {attempt + 1} login attempts",
                        retry_after=err.retry_after,
                    ) from err
                _LOGGER.debug(
                    "Maestro login attempt %d/%d failed: %s; retrying",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    err,
                )
                await _wait_before_retry(attempt)

    async def _login_once(self) -> None:
        """Store a valid token or raise a classified, non-sensitive failure."""
        self._token = None
        payload = {"username": self._username, "password": self._password}
        headers = {"content-type": CONTENT_TYPE, "tenantid": TENTANT_ID}

        try:
            async with self._session.post(
                LOGIN_URL, json=payload, headers=headers, timeout=self._timeout
            ) as resp:
                if resp.status == 200:
                    data: object = await resp.json()
                    token = data.get("Token") if isinstance(data, dict) else None
                    if not isinstance(token, str) or not token:
                        raise MaestroConnectionException(
                            "Failed to login: response contains no valid token"
                        )
                    self._token = token
                    _LOGGER.debug("Login successful, token acquired")
                    return
                if resp.status in (400, 401, 403):
                    raise MaestroAuthenticationException(
                        f"Failed to login with status {resp.status}"
                    )
                raise _connection_failure(resp, "Maestro login")
        except TimeoutError as err:
            raise _MaestroTransientConnectionException(
                f"Maestro login timed out ({SINGLE_REQUEST_TIMEOUT:g} s per-attempt timeout)"
            ) from err
        except (aiohttp.ContentTypeError, ValueError) as err:
            raise MaestroConnectionException(
                "Maestro login returned invalid JSON"
            ) from err
        except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError) as err:
            raise _MaestroTransientConnectionException(
                f"Unable to connect to the Maestro login service ({type(err).__name__})"
            ) from err
        except aiohttp.ClientError as err:
            raise MaestroConnectionException(
                f"Unable to connect to the Maestro login service ({type(err).__name__})"
            ) from err

    async def _get_token(self, rejected_token: str | None = None) -> str:
        """Share one login between simultaneous requests, including token renewal."""
        async with self._authentication_lock:
            # A concurrent request may already have replaced the rejected token.
            if self._token is None or self._token == rejected_token:
                await self._login()
            assert self._token is not None
            return self._token

    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: object = None,
    ) -> object:
        """Share three request attempts across transient retries and auth recovery.

        Each needed login has its own three-attempt budget; token renewal is allowed once.
        """
        token = await self._get_token()
        token_renewed = False
        # Auth replay and transient recovery share this budget, never nested retries.
        for attempt in range(MAX_ATTEMPTS):
            try:
                return await self._request_once(method, url, token, headers, body)
            except MaestroAuthenticationException as err:
                _LOGGER.debug(
                    "Maestro request attempt %d/%d rejected authentication",
                    attempt + 1,
                    MAX_ATTEMPTS,
                )
                if token_renewed:
                    async with self._authentication_lock:
                        # A late rejection must not invalidate a newer working token.
                        if self._token is not None and self._token != token:
                            raise MaestroConnectionException(
                                "Maestro request used a superseded authentication token"
                            ) from err
                        if self._token == token:
                            self._token = None
                    raise
                if attempt == MAX_ATTEMPTS - 1:
                    # Do not exceed the operation budget just to replay an expired token.
                    raise MaestroConnectionException(
                        "Maestro authentication recovery deferred after three request attempts"
                    ) from err
                _LOGGER.debug(
                    "Renewing authentication once before replaying the request"
                )
                token = await self._get_token(rejected_token=token)
                token_renewed = True
            except _MaestroTransientConnectionException as err:
                # Commands share these retries, even if an earlier attempt reached the stove.
                if attempt == MAX_ATTEMPTS - 1:
                    raise _MaestroTransientConnectionException(
                        f"{err} after {attempt + 1} request attempts",
                        retry_after=err.retry_after,
                    ) from err
                _LOGGER.debug(
                    "Maestro request attempt %d/%d failed: %s; retrying",
                    attempt + 1,
                    MAX_ATTEMPTS,
                    err,
                )
                await _wait_before_retry(attempt)
        raise MaestroConnectionException("Maestro request retry budget exhausted")

    async def _request_once(
        self,
        method: str,
        url: str,
        token: str,
        headers: dict[str, str] | None,
        body: object,
    ) -> object:
        """Send one request and preserve its failure without logging private details."""
        request_headers = {
            **(headers or {}),
            "auth-token": token,
            "content-type": CONTENT_TYPE,
            "tenantid": TENTANT_ID,
        }
        serialized_body = json.dumps(body, ensure_ascii=False)
        try:
            async with self._session.request(
                method,
                url,
                data=serialized_body,
                headers=request_headers,
                timeout=self._timeout,
            ) as response:
                if response.status in (401, 403):
                    raise MaestroAuthenticationException(
                        f"Maestro request rejected authentication (HTTP {response.status})"
                    )
                if response.status != 200:
                    raise _connection_failure(response, "Maestro request")
                result: object = await response.json()
        except TimeoutError as err:
            raise _MaestroTransientConnectionException(
                f"Maestro request timed out ({SINGLE_REQUEST_TIMEOUT:g} s per-attempt timeout)"
            ) from err
        except (aiohttp.ContentTypeError, ValueError) as err:
            raise MaestroConnectionException(
                "Maestro service returned invalid JSON"
            ) from err
        except (aiohttp.ClientConnectionError, aiohttp.ClientPayloadError) as err:
            raise _MaestroTransientConnectionException(
                f"Unable to communicate with the Maestro service ({type(err).__name__})"
            ) from err
        except aiohttp.ClientError as err:
            raise MaestroConnectionException(
                f"Unable to communicate with the Maestro service ({type(err).__name__})"
            ) from err
        if result is None:
            raise MaestroConnectionException(
                "Maestro service returned an empty response"
            )
        return result

    async def retrieve_linked_stove_infos(
        self, *, require_unique_codes: bool = False
    ) -> list[StoveInfo]:
        """Get linked stoves without hiding unidentified records during removal checks."""
        with _request_context("Discovering stoves"):
            stove_payloads = await self.make_request("POST", STOVE_INFO_URL, body={})
        if not isinstance(stove_payloads, list):
            raise MaestroConnectionException(
                "Maestro service returned an invalid stove list"
            )

        stoves = []
        for stove_payload in stove_payloads:
            stove_info = StoveInfo(require_json_object(stove_payload))
            if stove_info.node is None:
                raise MaestroConnectionException(
                    "Maestro service returned an invalid stove list"
                )
            unique_code = stove_info.node.unique_code
            if require_unique_codes and (
                not isinstance(unique_code, str) or not unique_code.strip()
            ):
                raise MaestroConnectionException(
                    "Maestro service returned a stove list with missing serial numbers"
                )
            if stove_info.node.unique_code:  # avoid adding a stove without serial number as this is the unique identifier in HA
                stoves.append(stove_info)

        return stoves

    async def do_ping_for_stove(self, device_id: str, device_name: str) -> None:
        """Pings the stove to check connectivity."""
        url = f"{PING_URL}/{device_id}"
        with _request_context(f"Ping for '{device_name}'"):
            await self.make_request("POST", url=url)

    async def get_stove_model_for_stove(self, model_id: str, device_name: str) -> Model:
        """Gets the stove model for a given model ID."""
        with _request_context(f"Model for '{device_name}'"):
            response = await self.make_request("GET", f"{STOVE_MODEL_URL}/{model_id}")
        return Model(require_json_object(response))

    async def get_stove_status_for_stove(
        self, device_id: str, device_name: str
    ) -> Status:
        """Gets the stove status for a given device ID."""
        with _request_context(f"Status for '{device_name}'"):
            response = await self.make_request(
                "GET", f"{APPLIANCE_URL}/{device_id}/Status"
            )
        return Status(require_json_object(response))

    async def get_stove_state_for_stove(
        self, device_id: str, device_name: str
    ) -> State:
        """Gets the stove state for a given device ID."""
        with _request_context(f"State for '{device_name}'"):
            response = await self.make_request(
                "GET", f"{APPLIANCE_URL}/{device_id}/State"
            )
        return State(require_json_object(response))

    async def get_consumption_for_stove(
        self, unique_code: str, anchor_date: date
    ) -> ConsumptionHistory:
        """Fetch dated history without treating an HTTP failure as unsupported."""
        url = f"{CONSUMPTION_URL}/{unique_code}/week/{anchor_date:%Y%m%d}"
        with _request_context("Consumption history"):
            response = await self.make_request("GET", url)
        return ConsumptionHistory.from_response(response)

    async def get_counters_for_stove(
        self, device_id: str, device_name: str
    ) -> Counters:
        """Retrieve lifetime statistics without pinging or sending commands."""
        with _request_context(f"Counters for '{device_name}'"):
            response = await self.make_request(
                "GET", f"{APPLIANCE_URL}/{device_id}/Counters"
            )
        return Counters(response)

    async def activate_program_with_commands_for_stove(
        self,
        device_id: str,
        model_id: str,
        configuration_id: str | None,
        sensor_set_type_id: str,
        commands: list[ProgramCommand],
        callback_on_success: Callable[[], None] | None = None,
    ) -> None:
        """Activate a program on the stove with multiple commands for a given device ID."""
        url = f"{ACTIVATE_PROGRAM_URL}/{device_id}"
        body = dataclasses.asdict(
            ActivateProgramRequest(
                model_id, configuration_id, sensor_set_type_id, commands
            )
        )
        with _request_context("Sending command"):
            await self.make_request("POST", url=url, body=body)
        if callback_on_success is not None:
            callback_on_success()


class MaestroAuthenticationException(Exception):
    """Signal rejected authentication without choosing a Home Assistant action."""


class MaestroConnectionException(Exception):
    """Carry a service failure and an optional server-requested retry delay."""

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        """Retain a server-requested delay for Home Assistant's recovery scheduler."""
        super().__init__(message)
        self.retry_after = retry_after


class _MaestroTransientConnectionException(MaestroConnectionException):
    """A temporary failure eligible for bounded request retries."""
