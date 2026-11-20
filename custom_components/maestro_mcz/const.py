"""Constants for the maestro_mcz integration."""

DOMAIN = "maestro_mcz"
MANUFACTURER = "MCZ"
DEFAULT_POLLING_INTERVAL = 10
MOCKED_FOLDER = "MOCKED_FOLDER"

# M1 board families keyed by their sensor-set identifiers.
M1_BOARD_TYPES = {
    (
        "7c201fd8-42bd-4333-914d-0f5822070757\u00a7"
        "00000000-0000-0000-0000-000000000000\u00a7"
        "314b03b8-f4ed-11eb-a33c-0242ac120003"
    ): "M1.Air",
    (
        "7c201fd8-42bd-4333-914d-0f5822070757\u00a7"
        "2132564a-aa41-46be-a31c-7e26f94692ce\u00a7"
        "8f90d262-2818-4054-b3ec-5f71f0e90466"
    ): "M1.Hydro",
}
