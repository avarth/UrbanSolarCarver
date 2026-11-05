"""Report what the docs and the vault name that no longer exists.

    .venv/Scripts/python.exe tools/check_references.py

In the docs and README.md: a service route (with its method when it gives one), a backticked path or code file, and a backticked
name such as a function, setting or route segment, which must still appear in the code. Stale docs mostly name things that way:
a page that says "the `carve-further` route" has no path to check. In the vault, which is not in git and so cannot be a test: the
paths, the line of a ``file:line``, ``[[wikilinks]]`` and commit hashes; a note may name what is planned or gone, so not its names.
tests/test_docs_references.py runs the docs part; run the whole of it before trusting the vault. A line number inside a file can
still have moved: only a line past the end of the file is reported.

Left out: CHANGELOG.md, whose entries name what was removed, docs/superpowers/ (dated design notes), vault/archive/.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNCHECKED_DOCS = "superpowers"
NOT_IN_A_FRESH_CHECKOUT = {"app/openapi.json"}  # generated and ignored by git, named by the docs

CODE_FOLDERS = ("src", "app/src", "app/scripts", "grasshopper", "configs", "tools", "tests", "setup_env.py", "pyproject.toml", "mkdocs.yml")
# Built or generated files, and this check with its test, which quote removed names: each would keep a name alive after the code lost it.
NOT_THE_CODE = ("ui_static/", "example_projects/", "generated_types.ts", "check_references.py", "test_docs_references.py")
CODE_TEXT = (".py", ".ts", ".tsx", ".mjs", ".yaml", ".yml", ".toml", ".json")
EXTERNAL_NAMES = {"nvidia-smi"}  # commands of other programs that the docs name

TOP_FOLDERS = ("src/", "tests/", "tools/", "app/", "docs/", "examples/", "grasshopper/", "benchmarks/", "configs/", "design/")
CODE_FILES = (".py", ".ts", ".tsx", ".mjs", ".cjs", ".ipynb")
ROUTE_METHODS = "GET|POST|PUT|PATCH|DELETE"

ROUTE = re.compile(rf"`(?:(?P<method>{ROUTE_METHODS}) )?(?P<path>/[^`\s?]*)[^`]*`")
PATH = re.compile(r"`(?P<path>[\w./-]+?)(?::(?P<line>\d+))?`")
NAME = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*(?:[_-][A-Za-z0-9_]+)+|[a-z]+[A-Z]\w+|[A-Z][a-z]+[A-Z]\w+)`")  # snake, kebab or camel
WIKILINK = re.compile(r"\[\[([^]|#]+)")
COMMIT = re.compile(r"`([0-9a-f]{7,40})`")


def git(*arguments: str) -> str:
    return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout


def repository_names() -> dict[str, list[Path]]:
    """Every name a reference may use for a file or folder of the repository, with the files it can mean.

    A file answers to its path and to each tail of it (``api_core/preprocessing.py``, ``preprocessing.py``), a folder to its path.
    """
    names: dict[str, list[Path]] = {}
    for file in git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0"):
        if not file or not (ROOT / file).is_file():
            continue
        parts = file.split("/")
        for start in range(len(parts)):
            names.setdefault("/".join(parts[start:]), []).append(ROOT / file)
        for end in range(1, len(parts)):
            names.setdefault("/".join(parts[:end]), [])
    return names


def service_routes() -> dict[str, set[str]]:
    from urbansolarcarver.local_web_service.server import openapi_document
    return {path: {method.upper() for method in methods} for path, methods in openapi_document()["paths"].items()}


def _segments(route: str) -> list[str]:
    route = re.sub(r"<[^>]+>", "{}", route.rstrip("/"))
    return (route if route.startswith("/api") else "/api" + route).split("/")


def _same_route(written: list[str], route: list[str]) -> bool:
    return len(written) == len(route) and all(a == b or b.startswith("{") for a, b in zip(written, route))


def route_problems(text: str, routes: dict[str, set[str]]) -> list[str]:
    """The routes *text* names that the service does not have. A bare path counts as a route when it starts with /api or /projects."""
    problems = []
    for match in ROUTE.finditer(text):
        method, written = match["method"], match["path"]
        if written == "/api" or not (method or written.startswith(("/api", "/projects"))):
            continue
        segments = _segments(written)
        found = [methods for route, methods in routes.items() if _same_route(segments, route.split("/"))]
        if not found:
            problems.append(f"no route {written}")
        elif method and not any(method in methods for methods in found):
            problems.append(f"route {written} has no {method}")
    return problems


def path_problems(text: str, names: dict[str, list[Path]]) -> list[str]:
    """The folders and code files *text* names that do not exist, and the ``file:line`` past the end of the file."""
    problems = []
    for match in PATH.finditer(text):
        token, line = match["path"].rstrip("/"), match["line"]
        if token.startswith(".") or not (match["path"].startswith(TOP_FOLDERS) or token.endswith(CODE_FILES)):
            continue
        if token in NOT_IN_A_FRESH_CHECKOUT:
            continue
        if token not in names and not (ROOT / token).exists():
            problems.append(f"no file {token}")
        elif line and token in names and names[token]:
            lengths = [len(file.read_text(encoding="utf-8", errors="replace").splitlines()) for file in names[token]]
            if int(line) > max(lengths):
                problems.append(f"{token}:{line} is past the end of the file ({max(lengths)} lines)")
    return problems


def code_words() -> set[str]:
    words = set()
    for file in git("ls-files", "--cached", "--others", "--exclude-standard", *CODE_FOLDERS).splitlines():
        path = ROOT / file
        if file.endswith(CODE_TEXT) and not any(part in file for part in NOT_THE_CODE) and path.is_file():
            words |= set(re.findall(r"[A-Za-z_][\w-]*", path.read_text(encoding="utf-8", errors="replace")))
    return words


def name_problems(text: str, words: set[str]) -> list[str]:
    """The snake_case, kebab-case and camelCase names *text* puts in backticks that appear nowhere in the code."""
    return [f"no name {name} in the code" for name in sorted(set(NAME.findall(text)) - words - EXTERNAL_NAMES)]


def wikilink_problems(text: str, vault: Path) -> list[str]:
    return [f"no note [[{name}]]" for name in WIKILINK.findall(text) if not (vault / f"{name.strip()}.md").exists()]


def commit_problems(text: str) -> list[str]:
    hashes = sorted(set(COMMIT.findall(text)))
    if not hashes:
        return []
    answers = subprocess.run(["git", "cat-file", "--batch-check"], cwd=ROOT, input="\n".join(hashes) + "\n",
                             capture_output=True, text=True, check=True).stdout.splitlines()
    return [f"no commit {commit}" for commit, answer in zip(hashes, answers) if answer.endswith("missing")]


def docs_problems() -> list[str]:
    names, routes, words = repository_names(), service_routes(), code_words()
    pages = [ROOT / "README.md", *(p for p in sorted((ROOT / "docs").rglob("*.md")) if UNCHECKED_DOCS not in p.parts)]
    return [f"{page.relative_to(ROOT).as_posix()}: {problem}"
            for page in pages
            for text in [page.read_text(encoding="utf-8")]
            for problem in route_problems(text, routes) + path_problems(text, names) + name_problems(text, words)]


def vault_folder() -> Path:
    """The vault of the main checkout: a worktree has none of its own."""
    return Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip()).parent / "vault"


def vault_problems(vault: Path) -> list[str]:
    names = repository_names()
    names.update(dict.fromkeys(git("branch", "--format=%(refname:short)").splitlines(), []))  # a note may name a branch
    notes = [note for note in sorted(vault.rglob("*.md")) if "archive" not in note.relative_to(vault).parts]
    return [f"vault/{note.relative_to(vault).as_posix()}: {problem}"
            for note in notes
            for text in [note.read_text(encoding="utf-8")]
            for problem in path_problems(text, names) + wikilink_problems(text, vault) + commit_problems(text)]


def main() -> int:
    vault = vault_folder()
    problems = docs_problems() + (vault_problems(vault) if vault.is_dir() else [])
    print("\n".join(problems))
    print(f"{len(problems)} references do not resolve" + ("" if vault.is_dir() else " (docs only: no vault here)"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
