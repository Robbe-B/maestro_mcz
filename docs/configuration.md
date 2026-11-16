# Configuration

[Documentation home](README.md) | [Installation](installation.md) | [Entities and controls](entities.md)

## Account and devices

Add the integration with the credentials you use for the official Maestro app. It retrieves the stoves linked to that account and creates devices with the features it recognizes.

You only need to add your account once, even if it has several stoves. You cannot add the same account twice.

If a stove is missing, verify that it appears under the same account in the official app, then reload the integration after making account changes. See [missing devices and entities](troubleshooting.md#devices-or-entities-are-missing).

> [!NOTE]
> This setup requires the Maestro cloud and an internet connection. You do not need the stove's local network address or Bluetooth pairing.

### Remove an unlinked stove

First unlink the stove from your account in the official app. In Home Assistant, go to **Settings > Devices & services > Devices**, open the stove, and choose **Delete** from its menu.

The integration checks the account's current stove list before allowing removal. A linked stove cannot be removed this way, even when it is offline; the error asks you to unlink it in the official app first. If the account needs you to sign in again or its stove list cannot be checked, the error explains that instead and the device stays in Home Assistant.

Removal is manual, not automatic. After removal, the integration reloads that account, briefly interrupting its other stove entities. For accounts replaying saved diagnostic reports, change the saved files and reload the account before removing an old device.

## Polling interval

The polling interval controls how often Home Assistant requests updated stove data from the cloud.

1. Go to **Settings > Devices & services**.
2. Find **Maestro MCZ** and open the options for your account entry, usually labeled **Configure** or shown as a settings icon.
3. Change **Polling Interval (seconds)** and save.

Saving options reloads the integration. A brief interruption while it reloads is expected.

| Version | Default | Accepted range |
|---|---|---|
| `1.0.5` (older release) | 30 seconds | 30-300 seconds |
| Current version | 10 seconds | 10-300 seconds |

Existing saved options can override the default. The options form constrains values to the range supported by that version.

A shorter interval increases cloud requests; it does not make the stove respond instantly. Start with your version's default and increase it if you do not need frequent updates.

The [lifetime statistics](entities.md#lifetime-statistics) and [consumption history](entities.md#consumption-history) have separate update schedules. Changing the live polling interval does not affect them.

## Updates and response time

This integration reads updates through the cloud, not directly from the stove.

After changing a setting, allow several seconds for the displayed value to update. Slow internet or cloud responses can add to the delay. A shorter polling interval does not guarantee a faster response to commands.

Allow the state to settle before repeating a command. If the official app also shows stale information, investigate the stove or cloud connection rather than only reducing the polling interval.

## Operating modes and controls

Use the climate control for power and target temperature, and select a preset only if it is available for your stove. **Auto is a stove preset**; the main heating choices are **Heat** and **Off**.

Fan controls can change with the stove's operating mode. A fan that is unavailable in one mode may be available in another, with different speeds or presets.

The stove's **Timer** switch enables or disables its existing timer function. It is not a schedule editor. Continue using the official app for schedule creation and for settings that are not exposed in Home Assistant.

## Connectivity and limitations

Both sides of the cloud connection matter:

| Indicator | What it represents |
|---|---|
| **Cloud Connection Status** | Whether the integration considers its connection to the Maestro cloud authenticated and usable |
| **Device Connection Status** | Whether the cloud reports the stove connected |

These indicators show the last reported connection status, which may be out of date. The device indicator can itself be unavailable when the integration cannot reach the cloud. See [connection troubleshooting](troubleshooting.md#entities-are-unavailable-or-values-stop-updating).

Cloud outages, internet problems, or changes to the Maestro service can interrupt control. This setup cannot control the stove without the cloud, and not every official app feature is available.

---

**Next:** [Explore the available entities and controls](entities.md)
