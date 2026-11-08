"""Diagnostics stay useful without leaking configured account credentials."""

from dataclasses import asdict
import json

from homeassistant.components.diagnostics import REDACTED

from custom_components.maestro_mcz.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redaction_and_round_trip(hass, entry, coordinator, stove):
    """Make reports useful to helpers without exposing passwords or changing readings."""
    # 1. Give the stove private details that must not appear in a shared report.
    stove.Status.sm_sn = "synthetic-serial"
    stove.Status.ssid_wifi = "synthetic-network"
    stove.Status.pwd_wifi = "synthetic-wifi-password"
    stove.Status.mac_wifi = "AA:BB:CC:DD:EE:FF"
    original_status = asdict(stove.Status)

    # 2. Ask Home Assistant to produce a report suitable for sharing.
    report = await async_get_config_entry_diagnostics(hass, entry)
    stove_data = report["devices"]["Living Room"]["coordinator.stove_data"]

    # 3. Private details are hidden, but useful readings are still included.
    assert report["config_entry_data"] == {"username": REDACTED, "password": REDACTED}
    assert stove_data["UniqueCode"] == REDACTED
    for key in ("sm_sn", "ssid_wifi", "pwd_wifi", "mac_wifi"):
        assert stove_data["Status"][key] == REDACTED
    assert stove_data["State"]["temp_amb_install"] == 20.5
    assert stove_data["Model"]["model_name"] == "Synthetic Air Stove"

    # 4. Making the report must not alter the stove or break JSON export.
    assert asdict(stove.Status) == original_status
    json.dumps(report)
