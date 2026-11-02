"""The committed front-end types (app/src/api_client/generated_types.ts) describe the service as it is now.

The app reads every reply through ``components["schemas"]`` of that file, which ``npm run api-types`` generates from
``openapi_document()``. A route, a model or a field added, renamed or removed in the service without regenerating the file
leaves the app type-checking against a service that no longer exists. These tests read the paths with their methods, the
schema names and each schema's field names from the file (as openapi-typescript 7 writes them) and compare them with the
document.
"""
import re
from pathlib import Path

import pytest

from urbansolarcarver.local_web_service.server import openapi_document

GENERATED_TYPES = Path(__file__).resolve().parent.parent / "app" / "src" / "api_client" / "generated_types.ts"
REGENERATE = "the service's OpenAPI document changed: run `npm run api-types` in app/ and commit generated_types.ts"
HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

# openapi-typescript writes one member per line, nested by four spaces: a path or a schema at 4 spaces inside its interface
# or block, a method or a schema's field at 8 (12 for fields). A member name is an identifier or a quoted string, and
# "?: never" marks a method the path does not have.
_MEMBER = r'(?:"(?P<quoted>[^"]+)"|(?P<plain>[A-Za-z_$][\w$]*))(?P<optional>\?)?: '


def _block(text: str, opening: str, closing: str) -> str:
    """The lines between the line *opening* and the first line after it that is exactly *closing*."""
    start = text.index(opening + "\n") + len(opening) + 1
    return text[start:text.index("\n" + closing + "\n", start)]


def _members(block: str, indent: int):
    """The (name, line) of each member of *block* written at *indent* spaces."""
    pattern = re.compile(" " * indent + _MEMBER)
    for line in block.splitlines():
        match = pattern.match(line)
        if match:
            yield match.group("quoted") or match.group("plain"), line


def _members_with_bodies(block: str, indent: int) -> dict[str, str]:
    """Each member of *block* at *indent* spaces and the text after it up to the next member at that indent."""
    lines = block.splitlines()
    pattern = re.compile(" " * indent + _MEMBER)
    starts = [(index, match) for index, line in enumerate(lines) if (match := pattern.match(line))]
    bodies = {}
    for (index, match), following in zip(starts, starts[1:] + [(len(lines), None)]):
        bodies[match.group("quoted") or match.group("plain")] = "\n".join(lines[index + 1:following[0]])
    return bodies


@pytest.fixture(scope="module")
def document() -> dict:
    return openapi_document()


@pytest.fixture(scope="module")
def generated() -> str:
    return GENERATED_TYPES.read_text(encoding="utf-8")


def generated_paths(text: str) -> dict[str, set[str]]:
    paths = _block(text, "export interface paths {", "}")
    return {path: {method for method, line in _members(body, 8) if method in HTTP_METHODS and not line.endswith("?: never;")}
            for path, body in _members_with_bodies(paths, 4).items()}


def generated_schemas(text: str) -> dict[str, set[str]]:
    """Each schema of ``components["schemas"]`` and the names of its fields (none for a schema that is not an object)."""
    schemas = _block(_block(text, "export interface components {", "}"), "    schemas: {", "    };")
    return {name: {field for field, _line in _members(body, 12)} for name, body in _members_with_bodies(schemas, 8).items()}


def test_the_generated_types_have_the_paths_and_methods_of_the_service(document, generated):
    expected = {path: {method for method in item if method in HTTP_METHODS} for path, item in document["paths"].items()}
    found = generated_paths(generated)
    assert found, "no path read from generated_types.ts: the reader no longer matches how openapi-typescript writes the file"
    differences = {path: {"service": sorted(expected.get(path, ())), "generated_types.ts": sorted(found.get(path, ()))}
                   for path in expected.keys() | found.keys() if expected.get(path) != found.get(path)}
    assert not differences, f"{REGENERATE}. Paths whose methods differ: {differences}"


def test_the_generated_types_have_the_schemas_of_the_service(document, generated):
    expected = set(document["components"]["schemas"])
    found = set(generated_schemas(generated))
    assert found, "no schema read from generated_types.ts: the reader no longer matches how openapi-typescript writes the file"
    assert found == expected, (f"{REGENERATE}. Only in the service: {sorted(expected - found)}; "
                               f"only in generated_types.ts: {sorted(found - expected)}")


def test_the_generated_types_have_the_fields_of_each_schema(document, generated):
    found = generated_schemas(generated)
    differences = {}
    for name, schema in document["components"]["schemas"].items():
        fields = set(schema.get("properties", {}))
        if name in found and found[name] != fields:
            differences[name] = {"only in the service": sorted(fields - found[name]),
                                 "only in generated_types.ts": sorted(found[name] - fields)}
    assert not differences, f"{REGENERATE}. Schemas whose fields differ: {differences}"
