# Documentation

Keep the README user-facing and edit it only when the user explicitly requests
a README update. Do not update it automatically for implementation, setup,
usage, or user-visible behavior changes.

Preserve the current plain-language, uncluttered balance in the README and
user guides. Write for someone installing or using the integration, not someone
reading its source code. Explain what to do, what to expect, and relevant
limitations without requiring implementation knowledge.

Keep the installation shortcut and shortest setup path prominent in the README.
Make detailed guides available when needed rather than required reading before
installation. Include technical details only when they help the reader complete
a task or understand a limitation; explain unfamiliar terms when needed.

Keep documentation readable as plain Markdown as well as when rendered. Prefer
short paragraphs and use headings, lists, and tables where they genuinely help.
Avoid duplicated instructions, exhaustive internal details, and unnecessary
sections. Update the relevant guide instead of appending technical notes to
user-facing pages.

Preserve valuable technical background in separate developer documentation or
issue artifacts, not the README or user guides. Keep agent instructions in this
file rather than technical analyses.

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
