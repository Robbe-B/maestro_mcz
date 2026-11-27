"""Save cloud model definitions without using them for runtime model selection."""

import logging
from dataclasses import asdict
from hashlib import sha256
from typing import TypedDict

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .maestro.controller.response_types import JsonObject
from .maestro.controller.responses.model import Model

_LOGGER = logging.getLogger(__name__)
_STORAGE_VERSION = 1


class ModelSnapshot(TypedDict):
    """Associate complete model metadata with the cloud-confirmed stove serial."""

    unique_code: str
    model_id: str
    sensor_set_type_id: str
    fetched_at: str
    model: JsonObject


class ModelCache:
    """Persist one independent snapshot per physical stove, never live readings."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Bind storage to this Home Assistant installation."""
        self._hass = hass

    async def async_save_model(
        self,
        unique_code: str,
        model_id: str,
        sensor_set_type_id: str,
        model: Model,
    ) -> None:
        """Save freshly fetched metadata while leaving cloud operation unaffected."""
        snapshot: ModelSnapshot = {
            "unique_code": unique_code,
            "model_id": model_id,
            "sensor_set_type_id": sensor_set_type_id,
            "fetched_at": dt_util.utcnow().isoformat(),
            "model": asdict(model),
        }
        # Hash the serial so cloud identifiers cannot become filesystem paths.
        identity = sha256(unique_code.encode()).hexdigest()
        store = Store[ModelSnapshot](
            self._hass,
            _STORAGE_VERSION,
            f"{DOMAIN}.model_definition.{identity}",
            private=True,
            atomic_writes=True,
            serialize_in_event_loop=False,
        )
        try:
            await store.async_save(snapshot)
        except (HomeAssistantError, OSError) as err:
            _LOGGER.error("Unable to save stove model definition: %s", err)
