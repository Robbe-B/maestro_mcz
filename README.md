# Maestro MCZ

**Your MCZ stove, at home in Home Assistant.**

<p>
  <img src="docs/app_icon.png" alt="Maestro app icon" width="96" height="96">
  <img src="docs/old_app_icon.png" alt="Earlier Maestro app icon" width="96" height="96">
</p>

Monitor your stove and control its supported settings from Home Assistant using the Maestro cloud service.

[![Latest stable release](https://img.shields.io/github/v/release/Robbe-B/maestro_mcz?label=stable)](https://github.com/Robbe-B/maestro_mcz/releases/latest)
[![HACS custom integration](https://img.shields.io/badge/HACS-custom_integration-41BDF5)](https://www.hacs.xyz/docs/faq/custom_repositories/)

[Get started](docs/installation.md) | [Documentation](docs/README.md) | [Troubleshooting](docs/troubleshooting.md) | [Release notes](https://github.com/Robbe-B/maestro_mcz/releases)

## Get started

[![Open the Maestro MCZ repository in Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Robbe-B&repository=maestro_mcz&category=integration)

**Open the repository with the button above, then confirm the download in Home Assistant.** Depending on your Home Assistant version, the button opens the repository in HACS or Marketplace; it does not install or configure the integration automatically.

You need **Home Assistant 2026.3.0 or newer**, a Maestro account, and a stove already linked to that account and working in the official app.

1. Download **Maestro MCZ (cloud)** and restart Home Assistant.
2. Go to **Settings > Devices & services > Add integration**, search for **Maestro MCZ**, and sign in with your Maestro credentials.

**Button not working?** Use [Marketplace, HACS, or manual installation](docs/installation.md). Home Assistant 2026.11 or newer uses Marketplace instead of the separate HACS integration.

## What you can do

| Control | Monitor |
| --- | --- |
| Turn the stove on or off and set a target temperature | Ambient temperature and operating state |
| Choose supported operating presets | Alarm status and last alarm code |
| Adjust available fans and manual power | Cloud and device connectivity |
| Manage exposed Start / Stop, timer, and configuration settings | Additional temperatures, fan speeds, and maintenance information |

Features are discovered from the stove's cloud model. **Not every stove exposes every entity or setting.** See the [entity reference](docs/entities.md) for details.

> [!IMPORTANT]
> This is a community-maintained custom integration, not an official MCZ integration. The documented connection is cloud-based: both Home Assistant and the stove need access to the Maestro service. It is not an offline or local-only integration.

## Find your way

| Guide | What it covers |
| --- | --- |
| [Installation](docs/installation.md) | Marketplace, HACS, manual installation, updates, and removal |
| [Configuration](docs/configuration.md) | Account setup, polling intervals, and cloud behavior |
| [Entities and controls](docs/entities.md) | Available platforms, model-dependent features, and disabled entities |
| [Troubleshooting](docs/troubleshooting.md) | Connection problems, missing entities, logs, and diagnostics |

The documentation lives alongside the code so it can be reviewed and updated in the same pull requests. Start at the [documentation home](docs/README.md); the wiki is no longer needed to follow these guides.

## Help and contribute

For a problem, start with [troubleshooting](docs/troubleshooting.md), then [open a bug report](https://github.com/Robbe-B/maestro_mcz/issues/new?template=bug_report.md). Include your Home Assistant and integration versions, stove model, and a description of what happens in the official app.

[Suggest a feature](https://github.com/Robbe-B/maestro_mcz/issues/new?template=feature_request.md) or browse the [milestones](https://github.com/Robbe-B/maestro_mcz/milestones). Documentation corrections are welcome too; see [maintaining the documentation](docs/maintaining-docs.md).

Thanks to everyone contributing code, translations, reports, and device information.

[![Buy Me a Coffee](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://buymeacoffee.com/rbprojects)
