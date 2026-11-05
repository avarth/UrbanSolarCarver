"""List Python code nothing seems to call, with vulture. A report to read, not a rule: it is not part of the tests.

    .venv/Scripts/python.exe tools/find_dead_code.py

Two lists, for src/urbansolarcarver:
  unused everywhere    no use in the package, the tests, the tools or the Grasshopper components
  used only by tests   used by a test but by nothing that ships, so either the tests alone keep it alive or it is a public function

Vulture only sees names, so check each entry before removing it: a name used through ``getattr``, a dataclass field written to a
JSON file or a public function of ``urbansolarcarver.api`` shows up here. Code that runs but is no longer needed does not.
"""
from pathlib import Path

from vulture import Vulture

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "urbansolarcarver"
USERS = [ROOT / "tests", ROOT / "tools", ROOT / "grasshopper", ROOT / "setup_env.py"]

# Generated or packaged files, and the reply models, whose fields only the app reads.
SKIPPED = ["*ui_static*", "*example_projects*", "*api_models.py"]
# Called by a framework: FastAPI routes and handlers, the CLI's commands, Pydantic's validators.
CALLED_BY_A_FRAMEWORK = ["@app.*", "@cli.*", "@*.command", "@*.get", "@*.post", "@*.put", "@*.patch", "@*.delete", "@*.websocket",
                         "@*.exception_handler", "@*.callback", "@*validator*", "@computed_field"]
NAMES_ONLY_A_FRAMEWORK_READS = ["model_config", "test_*", "__test__", "pytest_*", "__getattr__"]


def unused(paths: list[Path]) -> list:
    scan = Vulture(ignore_names=NAMES_ONLY_A_FRAMEWORK_READS, ignore_decorators=CALLED_BY_A_FRAMEWORK)
    scan.scavenge([str(path) for path in paths], exclude=SKIPPED)
    return scan.get_unused_code(min_confidence=60)


def in_the_package(item) -> bool:
    return Path(item.filename).resolve().is_relative_to(PACKAGE)


def line(item) -> str:
    return f"  {Path(item.filename).resolve().relative_to(ROOT).as_posix()}:{item.first_lineno}: {item.typ} {item.name}"


def main() -> None:
    everywhere = [item for item in unused([PACKAGE, *USERS]) if in_the_package(item)]
    found_everywhere = {item.name for item in everywhere}
    only_tests = [item for item in unused([PACKAGE, ROOT / "tools", ROOT / "grasshopper", ROOT / "setup_env.py"])
                  if in_the_package(item) and item.name not in found_everywhere]
    for title, items in (("unused everywhere", everywhere), ("used only by tests", only_tests)):
        print(f"{title}: {len(items)}")
        print("\n".join(line(item) for item in items))


if __name__ == "__main__":
    main()
