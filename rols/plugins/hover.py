# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.
# Copyright 2024- Python Language Server Contributors (Rope backend).

import logging

from rope.contrib import fixsyntax
from rope.contrib.codeassist import get_calltip

from rols import _utils, hookimpl
from rols.plugins import _rope_utils

log = logging.getLogger(__name__)


@hookimpl
def rols_hover(config, workspace, document, position):
    signature_config = config.settings().get("signature", {})

    project = _rope_utils.get_project(config, workspace, document)
    if project is None:
        return {"contents": ""}

    resource = _rope_utils.get_resource(project, document)
    offset = document.offset_at_position(position)

    try:
        fixer = fixsyntax.FixSyntax(project, document.source, resource, maxfixes=3)
        pyname = fixer.pyname_at(offset)
    except Exception as e:
        log.debug("Failed to resolve Rope name for hover: %s", e)
        return {"contents": ""}

    if pyname is None:
        return {"contents": ""}

    try:
        pyobject = pyname.get_object()
        docstring = pyobject.get_doc() or ""
    except Exception as e:
        log.debug("Failed to get Rope docstring for hover: %s", e)
        docstring = ""

    try:
        signature = get_calltip(
            project, document.source, offset, resource, maxfixes=3, remove_self=True
        )
    except Exception as e:
        log.debug("Failed to get Rope calltip for hover: %s", e)
        signature = None

    hover_capabilities = config.capabilities.get("textDocument", {}).get("hover", {})
    supported_markup_kinds = hover_capabilities.get("contentFormat", ["markdown"])
    preferred_markup_kind = _utils.choose_markup_kind(supported_markup_kinds)

    include_docstring = signature_config.get("include_docstring", True)
    if not include_docstring:
        if signature:
            docstring = ""
        else:
            docstring = docstring.strip().split("\n")[0].strip()

    if not signature and not docstring:
        return {"contents": ""}

    return {
        "contents": _utils.format_docstring(
            docstring,
            preferred_markup_kind,
            signatures=[signature] if signature else None,
            signature_config=signature_config,
        )
    }
