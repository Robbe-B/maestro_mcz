"""Read and control one stove through the cloud, without choosing HA entities."""

import asyncio
import logging
from collections.abc import Callable

from .controller.controller_interface import MaestroControllerInterface
from .controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)
from .controller.requests.activate_program import ProgramCommand
from .controller.responses.model import SensorConfiguration
from .controller.responses.state import State
from .controller.responses.status import Status

_LOGGER = logging.getLogger(__name__)


class CloudStoveProvider:
    """Handle the cloud conversation for one physical stove.

    MaestroStove decides which model controls apply and what readings mean.
    This provider asks the cloud for updates, retains the returned replies,
    and sends commands to the correct stove. It does not load models, discover
    account devices, or decide which Home Assistant entities to create.
    The existing controller still handles login, request retries, and server
    instructions to wait before trying again.
    """

    def __init__(
        self,
        controller: MaestroControllerInterface,
        *,
        device_id: str,
        name: str,
        model_id: str,
        sensor_set_type_id: str,
    ) -> None:
        """Remember how to address this stove using the account's existing client.

        Construction makes no requests. Each stove has its own cached replies
        and connection flags, while sharing the account's login and HTTP client.
        """
        self._controller = controller
        self._device_id = device_id
        self._name = name
        self._model_id = model_id
        self._sensor_set_type_id = sensor_set_type_id
        self._state: State | None = None
        self._status: Status | None = None
        self._is_cloud_connected = False
        self._is_stove_connected = False

    @property
    def state(self) -> State | None:
        """Return the last state reply without fetching anything.

        A successful state request replaces this reply even if the status
        request fails. A retained reply alone does not mean the stove is online.
        """
        return self._state

    @property
    def status(self) -> Status | None:
        """Return the last status reply exactly as the controller supplied it.

        Interpreting settings and device details belongs to the shared stove.
        """
        return self._status

    @property
    def is_cloud_connected(self) -> bool:
        """Return the cloud connection flag maintained during live refreshes."""
        return self._is_cloud_connected

    @property
    def is_stove_connected(self) -> bool:
        """Return whether the last usable status said the stove was online.

        This is separate from reaching the cloud: the service can respond while
        the physical stove is disconnected.
        """
        return self._is_stove_connected

    async def async_ping(self, m1_ping: SensorConfiguration | None) -> None:
        """Ask the cloud to refresh the stove's readings before fetching them.

        M1 needs two model-defined read requests. Without that M1 binding,
        use the dedicated cloud ping and do not send a configuration command.
        """
        if m1_ping is not None:
            try:
                await self.async_ping_m1_configuration(m1_ping)
            except MaestroConnectionException as err:
                raise type(err)(
                    f"Ping for '{self._name}': {err}", retry_after=err.retry_after
                ) from err
            return
        await self._controller.do_ping_for_stove(self._device_id, self._name)

    async def async_ping_m1_configuration(self, ping: SensorConfiguration) -> None:
        """Ask an M1 stove for parameters first, then device information.

        These are read requests carried through the command endpoint, not user
        setting changes. Reject incomplete or unexpected bindings rather than
        guessing a command address or value.
        """
        configuration = ping.configuration
        mappings = configuration.mappings
        if (
            not ping.configuration_id
            or not configuration.sensor_id
            or not configuration.enabled
            or configuration.type != "int"
            or not isinstance(mappings, dict)
            or type(mappings.get("C|RecuperoParametri")) is not int
            or mappings.get("C|RecuperoParametri") != 0
            or type(mappings.get("C|RecuperoInfo")) is not int
            or mappings.get("C|RecuperoInfo") != 1
        ):
            raise MaestroConnectionException(
                f"Invalid M1 PING STOVE configuration for device '{self._name}'"
            )

        # Keep the established order and pause after each request, including the last.
        for command in ("C|RecuperoParametri", "C|RecuperoInfo"):
            await self.async_activate_program(
                ping.configuration_id,
                [ProgramCommand(configuration.sensor_id, mappings[command])],
            )
            await asyncio.sleep(1)

    async def async_ping_configuration(self, ping: SensorConfiguration) -> None:
        """Send a model-defined M2+ ping only when explicitly requested.

        Normal refresh never calls this helper: configuration pings can cause
        issues on some models. A connection failure is reported as a warning,
        but rejected authentication still reaches the caller.
        """
        try:
            configuration = ping.configuration
            mappings = configuration.mappings
            if (
                not ping.configuration_id
                or not configuration.sensor_id
                or not configuration.enabled
                or configuration.type != "int"
                or not isinstance(mappings, dict)
                or type(mappings.get("Ping")) is not int
            ):
                raise MaestroConnectionException(
                    f"Invalid M2+ ping configuration for device '{self._name}'"
                )

            await self.async_activate_program(
                ping.configuration_id,
                [ProgramCommand(configuration.sensor_id, mappings["Ping"])],
            )
        except MaestroConnectionException as err:
            _LOGGER.warning(
                "M2+ configuration ping failed for '%s'; continuing with cloud refresh: %s",
                self._name,
                err,
            )

    async def _async_read_status(
        self, on_status_received: Callable[[Status | None], None] | None
    ) -> None:
        """Fetch status and let the shared stove process the received device details.

        A failed request leaves the previous reply intact. Notify the caller
        immediately after a successful request, even if the state read later
        fails, so useful serial and firmware details are not lost.
        """
        self._status = await self._controller.get_stove_status_for_stove(
            self._device_id, self._name
        )
        if on_status_received is not None:
            on_status_received(self._status)

    async def _async_read_state(self) -> None:
        """Fetch and retain state, leaving the previous reply intact on request failure."""
        self._state = await self._controller.get_stove_state_for_stove(
            self._device_id, self._name
        )

    async def async_refresh(
        self,
        m1_ping: SensorConfiguration | None,
        *,
        on_status_received: Callable[[Status | None], None] | None = None,
    ) -> None:
        """Ping the stove, then request its status and state together.

        Keep each successful reply even when the other request fails, but report
        the failed cycle to the caller. Login failures take priority, followed
        by server-requested waiting periods, then ordinary reading failures.
        This lets account recovery act on the most important problem.
        """
        try:
            await self.async_ping(m1_ping)
            self._is_cloud_connected = self._controller.is_authenticated
            # Wait for both outcomes so a quick reading failure cannot hide a login error.
            results = await asyncio.gather(
                self._async_read_status(on_status_received),
                self._async_read_state(),
                return_exceptions=True,
            )
            # These errors affect the entire account, not just one missing reading.
            for result in results:
                if isinstance(result, MaestroAuthenticationException):
                    raise result
            for result in results:
                if (
                    isinstance(result, MaestroConnectionException)
                    and result.retry_after is not None
                ):
                    raise result
            for result in results:
                if isinstance(result, BaseException):
                    raise result

            # Reaching the service does not prove the stove itself is connected.
            if self._status is not None and self._status.is_connected is not None:
                self._is_stove_connected = self._status.is_connected
        except MaestroAuthenticationException, MaestroConnectionException:
            # Retain replies for diagnostics, but do not present a failed cycle as online.
            self._is_cloud_connected = False
            raise

    async def async_activate_program(
        self,
        configuration_id: str | None,
        commands: list[ProgramCommand],
        callback_on_success: Callable[[], None] | None = None,
    ) -> None:
        """Send the supplied command batch to this stove through the existing client.

        Preserve the model addresses, values, and success callback unchanged.
        The controller owns retries and calls the callback after acceptance;
        this provider adds no retry loop or alternative connection.
        """
        await self._controller.activate_program_with_commands_for_stove(
            self._device_id,
            self._model_id,
            configuration_id,
            self._sensor_set_type_id,
            commands,
            callback_on_success,
        )
