"""Lifetime statistics stay correctly scaled and separate from live controls."""

import asyncio
import json
from copy import deepcopy
from dataclasses import asdict
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, PropertyMock, patch

import pytest
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorStateClass,
    async_rounded_state,
)
from homeassistant.const import UnitOfTime
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import UpdateFailed
from homeassistant.util import dt as dt_util
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.maestro_mcz.const import DOMAIN
from custom_components.maestro_mcz.coordinator import MczCountersCoordinator
from custom_components.maestro_mcz.diagnostics import async_get_config_entry_diagnostics
from custom_components.maestro_mcz.maestro.controller.maestro_controller import (
    MaestroAuthenticationException,
    MaestroConnectionException,
)
from custom_components.maestro_mcz.maestro.controller.mocked_controller import (
    MockedController,
)
from custom_components.maestro_mcz.maestro.controller.responses.counters import Counters
from custom_components.maestro_mcz.maestro.controller.responses.model import (
    ModelConfiguration,
)
from custom_components.maestro_mcz.maestro.controller.responses.stove_info import (
    StoveInfo,
)
from custom_components.maestro_mcz.maestro.model_value_reader import get_counter_value
from custom_components.maestro_mcz.maestro.models import model_definitions
from custom_components.maestro_mcz.maestro.models.models_types import (
    CounterMczConfigItem,
    MczStoveModelGeneration,
)
from custom_components.maestro_mcz.sensor import MczCounterSensor


@pytest.fixture
def counters_payload():
    """Provide M2+ hours, a genuine zero bucket, and a separate maintenance countdown."""
    return {
        "num_acc": 123,
        "cont_tot_h_lavoro": 1000,
        "cont_tot_t_lav1": 0,
        "cont_tot_t_lav2": 10,
        "cont_tot_t_lav3": 20,
        "cont_tot_t_lav4": 30,
        "cont_tot_t_lav5": 40,
        "ore_prox_manut": -3,
        "IsConnected": False,
    }


@pytest.fixture
async def counters_factory(hass, entry, controller, stove):
    """Remove each test's optional statistics timer after its scenario."""
    coordinators = []

    def create():
        coordinator = MczCountersCoordinator(hass, entry, controller, stove)
        coordinators.append(coordinator)
        return coordinator

    yield create
    for coordinator in coordinators:
        await coordinator.async_shutdown()


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        ({}, None),
        ({"cont_tot_h_lavoro": 0}, 0),
        ({"cont_tot_h_lavoro": 0, "cont_tot_t_lavoro": 5400}, 0),
        ({"cont_tot_t_lavoro": 5400}, 1.5),
        ({"cont_tot_h_lavoro": 2, "cont_tot_t_lavoro": 7200}, 2),
    ],
)
def test_totals_preserve_units_zero_and_missing_values(total, expected):
    """Use the explicitly named total without inventing time from incomplete power buckets."""
    # 1. Give the service a total and a power bucket that need not cover all operation.
    payload = total | {"cont_tot_t_lav1": 999}
    original = deepcopy(payload)

    # 2. Parse the saved reading without altering it.
    counters = Counters(payload)
    total_definition = next(
        definition
        for definition in model_definitions.supported_counters
        if definition.sensor_get_name == "total_operating_hours"
    )
    operating_hours = get_counter_value(
        total_definition, counters, MczStoveModelGeneration.M2_PLUS
    )

    # 3. Missing values stay missing, and seconds are converted only for the seconds total.
    assert operating_hours == expected
    assert counters.num_acc is None
    assert counters.cont_tot_t_lav1 == 999
    assert payload == original


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "",
        {"num_acc": True},
        {"num_acc": "3"},
        {"num_acc": -1},
        {"cont_tot_h_lavoro": -1},
        {"cont_tot_t_lav1": 1.5},
        {"cont_tot_t_lav2": float("nan")},
        {"cont_tot_t_lav3": float("inf")},
        {"cont_tot_t_lav4": 10**400},
        {"ore_prox_manut": False},
    ],
)
def test_invalid_counters_fail_explicitly(payload):
    """Reject malformed statistics so broken responses cannot become credible lifetime totals."""
    # 1. Use this case's invalid response or reading.
    # 2. Parsing must report a failure rather than manufacture a zero.
    with pytest.raises((TypeError, ValueError)):
        Counters(payload)


@pytest.mark.parametrize(
    ("generation", "raw_power", "expected"),
    [
        (MczStoveModelGeneration.M1, 5400, 1.5),
        (MczStoveModelGeneration.M2_PLUS, 3, 3),
    ],
)
async def test_power_units_follow_controller_family(
    counters_factory, controller, stove, coordinator, generation, raw_power, expected
):
    """Display both families in hours so their operating times can be compared safely."""
    # 1. The cloud has a reading even though the physical stove is disconnected.
    counters = counters_factory()
    controller.get_counters_for_stove.return_value = Counters(
        {"cont_tot_t_lav1": raw_power, "num_acc": 0}
    )
    stove.Status.is_connected = False
    power_sensor = MczCounterSensor(
        counters, model_definitions.supported_counters[2], coordinator
    )
    assert power_sensor.native_value is None
    assert not power_sensor.available

    # 2. Read the lifetime counters with this case's identified control family.
    with patch.object(
        type(stove), "model_generation", new_callable=PropertyMock
    ) as family:
        family.return_value = generation
        await counters.async_refresh()

        # 3. Cloud statistics remain readable with correctly normalized units.
        assert power_sensor.native_value == expected
        assert power_sensor.available is (expected is not None)
        ignition_sensor = MczCounterSensor(
            counters, model_definitions.supported_counters[0], coordinator
        )
        assert ignition_sensor.native_value == 0
        assert ignition_sensor.available
    controller.get_counters_for_stove.assert_awaited_once_with(
        "device-1", "Living Room"
    )


@pytest.mark.parametrize("family", ["m1", "m2", "missing-ping"])
async def test_real_platform_uses_m1_seconds_and_m2_default(
    hass, entry, controller, configuration, family
):
    """Show whole hours on both families while keeping precise readings for history."""
    # 1. Identify M1 by its command, or keep the normal M2+ fallback.
    model = controller.get_stove_model_for_stove.return_value
    model.model_configurations = [
        group
        for group in model.model_configurations
        if family == "m2" or group.configuration_name != "cod_for_spe_mqtt"
    ]
    if family == "m1":
        model.model_configurations.append(
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
    raw_time = 5400 if family == "m1" else 2
    total_key = "cont_tot_t_lavoro" if family == "m1" else "cont_tot_h_lavoro"
    counter_values = {"num_acc": 0, total_key: raw_time}
    for power in range(1, 6):
        counter_values[f"cont_tot_t_lav{power}"] = raw_time
    controller.get_counters_for_stove.return_value = Counters(counter_values)
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
        patch(
            "custom_components.maestro_mcz.maestro.MaestroStove._do_ping_m1_configuration",
            new_callable=AsyncMock,
        ),
    ):
        # 2. Load real platforms without waiting through M1's command delays.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    # 3. All time counters display whole hours while keeping precise hour readings.
    registry = er.async_get(hass)
    expected_hours = 1.5 if family == "m1" else 2
    counter_keys = ["total_operating_hours"]
    counter_keys.extend(f"cont_tot_t_lav{power}" for power in range(1, 6))
    for key in counter_keys:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, f"SERIAL-001-{key}")
        state = hass.states.get(entity_id)
        assert float(state.state) == expected_hours
        assert state.attributes["unit_of_measurement"] == "h"
        displayed_hours = async_rounded_state(hass, entity_id, state)
        assert displayed_hours == "2"
    controller.get_counters_for_stove.assert_awaited_once_with(
        "device-1", "Living Room"
    )
    if family == "m1":
        controller.get_consumption_for_stove.assert_not_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_new_counter_definition_drives_discovery_and_presentation(
    hass, entry, controller, monkeypatch
):
    """Support another counter through its definition without changing sensor code."""
    # 1. Describe a different counter that displays a saved seconds field in minutes.
    custom_counter = CounterMczConfigItem(
        user_friendly_name="Custom operating time",
        sensor_get_name="custom_operating_time",
        value_sources={"cont_tot_t_lav3": 60},
        unit=UnitOfTime.MINUTES,
        display_precision=1,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL,
    )
    monkeypatch.setattr(model_definitions, "supported_counters", [custom_counter])
    controller.get_counters_for_stove.return_value = Counters(
        {"cont_tot_t_lav3": 5400, "num_acc": 123}
    )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Load the normal platform using only the replacement definition.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    # 3. The definition controls discovery, identity, conversion, and presentation.
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "sensor", DOMAIN, "SERIAL-001-custom_operating_time"
    )
    state = hass.states.get(entity_id)
    assert state.name == "Living Room Custom operating time"
    assert float(state.state) == 90
    assert state.attributes["unit_of_measurement"] == "min"
    assert state.attributes["state_class"] == "total"
    assert "icon" not in state.attributes
    assert registry.async_get(entity_id).entity_category is None
    assert registry.async_get_entity_id("sensor", DOMAIN, "SERIAL-001-num_acc") is None
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize(
    ("error", "expected", "translation_key"),
    [
        (
            MaestroAuthenticationException("expired"),
            ConfigEntryAuthFailed,
            "counters_invalid_auth",
        ),
        (
            MaestroConnectionException("offline"),
            UpdateFailed,
            "counters_cannot_connect",
        ),
        (ValueError("invalid"), UpdateFailed, "counters_invalid_response"),
        (TypeError("invalid shape"), UpdateFailed, "counters_invalid_response"),
    ],
)
async def test_counters_errors_are_classified(
    counters_factory, controller, error, expected, translation_key
):
    """Distinguish login, connection, and data problems so HA can handle each appropriately."""
    # 1. Only the optional statistics request fails.
    counters = counters_factory()
    controller.get_counters_for_stove.side_effect = error

    # 2. Request statistics through the real coordinator.
    with pytest.raises(expected) as raised:
        await counters._async_update_data()

    # 3. The translated failure preserves the cause instead of hiding it as missing data.
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == translation_key
    assert raised.value.__cause__ is error


@pytest.mark.parametrize("polling_disabled", [False, True])
async def test_discovery_recovery_polling_and_unload(
    hass, entry, controller, counters_payload, freezer, polling_disabled
):
    """Discover counters later, keep their identities, and never couple their schedule to controls."""
    # 1. Live controls and maintenance work while the optional endpoint initially fails.
    freezer.move_to("2026-11-15T12:00:00+00:00")
    hass.config_entries.async_update_entry(entry, pref_disable_polling=polling_disabled)
    controller.get_stove_status_for_stove.return_value.ore_prox_manut = 937
    controller.get_counters_for_stove.side_effect = MaestroConnectionException(
        "offline"
    )
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data.coordinator
    counters = coordinator.counters_coordinators["SERIAL-001"]
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, "SERIAL-001-num_acc") is None
    maintenance_id = registry.async_get_entity_id(
        "sensor", DOMAIN, "SERIAL-001-ore_prox_manut"
    )
    assert hass.states.get(maintenance_id).state == "937"

    # 2. A later partial response reveals just one real zero; a full reply adds the rest.
    controller.get_counters_for_stove.side_effect = None
    controller.get_counters_for_stove.return_value = Counters({"num_acc": 0})
    await counters.async_refresh()
    await hass.async_block_till_done()
    ignition_id = registry.async_get_entity_id("sensor", DOMAIN, "SERIAL-001-num_acc")
    assert hass.states.get(ignition_id).state == "0"
    assert (
        registry.async_get_entity_id(
            "sensor", DOMAIN, "SERIAL-001-total_operating_hours"
        )
        is None
    )
    controller.get_counters_for_stove.return_value = Counters(counters_payload)
    await counters.async_refresh()
    await hass.async_block_till_done()

    # 3. All seven counters share the stove, with translated names and lifetime statistics.
    for definition in model_definitions.supported_counters:
        unique_id = f"SERIAL-001-{definition.sensor_get_name}"
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        state = hass.states.get(entity_id)
        assert state.attributes["state_class"] == "total_increasing"
        assert (
            registry.async_get(entity_id).entity_category
            is er.EntityCategory.DIAGNOSTIC
        )
        assert (
            registry.async_get(entity_id).device_id
            == registry.async_get(maintenance_id).device_id
        )
        if definition.sensor_get_name != "num_acc":
            assert state.attributes["unit_of_measurement"] == "h"
            assert state.attributes["device_class"] == "duration"
    assert hass.states.get(ignition_id).name == "Living Room Ignition count"
    power_id = registry.async_get_entity_id(
        "sensor", DOMAIN, "SERIAL-001-cont_tot_t_lav1"
    )
    assert float(hass.states.get(power_id).state) == 0
    assert hass.states.get(maintenance_id).state == "937"

    # 4. Missing readings become unavailable; a failed refresh affects only statistics.
    controller.get_counters_for_stove.return_value = Counters({})
    await counters.async_refresh()
    assert hass.states.get(ignition_id).state == "unavailable"
    controller.get_counters_for_stove.side_effect = MaestroConnectionException(
        "offline"
    )
    await counters.async_refresh()
    climate_id = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
    assert hass.states.get(climate_id).state == "heat"
    assert hass.states.get(maintenance_id).state == "937"
    controller.get_counters_for_stove.side_effect = None
    controller.get_counters_for_stove.return_value = Counters(counters_payload)
    await counters.async_refresh()
    await hass.async_block_till_done()
    matching = [
        item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
        if item.unique_id == "SERIAL-001-num_acc"
    ]
    assert len(matching) == 1
    assert hass.states.get(ignition_id).state == "123"

    # 5. Live refresh and the first 59 minutes do not request the slow-changing counters.
    request_count = controller.get_counters_for_stove.await_count
    await coordinator.async_refresh()
    freezer.tick(timedelta(minutes=59))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_counters_for_stove.await_count == request_count
    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    expected_count = request_count if polling_disabled else request_count + 1
    assert controller.get_counters_for_stove.await_count == expected_count

    # 6. Unloading cancels all future statistics requests.
    assert await hass.config_entries.async_unload(entry.entry_id)
    freezer.tick(timedelta(hours=2))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert controller.get_counters_for_stove.await_count == expected_count


@pytest.mark.parametrize("polling_disabled", [False, True])
async def test_counter_availability_follows_cloud_without_extra_requests(
    hass, entry, controller, polling_disabled
):
    """Hide cached counters during cloud outages and restore them without hourly requests."""
    # 1. Discover a genuine zero through the real platforms and normal startup request.
    hass.config_entries.async_update_entry(entry, pref_disable_polling=polling_disabled)
    controller.get_counters_for_stove.return_value = Counters({"num_acc": 0})
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
    account = entry.runtime_data.coordinator
    counters = account.counters_coordinators["SERIAL-001"]
    registry = er.async_get(hass)
    ignition_id = registry.async_get_entity_id("sensor", DOMAIN, "SERIAL-001-num_acc")
    assert hass.states.get(ignition_id).state == "0"
    initial_requests = controller.get_counters_for_stove.await_count
    assert initial_requests == 1

    # 2. A live cloud failure immediately hides counters, before their hourly refresh.
    controller.get_stove_state_for_stove.side_effect = MaestroConnectionException(
        "cloud unavailable"
    )
    await account.async_refresh()
    await hass.async_block_till_done()
    assert not account.last_update_success
    assert counters.last_update_success
    assert hass.states.get(ignition_id).state == "unavailable"
    assert controller.get_counters_for_stove.await_count == initial_requests

    # 3. Cloud recovery restores the saved zero without another statistics request.
    controller.get_stove_state_for_stove.side_effect = None
    await account.async_refresh()
    await hass.async_block_till_done()
    assert account.last_update_success
    assert hass.states.get(ignition_id).state == "0"
    assert controller.get_counters_for_stove.await_count == initial_requests

    # 4. An offline physical stove does not hide statistics when cloud access still works.
    controller.get_stove_status_for_stove.return_value.is_connected = False
    await account.async_refresh()
    await hass.async_block_till_done()
    assert account.last_update_success
    assert not account.stoves["SERIAL-001"].is_connected
    assert hass.states.get(ignition_id).state == "0"
    assert controller.get_counters_for_stove.await_count == initial_requests

    # 5. A statistics-only failure stays unavailable despite successful live updates.
    controller.get_counters_for_stove.side_effect = MaestroConnectionException(
        "statistics unavailable"
    )
    await counters.async_refresh()
    await account.async_refresh()
    await hass.async_block_till_done()
    assert account.last_update_success
    assert not counters.last_update_success
    assert hass.states.get(ignition_id).state == "unavailable"
    assert controller.get_counters_for_stove.await_count == initial_requests + 1

    # 6. Unloading removes both subscriptions, so later updates cannot reach removed entities.
    assert account._listeners
    assert counters._listeners
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not account._listeners
    assert not counters._listeners
    account.async_set_updated_data(None)
    await hass.async_block_till_done()
    assert controller.get_counters_for_stove.await_count == initial_requests + 1


async def test_slow_counters_do_not_delay_controls(hass, entry, controller):
    """Load heating controls promptly and cancel an outstanding statistics request on unload."""
    # 1. Statistics never finish, although ordinary stove requests work.
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def delayed_counters(_device_id, _device_name):
        """Represent a slow cloud reply without real network access."""
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    controller.get_counters_for_stove.side_effect = delayed_counters
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Setup finishes even while statistics are still loading.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await asyncio.wait_for(started.wait(), timeout=1)

    # 3. Heating works and removing the integration cancels the optional request.
    registry = er.async_get(hass)
    climate_id = registry.async_get_entity_id("climate", DOMAIN, "SERIAL-001")
    assert hass.states.get(climate_id).state == "heat"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert cancelled.is_set()


async def test_one_stoves_failure_does_not_break_anothers_statistics(
    hass, entry, controller, stove_info_payload
):
    """Keep counters isolated per stove when one cloud endpoint is unavailable."""
    # 1. Two stoves share an account, but only the second returns statistics.
    bedroom_payload = deepcopy(stove_info_payload)
    bedroom_payload["Node"].update(
        {"Id": "device-2", "UniqueCode": "SERIAL-002", "Name": "Bedroom"}
    )
    controller.retrieve_linked_stove_infos.return_value.append(
        StoveInfo(bedroom_payload)
    )

    async def counters_for_stove(device_id, _device_name):
        """Reject only the first stove's optional endpoint."""
        if device_id == "device-1":
            raise MaestroConnectionException("offline")
        return Counters({"num_acc": 7})

    controller.get_counters_for_stove.side_effect = counters_for_stove
    with (
        patch(
            "custom_components.maestro_mcz.MaestroController", return_value=controller
        ),
        patch("custom_components.maestro_mcz._has_mocked_folder", return_value=None),
    ):
        # 2. Load both devices through the real platforms.
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)

    # 3. The supported counter appears while both stoves retain working heating controls.
    registry = er.async_get(hass)
    assert registry.async_get_entity_id("sensor", DOMAIN, "SERIAL-001-num_acc") is None
    bedroom_id = registry.async_get_entity_id("sensor", DOMAIN, "SERIAL-002-num_acc")
    assert hass.states.get(bedroom_id).state == "7"
    for unique_code in ("SERIAL-001", "SERIAL-002"):
        climate_id = registry.async_get_entity_id("climate", DOMAIN, unique_code)
        assert hass.states.get(climate_id).state == "heat"
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("snapshot", ["unqueried", "recorded", "failed"])
async def test_diagnostics_and_replay_preserve_counters(
    hass,
    entry,
    coordinator,
    counters_factory,
    controller,
    counters_payload,
    tmp_path,
    snapshot,
):
    """Make statistics problems reproducible without exporting serial numbers or changing units."""
    # 1. Attach unqueried, recorded, or failed counters to the account.
    counters = counters_factory()
    coordinator.counters_coordinators["SERIAL-001"] = counters
    controller.get_counters_for_stove.return_value = Counters(counters_payload)
    if snapshot != "unqueried":
        await counters.async_refresh()
    if snapshot == "failed":
        controller.get_counters_for_stove.side_effect = MaestroConnectionException(
            "offline"
        )
        await counters.async_refresh()

    # 2. Save the normal diagnostic download and replay it without cloud access.
    report = await async_get_config_entry_diagnostics(hass, entry)
    statistics = report["devices"]["Living Room"]["counters"]
    assert "SERIAL-001" not in json.dumps(report)
    assert statistics["last_update_success"] is (snapshot != "failed")
    (tmp_path / "report.json").write_text(
        json.dumps({"data": report}), encoding="utf-8"
    )
    replay = MockedController(str(tmp_path))
    await replay.retrieve_linked_stove_infos()
    restored = await replay.get_counters_for_stove("device-1", "Living Room")

    # 3. Known values retain original units; unqueried snapshots and unknown stoves stay empty.
    if snapshot == "unqueried":
        assert restored == Counters({})
        assert statistics["last_successful_update"] is None
    else:
        assert asdict(restored) == statistics["values"]
        assert restored.ore_prox_manut == -3
        assert (
            statistics["last_successful_update"]
            == counters.data.last_updated.isoformat()
        )
    assert await replay.get_counters_for_stove("missing", "unknown") == Counters({})


@pytest.mark.parametrize(
    "saved", [None, [], {"values": []}, {"values": {"num_acc": "bad"}}]
)
async def test_replay_handles_old_reports_and_rejects_malformed_counters(saved):
    """Replay older reports without invented statistics and expose invalid saved data clearly."""
    # 1. Describe an older or malformed saved statistics section for one stove.
    replay = MockedController(None)
    replay._mocked_stoves[("device-1", "Living Room")] = Mock(counters=saved)

    # 2. Old reports stay empty; malformed reports must fail rather than hide corrupt readings.
    if saved is None:
        restored = await replay.get_counters_for_stove("device-1", "Living Room")
        assert restored == Counters({})
    else:
        with pytest.raises((TypeError, ValueError)):
            await replay.get_counters_for_stove("device-1", "Living Room")
