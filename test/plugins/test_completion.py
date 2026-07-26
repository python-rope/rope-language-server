# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

import os
import sys
from typing import NamedTuple

import pytest

from rols import lsp, uris
from rols.plugins.rope_completion import (
    rols_completion_item_resolve as rols_rope_completion_item_resolve,
)
from rols.plugins.rope_completion import rols_completions as rols_rope_completions

PY2 = sys.version[0] == "2"
LINUX = sys.platform.startswith("linux")
CI = os.environ.get("CI")
LOCATION = os.path.realpath(os.path.join(os.getcwd(), os.path.dirname(__file__)))

# Rope resolves completions against a resource on disk, so the tests write
# their source to a real file inside the workspace root and complete against
# that document.
DOC_NAME = "completion_subject.py"

DOC = """import os
print(os.path.isabs("/tmp"))

def hello():
    pass

def _a_hello():
    pass

class Hello():

    @property
    def world(self):
        return None

    def everyone(self, a, b, c=None, d=2):
        pass

hello_result = Hello().world

everyone_result = Hello().everyone

def documented_hello():
    \"\"\"Sends a polite greeting\"\"\"
    pass
"""


def _make_document(workspace, source):
    """Create an on-disk document within the workspace and return it."""
    path = os.path.join(workspace.root_path, DOC_NAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    doc_uri = uris.from_fs_path(path)
    workspace.put_document(doc_uri, source=source)
    return workspace.get_document(doc_uri)


def test_rope_import_completion(config, workspace) -> None:
    com_position = {"line": 0, "character": 7}
    doc = _make_document(workspace, DOC)
    items = rols_rope_completions(config, workspace, doc, com_position)
    assert items is None


class TypeCase(NamedTuple):
    document: str
    position: dict
    label: str
    expected: lsp.CompletionItemKind


# fmt: off
TYPE_CASES: dict[str, TypeCase] = {
    "variable": TypeCase(
        document="test = 1\ntes",
        position={"line": 1, "character": 3},
        label="test",
        # Rope reports plain variables as instances.
        expected=lsp.CompletionItemKind.Reference,
    ),
    "function": TypeCase(
        document="def test():\n    pass\ntes",
        position={"line": 2, "character": 3},
        label="test",
        expected=lsp.CompletionItemKind.Function,
    ),
    "keyword": TypeCase(
        document="fro",
        position={"line": 0, "character": 3},
        label="from",
        expected=lsp.CompletionItemKind.Keyword,
    ),
    "class": TypeCase(
        document="KeyErr",
        position={"line": 0, "character": 6},
        label="KeyError",
        expected=lsp.CompletionItemKind.Class,
    ),
    "property": TypeCase(
        document=(
            "class A:\n"
            "    @property\n"
            "    def test(self):\n"
            "        pass\n"
            "A().tes"
        ),
        position={"line": 4, "character": 7},
        label="test",
        # Rope treats a property access as an instance.
        expected=lsp.CompletionItemKind.Reference,
    ),
}
# fmt: on


@pytest.mark.parametrize("case", list(TYPE_CASES.values()), ids=list(TYPE_CASES.keys()))
def test_rope_completion_type(case, config, workspace):
    doc = _make_document(workspace, case.document)
    items = rols_rope_completions(config, workspace, doc, case.position)
    items = {i["label"]: i for i in items}
    assert case.label in items
    assert items[case.label]["kind"] == case.expected


def test_rope_completion(config, workspace) -> None:
    # Over 'i' in os.path.isabs(...)
    com_position = {"line": 1, "character": 15}
    doc = _make_document(workspace, DOC)
    items = rols_rope_completions(config, workspace, doc, com_position)

    assert items
    assert items[0]["label"] == "isabs"

    # Test we don't throw with big character
    rols_rope_completions(config, workspace, doc, {"line": 1, "character": 1000})


def test_rope_completion_item_resolve(config, workspace) -> None:
    # Over the trailing 'docu'
    doc_source = DOC + "docu"
    last_line = doc_source.count("\n")
    com_position = {"line": last_line, "character": 4}
    doc = _make_document(workspace, doc_source)
    completions = rols_rope_completions(config, workspace, doc, com_position)

    items = {c["label"]: c for c in completions}

    documented_hello_item = items["documented_hello"]

    assert "documentation" not in documented_hello_item
    assert "detail" not in documented_hello_item

    resolved = rols_rope_completion_item_resolve(
        config, completion_item=documented_hello_item, document=doc
    )
    assert resolved["documentation"] == {
        "kind": "markdown",
        "value": "Sends a polite greeting",
    }
    assert "documented_hello" in resolved["detail"]


def test_rope_completion_eager_resolve(config, workspace) -> None:
    doc_source = DOC + "docu"
    last_line = doc_source.count("\n")
    com_position = {"line": last_line, "character": 4}
    config.update({"plugins": {"rope_completion": {"eager": True}}})
    doc = _make_document(workspace, doc_source)
    completions = rols_rope_completions(config, workspace, doc, com_position)

    items = {c["label"]: c for c in completions}
    documented_hello_item = items["documented_hello"]

    # With eager resolution the documentation is provided up-front.
    assert documented_hello_item["documentation"] == {
        "kind": "markdown",
        "value": "Sends a polite greeting",
    }


def test_rope_completion_ordering(config, workspace) -> None:
    # Over the blank line
    com_position = {"line": 8, "character": 0}
    doc = _make_document(workspace, DOC)
    completions = rols_rope_completions(config, workspace, doc, com_position)

    items = {c["label"]: c["sortText"] for c in completions}

    # And that 'hidden' functions come after unhidden ones
    assert items["hello"] < items["_a_hello"]


def test_rope_method_completion(config, workspace) -> None:
    doc_source = DOC + "Hello().eve"
    last_line = doc_source.count("\n")
    com_position = {"line": last_line, "character": len("Hello().eve")}
    doc = _make_document(workspace, doc_source)

    config.capabilities["textDocument"] = {
        "completion": {"completionItem": {"snippetSupport": True}}
    }
    config.update({"plugins": {"rope_completion": {"include_params": True}}})

    completions = rols_rope_completions(config, workspace, doc, com_position)
    everyone_method = [c for c in completions if c["label"] == "everyone"][0]

    # Ensure snippets are generated for the parameters, skipping ``self``.
    assert everyone_method["insertTextFormat"] == lsp.InsertTextFormat.Snippet
    assert everyone_method["insertText"] == "everyone(${1:a}, ${2:b}, ${3:c}, ${4:d})$0"

    # Disable param snippets
    config.update({"plugins": {"rope_completion": {"include_params": False}}})

    completions = rols_rope_completions(config, workspace, doc, com_position)
    everyone_method = [c for c in completions if c["label"] == "everyone"][0]

    assert "insertTextFormat" not in everyone_method
    assert "insertText" not in everyone_method


def test_rope_snippet_completion(config, workspace) -> None:
    doc_snippets = "def foo(a, b): pass\nfo"
    com_position = {"line": 1, "character": 2}
    doc = _make_document(workspace, doc_snippets)
    config.capabilities["textDocument"] = {
        "completion": {"completionItem": {"snippetSupport": True}}
    }
    config.update({"plugins": {"rope_completion": {"include_params": True}}})
    completions = rols_rope_completions(config, workspace, doc, com_position)
    foo = [c for c in completions if c["label"] == "foo"][0]
    assert foo["insertText"] == "foo(${1:a}, ${2:b})$0"
    assert foo["insertTextFormat"] == lsp.InsertTextFormat.Snippet


def test_rope_completion_no_snippet_without_support(config, workspace) -> None:
    # When the client does not advertise snippet support, no snippet is emitted
    # even if include_params is enabled.
    doc_snippets = "def foo(a, b): pass\nfo"
    com_position = {"line": 1, "character": 2}
    doc = _make_document(workspace, doc_snippets)
    config.update({"plugins": {"rope_completion": {"include_params": True}}})
    completions = rols_rope_completions(config, workspace, doc, com_position)
    foo = [c for c in completions if c["label"] == "foo"][0]
    assert "insertText" not in foo
    assert "insertTextFormat" not in foo


def test_rope_completion_big_character(config, workspace) -> None:
    doc = _make_document(workspace, DOC)
    # Should not raise
    rols_rope_completions(config, workspace, doc, {"line": 1, "character": 1000})
