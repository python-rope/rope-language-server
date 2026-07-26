# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.
# Copyright 2024- Python Language Server Contributors (Rope backend).

import logging

from rope.base import evaluate, worder
from rope.refactor import occurrences

from rols import hookimpl, uris
from rols.plugins import _rope_utils

log = logging.getLogger(__name__)


def find_occurrences(project, resource, offset):
    """Yield Rope ``Occurrence`` objects for the name at ``offset``.

    Unlike ``rope.contrib.findit.find_occurrences`` this keeps the raw
    occurrence objects so callers can inspect ``is_defined()`` and whether the
    occurrence sits inside an import statement.
    """
    name = worder.get_name_at(resource, offset)
    this_pymodule = project.get_pymodule(resource)
    primary, pyname = evaluate.eval_location2(this_pymodule, offset)
    finder = occurrences.create_finder(project, name, pyname, instance=primary)
    for python_file in project.get_python_files():
        yield from finder.find_occurrences(python_file)


@hookimpl
def rols_references(config, workspace, document, position, exclude_declaration):
    project = _rope_utils.get_project(config, workspace, document)
    if project is None:
        return []

    resource = _rope_utils.get_resource(project, document)
    if resource is None:
        # find_occurrences needs an on-disk resource to search the project.
        return []

    offset = document.offset_at_position(position)

    try:
        occs = list(find_occurrences(project, resource, offset))
    except Exception as e:
        log.debug("Failed to run Rope find_occurrences: %s", e)
        return []

    _source_cache = {}

    def source_for(res):
        if res not in _source_cache:
            try:
                _source_cache[res] = res.read()
            except Exception:
                _source_cache[res] = ""
        return _source_cache[res]

    results = []
    for occ in occs:
        if exclude_declaration and (occ.is_defined() or occ.is_in_import_statement()):
            continue

        start, end = occ.get_word_range()
        results.append(
            {
                "uri": uris.from_fs_path(occ.resource.real_path),
                "range": _rope_utils.region_to_range(
                    source_for(occ.resource), start, end
                ),
            }
        )
    return results
