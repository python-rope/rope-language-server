# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021-2025 Python Language Server Contributors.
# Copyright 2026- Rope Language Server Contributors.
# Parts adapted from pylsp-rope (https://github.com/python-rope/pylsp-rope),
# Copyright (c) 2021 Lie Ryan, MIT licence; see LICENSES/pylsp-rope.txt.

"""Turn Rope change sets into LSP workspace edits."""

import ast
import difflib
import logging

from rope.base import fscommands
from rope.base.change import ChangeContents, ChangeSet
from rope.base.exceptions import RefactoringError

from rols import uris
from rols.plugins import _rope_utils

log = logging.getLogger(__name__)


def _iter_changes(changes):
    if isinstance(changes, ChangeSet):
        for change in changes.changes:
            yield from _iter_changes(change)
    else:
        yield changes


def _end_position(lines):
    """Return the position just after the last character of ``lines``."""
    if not lines:
        return {"line": 0, "character": 0}
    if lines[-1].endswith("\n"):
        return {"line": len(lines), "character": 0}
    return {"line": len(lines) - 1, "character": _rope_utils.utf16_length(lines[-1])}


def _position(lines, index):
    if index >= len(lines):
        return _end_position(lines)
    return {"line": index, "character": 0}


def line_diff(old, new, newline="\n"):
    """Return LSP ``TextEdit`` objects that turn ``old`` into ``new``.

    Both texts must use ``\\n`` line endings, as Rope's text does. Edits
    replace whole lines, which keeps the client's view of unchanged lines,
    and ``newline`` is used for the line endings of the inserted text.
    """
    old_lines = old.splitlines(True)
    new_lines = new.splitlines(True)
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    edits = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            continue
        text = "".join(new_lines[j1:j2])
        if newline != "\n":
            text = text.replace("\n", newline)
        edits.append(
            {
                "range": {
                    "start": _position(old_lines, i1),
                    "end": _position(old_lines, i2),
                },
                "newText": text,
            }
        )
    return edits


def _check_parses(resource, new_contents):
    if not resource.name.endswith((".py", ".pyi")):
        return
    try:
        ast.parse(new_contents)
    except (SyntaxError, ValueError) as exc:
        raise RefactoringError(
            f"Refusing a change that would leave {resource.path} with a "
            f"syntax error: {exc}"
        ) from exc


def supports_document_changes(config):
    capabilities = config.capabilities if config is not None else {}
    return bool(
        capabilities.get("workspace", {})
        .get("workspaceEdit", {})
        .get("documentChanges", False)
    )


def changeset_to_workspace_edit(
    workspace, changes, *, document_changes, first_uri=None
):
    """Convert a Rope ``ChangeSet`` into an LSP ``WorkspaceEdit``.

    The edits are computed against what the client has: the open document's
    text, or the file on disk. Rope must have read the same text through the
    workspace overlay. Changes that create, move or remove files are refused,
    and so is any change that would leave a Python module that does not
    parse.

    Returns ``None`` if the change set does not change anything.
    """
    per_uri = {}
    for change in _iter_changes(changes):
        if not isinstance(change, ChangeContents):
            raise RefactoringError(
                f"Rope wants to {change.get_description()!r}; creating, moving "
                "and removing files is not supported."
            )
        resource = change.resource
        new_contents = change.new_contents
        _check_parses(resource, new_contents)

        document = workspace.get_maybe_document(uris.from_fs_path(resource.real_path))
        if document is None:
            document = _open_document_for_path(workspace, resource.real_path)
        if document is not None:
            old = _rope_utils.normalize_newlines(document.source)
            newline = _rope_utils.newline_of(document.source)
            uri = document.uri
            version = document.version
        else:
            with open(resource.real_path, "rb") as handle:
                old, newline = fscommands.file_data_to_unicode(handle.read())
            uri = uris.from_fs_path(resource.real_path)
            version = None

        new = _rope_utils.normalize_newlines(new_contents)
        if old == new:
            continue
        edits = line_diff(old, new, newline or "\n")
        per_uri[uri] = (version, edits)

    if not per_uri:
        return None

    ordered = sorted(per_uri, key=lambda uri: (uri != first_uri, uri))
    if document_changes:
        return {
            "documentChanges": [
                {
                    "textDocument": {"uri": uri, "version": per_uri[uri][0]},
                    "edits": per_uri[uri][1],
                }
                for uri in ordered
            ]
        }
    return {"changes": {uri: per_uri[uri][1] for uri in ordered}}


def _open_document_for_path(workspace, path):
    """Find an open document whose URI is spelt differently from ``path``."""
    from rols.plugins._rope_overlay import path_key
    from rols.workspace import Document

    key = path_key(path)
    for document in list(workspace.documents.values()):
        if type(document) is Document and document.rope_path_key == key:
            return document
    return None
