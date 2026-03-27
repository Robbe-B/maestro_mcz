"""Representation of a MaestroController."""

import asyncio
import dataclasses
import json
import logging
import random
from typing import Any

import aiohttp

from .const import (
    ACTIVATE_PROGRAM_URL,
    APPLIANCE_URL,
    CONTENT_TYPE,
    LOGIN_URL,
    PING_URL,
    STOVE_INFO_URL,
    STOVE_MODEL_URL,
    TENTANT_ID,
)
from .controller_interface import MaestroControllerInterface
from .requests.activate_program import ActivateProgramRequest, ProgramCommand
from .responses.model import Model
from .responses.state import State
from .responses.status import Status
from .responses.stove_info import StoveInfo

_LOGGER = logging.getLogger(__name__)

MAX_RETRIES: int = 3  # Attempts
BACKOFF_BASE: float = 1  # Seconds
SINGLE_REQUEST_TIMEOUT: float = 10  # Seconds


class MaestroController(MaestroControllerInterface):
    """Class to control the communication layer between the API and the integration. (One instance per user account)."""

    def __init__(
        self, client_session: aiohttp.ClientSession, username: str, password: str
    ) -> None:
        """Initialize MaestroController."""
        self._username = username
        self._password = password
        self._token = None
        self._session = client_session
        self._timeout = aiohttp.ClientTimeout(total=SINGLE_REQUEST_TIMEOUT)

    @property
    def is_authenticated(self) -> bool:
        """Returns the current authentication state."""
        return self._token is not None

    async def _login(self, exception_on_failure: bool = False) -> bool:
        """Attempts to login and update the internal token."""

        def _raise_exception(exception_class: type[Exception], message: str) -> None:
            """Inner function to raise exceptions when exception_on_failure is True."""
            if exception_on_failure:
                raise exception_class(message)
            _LOGGER.error(message)

        payload = {"username": self._username, "password": self._password}
        headers = {"content-type": CONTENT_TYPE, "tenantid": TENTANT_ID}

        try:
            async with self._session.post(
                LOGIN_URL, json=payload, headers=headers, timeout=self._timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._token = data.get("Token")
                    _LOGGER.debug("Login successful, token acquired")
                    return True
                _raise_exception(
                    MaestroAuthenticationException,
                    f"Failed to login with status {resp.status}",
                )
        except MaestroAuthenticationException:
            self._token = None  # Ensure token is cleared on any login failure
            raise  # re-raise authentication exceptions without wrapping
        except TimeoutError:
            self._token = None  # Ensure token is cleared on any login failure
            _raise_exception(
                MaestroConnectionException, "Failed to connect during login (timeout)"
            )
        except Exception as e:  # noqa: BLE001
            self._token = None  # Ensure token is cleared on any login failure
            _raise_exception(
                MaestroConnectionException, f"Failed to connect during login: {e}"
            )
        return False

    async def _backoff(self, attempt: int):
        """Wait before retrying, using exponential backoff with jitter."""
        wait_time = (BACKOFF_BASE**attempt) + random.uniform(0, 1)
        _LOGGER.debug("Sleeping for %0.2f seconds before retry", wait_time)
        await asyncio.sleep(wait_time)

    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        body=None,
        avoid_retries: bool = False,
    ) -> Any:
        """Main entry point for requests with built-in retry logic and backoff."""
        attempts = 1 if avoid_retries else MAX_RETRIES
        for attempt in range(attempts):
            # 1. Ensure we have a token
            if not self.is_authenticated:
                if not await self._login():
                    # If login itself fails, wait and retry the whole process
                    await self._backoff(attempt)
                    continue

            # 2. Prepare headers
            if headers is None:
                headers = {}  # avoid mutable default argument

            headers["auth-token"] = self._token
            headers["content-type"] = CONTENT_TYPE
            headers["tenantid"] = TENTANT_ID

            try:
                async with self._session.request(
                    method,
                    url,
                    data=json.dumps(body, ensure_ascii=False),
                    headers=headers,
                    timeout=self._timeout,
                ) as resp:
                    # Success path
                    if resp.status == 200:
                        return await resp.json()

                    # Token expired or invalid path
                    if resp.status in (401, 403):
                        _LOGGER.warning(
                            "Authentication expired (Status %s). Clearing token",
                            resp.status,
                        )
                        self._token = None
                        # Don't return, let the next loop iteration re-login
                        continue

                    # Server-side flakiness (5xx errors)
                    if 500 <= resp.status < 600:
                        _LOGGER.warning(
                            "Cloud server error (%s): %s for %s",
                            resp.status,
                            resp.reason,
                            url,
                        )
                    else:
                        _LOGGER.error(
                            "Request failed with status %s: %s for %s",
                            resp.status,
                            resp.reason,
                            url,
                        )
                        return None  # Permanent failure (e.g. 404 or 400)
            except TimeoutError:
                _LOGGER.debug(
                    "Request timed out on attempt %s for %s", attempt + 1, url
                )
            except aiohttp.ClientError as e:
                _LOGGER.debug(
                    "Network error on attempt %s: %s for %s", attempt + 1, e, url
                )

            # If we reached here, something went wrong but is potentially retriable
            await self._backoff(attempt)

        # maximum retries reached, log and give up
        _LOGGER.error("Maximum retries (%s) reached for %s", attempts, url)
        return None

    async def retrieve_linked_stove_infos(self) -> list[StoveInfo]:
        """Gets information about the stoves linked to the user account."""
        await self._login(True)  # make sure login exceptions bubbel up

        res = await self.make_request("POST", STOVE_INFO_URL, body={})

        stoves = []
        if res is not None:
            for stove in res:
                stove_info = StoveInfo(stove)
                if stove_info.node.unique_code:  # avoid adding a stove without serial number as this is the unique identifier in HA
                    stoves.append(stove_info)

        return stoves

    async def do_ping_for_stove(self, device_id: str, device_name: str) -> None:
        """Pings the stove to check connectivity."""
        url = f"{PING_URL}/{device_id}"
        ping_res = await self.make_request("POST", url=url)
        if ping_res is None:
            raise MaestroConnectionException(f"Ping failed for device {device_name}.")

    async def get_stove_model_for_stove(self, model_id: str) -> Model:
        """Gets the stove model for a given model ID."""
        response = await self.make_request(
            "GET", f"{STOVE_MODEL_URL}/{model_id}", avoid_retries=True
        )
        if response is None:
            raise MaestroConnectionException(
                f"Failed to retrieve model for model ID {model_id}"
            )
        return Model(response)

    async def get_stove_status_for_stove(self, device_id: str) -> Status:
        """Gets the stove status for a given device ID."""
        response = await self.make_request(
            "GET", f"{APPLIANCE_URL}/{device_id}/Status", avoid_retries=True
        )
        if response is None:
            raise MaestroConnectionException(
                f"Failed to retrieve status for device ID {device_id}"
            )
        return Status(response)

    async def get_stove_state_for_stove(self, device_id: str) -> State:
        """Gets the stove state for a given device ID."""
        response = await self.make_request(
            "GET", f"{APPLIANCE_URL}/{device_id}/State", avoid_retries=True
        )
        if response is None:
            raise MaestroConnectionException(
                f"Failed to retrieve state for device ID {device_id}"
            )
        return State(response)

    async def activate_program_with_commands_for_stove(
        self,
        device_id: str,
        model_id: str,
        configuration_id: str,
        sensor_set_type_id: str,
        commands: list[ProgramCommand],
        callback_on_success=None,
    ) -> None:
        """Activate a program on the stove with multiple commands for a given device ID."""
        url = f"{ACTIVATE_PROGRAM_URL}/{device_id}"
        body = dataclasses.asdict(
            ActivateProgramRequest(
                model_id, configuration_id, sensor_set_type_id, commands
            )
        )
        success = await self.make_request("POST", url=url, body=body)
        if callback_on_success is not None and success is not None:
            callback_on_success()


class MaestroAuthenticationException(Exception):
    """An attempt to authenticate failed."""


class MaestroConnectionException(Exception):
    """An attempt to connect failed."""
