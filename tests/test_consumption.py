"""Consumption history stays dated, optional, and separate from live controls."""

import asyncio
from copy import deepcopy
from datetime import date, timedelta
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.maestro_mcz.coordinator import MczConsumptionCoordinator
from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.diagnostics import async_get_config_entry_diagnostics
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)
from custom_components.maestro_mcz.maestro.controller.responses.consumption import (
    ConsumptionHistory,
)
from custom_components.maestro_mcz.maestro.controller.responses.model import (
    ModelConfiguration,
)
from custom_components.maestro_mcz.maestro.controller.responses.stove_info import StoveInfo
from custom_components.maestro_mcz.sensor import MczYesterdayConsumptionSensor


def history_for(day, value):
    """Build the same dated response as the service, without contacting an account."""
    return ConsumptionHistory.from_response(
        {
            "Data": [{"Date": day.strftime("%Y%m%d"), "Consumption": value}],
            "Total": value,
            "VsPreviousInterval": None,
        }
    )


@pytest.fixture
def history_payload():
    """Provide an unsorted week, including a real day with no consumption."""
    return {
        "Data": [
            {"Date": "20261112", "Consumption": 0},
            {"Date": "20261111", "Consumption": 26.42388},
        ],
        "Total": 26.42388,
        "VsPreviousInterval": -76.16,
    }


@pytest.fixture
async def consumption_factory(hass, entry, controller, stove, freezer):
    """Keep test clocks predictable and remove each history timer after its scenario."""
    freezer.move_to("2026-11-13T12:00:00+00:00")
    coordinators = []

    def create(time_zone=None):
        stove._node.time_zone_iana = time_zone
        coordinator = MczConsumptionCoordinator(hass, entry, controller, stove)
        coordinators.append(coordinator)
        return coordinator

    yield create
    for coordinator in coordinators:
        await coordinator.async_shutdown()


def test_history_preserves_dates_values_and_missing_days(history_payload):
    """Keep the original dated estimates so an absent day is never invented as zero."""
    # 1. Save a copy of the unsorted service response.
    original_response = deepcopy(history_payload)

    # 2. Parse it and look up known and missing dates.
    history = ConsumptionHistory.from_response(history_payload)
    day_without_use = history.consumption_for_date(date(2026, 11, 12))
    day_with_use = history.consumption_for_date(date(2026, 11, 11))
    missing_day = history.consumption_for_date(date(2026, 11, 10))

    # 3. Precision, zero, chronological order, and the original response are preserved.
    assert day_without_use == 0
    assert day_with_use == 26.42388
    assert missing_day is None
    assert history.days[0].date == date(2026, 11, 11)
    assert history.total == 26.42388
    assert history.vs_previous_interval == -76.16
    assert history_payload == original_response


@pytest.mark.parametrize(
    "bad_value",
    [None, True, "12", -1, float("nan"), float("inf"), 10**400],
    ids=["missing", "boolean", "text", "negative", "nan", "infinity", "overflow"],
)
def test_history_rejects_invalid_consumption(history_payload, bad_value):
    """Refuse impossible readings rather than creating credible-looking energy figures."""
    # 1. Replace one day's estimate with an invalid value.
    history_payload["Data"][0]["Consumption"] = bad_value

    # 2. Parsing must reject the entire ambiguous response.
    with pytest.raises(ValueError):
        ConsumptionHistory.from_response(history_payload)


@pytest.mark.parametrize(
    "bad_date", [None, 20261112, "2026112", "2026-11-12", "20260230", "２０２６１１１２"]
)
def test_history_rejects_invalid_dates(history_payload, bad_date):
    """Reject ambiguous dates so consumption cannot silently move to the wrong day."""
    # 1. Give one reading a missing, malformed, or impossible calendar date.
    history_payload["Data"][0]["Date"] = bad_date

    # 2. The response is unusable rather than being guessed or partially accepted.
    with pytest.raises(ValueError):
        ConsumptionHistory.from_response(history_payload)


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        {},
        {"Data": {}, "Total": 0},
        {"Data": [None], "Total": 0},
        {"Data": [], "Total": True},
        {"Data": [], "Total": -1},
        {"Data": [], "Total": 0, "VsPreviousInterval": "unknown"},
        {
            "Data": [
                {"Date": "20261112", "Consumption": 10},
                {"Date": "20261112", "Consumption": 10},
            ],
            "Total": 20,
        },
    ],
)
def test_history_rejects_invalid_shape_or_duplicate_days(payload):
    """Do not hide broken responses or double-count duplicate calendar days."""
    # 1. Use the malformed response chosen by this case.
    # 2. Parsing must fail explicitly instead of returning partial history.
    with pytest.raises(ValueError):
        ConsumptionHistory.from_response(payload)


@pytest.mark.parametrize(
    ("instant", "time_zone", "expected_day"),
    [
        ("2026-01-01T00:30:00+00:00", "America/Los_Angeles", date(2025, 12, 30)),
        ("2026-01-01T00:30:00+00:00", "Pacific/Auckland", date(2025, 12, 31)),
        ("2026-03-29T22:30:00+00:00", "Europe/Brussels", date(2026, 3, 29)),
        ("2026-10-25T23:30:00+00:00", "Europe/Brussels", date(2026, 10, 25)),
    ],
    ids=["previous-year", "ahead-of-utc", "spring-clock-change", "autumn-clock-change"],
)
async def test_history_uses_stove_calendar(
    consumption_factory, controller, freezer, instant, time_zone, expected_day
):
    """Choose yesterday by the stove's calendar, including year and daylight-saving changes."""
    # 1. Put the stove in a different timezone at this case's calendar boundary.
    freezer.move_to(instant)
    history = consumption_factory(time_zone)
    controller.get_consumption_for_stove.return_value = history_for(expected_day, 12.5)

    # 2. Retrieve the day's estimate through the real history coordinator.
    await history.async_refresh()

    # 3. The request and displayed snapshot refer to the correct local date.
    controller.get_consumption_for_stove.assert_awaited_once_with(
        "SERIAL-001", expected_day
    )
    assert history.data.date == expected_day
    assert history.data.value == 12.5
    assert history.data.last_updated == dt_util.utcnow()


@pytest.mark.parametrize("time_zone", [None, "not/a-timezone"])
async def test_history_falls_back_to_home_assistant_timezone(
    hass, consumption_factory, controller, freezer, time_zone, caplog
):
    """Use HA's calendar when the stove lacks a usable timezone, and report an invalid one."""
    # 1. HA is still on the previous calendar day while UTC has reached January.
    await hass.config.async_set_time_zone("America/Los_Angeles")
    freezer.move_to("2026-01-01T00:30:00+00:00")
    history = consumption_factory(time_zone)

    # 2. Fetch optional history with the missing or invalid timezone.
    await history.async_refresh()

    # 3. Both cases use HA's date; malformed metadata is not silently ignored.
    assert history.data.date == date(2025, 12, 30)
    if time_zone is None:
        assert "Invalid consumption timezone" not in caplog.text
    else:
        assert "Invalid consumption timezone" in caplog.text


@pytest.mark.parametrize(
    ("error", "expected", "translation_key"),
    [
        (
            MaestroAuthenticationException("rejected account"),
            ConfigEntryAuthFailed,
            "consumption_invalid_auth",
        ),
        (
            MaestroConnectionException("offline"),
            UpdateFailed,
            "consumption_cannot_connect",
        ),
        (ValueError("broken response"), UpdateFailed, "consumption_invalid_response"),
    ],
)
async def test_history_errors_remain_distinguishable(
    consumption_factory, controller, error, expected, translation_key
):
    """Tell HA whether login, connectivity, or data failed without disabling stove support."""
    # 1. The optional service fails in this case's specific way.
    history = consumption_factory()
    controller.get_consumption_for_stove.side_effect = error

    # 2. Ask the coordinator for an update without HA's outer error handling.
    with pytest.raises(expected) as raised:
        await history._async_update_data()

    # 3. HA gets a translated, classified failure with its original cause preserved.
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == translation_key
    assert raised.value.__cause__ is error


async def test_missing_day_is_not_replaced_by_week_total_or_today(
    consumption_factory, controller
):
    """Keep yesterday missing when the service only supplies another day's estimate."""
    # 1. Today's reading exists, but yesterday's reading has not been published.
    history = consumption_factory()
    controller.get_consumption_for_stove.return_value = history_for(
        date(2026, 11, 13), 42
    )

    # 2. Retrieve the response and inspect the optional sensor.
    await history.async_refresh()
    sensor = MczYesterdayConsumptionSensor(history)

    # 3. Neither today's value nor its total is presented as yesterday's consumption.
    assert history.last_update_success
    assert history.data.value is None
    assert sensor.native_value is None
    assert not sensor.available


async def test_zero_history_is_available_while_stove_is_offline(
    consumption_factory, controller, stove
):
    """Allow genuine zero use and cloud history even when the live stove is unreachable."""
    # 1. The stove is offline, but yesterday's cloud history explicitly reports zero.
    history = consumption_factory()
    stove._is_stove_connected_to_cloud = False
    controller.get_consumption_for_stove.return_value = history_for(
        date(2026, 11, 12), 0
    )
    await history.async_refresh()

    # 2. Create the consumption sensor from its independent coordinator.
    sensor = MczYesterdayConsumptionSensor(history)

    # 3. The estimate is usable and cannot be mistaken for an accumulating meter.
    assert sensor.available
    assert sensor.native_value == 0
    assert sensor.device_class is SensorDeviceClass.ENERGY
    assert sensor.state_class is None
    assert sensor.unique_id == "SERIAL-001-consumption_yesterday"
    assert sensor.extra_state_attributes["consumption_date"] == "2026-11-12"
    assert sensor.extra_state_attributes["last_successful_update"] == (
        dt_util.utcnow().isoformat()
    )


@pytest.mark.parametrize("polling_disabled", [False, True])
async def test_midnight_expires_old_day_without_guessing_next_value(
    hass, entry, consumption_factory, controller, freezer, polling_disabled
):
    """Stop calling an old reading yesterday at local midnight, even with polling disabled."""
    # 1. The stove is one minute from midnight and yesterday's estimate is known.
    freezer.move_to("2026-11-13T22:59:00+00:00")
    history = consumption_factory("Europe/Brussels")
    controller.get_consumption_for_stove.return_value = history_for(
        date(2026, 11, 12), 10
    )
    await history.async_refresh()
    sensor = MczYesterdayConsumptionSensor(history)
    changed = Mock()
    remove_listener = history.async_add_listener(changed)
    hass.config_entries.async_update_entry(
        entry, pref_disable_polling=polling_disabled
    )
    assert sensor.available

    # 2. Midnight arrives before the service has published the newly completed day.
    freezer.move_to("2026-11-13T23:00:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)

    # 3. The old value is expired immediately; automatic refresh respects HA's option.
    assert not sensor.available
    assert sensor.native_value is None
    assert changed.called
    expected_requests = 1 if polling_disabled else 2
    assert controller.get_consumption_for_stove.await_count == expected_requests
    if not polling_disabled:
        controller.get_consumption_for_stove.assert_awaited_with(
            "SERIAL-001", date(2026, 11, 13)
        )

    # 4. The next hourly retry retrieves the newly published day unless polling is disabled.
    controller.get_consumption_for_stove.return_value = history_for(
        date(2026, 11, 13), 0
    )
    freezer.tick(timedelta(hours=1, seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    expected_requests = 1 if polling_disabled else 3
    assert controller.get_consumption_for_stove.await_count == expected_requests
    assert sensor.available is not polling_disabled
    assert sensor.native_value == (None if polling_disabled else 0)

    # 5. Once that day's reading is known, further hourly requests stop.
    freezer.tick(timedelta(hours=1, seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == expected_requests
    remove_listener()


async def test_unknown_snapshot_and_shutdown_do_not_invent_or_poll(
    hass, consumption_factory, controller, freezer
):
    """Keep an unqueried sensor unavailable and remove all calendar work on shutdown."""
    # 1. No response has ever established a consumption reading.
    history = consumption_factory("Europe/Brussels")
    sensor = MczYesterdayConsumptionSensor(history)
    assert not sensor.available
    assert sensor.native_value is None
    assert sensor.extra_state_attributes is None

    # 2. Shut down the coordinator before the next day's callback could fire.
    await history.async_shutdown()
    freezer.move_to("2026-11-14T12:00:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)

    # 3. A removed integration never makes a late history request.
    controller.get_consumption_for_stove.assert_not_awaited()


@pytest.mark.parametrize("model_name", ["M1 example", "Maestro+ example"])
@pytest.mark.parametrize("power_sensor", ["com_on_off", "unrecognized"])
@pytest.mark.parametrize("has_ping", [True, False], ids=["known-ping", "missing-ping"])
async def test_real_platform_discovers_history_later_and_keeps_one_entity(
    hass, entry, controller, freezer, model_name, power_sensor, has_ping
):
    """Discover history for known and unknown layouts without trusting product names."""
    # 1. Known newer pings or missing pings may both offer valid history.
    freezer.move_to("2026-11-13T12:00:00+00:00")
    model = controller.get_stove_model_for_stove.return_value
    model.model_name = model_name
    if not has_ping:
        model.model_configurations = [
            group for group in model.model_configurations
            if group.configuration_name != "cod_for_spe_mqtt"
        ]
    for group in model.model_configurations:
        for configuration in group.configurations:
            if configuration.sensor_name == "com_on_off":
                configuration.sensor_name = power_sensor
    controller.get_consumption_for_stove.side_effect = MaestroConnectionException(
        "Failed to retrieve consumption history"
    )
    with (
        patch("custom_components.maestro_mcz.MaestroController", return_value=controller),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert setup_succeeded
    registry = er.async_get(hass)
    unique_id = "SERIAL-001-consumption_yesterday"
    assert registry.async_get_entity_id("sensor", DOMAIN, unique_id) is None
    history = entry.runtime_data.consumption_coordinators["SERIAL-001"]

    # 2. Empty history still proves nothing; a later exact zero creates the sensor.
    controller.get_consumption_for_stove.side_effect = None
    await history.async_refresh()
    assert registry.async_get_entity_id("sensor", DOMAIN, unique_id) is None
    controller.get_consumption_for_stove.return_value = history_for(
        date(2026, 11, 12), 0
    )
    await history.async_refresh()
    await hass.async_block_till_done()

    # 3. The translated, dated entity appears once, without energy-meter statistics.
    entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
    state = hass.states.get(entity_id)
    assert state.state == "0.0"
    assert state.name == "Living Room Yesterday's consumption"
    assert state.attributes["unit_of_measurement"] == "kWh"
    assert state.attributes["device_class"] == "energy"
    assert state.attributes["consumption_date"] == "2026-11-12"
    assert "state_class" not in state.attributes

    # 4. A temporary failure does not break controls or duplicate the recovered sensor.
    controller.get_consumption_for_stove.side_effect = MaestroConnectionException(
        "Failed to retrieve consumption history"
    )
    await history.async_refresh()
    assert hass.states.get(entity_id).state == "unavailable"
    climate_entity_id = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
    if power_sensor == "com_on_off":
        expected_climate_state = "heat" if has_ping else "unknown"
        assert hass.states.get(climate_entity_id).state == expected_climate_state
    else:
        assert climate_entity_id is None
    controller.get_consumption_for_stove.side_effect = None
    await history.async_refresh()
    await hass.async_block_till_done()
    matching_entries = [
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.unique_id == unique_id
    ]
    assert len(matching_entries) == 1
    assert hass.states.get(entity_id).state == "0.0"

    # 5. Unload the integration; neither hourly polling nor midnight may run afterward.
    await hass.config_entries.async_unload(entry.entry_id)
    request_count_at_unload = controller.get_consumption_for_stove.await_count
    freezer.move_to("2026-11-14T12:00:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == request_count_at_unload


@pytest.mark.parametrize("include_newer_stove", [False, True], ids=["m1-only", "mixed"])
@pytest.mark.parametrize("power_sensor", ["m1_stato_stufa", "com_on_off", "unrecognized"])
async def test_m1_stoves_are_never_queried_for_consumption(
    hass,
    entry,
    controller,
    stove_info_payload,
    freezer,
    include_newer_stove,
    power_sensor,
    configuration,
    monkeypatch,
):
    """Skip M1's misleading zero history without stopping its controls or newer stoves."""
    # 1. Identify M1 by its read channel, whatever power controls it exposes.
    await hass.config.async_set_time_zone("UTC")
    freezer.move_to("2026-11-13T12:00:00+00:00")
    newer_model = controller.get_stove_model_for_stove.return_value
    older_model = deepcopy(newer_model)
    older_model.model_name = "Older example"
    older_model.model_configurations = [
        group for group in older_model.model_configurations
        if group.configuration_name != "cod_for_spe_mqtt"
    ]
    for group in older_model.model_configurations:
        for sensor_configuration in group.configurations:
            if sensor_configuration.sensor_name == "com_on_off":
                sensor_configuration.sensor_name = power_sensor
    # Skip command delays already covered by stove tests; this clock is frozen.
    monkeypatch.setattr(
        "custom_components.maestro_mcz.maestro.MaestroStove._do_ping_m1_configuration",
        AsyncMock(),
    )
    older_model.model_configurations.append(
        ModelConfiguration(
            {
                "ConfigurationName": "PING STOVE",
                "ConfigurationId": "config-m1-ping",
                "Timed": False,
                "Limitations": None,
                "Configurations": [
                    configuration(
                        "m1_cod_for_spe_mqtt",
                        Mappings={"C|RecuperoParametri": 0, "C|RecuperoInfo": 1},
                    )
                ],
            }
        )
    )
    controller.get_stove_model_for_stove.side_effect = (
        [older_model, newer_model] if include_newer_stove else [older_model]
    )
    if include_newer_stove:
        bedroom_payload = deepcopy(stove_info_payload)
        bedroom_payload["Node"].update(
            {
                "Id": "device-2",
                "UniqueCode": "SERIAL-002",
                "Name": "Bedroom",
                "ModelId": "model-2",
            }
        )
        controller.retrieve_linked_stove_infos.return_value.append(
            StoveInfo(bedroom_payload)
        )

    async def published_history(_unique_code, day):
        """Return a real zero for any newer stove that is actually queried."""
        return history_for(day, 0)

    controller.get_consumption_for_stove.side_effect = published_history

    # 2. Load the real platforms and check which stove receives a history sensor.
    with (
        patch("custom_components.maestro_mcz.MaestroController", return_value=controller),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert setup_succeeded
    registry = er.async_get(hass)
    assert "SERIAL-001" not in entry.runtime_data.consumption_coordinators
    assert registry.async_get_entity_id(
        "sensor", DOMAIN, "SERIAL-001-consumption_yesterday"
    ) is None
    climate_entity = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
    if power_sensor != "unrecognized":
        assert hass.states.get(climate_entity).state == "heat"
    else:
        assert climate_entity is None
    if include_newer_stove:
        bedroom_sensor = registry.async_get_entity_id(
            "sensor", DOMAIN, "SERIAL-002-consumption_yesterday"
        )
        assert hass.states.get(bedroom_sensor).state == "0.0"
        controller.get_consumption_for_stove.assert_awaited_once_with(
            "SERIAL-002", date(2026, 11, 12)
        )
    else:
        controller.get_consumption_for_stove.assert_not_awaited()

    # 3. Hourly timers and the next midnight must never query the M1 stove either.
    freezer.tick(timedelta(hours=1, seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    expected_requests = 1 if include_newer_stove else 0
    assert controller.get_consumption_for_stove.await_count == expected_requests
    freezer.move_to("2026-11-14T00:00:00+00:00")
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    expected_requests = 2 if include_newer_stove else 0
    assert controller.get_consumption_for_stove.await_count == expected_requests
    for request in controller.get_consumption_for_stove.await_args_list:
        assert request.args[0] == "SERIAL-002"
    await hass.config_entries.async_unload(entry.entry_id)


async def test_slow_initial_history_does_not_hold_up_controls(hass, entry, controller):
    """Load live controls without waiting for optional history, and cancel it on unload."""
    # 1. The live cloud works, but the history service never completes its request.
    history_started = asyncio.Event()
    history_cancelled = asyncio.Event()

    async def delayed_history(_unique_code, _day):
        """Represent a slow optional service without making a real network request."""
        history_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            history_cancelled.set()

    controller.get_consumption_for_stove.side_effect = delayed_history
    with (
        patch("custom_components.maestro_mcz.MaestroController", return_value=controller),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Setting up HA must finish even while the optional request is still waiting.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await asyncio.wait_for(history_started.wait(), timeout=1)

    # 3. Heating controls are usable, and unloading cancels the outstanding request.
    assert setup_succeeded
    registry = er.async_get(hass)
    climate_entity_id = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
    assert hass.states.get(climate_entity_id).state == "heat"
    await hass.config_entries.async_unload(entry.entry_id)
    assert history_cancelled.is_set()


async def test_history_failure_is_isolated_to_one_stove(
    hass, entry, controller, stove_info_payload, freezer
):
    """Keep another stove's history and controls working when one endpoint rejects history."""
    # 1. Link a second stove; only its history endpoint provides a valid reading.
    freezer.move_to("2026-11-13T12:00:00+00:00")
    bedroom_payload = deepcopy(stove_info_payload)
    bedroom_payload["Node"].update(
        {"Id": "device-2", "UniqueCode": "SERIAL-002", "Name": "Bedroom"}
    )
    controller.retrieve_linked_stove_infos.return_value.append(
        StoveInfo(bedroom_payload)
    )

    async def consumption_for_stove(unique_code, day):
        """Make the service reject only the living-room stove's history."""
        if unique_code == "SERIAL-001":
            raise MaestroConnectionException("Failed to retrieve consumption history")
        return history_for(day, 7)

    controller.get_consumption_for_stove.side_effect = consumption_for_stove
    with (
        patch("custom_components.maestro_mcz.MaestroController", return_value=controller),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Load both devices through the real integration.
        setup_succeeded = await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    # 3. Only the supported history sensor appears, while both heating controls work.
    assert setup_succeeded
    registry = er.async_get(hass)
    living_room_sensor = registry.async_get_entity_id(
        "sensor", DOMAIN, "SERIAL-001-consumption_yesterday"
    )
    bedroom_sensor = registry.async_get_entity_id(
        "sensor", DOMAIN, "SERIAL-002-consumption_yesterday"
    )
    assert living_room_sensor is None
    assert hass.states.get(bedroom_sensor).state == "7.0"
    for unique_code in ("SERIAL-001", "SERIAL-002"):
        climate_entity = registry.async_get_entity_id("climate", DOMAIN, unique_code)
        assert hass.states.get(climate_entity).state == "heat"
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("consumption", [0, 10])
async def test_known_history_is_not_requested_again_with_live_or_hourly_updates(
    hass, entry, controller, freezer, consumption
):
    """Keep a known yesterday reading, including zero, without unnecessary cloud requests."""
    # 1. Load a stove with a known estimate and record the single initial history request.
    freezer.move_to("2026-11-13T12:00:00+00:00")
    controller.get_consumption_for_stove.return_value = history_for(
        date(2026, 11, 12), consumption
    )
    with (
        patch("custom_components.maestro_mcz.MaestroController", return_value=controller),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == 1

    # 2. Refresh live readings, then advance beyond one ordinary live polling interval.
    await entry.runtime_data.async_refresh()
    freezer.tick(timedelta(seconds=30))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == 1

    # 3. Reaching the next hour does not retrieve the same completed day again.
    freezer.tick(timedelta(hours=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == 1
    await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    "initial_error",
    [None, MaestroConnectionException("offline"), ValueError("broken response")],
    ids=["not-published", "request-failed", "invalid-response"],
)
async def test_history_retries_hourly_until_yesterday_is_available(
    hass, consumption_factory, controller, freezer, initial_error
):
    """Retry missing or failed history hourly, then stop once a valid zero is published."""
    # 1. Yesterday is unpublished or its request fails; keep listening for recovery.
    history = consumption_factory()
    sensor = MczYesterdayConsumptionSensor(history)
    controller.get_consumption_for_stove.side_effect = initial_error
    await history.async_refresh()
    remove_listener = history.async_add_listener(Mock())
    assert controller.get_consumption_for_stove.await_count == 1
    assert not sensor.available

    # 2. Wait nearly an hour without a request, then retry the still-missing reading.
    freezer.tick(timedelta(minutes=59))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == 1
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == 2
    assert not sensor.available

    # 3. A later hourly retry receives a real zero and makes the sensor available.
    controller.get_consumption_for_stove.side_effect = None
    controller.get_consumption_for_stove.return_value = history_for(
        date(2026, 11, 12), 0
    )
    freezer.tick(timedelta(hours=1, seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == 3
    assert sensor.available
    assert sensor.native_value == 0

    # 4. Further hours keep the recorded reading without more cloud traffic.
    freezer.tick(timedelta(hours=1, seconds=1))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_consumption_for_stove.await_count == 3
    remove_listener()


@pytest.mark.parametrize("history_state", ["not-yet-queried", "recorded", "rejected"])
async def test_history_diagnostics_explain_availability_without_serials(
    hass, entry, coordinator, consumption_factory, controller, history_state
):
    """Make optional-history problems diagnosable without sharing the stove's serial number."""
    # 1. Attach unqueried, recorded, or rejected history to the existing test account.
    history = consumption_factory()
    coordinator.consumption_coordinators["SERIAL-001"] = history
    if history_state == "recorded":
        controller.get_consumption_for_stove.return_value = history_for(
            date(2026, 11, 12), 12.5
        )
        await history.async_refresh()
    elif history_state == "rejected":
        controller.get_consumption_for_stove.side_effect = MaestroConnectionException(
            "Failed to retrieve consumption history"
        )
        await history.async_refresh()

    # 2. Download the same diagnostics a user would attach to a bug report.
    report = await async_get_config_entry_diagnostics(hass, entry)
    consumption = report["devices"]["Living Room"]["consumption"]

    # 3. Availability and dated readings explain the situation without a request URL.
    assert consumption["last_update_success"] is (history_state != "rejected")
    if history_state == "recorded":
        assert consumption["consumption_date"] == "2026-11-12"
        assert consumption["value"] == 12.5
        assert consumption["last_successful_update"] == dt_util.utcnow().isoformat()
    else:
        assert consumption["consumption_date"] is None
        assert consumption["value"] is None
        assert consumption["last_successful_update"] is None
    exported_report = json.dumps(report)
    assert "SERIAL-001" not in exported_report
