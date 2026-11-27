"""Keep existing stove imports available from the Maestro package.

The implementation lives in stove.py. Import that module directly from new
code so ownership stays clear and this compatibility entry point stays small.
"""

from .stove import (
    MaestroStove,
    MaestroStoveDeviceMetadata,
    ModelFetchedCallback,
    get_control_names,
)

__all__ = [
    "MaestroStove",
    "MaestroStoveDeviceMetadata",
    "ModelFetchedCallback",
    "get_control_names",
]
