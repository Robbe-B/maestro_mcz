# Configuration

[Documentation home](README.md) | [Installation](installation.md) | [Entities and controls](entities.md)

## Account and devices

Add the integration with the credentials you use for the official Maestro app. It retrieves the stoves linked to that account and creates devices with the features it recognizes.

The account username identifies the integration entry. You do not need a separate entry for each stove on the same account, and adding the same account again is prevented.

If a stove is missing, verify that it appears under the same account in the official app, then reload the integration after making account changes. See [missing devices and entities](troubleshooting.md#devices-or-entities-are-missing).

> [!NOTE]
> The documented setup uses the Maestro cloud. There is no local IP address, MQTT broker, or Bluetooth pairing step in this cloud setup.

## Polling interval

The polling interval controls how often Home Assistant requests updated stove data from the cloud.

1. Go to **Settings > Devices & services**.
2. Find **Maestro MCZ** and open the options for your account entry, usually labeled **Configure** or shown as a settings icon.
3. Change **Polling Interval (seconds)** and save.

Saving options reloads the integration. A brief interruption while it reloads is expected.

| Version | Default | Accepted range |
|---|---|---|
| `1.0.5` stable | 30 seconds | 30-300 seconds |
| `1.0.6` / current `main` | 10 seconds | 10-300 seconds |

Existing saved options can override the default. The options form constrains values to the range supported by that version.

A shorter interval increases cloud requests; it does not make the stove respond instantly. Start with your version's default and increase it if you do not need frequent updates.

## Updates and response time

This integration reads cloud-reported state rather than a direct local feed. A command and its resulting state update are separate events.

After a setting is changed, the current cloud implementation waits about three seconds before refreshing, then waits about three more seconds and refreshes again. Network requests add to that time. A displayed value may therefore lag behind the action, and a normal polling interval is not a guarantee of end-to-end response time.

Allow the state to settle before repeating a command. If the official app also shows stale information, investigate the stove or cloud connection rather than only reducing the polling interval.

## Operating modes and controls

Use the climate entity for power and target temperature, and select a preset only if your stove exposes it. **Auto is a stove preset, not a separate Home Assistant HVAC mode.** The climate entity uses **Heat** and **Off**.

Fan controls can change with the stove's operating mode. A fan that is unavailable in one mode may be available in another; available speeds and presets come from that mode's cloud configuration.

The stove's **Timer** switch enables or disables its existing timer function. It is not a schedule editor. Continue using the official app for schedule creation and for settings that are not exposed in Home Assistant.

## Connectivity and limitations

Both sides of the cloud connection matter:

| Indicator | What it represents |
|---|---|
| **Cloud Connection Status** | Whether the integration considers its connection to the Maestro cloud authenticated and usable |
| **Device Connection Status** | Whether the cloud reports the stove connected |

These are last-reported indicators, not independent live network probes. The device indicator can itself be unavailable when the integration cannot reach the cloud. See [connection troubleshooting](troubleshooting.md#entities-are-unavailable-or-values-stop-updating).

Cloud outages, internet problems, or changes to the Maestro service can interrupt control. Offline operation and complete parity with the official app are not guaranteed.

---

**Next:** [Explore the available entities and controls](entities.md)
