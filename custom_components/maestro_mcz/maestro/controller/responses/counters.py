"""Lifetime counters returned by the appliance statistics endpoint."""

import math
from dataclasses import dataclass, field, fields


@dataclass
class Counters:
    """Validate nullable lifetime counters while preserving their reported units."""

    num_acc: int | None = None
    cont_tot_h_lavoro: int | None = None
    cont_tot_t_lavoro: int | None = None
    cont_tot_t_lav1: int | None = None
    cont_tot_t_lav2: int | None = None
    cont_tot_t_lav3: int | None = None
    cont_tot_t_lav4: int | None = None
    cont_tot_t_lav5: int | None = None
    ore_prox_manut: int | None = field(default=None, metadata={"allow_negative": True})

    def __init__(self, response: object) -> None:
        """Reject invalid readings without inventing zeros for missing counters."""
        if not isinstance(response, dict):
            raise TypeError("Counters response must be an object")
        for counter_field in fields(self):
            value = response.get(counter_field.name)
            if value is not None:
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ValueError(f"Counter {counter_field.name} must be an integer")
                try:
                    finite = math.isfinite(value)
                except OverflowError as err:
                    raise ValueError(
                        f"Counter {counter_field.name} is too large"
                    ) from err
                if not finite or (
                    value < 0
                    and not counter_field.metadata.get("allow_negative", False)
                ):
                    raise ValueError(
                        f"Counter {counter_field.name} is outside its range"
                    )
            setattr(self, counter_field.name, value)
