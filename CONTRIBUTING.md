# Contributing

Thank you for your interest in Urban Solar Carver.

## Bug Reports

Open an [issue](https://github.com/avarth/UrbanSolarCarver/issues) with:
- A description of the problem
- Your OS, Python version, GPU model, and CUDA version
- The YAML config file (or relevant parameters)
- The full error traceback

## Feature Requests

Open an issue describing the use case and expected behavior. For new carving modes, include references to the underlying physics or standards.

## Pull Requests

1. Fork the repository and create a branch from `main`.
2. Install in development mode: `pip install -e .[dev]`
3. Make your changes and add tests if applicable.
4. Run the tests as [docs/testing.md](docs/testing.md) describes: `pytest -m "not slow" -n 8` after each change (about 45 s on 8 cores), `pytest -m "not sweep" -n 8` before each commit (about 1.5 minutes) and `pytest -n 8` before opening the PR (about 2 minutes). Tests marked `gpu` are skipped automatically without CUDA. There is no CI: the engine runs on the GPU, which hosted runners do not have, so the tests run locally.
5. If you changed anything under `grasshopper/components/`, rebuild the `.ghuser` files (`pip install -e .[ghbuild]`, then `python grasshopper/build_ghuser.py`) and commit them with the source change. See [docs/grasshopper.md](docs/grasshopper.md#rebuilding-the-components).
6. Open a PR with a clear description of the changes.

## Checking a fresh install

A long-lived virtual environment hides installation problems (a missing
dependency, an outdated editable install). From time to time, and before a
release, install into a new folder and run the tests there:

```bash
python install/setup_env.py --venv-dir ../usc-fresh-install
../usc-fresh-install/Scripts/python.exe -m pytest tests/    # bin/python on Linux and macOS
```

Then delete the folder. Fix what fails in `pyproject.toml` or `install/setup_env.py`.

`install/setup_env.py` installs the exact versions in `install/requirements-lock.txt`, which the tests last passed on. Before a release, also try
what is new: repeat the check with `--latest`, run the whole suite including the GPU tests, and compare the results of a few
example projects with the locked versions, because a new torch can move numbers without failing a test. If that holds, run
`tools/write_lockfile.py` from that environment and commit the file. An upgrade of torch or Warp counts as an engine change.

## Making a release

Releases are made at milestones, not after every merge. Each GitHub release becomes a citable version on Zenodo.

1. Set the version in `pyproject.toml` and `CITATION.cff` (with `date-released`), and turn `[Unreleased]` in `CHANGELOG.md`
   into the new version with a short **Highlights** list. Reinstall the package (`pip install -e . --no-deps`) so the version
   test sees it, run the whole suite, merge and push.
2. Tag and publish: `git tag -a v0.13.0 -m v0.13.0`, `git push origin v0.13.0`, then `gh release create v0.13.0 --notes-file ...`.
3. Build the app downloads from the tag and add them to the release, under the same names every time (the installation guide
   links to `releases/latest/download/UrbanSolarCarver-windows.zip` and `.../UrbanSolarCarver-linux.tar.gz`):

   ```
   .venv/Scripts/python.exe tools/build_app_zip.py
   gh release upload v0.13.0 build/UrbanSolarCarver-windows.zip build/UrbanSolarCarver-linux.tar.gz
   ```

   After a package upgrade, `tools/write_lockfile.py --hashes` also rewrites `install/requirements-linux-cu126-hashed.txt` and `-cu130-`, the
   CUDA libraries the Linux build of torch needs; it asks `uv pip compile` for them, so uv must be on PATH.

4. Redeploy the docs: `.venv/Scripts/python.exe -m mkdocs gh-deploy --strict`.

## Code Style

- Follow existing patterns in the codebase.
- Use numpy-style docstrings for public functions and classes.
- Keep commits focused and descriptive.

## License

By contributing, you agree that your contributions will be licensed under the [AGPL-3.0](LICENSE).
