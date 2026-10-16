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
4. Run the test suite: `pytest tests/` (about 3.5 minutes with a GPU). `pytest -m "not slow"` leaves out the end-to-end scenes, simulations and daemon-process tests and takes under a minute; tests marked `gpu` are skipped automatically without CUDA. Every push runs the tests that do not need CUDA on GitHub Actions (`.github/workflows/tests_on_cpu.yml`).
5. If you changed anything under `grasshopper/components/`, rebuild the `.ghuser` files (`pip install -e .[ghbuild]`, then `python grasshopper/build_ghuser.py`) and commit them with the source change. See [docs/grasshopper.md](docs/grasshopper.md#rebuilding-the-components).
6. Open a PR with a clear description of the changes.

## Code Style

- Follow existing patterns in the codebase.
- Use numpy-style docstrings for public functions and classes.
- Keep commits focused and descriptive.

## License

By contributing, you agree that your contributions will be licensed under the [AGPL-3.0](LICENSE).
