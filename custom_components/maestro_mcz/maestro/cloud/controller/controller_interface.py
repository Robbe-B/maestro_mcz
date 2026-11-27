"""Describe the Cloud-shaped operations used by live and saved-report clients."""

from collections.abc import Callable
from datetime import date
from typing import Protocol

from ..requests.activate_program import ProgramCommand
from ..responses.consumption import ConsumptionHistory
from ..responses.counters import Counters
from ..responses.model import Model
from ..responses.state import State
from ..responses.status import Status
from ..responses.stove_info import StoveInfo


class MaestroControllerInterface(Protocol):
    """Define the account/device operations shared by live and replay clients.

    Implementations supply parsed responses and command dispatch; callers own
    stove caches, Home Assistant entity state and polling schedules.
    """

    @property
    def is_authenticated(self) -> bool:
        """Returns the current authentication state."""
        ...

    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        body: object = None,
    ) -> object:
        """Makes a request to the API."""
        ...

    async def retrieve_linked_stove_infos(
        self, *, require_unique_codes: bool = False
    ) -> list[StoveInfo]:
        """Get linked stoves, optionally requiring every record to have a serial number."""
        ...

    async def do_ping_for_stove(self, device_id: str, device_name: str) -> None:
        """Pings the stove to check connectivity."""
        ...

    async def get_stove_model_for_stove(
        self, model_id: str, device_name: str
    ) -> Model | None:
        """Gets the stove model for a given model ID."""
        ...

    async def get_stove_status_for_stove(
        self, device_id: str, device_name: str
    ) -> Status | None:
        """Gets the stove status for a given device ID."""
        ...

    async def get_stove_state_for_stove(
        self, device_id: str, device_name: str
    ) -> State | None:
        """Gets the stove state for a given device ID."""
        ...

    async def get_consumption_for_stove(
        self, unique_code: str, anchor_date: date
    ) -> ConsumptionHistory:
        """Get the week containing the requested date, if the service provides it."""
        ...

    async def get_counters_for_stove(
        self, device_id: str, device_name: str
    ) -> Counters:
        """Get lifetime statistics independently of the live stove readings."""
        ...

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
        ...
