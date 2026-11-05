# Copyright 2026- Python Language Server Contributors (Rope backend).

"""Rope bugs that the refactoring code actions work around.

Each test asserts the behaviour Rope should have and is a strict xfail. When
Rope fixes the bug, the test fails: remove the workaround in
``rols/plugins/rope_refactor/actions.py`` and the test.
"""

import os

import pytest
from rope.base.exceptions import RefactoringError
from rope.refactor import extract, inline
from rope.refactor.importutils import ImportOrganizer

from rols import uris


def put(workspace, name, text):
    path = os.path.join(workspace.root_path, name)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    workspace.put_document(uris.from_fs_path(path), text, version=1)


def _module(workspace, source, name="m.py"):
    put(workspace, name, source)
    project = workspace._rope_project_builder({})
    return project, project.get_resource(name)


@pytest.mark.xfail(strict=True, reason="python-rope/rope#825")
def test_rope_825_extract_method_in_class_body(workspace):
    source = 'class TSV:\n    delimiter = "\\t"\n\n\nprint(TSV.delimiter)\n'
    project, resource = _module(workspace, source)
    start = source.index('"\\t"')
    changes = extract.ExtractMethod(project, resource, start, start + 4).get_changes(
        "extracted"
    )
    new = changes.changes[0].new_contents
    assert new.index("def extracted") < new.index("class TSV")


@pytest.mark.xfail(strict=True, reason="python-rope/rope#924")
def test_rope_924_extract_method_into_existing_name(workspace):
    source = "def helper():\n    return 42\n\n\ndef f(a):\n    return a + 1\n"
    project, resource = _module(workspace, source)
    start = source.index("a + 1")
    with pytest.raises(RefactoringError):
        extract.ExtractMethod(project, resource, start, start + 5).get_changes("helper")


@pytest.mark.xfail(strict=True, reason="python-rope/rope#926")
def test_rope_926_extract_empty_region(workspace):
    source = "def f(a):\n    b = a + 1\n    return b\n"
    project, resource = _module(workspace, source)
    start = source.index("a + 1")
    with pytest.raises(RefactoringError):
        extract.ExtractVariable(project, resource, start, start).get_changes("v")


@pytest.mark.xfail(strict=True, reason="python-rope/rope#923")
def test_rope_923_inline_skips_module_with_syntax_error(workspace):
    put(workspace, "b.py", "from a import helper\nprint(helper(4))\nif\n")
    project, resource = _module(workspace, "def helper(x):\n    return x * 2\n", "a.py")
    with pytest.raises(Exception):
        inline.create_inline(project, resource, 4).get_changes()


@pytest.mark.xfail(strict=True, reason="python-rope/rope#368")
def test_rope_368_organise_imports_keeps_noqa_imports(workspace):
    source = "import signal  # noqa: F401\nimport os\n\n\nprint(os.name)\n"
    project, resource = _module(workspace, source)
    changes = ImportOrganizer(project).organize_imports(resource)
    assert changes is None or "import signal" in changes.changes[0].new_contents
