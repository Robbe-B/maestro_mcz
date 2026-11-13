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
| Binary sensor | Read on/off status | Alarm, Pellet Level Low, cloud connection, device connection |
| Button | Run a one-time command | Alarm Reset, Set System Date & Time |
| Date/time | Set the stove clock | Date & Time; disabled by default |

Entity IDs are assigned by Home Assistant and may differ between installations. Use your actual entity IDs in dashboards and automations; the display names here are not fixed IDs.

## Climate

The main climate entity supports **Heat** and **Off** when a recognized power configuration is present. Target temperature and presets are added when matching thermostat and mode configurations are available.

Possible presets include **Manual**, **Auto**, **Overnight**, **Comfort**, and **Turbo**. Your stove determines the available subset and temperature range. The integration normalizes some older model names: `dynamic` becomes `auto`, and `power` becomes `turbo`.

Some older stoves may show extra presets they do not support. Use **Manual** or **Auto** if another preset does not work.

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

### Consumption history

**Yesterday's consumption** shows the Maestro cloud's estimate in kWh. It appears only after the service returns a reading for yesterday, including a genuine zero. M1 stoves are not queried because their cloud history only returns zero.

History is requested at startup and local midnight, separately from live stove updates. If yesterday's reading is missing or the request fails, it retries hourly until a reading is available, including zero. Once retrieved, the reading is kept until the next day without further scheduled requests. The sensor uses the stove's cloud-configured timezone, or Home Assistant's timezone if none is provided. Its attributes show the consumption date and the last successful retrieval time.

The sensor can remain available while the stove is offline, provided its cloud history is accessible. It becomes unavailable if the history request fails or yesterday's reading is missing. At midnight, the previous day's value is no longer shown as yesterday; the cloud may take time to publish the next reading. Empty history is not treated as zero or as proof that the stove is unsupported.

This is the app's estimated energy figure, not a measurement of electricity drawn by the stove. It is not a live meter and does not provide Energy dashboard integration or historical imports.

Diagnostic replay uses the saved consumption value without contacting the cloud. Older reports without consumption data do not create a reading.

If several replay files describe the same stove ID and name, the most recently modified file is used. Reports with different stove names keep their own saved readings.

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

The integration matches known feature definitions against cloud-provided model configuration and state. Different generations, firmware, operating modes, and accessories can expose different features.

This means an entity may not be created, may be disabled by default, or may become unavailable in a particular mode. Those are different situations.

The integration distinguishes M1 and M2+ control families using known ping commands in the stove's cloud configuration, not its product name or power controls. M2+ does not identify an exact M2 or M3 generation. Unrecognized ping configurations remain unknown. AIR, HYDRO, and CORE describe product categories, not controller generations.

To inspect disabled entities, open **Settings > Devices & services > Entities**, filter by **Maestro MCZ**, and include disabled entities. Enable an entity only if you need it and it applies to your stove.

If a feature works in the official app but is missing here, follow [the reporting guidance](troubleshooting.md#devices-or-entities-are-missing) rather than assuming that another stove's entity list should match yours.

---

**Need help?** [Troubleshoot a missing or unavailable entity](troubleshooting.md)
