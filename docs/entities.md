# Entities and controls

[Documentation home](README.md) | [Configuration](configuration.md) | [Troubleshooting](troubleshooting.md)

The integration supports nine Home Assistant entity platforms. The tables below describe implemented features, **not a guaranteed list for every stove**.

## At a glance

| Platform | Purpose | Examples, where supported |
|---|---|---|
| Climate | Everyday heating controls | Power, target temperature, operating presets |
| Fan | Ventilation controls | Fan 1, Fan 2, Fan 3 |
| Select | Choose a supported value | Manual Power, Tones |
| Switch | Enable or disable a function | Start / Stop, Timer |
| Number | Adjust numeric settings | Ignition/shutdown delays, hysteresis, pump threshold |
| Sensor | Read measurements and status | Temperatures, operating mode, maintenance information |
| Binary sensor | Read on/off status | Alarm, cloud connection, device connection |
| Button | Run a one-time command | Alarm Reset, Set System Date & Time |
| Date/time | Set the stove clock | Date & Time; disabled by default |

Entity IDs are assigned by Home Assistant and may differ between installations. Use your actual entity IDs in dashboards and automations; the display names here are not fixed IDs.

## Climate

The main climate entity supports **Heat** and **Off** when a recognized power configuration is present. Target temperature and presets are added when matching thermostat and mode configurations are available.

Possible presets include **Manual**, **Auto**, **Overnight**, **Comfort**, and **Turbo**. Your stove determines the available subset and temperature range. The integration normalizes some older model names: `dynamic` becomes `auto`, and `power` becomes `turbo`.

**Heat** expresses the selected HVAC mode; it does not mean the stove is burning at that instant. Startup, shutdown, standby, and other phases can affect the reported heating action.

## Fans and manual power

Up to three fan controls are implemented. Their speeds, presets, and availability depend on the stove's current operating mode and enabled model configuration.

The **Manual Power** select is a separate control for the stove's manual power setting. It is not the same as a fan speed percentage, and its values are model-dependent.

## Switches and configuration settings

| Entity or group | Purpose |
|---|---|
| **Start / Stop** | Enable or disable the stove's eco Start / Stop function; this is not the main power control |
| **Timer** | Enable or disable the stove's timer function, not edit its schedule |
| **Start / Stop - Delay in Ignition / Shutdown** | Adjust the exposed delays, in seconds |
| **Start / Stop - Negative / Positive Hysteresis** | Adjust the exposed Start / Stop temperature thresholds |
| **Ambient - Negative / Positive Hysteresis** | Adjust exposed ambient-temperature hysteresis |
| **Circulation Pump - On - Minimum Temperature** | Adjust the exposed pump-on temperature threshold on applicable hydro models |
| **Tones** | Choose a supported sound level |

Numeric ranges and steps are read from the cloud model. Consult your stove's manual before changing advanced settings; this documentation does not prescribe tuning values.

## Measurements and status

| Group | Implemented sensor names |
|---|---|
| Room and heating temperatures | Ambient Temperature, Water Temperature, Puffer Temperature, Wi-Fi Probe Temperature |
| Internal temperatures | Exhaust Temperature, Board Temperature |
| Operating information | Current State, Current Mode, Last Alarm Code |
| Mechanical information | Exhaust Fan Speed, Transport Screw Speed |
| Maintenance | Next Maintenance |

Water and puffer readings are relevant only where the stove exposes them. Sensor creation depends on the returned data; the existence of an internal field or a sensor name in the code does not establish that your stove provides a meaningful reading.

## Connectivity and alarms

**Cloud Connection Status** and **Device Connection Status** help distinguish the integration-to-cloud connection from the stove-to-cloud connection. See [how to interpret them](configuration.md#connectivity-and-limitations).

The **Alarm** binary sensor indicates an error state. **Last Alarm Code** provides the last reported code. Use the stove's manual or MCZ support to interpret a code; this integration is not a fault-diagnosis or safety system.

The **Alarm Reset** button sends a reset command when the model exposes one. Resolve the cause and follow the manufacturer's instructions before resetting an alarm.

## Stove clock

**Set System Date & Time** requests synchronization with Home Assistant's system time. **Date & Time** provides a separate editable stove-clock entity, but is **disabled by default**.

After changing the clock, check it in the official app or on the stove, especially if you rely on the stove's timer.

## Why entities differ between stoves

The integration matches known feature definitions against cloud-provided model configuration and state. Different generations, firmware, operating modes, and accessories can expose different features.

This means an entity may not be created, may be disabled by default, or may become unavailable in a particular mode. Those are different situations.

To inspect disabled entities, open **Settings > Devices & services > Entities**, filter by **Maestro MCZ**, and include disabled entities. Enable an entity only if you need it and it applies to your stove.

If a feature works in the official app but is missing here, follow [the reporting guidance](troubleshooting.md#devices-or-entities-are-missing) rather than assuming that another stove's entity list should match yours.

---

**Need help?** [Troubleshoot a missing or unavailable entity](troubleshooting.md)
