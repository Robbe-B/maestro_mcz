"""Representation of a MaestroController."""

import asyncio
import json
import logging
import random
from typing import Any

import aiohttp

from .. import MaestroStove
from ..const import CONTENT_TYPE, LOGIN_URL, STOVE_INFO_URL, TENTANT_ID
from ..responses.stove_info import StoveInfo
from .controller_interface import MaestroControllerInterface

_LOGGER = logging.getLogger(__name__)

MAX_RETRIES = 5
BACKOFF_BASE = 2  # Seconds


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
        self._stoves = []
        self._timeout = aiohttp.ClientTimeout(total=15)

    @property
    def Connected(self) -> bool:
        """Returns the current connection state."""
        return self._token is not None

    @property
    def Stoves(self):
        """Returns a list of stoves linked to your account (once logged in)."""
        return self._stoves

    async def _login(self) -> bool:
        """Attempts to login and update the internal token."""
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
                _LOGGER.error("Login failed with status %s", resp.status)
                return False
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Login error: %s", e)
            return False

    async def _backoff(self, attempt: int):
        """Wait before retrying, using exponential backoff with jitter."""
        wait_time = (BACKOFF_BASE**attempt) + random.uniform(0, 1)
        _LOGGER.debug("Sleeping for %0.2f seconds before retry", wait_time)
        await asyncio.sleep(wait_time)

    async def MakeRequest(
        self, method: str, url: str, headers: dict | None = None, body=None
    ) -> Any:
        """Main entry point for requests with built-in retry logic and backoff."""

        for attempt in range(MAX_RETRIES):
            # 1. Ensure we have a token
            if not self.Connected:
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
                            "Cloud server error (%s): %s. Retrying now",
                            resp.status,
                            resp.reason,
                        )
                    else:
                        _LOGGER.error(
                            "Request failed with status %s: %s",
                            resp.status,
                            resp.reason,
                        )
                        return None  # Permanent failure (e.g. 404 or 400)

            except (TimeoutError, aiohttp.ClientError) as e:
                _LOGGER.warning("Network error on attempt %s: %s", attempt + 1, e)

            # If we reached here, something went wrong but is potentially retriable
            await self._backoff(attempt)

        _LOGGER.error("Maximum retries reached for %s", url)
        return None

    async def StoveInfo(self):
        """Gets information about the stoves linked to the user account."""
        res = await self.MakeRequest("POST", STOVE_INFO_URL, body={})

        if res is not None:
            for stove in res:
                maesto_stove = MaestroStove(self, StoveInfo(stove))
                await maesto_stove.AsyncInit()
                self._stoves.append(maesto_stove)
