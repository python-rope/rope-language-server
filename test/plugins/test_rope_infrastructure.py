# Copyright 2026- Python Language Server Contributors (Rope backend).

"""The plumbing behind the Rope refactorings: overlay, offsets and edits."""

import os

import pytest
from pylsp_jsonrpc.exceptions import JsonRpcException
from rope.base.change import ChangeContents, ChangeSet, CreateFile, MoveResource
from rope.base.exceptions import RefactoringError
from rope.refactor.rename import Rename

from rols import _utils, hookimpl, uris
from rols.config.config import Config
from rols.plugins import _rope_edits, _rope_utils
from rols.plugins._rope_overlay import WorkspaceFileCommands, encode_source
from rols.plugins.rope_rename import rols_rename
from test.test_utils import apply_text_edits


def put(workspace, name, text, on_disk=None, version=1):
    path = os.path.join(workspace.root_path, name)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text if on_disk is None else on_disk)
    uri = uris.from_fs_path(path)
    workspace.put_document(uri, text, version=version)
    return uri, path


def project_for(workspace):
    return workspace._rope_project_builder({})


# Offsets


@pytest.mark.parametrize(
    "line, character, expected",
    [(0, 0, 0), (0, 2, 2), (1, 1, 4), (2, 2, 8), (2, 99, 8), (9, 0, 8), (0, 99, 2)],
)
def test_position_to_offset_counts_crlf_as_one(line, character, expected):
    source = "ab\r\ncd\r\nef"
    assert (
        _rope_utils.position_to_offset(source, {"line": line, "character": character})
        == expected
    )
    assert _rope_utils.normalize_newlines(source) == "ab\ncd\nef"


@pytest.mark.parametrize(
    "text, expected", [("a\r\nb", "\r\n"), ("a\rb", "\r"), ("a\nb", "\n"), ("", "\n")]
)
def test_newline_of(text, expected):
    assert _rope_utils.newline_of(text) == expected


# Line diff


@pytest.mark.parametrize(
    "old, new",
    [
        ("a\nb\nc\n", "a\nB\nc\n"),
        ("a\nb", "a\nb\nc"),
        ("a\nb\nc", "a\nb"),
        ("a\nb\n", "a\n"),
        ("a\nb\n", ""),
        ("", "x = 1\n"),
        ("žluťoučký = 1\nkůň = 2\n", "žluťoučký = 1\nkůň = 3\nend\n"),
        ("a\n", "b\nc\na\n"),
    ],
)
def test_line_diff_reproduces_new_text(old, new):
    assert apply_text_edits(old, _rope_edits.line_diff(old, new)) == new


def test_line_diff_keeps_crlf():
    old = "a\r\nb\r\nc\r\n"
    edits = _rope_edits.line_diff("a\nb\nc\n", "a\nB\nb2\nc\n", "\r\n")
    assert apply_text_edits(old, edits) == "a\r\nB\r\nb2\r\nc\r\n"


# Overlay


def test_overlay_serves_open_documents(workspace):
    uri, path = put(workspace, "m.py", "x = 2\n", on_disk="x = 1\n")
    other = os.path.join(workspace.root_path, "other.py")
    with open(other, "w", encoding="utf-8") as handle:
        handle.write("y = 1\n")
    commands = WorkspaceFileCommands(workspace, workspace.root_path)
    assert commands.read(path) == b"x = 2\n"
    assert commands.read(other) == b"y = 1\n"
    workspace.rm_document(uri)
    assert commands.read(path) == b"x = 1\n"


def test_overlay_ignores_cells_and_notebooks(workspace):
    path = os.path.join(workspace.root_path, "cell.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("on disk\n")
    workspace.put_cell_document(uris.from_fs_path(path), "notebook", "python", "cell")
    assert workspace._rope_overlay_source(path) is None


def test_encode_source_respects_coding_declaration():
    source = "# -*- coding: latin-1 -*-\nname = 'Matěj'\n"
    source = source.replace("ě", "é")
    assert encode_source(source) == source.encode("latin-1")
    # An unknown coding falls back to UTF-8 (python-rope/rope#83).
    bogus = "# coding: no-such-codec\nname = 'é'\n"
    assert encode_source(bogus) == bogus.encode("utf-8")


def test_rope_project_reads_unsaved_buffers(workspace):
    uri, path = put(workspace, "m.py", "def g():\n    pass\n", on_disk="def f():\n")
    project = project_for(workspace)
    resource = project.get_resource("m.py")
    assert sorted(project.get_pymodule(resource).get_attributes()) == ["g"]
    workspace.update_document(uri, {"text": "def h():\n    pass\n"}, version=2)
    project = project_for(workspace)
    resource = project.get_resource("m.py")
    assert sorted(project.get_pymodule(resource).get_attributes()) == ["h"]


# ChangeSet conversion


def test_changeset_to_workspace_edit_formats(workspace):
    uri, path = put(workspace, "m.py", "x = 1\nprint(x)\n", version=7)
    other_path = os.path.join(workspace.root_path, "other.py")
    with open(other_path, "w", encoding="utf-8", newline="") as handle:
        handle.write("from m import x\r\nprint(x)\r\n")
    project = project_for(workspace)
    changes = Rename(project, project.get_resource("m.py"), 0).get_changes("y")

    edit = _rope_edits.changeset_to_workspace_edit(
        workspace, changes, document_changes=True, first_uri=uri
    )
    other_uri = uris.from_fs_path(other_path)
    assert [c["textDocument"] for c in edit["documentChanges"]] == [
        {"uri": uri, "version": 7},
        {"uri": other_uri, "version": None},
    ]
    other_edits = edit["documentChanges"][1]["edits"]
    assert (
        apply_text_edits("from m import x\r\nprint(x)\r\n", other_edits)
        == "from m import y\r\nprint(y)\r\n"
    )

    edit = _rope_edits.changeset_to_workspace_edit(
        workspace, changes, document_changes=False, first_uri=uri
    )
    assert list(edit["changes"]) == [uri, other_uri]


def test_changeset_without_changes_is_none(workspace):
    put(workspace, "m.py", "x = 1\n")
    project = project_for(workspace)
    resource = project.get_resource("m.py")
    changes = ChangeSet("nothing")
    changes.add_change(ChangeContents(resource, "x = 1\n"))
    assert (
        _rope_edits.changeset_to_workspace_edit(
            workspace, changes, document_changes=False
        )
        is None
    )


def test_changeset_refuses_file_operations(workspace):
    put(workspace, "m.py", "x = 1\n")
    project = project_for(workspace)
    resource = project.get_resource("m.py")
    for change in (
        CreateFile(project.root, "new.py"),
        MoveResource(resource, "moved.py"),
    ):
        changes = ChangeSet("file operation")
        changes.add_change(change)
        with pytest.raises(RefactoringError, match="not supported"):
            _rope_edits.changeset_to_workspace_edit(
                workspace, changes, document_changes=True
            )


def test_changeset_refuses_code_that_does_not_parse(workspace):
    put(workspace, "m.py", "x = 1\n")
    project = project_for(workspace)
    changes = ChangeSet("broken")
    changes.add_change(ChangeContents(project.get_resource("m.py"), "x = (\n"))
    with pytest.raises(RefactoringError, match="syntax error"):
        _rope_edits.changeset_to_workspace_edit(
            workspace, changes, document_changes=True
        )


# Rename sees unsaved buffers


def test_rename_uses_unsaved_buffer(workspace, config):
    on_disk = "foo = 1\nprint(foo)\n"
    unsaved = "foo = 1\nbar = foo + 1\nprint(foo)\n"
    uri, _ = put(workspace, "m.py", unsaved, on_disk=on_disk)
    document = workspace.get_document(uri)
    result = rols_rename(config, workspace, document, {"line": 0, "character": 0}, "z")
    (change,) = result["documentChanges"]
    assert change["edits"][0]["newText"] == "z = 1\nbar = z + 1\nprint(z)\n"
    assert change["edits"][0]["range"]["end"] == {"line": 3, "character": 0}


# Core server plumbing


@pytest.mark.parametrize(
    "kind, only, expected",
    [
        ("refactor.extract", ["refactor"], True),
        ("refactor", ["refactor.extract"], False),
        ("quickfix", ["refactor"], False),
        ("source.organizeImports", ["source"], True),
        ("refactorx", ["refactor"], False),
        ("quickfix", [""], True),
        (None, ["quickfix"], False),
    ],
)
def test_code_action_kind_matches(kind, only, expected):
    assert _utils.code_action_kind_matches(kind, only) is expected


def test_plugin_manager_passes_protocol_errors_through(workspace):
    config = Config(workspace.root_uri, {}, 0, {})

    class Plugin:
        @hookimpl
        def rols_code_action_resolve(self, code_action):
            if code_action.get("fail") == "protocol":
                raise JsonRpcException("content modified", code=-32801)
            raise ValueError("unexpected")

    config.plugin_manager.register(Plugin(), "test-plugin")
    hook = config.plugin_manager.hook.rols_code_action_resolve
    common = {"config": config, "workspace": workspace, "document": None}
    with pytest.raises(JsonRpcException):
        hook(code_action={"fail": "protocol"}, **common)
    assert hook(code_action={"fail": "other"}, **common) == []
