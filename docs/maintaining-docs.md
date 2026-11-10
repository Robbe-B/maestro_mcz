# Contributing to the documentation

[Documentation home](README.md) | [Repository home](../README.md)

These guides help people install and use Maestro MCZ. Contributions that make them clearer or more accurate are welcome.

## Where information belongs

| File | Covers |
|---|---|
| `README.md` | Project introduction, quick start, and support links |
| `docs/README.md` | Guide directory and navigation |
| `docs/installation.md` | Requirements, installation methods, updates, and removal |
| `docs/configuration.md` | Account setup, options, and connection behavior |
| `docs/entities.md` | Controls, sensors, and model-dependent features |
| `docs/troubleshooting.md` | Common problems, recovery steps, logs, and diagnostics |

Update the guide that owns the topic. Keep the README concise and link to detailed instructions instead of duplicating them.

## Keep instructions accurate

When a change affects how people install or use the integration, update the relevant guide in the same contribution. Check instructions and feature descriptions against the current integration and Home Assistant interface. Explain when behavior depends on a stove model or its configuration; do not imply that every stove exposes every feature.

Use the guides to describe supported, user-visible behavior. Avoid documenting development plans or presenting unverified behavior as available.

## Writing and review checklist

- Use plain language and headings that help readers find a task or answer.
- Prefer short paragraphs and clear numbered steps for procedures.
- Keep each instruction in one primary location; link to it elsewhere.
- Use relative links between repository pages and descriptive alt text for images.
- Check that links, heading anchors, and image paths work.
- Review screenshots and examples for credentials or other private information before adding them.
- Preview the Markdown on GitHub and confirm the result is readable.

The documentation is plain Markdown and does not require a separate build step.
