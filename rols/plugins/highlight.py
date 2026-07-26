# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.
# Copyright 2024- Python Language Server Contributors (Rope backend).

import logging

from rope.base import evaluate, libutils, worder
from rope.refactor import occurrences

from rols import hookimpl, lsp
from rols.plugins import _rope_utils

log = logging.getLogger(__name__)


@hookimpl
def rols_document_highlight(config, workspace, document, position):
    project = _rope_utils.get_project(config, workspace, document)
    if project is None:
        return []

    resource = _rope_utils.get_resource(project, document)
    offset = document.offset_at_position(position)
    source = document.source

    try:
        pymodule = libutils.get_string_module(project, source, resource)
        name = worder.Worder(source).get_word_at(offset)
        primary, pyname = evaluate.eval_location2(pymodule, offset)
        finder = occurrences.create_finder(project, name, pyname, instance=primary)
        occs = list(finder.find_occurrences(pymodule=pymodule))
    except Exception as e:
        log.debug("Failed to compute Rope document highlights: %s", e)
        return []

    results = []
    for occ in occs:
        start, end = occ.get_word_range()
        is_write = occ.is_defined() or occ.is_written() or occ.is_in_import_statement()
        results.append(
            {
                "range": _rope_utils.region_to_range(source, start, end),
                "kind": (
                    lsp.DocumentHighlightKind.Write
                    if is_write
                    else lsp.DocumentHighlightKind.Read
                ),
            }
        )
    return results
