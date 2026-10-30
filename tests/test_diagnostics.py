"""Diagnostics stay useful without leaking configured account credentials."""

from dataclasses import asdict
import json

from homeassistant.components.diagnostics import REDACTED

from custom_components.maestro_mcz.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redaction_and_round_trip(hass, entry, coordinator, stove):
    stove.Status.sm_sn = "synthetic-serial"
    stove.Status.ssid_wifi = "synthetic-network"
    stove.Status.pwd_wifi = "synthetic-wifi-password"
    stove.Status.mac_wifi = "AA:BB:CC:DD:EE:FF"
    original = asdict(stove.Status)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["config_entry_data"] == {"username": REDACTED, "password": REDACTED}
    data = result["devices"]["Living Room"]["coordinator.stove_data"]
    assert data["UniqueCode"] == REDACTED
    for key in ("sm_sn", "ssid_wifi", "pwd_wifi", "mac_wifi"):
        assert data["Status"][key] == REDACTED
    assert data["State"]["temp_amb_install"] == 20.5
    assert data["Model"]["model_name"] == "Synthetic Air Stove"
    assert asdict(stove.Status) == original
    json.dumps(result)
