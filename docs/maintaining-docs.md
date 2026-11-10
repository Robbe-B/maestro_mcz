# Maintaining the documentation

[Documentation home](README.md) | [Repository home](../README.md)

This page is for maintainers. Keep user instructions in the repository so the documentation can be reviewed and updated alongside the integration.

## One home for each topic

| File | Responsibility |
|---|---|
| `README.md` | Shared introduction, short setup path, and support links |
| `docs/README.md` | Documentation landing page and navigation |
| `docs/installation.md` | Prerequisites, installation methods, updates, and removal |
| `docs/configuration.md` | Account setup, options, and connection behavior |
| `docs/entities.md` | User-facing feature reference and model limitations |
| `docs/troubleshooting.md` | Symptoms, recovery steps, logs, and diagnostics |

Keep detailed instructions in their guide rather than copying them into the README. The README serves both GitHub and the Home Assistant repository view, so maintain one introduction and make detailed guides available from it.

## Verify documentation against the integration

When behavior changes, check the relevant files in the [integration source](https://github.com/Robbe-B/maestro_mcz/tree/main/custom_components/maestro_mcz). Do not infer user-visible support from a platform filename alone.

| Documentation claim | Source to inspect |
|---|---|
| Minimum Home Assistant version and integration display name | Root `hacs.json` and `manifest.json` |
| Setup steps, options, and accepted values | `config_flow.py` and `strings.json` |
| Polling and refresh behavior | `const.py` and `__init__.py` |
| Feature names, default enablement, and model mappings | `maestro/models/models.py` and the relevant platform |
| Connectivity meanings | `maestro/__init__.py` and `binary_sensor.py` |
| Diagnostic contents and redaction | `diagnostics.py` |

Update this source map if the relevant implementation moves. Describe only behavior that is supported by the integration and clearly explain any model-dependent limitations.

## Retire the wiki without losing its guidance

The old **Home** page's app icons and support link are retained in the documentation and README. The old **Setup** page's installation methods, account-addition steps, and screenshot are covered by the installation guide.

The existing image filenames are deliberately preserved. Moving or deleting them would break images embedded in older wiki pages.

1. Publish the repository documentation and confirm the README and guide links work.
2. Replace the wiki **Home** page with a short notice linking to the new documentation home.
3. Replace the wiki **Setup** page with a short notice linking directly to the installation guide. Keep the existing page names so bookmarks continue to work while the wiki is enabled.
4. Search the repository and wiki for remaining links to the old instructions and update them where appropriate.
5. Keep the notices during the transition. Disable the wiki only if you accept that its old URLs will no longer provide a useful landing page.

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
for installation and account setup.
```

These are migration suggestions, not changes to the wiki itself.

## Keep the reading experience consistent

Use relative links inside the repository, descriptive image text, task-oriented headings, and short tables for settings or symptoms. Use absolute GitHub links in wiki notices because they are read outside the repository file tree.

Before publishing documentation changes, check navigation, heading links, and image paths in GitHub. Confirm names, defaults, and instructions against the integration code and the Home Assistant interface where possible.

These guides are plain Markdown and require no documentation build. If a searchable website becomes worthwhile, publish these same source files through a documentation generator instead of maintaining a second copy.
