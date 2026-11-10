# Maintaining the documentation

[Documentation home](README.md) | [Repository home](../README.md)

This page is for maintainers. User instructions live in the repository so code and documentation can change together in a pull request.

## One home for each topic

| File | Responsibility |
|---|---|
| `README.md` | Shared introduction for GitHub and the Home Assistant repository view, short setup path, support links |
| `docs/README.md` | Documentation landing page and navigation |
| `docs/installation.md` | Prerequisites, installation, updates, removal |
| `docs/configuration.md` | Account setup, options, connection behavior |
| `docs/entities.md` | User-facing feature reference and model limitations |
| `docs/troubleshooting.md` | Symptoms, recovery steps, logs, diagnostics |

Keep detailed instructions in their guide rather than copying them into the README. The README serves both GitHub and the Home Assistant repository view; do not maintain a separate introduction. A short prerequisite summary belongs in the README, while detailed steps should have one source of truth.

## What to verify when behavior changes

Check these files in the [integration source](https://github.com/Robbe-B/maestro_mcz/tree/main/custom_components/maestro_mcz), rather than inferring support from a platform filename:

| Documentation claim | Source to inspect |
|---|---|
| Minimum Home Assistant version and HACS display name | Root `hacs.json` |
| Integration name and connection classification | `manifest.json` |
| Setup steps, options, ranges, duplicate-account behavior | `config_flow.py` and `strings.json` |
| Polling defaults and refresh behavior | `const.py` and `__init__.py` |
| Feature names, default enablement, model mappings | `maestro/models/models.py` and the relevant platform |
| Connectivity semantics | `maestro/__init__.py` and `binary_sensor.py` |
| Diagnostic content and attempted redaction | `diagnostics.py` |

Treat these paths as the current cloud architecture, not a permanent constraint on future refactors. When implementation moves, update this map.

This local documentation proposal was based on GitHub `main` at commit `a3325b7`, inspected on **10 November 2026**, plus the existing wiki's **Home** and **Setup** pages. The supplied local integration is a different development snapshot with Bluetooth work. No integration code was changed as part of this proposal.

At that review, `1.0.5` was the stable release and `1.0.6` was a pre-release. Their polling defaults differ. Recheck release metadata before publishing, and preserve version notes while users need them. Do not advertise development features as stable capabilities without verifying the released setup path.

Installation navigation was also checked against the official [HACS transition guide](https://www.hacs.xyz/docs/marketplace/) and [Home Assistant Marketplace guide](https://www.home-assistant.io/integrations/marketplace/). Keep the older HACS instructions while supporting Home Assistant versions before 2026.11.

## Retire the wiki without losing its guidance

The old **Home** page's app icons and support link are retained in the documentation and README. The old **Setup** page's HACS method, manual method, account-addition steps, and screenshot are covered by the installation guide, with updated navigation.

The existing image filenames are deliberately preserved. Moving or deleting them would break images embedded in older wiki pages.

1. Merge and publish the repository documentation first. Confirm that the README and HACS links open the new guides.
2. Replace the wiki **Home** page with a short notice linking to the new documentation home.
3. Replace the wiki **Setup** page with a short notice linking directly to the installation guide. Keep the existing page names so bookmarks still work while the wiki is enabled.
4. Search repository documentation, integration metadata, issue templates, and release guidance for remaining wiki links and update them where appropriate.
5. Keep the notices during the transition. Disable the wiki in repository settings only when you accept that old wiki URLs will no longer provide a useful landing page.

Suggested text for the wiki **Home** page:

```markdown
# Documentation has moved

The maintained Maestro MCZ guides now live with the source code:

[Open the documentation](https://github.com/Robbe-B/maestro_mcz/blob/main/docs/README.md).

For setup, go directly to the
[installation guide](https://github.com/Robbe-B/maestro_mcz/blob/main/docs/installation.md).
```

Suggested text for the wiki **Setup** page:

```markdown
# Installation instructions have moved

Use the maintained
[installation guide](https://github.com/Robbe-B/maestro_mcz/blob/main/docs/installation.md)
for HACS, manual installation, and account setup.
```

These are migration suggestions, not changes to the published wiki.

## Keep the reading experience consistent

Use relative links inside the repository, descriptive image text, task-oriented headings, and short tables for settings or symptoms. Use absolute GitHub links in wiki transition notices because they are read outside the repository file tree.

Before publishing, open the README and guides in GitHub and check the navigation, heading links, images, and HACS shortcut. Confirm entity names and defaults against the version being documented. Do not add a claimed compatibility list, screenshot, or troubleshooting fix without evidence.

These guides are plain Markdown and require no documentation build. If a searchable website becomes worthwhile, publish these same source files through a documentation generator instead of maintaining a second copy.
