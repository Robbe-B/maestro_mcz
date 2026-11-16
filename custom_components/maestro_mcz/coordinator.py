"""Independent coordinators for live data, consumption history, and statistics."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL, DOMAIN
from .maestro import MaestroStove
from .maestro.account import MaestroAccount
from .maestro.controller.controller_interface import MaestroControllerInterface
from .maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)
from .maestro.controller.responses.counters import Counters

_LOGGER = logging.getLogger(__name__)
CONSUMPTION_RETRY_INTERVAL = timedelta(hours=1)
COUNTERS_UPDATE_INTERVAL = timedelta(hours=1)


@dataclass(frozen=True)
class MczRuntimeData:
    """Keep account ownership separate from Home Assistant's polling lifecycle."""

    account: MaestroAccount
    coordinator: MczAccountCoordinator


type MczConfigEntry = ConfigEntry[MczRuntimeData]


class MczAccountCoordinator(DataUpdateCoordinator[None]):
    """MCZ Coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MczConfigEntry,
        name: str,
        account: MaestroAccount,
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
        self._account = account
        self.consumption_coordinators: dict[str, MczConsumptionCoordinator] = {}
        self.counters_coordinators: dict[str, MczCountersCoordinator] = {}

    async def _async_setup(self) -> None:
        """Set up the coordinator."""
        if not self.stoves:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="account_no_stoves",
            )
        try:
            await self._account.async_initialize()
        except MaestroAuthenticationException as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="account_invalid_auth",
            ) from err
        except MaestroConnectionException as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="account_cannot_connect",
                translation_placeholders={"error": str(err)},
                retry_after=err.retry_after,
            ) from err

    async def _async_update_data(self) -> None:
        """Fetch data from API endpoint."""
        if not self.stoves:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="account_no_stoves",
            )

        try:
            await self._account.async_refresh()
        except MaestroAuthenticationException as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="account_invalid_auth",
            ) from err
        except MaestroConnectionException as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="account_cannot_connect",
                translation_placeholders={"error": str(err)},
                retry_after=err.retry_after,
            ) from err

    async def update_data_after_set(
        self,
    ) -> None:  # should be revised in the future to be more efficient
        """Force refresh of data from API endpoint after a SET was executed."""
        # we need to wait here because there is an actual delay between sending a SET and receiving the updated value from the polled MCZ database
        await asyncio.sleep(3)
        await self.async_refresh()
        await asyncio.sleep(3)
        await self.async_refresh()

    @property
    def stoves(self) -> Mapping[str, MaestroStove]:
        """Return the account-owned stoves used by the entity platforms."""
        return self._account.stoves


@dataclass(frozen=True)
class CountersData:
    """A successful statistics response and its retrieval time."""

    values: Counters
    last_updated: datetime


class MczCountersCoordinator(DataUpdateCoordinator[CountersData]):
    """Poll slow-changing lifetime counters without delaying live stove controls."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: MczConfigEntry,
        controller: MaestroControllerInterface,
        stove: MaestroStove,
    ) -> None:
        """Use an hourly schedule separate from the live polling option."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{config_entry.title} / {stove.Name} counters",
            update_interval=COUNTERS_UPDATE_INTERVAL,
        )
        self._controller = controller
        self.stove = stove

    async def _async_update_data(self) -> CountersData:
        """Keep optional statistics failures separate from account controls."""
        try:
            counters = await self._controller.get_counters_for_stove(
                self.stove.Id, self.stove.Name
            )
        except MaestroAuthenticationException as err:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN,
                translation_key="counters_invalid_auth",
            ) from err
        except MaestroConnectionException as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="counters_cannot_connect",
                translation_placeholders={"error": str(err)},
                retry_after=err.retry_after,
            ) from err
        except (TypeError, ValueError) as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="counters_invalid_response",
            ) from err
        return CountersData(values=counters, last_updated=dt_util.utcnow())


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
            name=f"{config_entry.title} / {stove.Name} consumption",
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
                retry_after=err.retry_after,
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
        midnight = datetime.combine(next_day, time(0, 1), self._time_zone)
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
