# Testing Guide

qbt-rules has a real pytest suite covering every module — this page is a map of what's there and how to run it, not a tutorial on pytest itself.

## Running the tests

```sh
uv run pytest                                            # unit and golden tests, with an 80% coverage floor
uv run pytest tests/unit/test_resolver.py --no-cov       # one file, no coverage floor
uv run pytest tests/unit -k dry_run --no-cov             # a subset by name
uv run pytest -m "not redis"                             # skip the tests that need a live Redis server
RUN_INTEGRATION=1 uv run pytest -m integration --no-cov  # integration tests (real external systems), no coverage floor
sh scripts/checks.sh                                     # everything CI's checks job runs
```

CI runs the tests on every supported Python version, together with ruff, mypy (strict), the wiki checks and the manifest checks. All of them block a merge.

Two custom markers are registered in `pyproject.toml` (`--strict-markers` means an unregistered marker is a hard error, not a silent no-op):

| Marker | Meaning |
|--------|---------|
| `integration` | Talks to real external systems; skipped unless `RUN_INTEGRATION=1`, deselect with `-m "not integration"` |
| `redis` | Requires a live Redis instance (skipped without one); deselect with `-m "not redis"` if you don't have one running |

### Coverage

Coverage is on by default (`--cov` with `term-missing` is baked into `pyproject.toml`'s `addopts`, so plain `uv run pytest` always reports it, and fails under 80%). For a browsable report:

```bash
uv run pytest --cov-report=html
# full HTML report lands in htmlcov/
open htmlcov/index.html
```

## Test layout

| Path | What goes there |
|---|---|
| `tests/unit/` | Fast and offline: no network, no real external systems. One file per module (`test_resolver.py`, `test_web.py`, `test_legacy_cli.py`, ...). Most tests. |
| `tests/unit/test_engine/` | `engine.py`'s surface split by concern (`ConditionEvaluator`, `ActionExecutor`, `RulesEngine`, and per-action files — see [Architecture Internals](Architecture-Internals)) |
| `tests/golden/` | Golden responses for the JSON API: every route in `web.py` driven through the Flask test client against a real queue (SQLite and fakeredis), compared byte for byte with `tests/golden/responses/<backend>/<case>.json`. After an intended change, regenerate with `QBT_RULES_UPDATE_GOLDENS=1 uv run pytest tests/golden` and review the diff |
| `tests/integration/` | Real dependencies, marked `@pytest.mark.integration`; skipped unless `RUN_INTEGRATION=1` |
| `tests/conftest.py` | Shared fixtures: `clean_env` (no `QBT_RULES_*` leakage), `write_config`, and the project's mocks |

## Writing tests

- Every behaviour change needs a test that fails without it. A bug fix starts with the failing test.
- Assert outcomes (outputs, side effects, errors), not internal calls.
- Use placeholders for anything that looks real: `example.org`, `192.0.2.0/24`, fake tokens.
- Don't lower the coverage floor or skip a test to make CI pass.

### Writing Tests for New Code

If you're following [Extending the Engine](Extending-the-Engine) to add an operator or action:

- A new **operator** in `ConditionEvaluator._apply_operator` belongs in `tests/unit/test_engine/` — assert it directly against both scalar and collection field values (collections exercise the ANY/ALL-match branching described in [Conditions](Conditions#collection-field-behavior)).
- A new **action** in `ActionExecutor` belongs in the same directory — assert both the "changes something" path and the idempotent skip path (if applicable) against a mocked `qbittorrent.py` client, the same pattern the built-in actions use. Add it to `schema.py` too, so the rules editor's validator knows it.
- A new **queue backend** under `queue_backends/` should implement the same test contract `test_sqlite_queue.py`/`test_redis_queue.py` already exercise against `queue_manager.py`'s abstract interface, so it's verified to be a drop-in replacement.
- Anything touching the resolver (`refs`/`$ref`/`${vars.x}`) has both a focused unit suite (`test_resolver.py`, `test_resolver_edge_cases.py`) and end-to-end suites (`test_resolver_e2e.py`, `test_resolver_integration.py`) — new resolver behavior should get coverage in both, since edge cases (circular refs, type mismatches) are easy to get right in isolation and wrong once a real rule file is involved.
- A change to an API response changes a golden file: regenerate it (above) and say so in the PR.

Before opening a pull request, run the full suite plus a real config validation pass — see [Contributing](Contributing) for the complete workflow.
