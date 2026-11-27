# Documentation

Keep the README user-facing and edit it only when the user explicitly requests
a README update. Do not update it automatically for implementation, setup,
usage, or user-visible behavior changes.

The README and user guides are for nontechnical users. Assume no programming
or knowledge of the integration's internals. Keep explanations short, practical,
and in plain language: what to do, what to expect, and any relevant limitations.
Describe the controls users see, not how the code chooses commands. Avoid
internal identifiers, protocol details, and implementation history.

Keep the installation shortcut and shortest setup path prominent in the README.
Make detailed guides available when needed rather than required reading before
installation. Include technical details only when they help the reader complete
a task or understand a limitation; explain unfamiliar terms when needed.

Keep documentation readable as plain Markdown as well as when rendered. Prefer
short paragraphs and use headings, lists, and tables where they genuinely help.
Avoid duplicated instructions, exhaustive internal details, and unnecessary
sections. Update the relevant guide instead of appending technical notes to
user-facing pages.

Preserve valuable technical background in issue artifacts, not the README or
user guides. Keep agent instructions in this file rather than technical analyses.

# Publishing a release

1. Merge the changes to release, including `.github/workflows/release.yml`, before
   creating the release tag. Use `1.7.0` format without a prefix; pre-release suffixes
   such as `b1` and `rc1` are also supported.
2. Publish a GitHub release for that tag. Publishing a tag alone or saving a
   draft release does not build the download.
3. Wait for **Package release** in GitHub Actions to finish and confirm that
   **maestro_mcz.zip** appears in the release assets. If packaging or upload
   fails, correct the cause and rerun the workflow.

The workflow checks out the released tag and sets `manifest.json` to the tag's
version only in the packaging workspace. Do not make a
manual manifest version-bump commit for a release. The archive contains the
integration files at its root, ready for HACS and Marketplace. Rerunning the
workflow replaces the release's existing archive.

Direct branch downloads and GitHub's source archives retain the repository's
manifest version. Older releases without the ZIP asset are not repackaged
automatically; enabling ZIP downloads does not add assets to existing releases.

# Home Assistant quality

Aim for Platinum-quality Home Assistant changes. Consult the current
[Integration Quality Scale](https://contributors.home-assistant.io/core/quality-scale/)
when implementing or reviewing changes. Do not claim a tier unless the whole
integration meets its requirements.

# Python linting

Keep Python linting and formatting in mind while writing code. Use existing
tooling and configuration, and run available checks on changed Python files
before finishing. Fix issues introduced by the change without weakening rules,
adding blanket suppressions, or reformatting unrelated code.

# Python typing

Maintain strict typing across all production modules, including the bundled
Maestro client. After relevant Python changes, run
`python -m mypy --config-file tests/pyproject.toml` from the repository root.
Keep this check enforced in CI. Fix typing errors rather than weakening checks,
excluding modules, or adding blanket suppressions.

# Imports

Keep module dependencies acyclic. Import coordinators and their shared types
from `coordinator.py`, not the integration's `__init__.py`. Keep shared constants
in `const.py` so coordinators and platforms do not depend on setup or config-flow
modules.

# Model architecture

Within `custom_components\maestro_mcz\maestro`:

- `models\models_types.py` declares configuration dataclasses, schema fields,
  enums, and genuinely generic defaults.
- `models\model_definitions.py` holds the supported and legacy feature catalogue,
  concrete API field/control bindings, and feature-specific configuration.
- `model_value_reader.py` reads the declared field from the selected cached
  State/Status response; it does not fetch HTTP responses.

# Live communication

`maestro\cloud_provider.py` owns per-stove cloud ping sequences, live requests,
cached State/Status replies, connection tracking, and command dispatch.
`MaestroStove` retains identity, model loading/matching, entity-facing behavior,
and device metadata interpretation. Account discovery and statistics remain
separate from the live provider. Do not put entity selection or model storage
inside a transport provider.

# Entity naming

- Use Home Assistant translations for default entity names, not hardcoded overrides.
- Use sentence case, preserving acronyms and proper names.
- Keep catalogue names and `strings.json` aligned. When user-facing text or
  translation keys are added, removed, or changed, update `strings.json` and all
  shipped locale files in the same change, preserving matching keys and
  placeholders.
- Preserve internal keys, existing entity IDs/unique IDs, customized names, and
  automation-facing state and option values when changing display names.

# Test readability

Write and maintain tests as clear scenarios that a nontechnical reader can
follow. Each test's docstring must explain its goal and why the behavior matters
in plain English.

Use short, numbered comments to describe the starting situation, the action,
and the expected outcome. Explain the story, not every line of Python.

Prefer descriptive names, named intermediate results, and separate assertions
over compact expressions, chained assertions, and deeply nested mock access.
Keep shared fixtures and helpers understandable, explaining non-obvious setup.

Preserve meaningful assertions, test cases, and coverage when improving
readability. Apply this style to both new tests and changes to existing tests.
