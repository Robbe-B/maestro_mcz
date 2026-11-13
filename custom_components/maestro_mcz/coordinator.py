"""Coordinators for live stove data and dated consumption history."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL, DOMAIN
from .maestro import MaestroStove
from .maestro.controller.controller_interface import MaestroControllerInterface
from .maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)

_LOGGER = logging.getLogger(__name__)
CONSUMPTION_RETRY_INTERVAL = timedelta(hours=1)

type MczConfigEntry = ConfigEntry[MczAccountCoordinator]


class MczAccountCoordinator(DataUpdateCoordinator):
    """MCZ Coordinator."""

    _stoves: dict[str, MaestroStove] | None = None

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MczConfigEntry,
        name: str,
        stoves: list[MaestroStove] | None,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass=hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name=name,
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
                )
            ),
        )
        self._stoves = {stove.UniqueCode: stove for stove in stoves} if stoves else None
        self.consumption_coordinators: dict[str, MczConsumptionCoordinator] = {}

    async def _async_setup(self):
        """Set up the coordinator."""
        if self._stoves is None:
            raise UpdateFailed("No stoves found for this account.")
        for stove in self._stoves.values():
            try:
                await stove.async_init()
            except MaestroConnectionException as err:
                raise UpdateFailed(
                    f"Error communicating with Maestro API: {err}"
                ) from err

    async def _async_update_data(self):
        """Fetch data from API endpoint."""
        if self._stoves is None:
            raise UpdateFailed("No stoves found for this account.")

        for stove in self._stoves.values():
            try:
                await stove.refresh()
            except MaestroAuthenticationException as err:
                # Cancels future updates & Triggers re-auth flow
                raise ConfigEntryAuthFailed from err
            except MaestroConnectionException as err:
                # This marks entities as unavailable and schedules a retry
                raise UpdateFailed(
                    f"Error communicating with Maestro API: {err}"
                ) from err

    async def update_data_after_set(
        self,
    ):  # should be revised in the future to be more efficient
        """Force refresh of data from API endpoint after a SET was executed."""
        # we need to wait here because there is an actual delay between sending a SET and receiving the updated value from the polled MCZ database
        await asyncio.sleep(3)
        await self.async_refresh()
        await asyncio.sleep(3)
        await self.async_refresh()

    @property
    def stoves(self) -> dict[str, MaestroStove]:
        """Return the stoves."""
        return self._stoves


@dataclass(frozen=True)
class ConsumptionData:
    """An explicitly dated snapshot; missing history is not a zero reading."""

    date: date
    value: float | None
    last_updated: datetime


class MczConsumptionCoordinator(DataUpdateCoordinator[ConsumptionData]):
    """Fetch one stove's cloud history without affecting its live controls."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MczConfigEntry,
        controller: MaestroControllerInterface,
        stove: MaestroStove,
    ) -> None:
        """Use the stove's calendar when deciding which day was yesterday."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{stove.Name} consumption",
            update_interval=CONSUMPTION_RETRY_INTERVAL,
        )
        self._controller = controller
        self.stove = stove
        self._time_zone: tzinfo | None = None
        self._unsub_midnight: CALLBACK_TYPE | None = None

    @property
    def yesterday(self) -> date:
        """Return yesterday in the stove's local calendar, not UTC."""
        return dt_util.now(self._time_zone).date() - timedelta(days=1)

    async def _async_update_data(self) -> ConsumptionData:
        """Request only the week needed to find yesterday's exact dated bucket."""
        if self._time_zone is None:
            self._time_zone = await dt_util.async_get_time_zone(
                self.stove.time_zone_iana or self.hass.config.time_zone
            )
            if self._time_zone is None:
                _LOGGER.warning(
                    "Invalid consumption timezone for %s; using Home Assistant's timezone",
                    self.stove.Name,
                )
                self._time_zone = dt_util.DEFAULT_TIME_ZONE
            self._schedule_midnight()
        day = self.yesterday
        self.update_interval = CONSUMPTION_RETRY_INTERVAL
        try:
            history = await self._controller.get_consumption_for_stove(
                self.stove.UniqueCode, day
            )
        except MaestroAuthenticationException as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="consumption_invalid_auth",
            ) from err
        except MaestroConnectionException as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="consumption_cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err
        except ValueError as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="consumption_invalid_response",
            ) from err

        value = history.consumption_for_date(day)
        if value is not None:
            self.update_interval = None
        return ConsumptionData(
            date=day,
            value=value,
            last_updated=dt_util.utcnow(),
        )

    @callback
    def _schedule_midnight(self) -> None:
        """Expire yesterday's snapshot when the stove's calendar day changes."""
        next_day = dt_util.now(self._time_zone).date() + timedelta(days=1)
        midnight = datetime.combine(next_day, time.min, self._time_zone)
        self._unsub_midnight = async_track_point_in_utc_time(
            self.hass, self._async_midnight, dt_util.as_utc(midnight)
        )

    @callback
    def _async_midnight(self, _now: datetime) -> None:
        """Invalidate the old date immediately, even when polling is disabled."""
        self._unsub_midnight = None
        self.async_update_listeners()
        self._schedule_midnight()
        if self.config_entry is not None and not self.config_entry.pref_disable_polling:
            self.config_entry.async_create_background_task(
                self.hass,
                self.async_request_refresh(),
                name=f"{self.name} midnight refresh",
            )

    async def async_shutdown(self) -> None:
        """Cancel the calendar callback along with the ordinary polling timer."""
        if self._unsub_midnight is not None:
            self._unsub_midnight()
            self._unsub_midnight = None
        await super().async_shutdown()
