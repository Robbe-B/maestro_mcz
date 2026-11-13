"""Dated consumption estimates returned by the Maestro history service."""

from dataclasses import dataclass
from datetime import date, datetime
import math
from typing import Self


def _number(value: object, *, non_negative: bool = True) -> float:
    """Reject missing, non-numeric and non-finite consumption values."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Consumption must be a number")
    try:
        result = float(value)
    except OverflowError as err:
        raise ValueError("Consumption is outside the supported numeric range") from err
    if not math.isfinite(result) or (non_negative and result < 0):
        raise ValueError("Consumption is outside the supported numeric range")
    return result


@dataclass(frozen=True)
class ConsumptionDay:
    """One calendar day's estimated energy consumption."""

    date: date
    consumption: float


@dataclass(frozen=True)
class ConsumptionHistory:
    """Validated history without assuming that missing days mean zero."""

    days: tuple[ConsumptionDay, ...]
    total: float
    vs_previous_interval: float | None

    @classmethod
    def from_response(cls, response: object) -> Self:
        """Parse the documented API shape without accepting ambiguous readings."""
        if not isinstance(response, dict) or not isinstance(response.get("Data"), list):
            raise ValueError("Consumption response must contain a Data list")

        days: dict[date, ConsumptionDay] = {}
        for item in response["Data"]:
            if not isinstance(item, dict):
                raise ValueError("Consumption entries must be objects")
            raw_date = item.get("Date")
            if (
                not isinstance(raw_date, str)
                or len(raw_date) != 8
                or not raw_date.isascii()
                or not raw_date.isdigit()
            ):
                raise ValueError("Consumption dates must use yyyyMMdd")
            day = datetime.strptime(raw_date, "%Y%m%d").date()
            if day in days:
                raise ValueError("Consumption dates must be unique")
            days[day] = ConsumptionDay(day, _number(item.get("Consumption")))

        comparison = response.get("VsPreviousInterval")
        return cls(
            days=tuple(days[day] for day in sorted(days)),
            total=_number(response.get("Total")),
            vs_previous_interval=(
                _number(comparison, non_negative=False)
                if comparison is not None
                else None
            ),
        )

    def consumption_for_date(self, day: date) -> float | None:
        """Return the exact day's value, including zero, or no reading."""
        return next(
            (item.consumption for item in self.days if item.date == day),
            None,
        )
