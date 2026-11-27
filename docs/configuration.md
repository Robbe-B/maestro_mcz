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

Home Assistant normally requests updated stove data from the cloud every 10 seconds. This interval is the same for every account. There is no polling setting in the integration's options, and intervals saved in older versions no longer apply.

The [lifetime statistics](entities.md#lifetime-statistics) and [consumption history](entities.md#consumption-history) refresh hourly on separate schedules. Consumption history also refreshes at 00:05 in the stove's timezone.

For a different schedule, follow Home Assistant's [custom polling instructions](https://www.home-assistant.io/common-tasks/general/#defining-a-custom-polling-interval). Turning off **Enable polling for changes** in the account's **System options** also stops automatic statistics and consumption requests; include those sensors in your automation if you still want them to refresh.

## Updates and response time

This integration reads updates through the cloud, not directly from the stove.

After changing a setting, allow several seconds for the displayed value to update. Slow internet or cloud responses can add to the delay. More frequent updates do not guarantee a faster response to commands.

Commands are sent immediately. Changes made close together share the same follow-up updates, while displayed values remain based on what the cloud reports.

Allow the state to settle before repeating a command. If the official app also shows stale information, check the stove or cloud connection.

## Operating modes and controls

Use the climate control for power and target temperature, and select a preset only if it is available for your stove. **Auto is a stove preset**; the main heating choices are **Heat** and **Off**.

Fan controls can change with the stove's operating mode. A fan that is unavailable in one mode may be available in another, with different speeds or presets.

The stove's **Timer** switch enables or disables its existing timer function. It is not a schedule editor. Continue using the official app for schedule creation and for settings that are not exposed in Home Assistant.

## Connectivity and limitations

Both sides of the cloud connection matter:

| Indicator | What it represents |
|---|---|
| **Cloud connection status** | Whether the integration considers its connection to the Maestro cloud authenticated and usable |
| **Device connection status** | Whether the cloud reports the stove connected |

These indicators show the last reported connection status, which may be out of date. The device indicator can itself be unavailable when the integration cannot reach the cloud. See [connection troubleshooting](troubleshooting.md#entities-are-unavailable-or-values-stop-updating).

Cloud outages, internet problems, or changes to the Maestro service can interrupt control. This setup cannot control the stove without the cloud, and not every official app feature is available.

---

**Next:** [Explore the available entities and controls](entities.md)
