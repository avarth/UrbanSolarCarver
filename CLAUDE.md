# Project instructions

## Running the tests

Use the test tiers in `docs/testing.md`, not the whole suite after every change. A serial full run takes about 6
minutes; the tiers below take seconds to under 2 minutes.

| Step | Python | Front end (only when `app/` changed) |
|---|---|---|
| While editing | `python -m pytest tests/<file you changed>.py -m "not slow"` (or `-k <name>`) | `npx vitest run <test file>` |
| After a change | `python -m pytest -m "not slow" -n 8` (about 45 s) | `npm test && npm run typecheck` |
| Before a commit | `python -m pytest -m "not sweep" -n 8` (about 65 s) | `npm test && npm run build`, before the pytest run |
| Before a merge | `python -m pytest -n 8` (about 100 s), once | as before a commit |

- Run each tier once per step. Do not repeat the full run when nothing changed since the last passing one.
- Run the whole suite without `-n` only before a release, or to find a test that depends on another.
- One heavy run at a time: two sessions running `-n 8` at once on this machine slow each other down. When
  delegating, tell the helper which tier to run.
- In a git worktree without its own environment, put its sources first: `PYTHONPATH=src
  "D:/RESEARCH_CENTER/ACTIVE_PROJECTS/RSBenvelope_generation/urbanSolarCarver/.venv/Scripts/python.exe" -m pytest ...`.
- After `npm run build`, `tests/test_local_web_packaging.py` checks that `src/urbansolarcarver/ui_static` matches the
  sources; it is part of the commit tier.
- A new test that takes more than about 1 s goes under `@pytest.mark.slow`; an exhaustive sweep also under
  `@pytest.mark.sweep`.
