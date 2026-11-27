"""One Maestro account's client, linked stoves, and account-wide operations."""

import logging
from collections.abc import Callable, Iterable, Mapping
from collections.abc import Set as AbstractSet
from types import MappingProxyType

from . import MaestroStove, ModelFetchedCallback
from .controller.controller_interface import MaestroControllerInterface
from .controller.maestro_controller import MaestroConnectionException

_LOGGER = logging.getLogger(__name__)


class MaestroAccount:
    """Own one account's linked stoves and account-wide refresh failure policy.

    The controller owns authentication and request retries; each stove owns its
    cached replies and commands. Entity presentation and translation coverage
    are integration concerns, not responsibilities of this account client.
    """

    def __init__(
        self,
        controller: MaestroControllerInterface,
        stoves: Iterable[MaestroStove] = (),
        *,
        replay: bool = False,
        on_model_fetched: ModelFetchedCallback | None = None,
    ) -> None:
        """Bind one client and an optional already-loaded collection to this account."""
        self._controller = controller
        self._stoves = {stove.UniqueCode: stove for stove in stoves}
        self._replay = replay
        self._on_model_fetched = on_model_fetched if not replay else None
        self._failed_stoves: set[str] = set()

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
            stove = MaestroStove(
                self._controller,
                info,
                on_authentication_failed,
                on_model_fetched=self._on_model_fetched,
            )
            stoves[stove.UniqueCode] = stove
        self._stoves = stoves

    async def async_initialize(self) -> None:
        """Load every stove's model before its first live refresh."""
        for stove in self._stoves.values():
            await stove.async_init()

    async def async_refresh(self) -> None:
        """Refresh sequentially, isolating request failures but not account backoff."""
        last_error: MaestroConnectionException | None = None
        refreshed = False
        for stove in self._stoves.values():
            try:
                await stove.refresh()
            except MaestroConnectionException as err:
                if err.retry_after is not None:
                    raise
                last_error = err
                if stove.UniqueCode not in self._failed_stoves:
                    _LOGGER.warning("Error refreshing stove '%s': %s", stove.Name, err)
                    self._failed_stoves.add(stove.UniqueCode)
            else:
                refreshed = True
                if stove.UniqueCode in self._failed_stoves:
                    self._failed_stoves.remove(stove.UniqueCode)
                    _LOGGER.info("Refreshing stove '%s' recovered", stove.Name)
        if not refreshed and last_error is not None:
            raise last_error

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
