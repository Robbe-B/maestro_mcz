# Documentation

Keep the README user-facing and edit it only when the user explicitly requests
a README update. Do not update it automatically for implementation, setup,
usage, or user-visible behavior changes.

Preserve valuable technical background in separate developer documentation or
issue artifacts, not the README. Keep agent instructions in this file rather
than technical analyses.

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
