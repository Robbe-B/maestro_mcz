"""Interface for controller."""


class MaestroControllerInterface:
    """Interface for controller."""

    @property
    def Connected(self) -> bool:
        """Returns the current connection state."""
        pass  # noqa: PIE790

    @property
    def Stoves(self):
        """Returns a list of stoves linked to your account (once logged in)."""
        pass  # noqa: PIE790

    async def MakeRequest(
        self, method: str, url: str, headers: dict | None = None, body=None
    ):
        """Makes a request to the API."""
        pass  # noqa: PIE790

    async def StoveInfo(self):
        """Gets information about the stoves linked to the user account."""
        pass  # noqa: PIE790
