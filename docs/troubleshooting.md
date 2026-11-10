# Troubleshooting

[Documentation home](README.md) | [Installation](installation.md) | [Entities and controls](entities.md)

Start by checking the official Maestro app. Comparing the same stove and account there helps separate a Home Assistant problem from a stove or cloud-service problem.

## Find your symptom

| Symptom | Start here |
|---|---|
| Maestro MCZ is not listed when adding an integration | [Integration does not appear](#integration-does-not-appear) |
| Login fails or no stoves are found | [Setup or sign-in fails](#setup-or-sign-in-fails) |
| Controls are unavailable or readings are stale | [Connection and update problems](#entities-are-unavailable-or-values-stop-updating) |
| A control is missing | [Missing devices or entities](#devices-or-entities-are-missing) |
| A command appears not to work immediately | [Delayed commands](#a-command-is-delayed-or-a-value-changes-back) |
| You need to report a bug | [Collect evidence](#collect-logs-and-diagnostics) |

## Integration does not appear

Confirm that you restarted Home Assistant after downloading the files. A browser refresh alone is not enough.

For a manual installation, verify that `manifest.json` is directly inside `<configuration directory>/custom_components/maestro_mcz`, not in an additional nested folder. Copy the complete integration, not just its Python files.

Check that your Home Assistant version meets the release's minimum requirement, then inspect **Settings > System > Logs** for `maestro_mcz` errors. Do not mix files from different releases.

## Setup or sign-in fails

| What you see | What to check |
|---|---|
| Invalid authentication | Sign in to the official app with the same Maestro credentials; do not use Home Assistant or Wi-Fi credentials |
| Cannot connect | Check Home Assistant's internet access and whether the official app can reach the service |
| No stoves found | Confirm the stove is linked to that exact account and visible in the official app |
| Already configured | Open the existing account entry instead of adding it again |
| Unexpected error | Record the integration version, reproduce once, and collect the relevant logs |

If credentials recently changed, first check whether Home Assistant offers a repair or reconfiguration flow for your installed version. If it does not, collect logs before removing the entry. Removing and re-adding should be a last resort because dashboards and automations may need attention afterward.

## Entities are unavailable or values stop updating

Check **Cloud Connection Status** and **Device Connection Status**, then compare with the official app.

| Observation | Interpretation and next step |
|---|---|
| Cloud connection is off | Investigate Home Assistant's cloud access, authentication, and integration logs |
| Cloud is connected; device connection is off | Check the stove's network/cloud connection and its status in the official app |
| Device connection is unavailable | The integration may be unable to reach the cloud; do not infer stove connectivity from this alone |
| Both indicators are on, but values look old | They reflect the last reported state; compare values in the app, wait for a refresh, and collect logs if it persists |
| Only a fan is unavailable | Check whether the current operating mode exposes that fan's controls |

After correcting a connection problem, try reloading the account entry from **Settings > Devices & services**. Reinstalling files is usually not the first step for a cloud outage.

## Devices or entities are missing

Confirm that the device is linked to the account used in Home Assistant. Reload the integration if you added a stove to the account after setup.

For an individual entity, check whether it is disabled in the entity registry and whether the feature applies to your model and operating mode. **Date & Time** is intentionally disabled by default.

The integration does not expose every app feature. In particular, the **Timer** switch does not provide schedule editing. See the [entity reference](entities.md) before treating a missing control as a regression.

If you report an unsupported feature, include the stove model, the app screen showing the feature, and reviewed diagnostics. Do not include credentials, serial numbers, or network details in screenshots.

## A command is delayed or a value changes back

Commands travel through the Maestro cloud and updated values arrive separately. Allow several seconds for the post-command refreshes, and longer if the cloud or stove is slow.

Compare the result in the official app before repeatedly sending the same command. A lower polling interval cannot eliminate cloud delay. See [updates and response time](configuration.md#updates-and-response-time).

If the problem is reproducible, record the exact control, operating mode, expected result, and what both Home Assistant and the app show.

## Collect logs and diagnostics

1. Open **Settings > Devices & services** and find **Maestro MCZ**.
2. Use the integration's menu to **Enable debug logging**, if available.
3. Reproduce the problem once.
4. **Disable debug logging** to finish the capture and download the log.
5. Use the account entry or device menu to **Download diagnostics**, preferably while the problem is present.

Menu placement can differ by Home Assistant version. The [Home Assistant troubleshooting guide](https://www.home-assistant.io/docs/configuration/troubleshooting/#debug-logs-and-diagnostics) explains the standard workflow.

> [!WARNING]
> Review every file and screenshot before sharing it. Diagnostics attempt to redact selected credentials and identifiers, but logs and other fields can still reveal private information. Remove usernames, passwords, tokens, stove identifiers, serial numbers, MAC addresses, Wi-Fi details, and identifying device names. Never assume a diagnostic download is fully anonymous.

If diagnostics cannot be downloaded, include the error and the relevant reviewed log excerpt rather than delaying the report.

## Report a problem

Search [existing issues](https://github.com/Robbe-B/maestro_mcz/issues) first, then use the [bug report template](https://github.com/Robbe-B/maestro_mcz/issues/new?template=bug_report.md).

Include your **Home Assistant version**, **integration version**, **installation method**, **stove model**, and the steps to reproduce. Describe expected and actual behavior, whether the same action works in the official app, and the two connection indicators at the time.

Attach reviewed logs, diagnostics, and screenshots where helpful. For a new capability rather than a broken one, use the [feature request template](https://github.com/Robbe-B/maestro_mcz/issues/new?template=feature_request.md).

---

**Back to:** [Documentation home](README.md)
