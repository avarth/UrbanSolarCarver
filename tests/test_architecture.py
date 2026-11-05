"""The package keeps the layering written in pyproject.toml ([tool.importlinter]), and every module says what it is for.

docs/project-map.md explains the layers; the module docstrings are the description of each file.
"""
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "urbansolarcarver"


def test_the_imports_keep_the_layers_written_in_pyproject():
    from importlinter.application.use_cases import lint_imports
    from importlinter.configuration import configure
    configure()  # what the lint-imports command does first: the readers of the config file
    # Prints the report; a broken rule names the import that breaks it.
    assert lint_imports(config_filename=str(ROOT / "pyproject.toml"), cache_dir=None, no_logo=True), (
        "an import breaks a rule in pyproject.toml [tool.importlinter]: see the report above; "
        "run `lint-imports` from the repository for the same report")


def test_ruff_finds_no_mistakes():
    """The rules are in pyproject.toml [tool.ruff.lint]: unused imports and names, undefined names and the like, not style."""
    result = subprocess.run([sys.executable, "-m", "ruff", "check", "--output-format", "concise", str(ROOT)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_module_starts_with_a_docstring():
    missing = [str(path.relative_to(PACKAGE)) for path in sorted(PACKAGE.rglob("*.py"))
               if not {"ui_static", "example_projects"} & set(path.parts)
               and not ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))]
    assert not missing, f"modules without a docstring saying what they are for: {missing}"
