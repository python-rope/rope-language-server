# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.
# Copyright 2024- Python Language Server Contributors (Rope backend).

import logging
import re

from rope.contrib import fixsyntax
from rope.contrib.codeassist import get_calltip

from rols import _utils, hookimpl
from rols.plugins import _rope_utils

log = logging.getLogger(__name__)

SPHINX = re.compile(r"\s*:param\s+(?P<param>\w+):\s*(?P<doc>[^\n]+)")
EPYDOC = re.compile(r"\s*@param\s+(?P<param>\w+):\s*(?P<doc>[^\n]+)")
GOOGLE = re.compile(r"\s*(?P<param>\w+).*:\s*(?P<doc>[^\n]+)")

DOC_REGEX = [SPHINX, EPYDOC, GOOGLE]


@hookimpl
def rols_signature_help(config, workspace, document, position):
    signature_config = config.settings().get("signature", {})

    project = _rope_utils.get_project(config, workspace, document)
    if project is None:
        return {"signatures": []}

    resource = _rope_utils.get_resource(project, document)
    source = document.source
    offset = document.offset_at_position(position)

    # Rope wants the offset on the function being called, not inside (or after)
    # the open parenthesis. Walk back to the opening paren of the current call.
    function_offset = _find_call_offset(source, offset)
    if function_offset is None:
        return {"signatures": []}

    try:
        calltip = get_calltip(
            project,
            source,
            function_offset,
            resource,
            maxfixes=3,
            remove_self=True,
        )
    except Exception as e:
        log.debug("Failed to get Rope calltip for signature help: %s", e)
        return {"signatures": []}

    if not calltip:
        return {"signatures": []}

    try:
        fixer = fixsyntax.FixSyntax(project, source, resource, maxfixes=3)
        pyname = fixer.pyname_at(function_offset)
        docstring = pyname.get_object().get_doc() or "" if pyname else ""
    except Exception as e:
        log.debug("Failed to get Rope docstring for signature help: %s", e)
        docstring = ""

    signature_capabilities = config.capabilities.get("textDocument", {}).get(
        "signatureHelp", {}
    )
    signature_information_support = signature_capabilities.get(
        "signatureInformation", {}
    )
    supported_markup_kinds = signature_information_support.get(
        "documentationFormat", ["markdown"]
    )
    preferred_markup_kind = _utils.choose_markup_kind(supported_markup_kinds)

    param_names = _param_names(calltip)

    signature_docstring = docstring
    if not signature_config.get("include_docstring", True):
        signature_docstring = ""

    sig = {
        "label": calltip,
        "documentation": _utils.format_docstring(
            signature_docstring, markup_kind=preferred_markup_kind
        ),
    }

    if param_names:
        sig["parameters"] = [
            {
                "label": name,
                "documentation": _utils.format_docstring(
                    _param_docs(docstring, name), markup_kind=preferred_markup_kind
                ),
            }
            for name in param_names
        ]

    # We only return a single signature because Python doesn't allow overloading
    sig_info = {"signatures": [sig], "activeSignature": 0}

    active_parameter = _active_parameter(source, offset)
    if param_names and active_parameter is not None:
        sig_info["activeParameter"] = min(active_parameter, len(param_names) - 1)

    return sig_info


def _find_call_offset(source, offset):
    """Return an offset positioned on the function of the enclosing call.

    Walks backwards from ``offset`` to find the opening parenthesis of the
    current call expression, then points just before it (Rope expects the
    offset to fall on the function name, not after its open paren).
    """
    depth = 0
    i = offset - 1
    while i >= 0:
        char = source[i]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth == 0:
                return i - 1 if i > 0 else None
            depth -= 1
        i -= 1
    return None


def _active_parameter(source, offset):
    """Count the comma-separated argument index at ``offset`` within a call."""
    depth = 0
    commas = 0
    i = offset - 1
    while i >= 0:
        char = source[i]
        if char in ")]}":
            depth += 1
        elif char in "([{":
            if depth == 0:
                return commas
            depth -= 1
        elif char == "," and depth == 0:
            commas += 1
        i -= 1
    return None


def _param_names(calltip):
    """Extract parameter names from a Rope calltip string."""
    start = calltip.find("(")
    end = calltip.rfind(")")
    if start == -1 or end == -1 or end <= start + 1:
        return []
    params = []
    for part in calltip[start + 1 : end].split(","):
        name = part.strip().split("=")[0].split(":")[0].strip()
        name = name.lstrip("*")
        if name:
            params.append(name)
    return params


def _param_docs(docstring, param_name):
    for line in docstring.splitlines():
        for regex in DOC_REGEX:
            m = regex.match(line)
            if not m:
                continue
            if m.group("param") != param_name:
                continue
            return m.group("doc") or ""
