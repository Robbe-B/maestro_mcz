"""One Maestro account's client, linked stoves, and account-wide operations."""

from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from types import MappingProxyType

from . import MaestroStove
from .controller.controller_interface import MaestroControllerInterface
from .controller.maestro_controller import MaestroConnectionException


class MaestroAccount:
    """Keep authentication and stove ownership separate for every account."""

    def __init__(
        self,
        controller: MaestroControllerInterface,
        stoves: Iterable[MaestroStove] = (),
        *,
        replay: bool = False,
    ) -> None:
        """Bind one client and an optional already-loaded collection to this account."""
        self._controller = controller
        self._stoves = {stove.UniqueCode: stove for stove in stoves}
        self._replay = replay

    @property
    def stoves(self) -> Mapping[str, MaestroStove]:
        """Expose the loaded stoves without allowing another owner to replace them."""
        return MappingProxyType(self._stoves)

    async def async_load_stoves(
        self, on_authentication_failed: Callable[[], None] | None = None
    ) -> None:
        """Discover this account's stoves once, before polling starts."""
        stove_infos = await self._controller.retrieve_linked_stove_infos()
        stoves = {}
        for info in stove_infos:
            stove = MaestroStove(self._controller, info, on_authentication_failed)
            stoves[stove.UniqueCode] = stove
        self._stoves = stoves

    async def async_initialize(self) -> None:
        """Load every stove's model before its first live refresh."""
        for stove in self._stoves.values():
            await stove.async_init()

    async def async_refresh(self) -> None:
        """Refresh this account's loaded stoves without rediscovering devices."""
        for stove in self._stoves.values():
            await stove.refresh()

    async def async_has_linked_stove(self, unique_codes: AbstractSet[str]) -> bool:
        """Verify membership freshly, or use the loaded snapshot for saved reports."""
        if self._replay:
            return not unique_codes.isdisjoint(self._stoves)
        stove_infos = await self._controller.retrieve_linked_stove_infos(
            require_unique_codes=True
        )
        linked_codes = set()
        for info in stove_infos:
            code = info.node.unique_code if info.node is not None else None
            if not isinstance(code, str) or not code.strip():
                raise MaestroConnectionException(
                    "Maestro service returned an unidentified linked stove"
                )
            linked_codes.add(code)
        return not unique_codes.isdisjoint(linked_codes)
