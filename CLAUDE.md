# Claude workflow for this repo

## Red-Green TDD is mandatory for code changes

For every commit that touches production code (`main.py`, anything under
`templates/` that has logic, future modules, etc.), follow strict
Red-Green-Refactor:

1. **Red** — write a failing test first.
   - Run the test and show the failing output in the conversation
     before writing any implementation.
   - The failure must be for the right reason (assertion mismatch,
     not `ImportError` or `SyntaxError` on unrelated code).
2. **Green** — write the minimum implementation to make the test pass.
   - Run the test again and show it passing.
   - Do not add unrelated changes in the same step.
3. **Refactor** — only after green. Keep the tests green throughout.

Commit order:
- Prefer a single commit that contains both the new test and the
  implementation, so the tree is always green on `main`.
- If a change is large, a `test:` commit immediately followed by a
  `feat:`/`fix:` commit is also acceptable, but never push an
  implementation commit without its test.

### What does *not* require TDD

- Docs-only changes (`README.md`, `CLAUDE.md`, comments).
- Pure dependency bumps with no code edits.
- Template/CSS tweaks that are visual-only and have no branching logic.
- Build/config files (`.gitignore`, service definitions).

When in doubt, write the test.

## Test tooling

This repo does not yet have a test suite. The first TDD task must
bootstrap it:

```bash
.venv/bin/pip install pytest httpx
mkdir -p tests
touch tests/__init__.py tests/conftest.py
```

- Framework: `pytest`.
- HTTP: `httpx.AsyncClient` against the FastAPI `app` for endpoint tests
  (no live server needed).
- Isolate filesystem state with `tmp_path` and monkeypatch `BASE`,
  `PODCASTS`, `PENDING`, and `UPLOAD_TOKEN_FILE` so tests never touch
  real episode data.
- Run with `.venv/bin/pytest -q`.

## Branch discipline

All development on this project happens on the feature branch assigned
for the session. Never push to `main` directly.
