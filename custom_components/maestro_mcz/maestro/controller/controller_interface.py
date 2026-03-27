"""Interface for controller."""

from .requests.activate_program import ProgramCommand
from .responses.model import Model
from .responses.state import State
from .responses.status import Status
from .responses.stove_info import StoveInfo


class MaestroControllerInterface:
    """Interface for controller."""

    @property
    def is_authenticated(self) -> bool:
        """Returns the current authentication state."""
        pass  # noqa: PIE790

    async def make_request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        body=None,
        avoid_retries: bool = False,
    ):
        """Makes a request to the API."""
        pass  # noqa: PIE790

    async def retrieve_linked_stove_infos(self) -> list[StoveInfo]:
        """Gets information about the stoves linked to the user account."""
        pass  # noqa: PIE790

    async def do_ping_for_stove(self, device_id: str, device_name: str) -> None:
        """Pings the stove to check connectivity."""
        pass  # noqa: PIE790

    async def get_stove_model_for_stove(self, model_id: str) -> Model:
        """Gets the stove model for a given model ID."""
        pass  # noqa: PIE790

    async def get_stove_status_for_stove(self, device_id: str) -> Status:
        """Gets the stove status for a given device ID."""
        pass  # noqa: PIE790

    async def get_stove_state_for_stove(self, device_id: str) -> State:
        """Gets the stove state for a given device ID."""
        pass  # noqa: PIE790

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
        pass  # noqa: PIE790
