# Entities and controls

[Documentation home](README.md) | [Configuration](configuration.md) | [Troubleshooting](troubleshooting.md)

The integration provides the controls and readings below. **Not every stove supports every feature.**

## At a glance

| Platform | Purpose | Examples, where supported |
|---|---|---|
| Climate | Everyday heating controls | Power, target temperature, operating presets |
| Fan | Ventilation controls | Fan 1, Fan 2, Fan 3 |
| Select | Choose a supported value | Manual Power, Tones |
| Switch | Enable or disable a function | Start / Stop, Timer |
| Number | Adjust numeric settings | Ignition/shutdown delays, hysteresis, pump threshold |
| Sensor | Read measurements and status | Temperatures, operating mode, maintenance information |
| Binary sensor | Read on/off status | Alarm, Pellet Level Low, cloud connection, device connection |
| Button | Run a one-time command | Alarm Reset, Set System Date & Time |
| Date/time | Set the stove clock | Date & Time; disabled by default |

Entity IDs are assigned by Home Assistant and may differ between installations. Use your actual entity IDs in dashboards and automations; the display names here are not fixed IDs.

## Climate

Use the main climate control to turn the stove on with **Heat** or off with **Off**. Target temperature and presets are available where supported by your stove.

Possible presets include **Manual**, **Auto**, **Overnight**, **Comfort**, and **Turbo**. Your stove determines the available presets and temperature range.

Some older stoves may show extra presets they do not support. Use **Manual** or **Auto** if another preset does not work.

**Heat** means heating is enabled; it does not mean the stove is burning at that instant. The stove may be starting up, shutting down, or on standby.

## Fans and manual power

Up to three fan controls are implemented. Available speeds and presets depend on your stove. On air stoves, fan availability also depends on the current operating mode.

On supported hydro stoves, **Room Fan** controls room ventilation without needing a climate preset. **Auto** and **Silent** are fan settings where supported.

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

Water and puffer (buffer tank) readings are available only on supported stoves. A sensor listed here may not appear for your model.

### Lifetime statistics

Where supported, **Ignition count**, **Total operating time**, and **Operating time at power 1** through **5** show the stove's lifetime totals. Operating times are displayed in whole hours; more precise readings are kept for history. These sensors appear under the stove's diagnostic entities only after the cloud supplies a reading; a missing reading is not treated as zero.

Statistics refresh at startup and hourly, separately from the ten-second live updates. Disabling polling in Home Assistant also stops scheduled statistics updates. A statistics failure does not interrupt heating controls. These sensors become unavailable when the integration detects a cloud connection failure, and show their saved readings again when the connection recovers, provided the last statistics request succeeded. They can remain readable while the stove itself is offline.

**Next Maintenance** follows live stove updates, not the hourly statistics schedule.

### Consumption history

**Yesterday's consumption** shows the Maestro cloud's estimate in kWh. It appears only after the service returns a reading for yesterday, including a genuine zero. It is not available for M1 stoves.

The reading refreshes at startup, at 00:05, and hourly, separately from live stove updates. Hourly updates continue even after a reading is available, so later cloud corrections appear automatically. Zero is a valid reading, but the cloud may revise it later. The sensor uses the stove's timezone from the cloud, or Home Assistant's timezone if none is provided. Its attributes show the consumption date and the last successful retrieval time.

The sensor can remain available while the stove itself is offline. It becomes unavailable when the integration detects a cloud connection failure, if the history request fails, or if yesterday's reading is missing. When the cloud connection recovers, a saved reading for yesterday is shown again if the last history request succeeded. The previous day's displayed value may remain until the 00:05 update. The cloud may take longer to publish the next reading; a missing reading does not mean zero consumption or that the stove is unsupported.

This is the app's estimated energy figure, not a measurement of electricity drawn by the stove. It is not a live meter and does not provide Energy dashboard integration or historical imports.

## Connectivity and alarms

**Cloud Connection Status** and **Device Connection Status** help distinguish the integration-to-cloud connection from the stove-to-cloud connection. See [how to interpret them](configuration.md#connectivity-and-limitations).

The **Alarm** binary sensor indicates an error state. **Last Alarm Code** provides the last reported code. Use the stove's manual or MCZ support to interpret a code; this integration is not a fault-diagnosis or safety system.

**Pellet Level Low** turns on when the stove's pellet level probe reports that the hopper is running low and turns off when it reports enough pellets. It is only created when the stove reports an enabled probe and provides a reading. If the probe is later disabled or its enabled status is unknown, the entity shows no reading rather than a low-pellet warning. The MCZ app's warning may appear later; the two are not guaranteed to update together. A low-pellet reading does not by itself mean the stove has an alarm.

The **Alarm Reset** button sends a remote reset request when the model exposes one; it cannot clear every alarm. Some alarms require physical intervention and a reset on the stove's own panel. The button cannot bypass that restriction.

For example, MCZ manual guidance lists **A01, A02, A03, A05, and A21** as alarms that can only be reset from the stove's panel. The applicable codes may differ for your model. Resolve the cause and follow your stove's manual before attempting a reset or restart.

## Stove clock

**Set System Date & Time** requests synchronization with Home Assistant's system time. **Date & Time** provides a separate editable stove-clock entity, but is **disabled by default**.

After changing the clock, check it in the official app or on the stove, especially if you rely on the stove's timer.

## Why entities differ between stoves

Available features depend on the stove model, installed software, operating mode, and accessories.

This means an entity may not be created, may be disabled by default, or may become unavailable in a particular mode. Those are different situations.

To inspect disabled entities, open **Settings > Devices & services > Entities**, filter by **Maestro MCZ**, and include disabled entities. Enable an entity only if you need it and it applies to your stove.

If a feature works in the official app but is missing here, follow [the reporting guidance](troubleshooting.md#devices-or-entities-are-missing) rather than assuming that another stove's entity list should match yours.

---

**Need help?** [Troubleshoot a missing or unavailable entity](troubleshooting.md)
