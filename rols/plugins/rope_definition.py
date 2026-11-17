# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021-2025 Python Language Server Contributors.
# Copyright 2026- Rope Language Server Contributors.
import logging

from rope.contrib.findit import find_definition

from rols import hookimpl
from rols.plugins import _rope_utils

log = logging.getLogger(__name__)


@hookimpl
def rols_definitions(config, workspace, document, position):
    project = _rope_utils.get_project(config, workspace, document)
    if project is None:
        return []

    resource = _rope_utils.get_resource(project, document)
    offset = document.offset_at_position(position)

    try:
        location = find_definition(
            project, document.source, offset, resource, maxfixes=3
        )
    except Exception as e:
        log.debug("Failed to run Rope find_definition: %s", e)
        return []

    if location is None:
        return []

    source = _rope_utils.resource_source(location.resource, document)
    start, end = location.region
    return [
        {
            "uri": _rope_utils.resource_uri(location.resource, document),
            "range": _rope_utils.region_to_range(source, start, end),
        }
    ]
