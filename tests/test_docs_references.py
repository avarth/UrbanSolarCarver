"""The docs name only routes, files and code that exist (tools/check_references.py, which also covers the vault)."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_references", ROOT / "tools" / "check_references.py")
check_references = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_references)

ROUTES = {"/api/projects/{name}/shared-settings": {"PUT"}, "/api/projects/{name}/inputs/{role}": {"PUT", "DELETE"}}


@pytest.mark.slow
def test_every_route_file_and_name_in_the_docs_exists():
    assert check_references.docs_problems() == []


@pytest.mark.parametrize("text", [
    "`PUT /projects/{name}/shared-settings`",
    "`PUT /api/projects/<name>/shared-settings`",
    "`/projects/{name}/inputs/test_surfaces`",
    "`DELETE /projects/{name}/inputs/test_surfaces?file=a.ply` removes it",
    "all under `/api`",
    "the app's `/criteria/{id}` part and the folder `/usr/share`",
])
def test_a_route_the_service_has_passes(text):
    assert check_references.route_problems(text, ROUTES) == []


@pytest.mark.parametrize("text, problem", [
    ("`PUT /projects/{name}/config`", "no route /projects/{name}/config"),
    ("`/api/projects/<name>/carve-further`", "no route /api/projects/<name>/carve-further"),
    ("`POST /projects/{name}/shared-settings`", "route /projects/{name}/shared-settings has no POST"),
])
def test_a_route_the_service_does_not_have_is_reported(text, problem):
    assert check_references.route_problems(text, ROUTES) == [problem]


def test_paths_are_found_by_any_tail_and_a_line_must_be_in_the_file():
    names = check_references.repository_names()
    known = "`tools/check_references.py`, `check_references.py:1`, `src/urbansolarcarver/`, `.py`, `project.json`, `app/openapi.json`"
    assert check_references.path_problems(known, names) == []
    assert check_references.path_problems("`carve_further.py` and `tests/gone/`", names) == ["no file carve_further.py", "no file tests/gone"]
    assert check_references.path_problems("`check_references.py:99999`", names)[0].startswith("check_references.py:99999 is past the end")


def test_a_name_the_code_lost_is_reported_as_the_page_before_the_fix_of_3_november_would_have_been():
    words = check_references.code_words()
    assert "openapi_document" in words
    text = "The service's `carve-further` route and `openapi_document`, a `plain` word and `nvidia-smi`."
    assert check_references.name_problems(text, words) == ["no name carve-further in the code"]


def test_a_wikilink_needs_its_note_and_a_commit_hash_its_commit(tmp_path):
    (tmp_path / "bugs").mkdir()
    (tmp_path / "bugs" / "here.md").write_text("", encoding="utf-8")
    assert check_references.wikilink_problems("[[bugs/here]], [[bugs/here|alias]], [[bugs/gone]]", tmp_path) == ["no note [[bugs/gone]]"]
    assert check_references.commit_problems("`64e54e7` and `abcdef1234`") == ["no commit abcdef1234"]
