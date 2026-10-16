"""The version is written once, in pyproject.toml; everything else reads or matches it."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE).group(1)


def test_the_package_reports_the_pyproject_version():
    import urbansolarcarver
    assert urbansolarcarver.__version__ == _pyproject_version(), (
        f"the installed metadata says {urbansolarcarver.__version__}: an editable "
        f"install keeps the version it was installed with; refresh it with "
        f"`pip install -e . --no-deps` from the repository")


def test_the_citation_file_names_the_same_version():
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert re.search(r'^version:\s*"([^"]+)"', citation, re.MULTILINE).group(1) == _pyproject_version()


def test_the_cli_prints_the_package_version():
    from typer.testing import CliRunner
    import urbansolarcarver
    from urbansolarcarver.carver_cli import app
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert urbansolarcarver.__version__ in result.output
