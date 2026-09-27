# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.
# Copyright 2024- Python Language Server Contributors (Rope backend).

import logging

from rope.refactor.rename import Rename

from rols import _utils, hookimpl, uris
from rols.plugins import _rope_utils

log = logging.getLogger(__name__)


@hookimpl
def rols_rename(config, workspace, document, position, new_name):
    log.debug(
        "Executing rename of %s to %s", document.word_at_position(position), new_name
    )

    project = _rope_utils.get_project(config, workspace, document)
    if project is None:
        return {"documentChanges": []}

    resource = _rope_utils.path_to_resource(project, document.path)
    if resource is None:
        return {"documentChanges": []}

    rename = Rename(project, resource, document.offset_at_position(position))
    changeset = rename.get_changes(new_name, in_hierarchy=True, docs=True)
    log.debug("Finished rename: %s", changeset.changes)

    changes = []
    for change in changeset.changes:
        try:
            old = change.old_contents
            new = change.new_contents
            if old is None:
                old = change.resource.read()
        except Exception as exc:
            log.exception("Failed to get contents for rename change: %s", exc)
            continue

        uri = uris.from_fs_path(change.resource.real_path)
        doc = workspace.get_maybe_document(uri)
        changes.append(
            {
                "textDocument": {"uri": uri, "version": doc.version if doc else None},
                "edits": [
                    {
                        "range": {
                            "start": {"line": 0, "character": 0},
                            "end": {
                                "line": _num_lines(old),
                                "character": 0,
                            },
                        },
                        "newText": new,
                    }
                ],
            }
        )

    # Rope does not guarantee a stable ordering of the changes, so make the
    # output deterministic: the document the rename was invoked on comes first,
    # followed by the remaining documents sorted by their URI.
    document_uri = uris.from_fs_path(document.path)
    changes.sort(
        key=lambda change: (
            change["textDocument"]["uri"] != document_uri,
            change["textDocument"]["uri"],
        )
    )
    return {"documentChanges": changes}


def _num_lines(file_contents):
    "Count the number of lines in the given string."
    if _utils.get_eol_chars(file_contents):
        return len(file_contents.splitlines())
    return 0
