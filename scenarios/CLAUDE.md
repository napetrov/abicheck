# CLAUDE.md — `scenarios/`

The **user-scenario / flow catalog**: how real people use libraries, binaries,
and abicheck, used to drive **end-to-end validation** that abicheck works as a
scanner tool. Read `README.md` here first.

This is a separate entity from `examples/` (change-type fixtures) and
`docs/development/plans/` (capability backlog). A scenario = persona + real
situation + the abicheck commands + expected outcome.

## Layout

- `scenarios.yaml` — the machine-readable catalog (source of truth).
- `README.md` — concept, index, and how to add a scenario.

## Ground rules

- `scenarios.yaml` is validated by `tests/test_scenarios.py`. Every
  `automated: true` scenario must have a `test:` that invokes the abicheck CLI
  end-to-end and asserts the `expected` outcome; every scenario's `validates:`
  must be a real id in `docs/development/usecase-registry.yaml`.
- Prefer JSON-snapshot fixtures so automated scenarios run in the fast,
  pure-Python suite (no castxml/gcc). Use `@pytest.mark.integration` only when a
  flow genuinely needs real binaries/toolchains; otherwise mark it
  `automated: false` / `status: planned`.

## What NOT to do

- Don't turn this into change-type fixtures — that's `examples/`.
- Don't add an `automated: true` scenario without a passing end-to-end test.
- When a real-world usage gap is found (e.g. a GitHub issue like #235), add the
  scenario here so it becomes a permanent regression guard.
