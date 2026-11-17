# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021-2025 Python Language Server Contributors.
# Copyright 2026- Rope Language Server Contributors.
# Adapted from pylsp-rope (https://github.com/python-rope/pylsp-rope),
# Copyright (c) 2021 Lie Ryan, MIT licence; see LICENSES/pylsp-rope.txt.

"""Rope refactorings offered as code actions.

The actions themselves are in :mod:`.actions`. This module answers
``textDocument/codeAction`` and turns an action the user picked into a
workspace edit, either in ``codeAction/resolve`` or, for clients that can't
resolve edits, in ``workspace/executeCommand`` followed by
``workspace/applyEdit``. Rope never writes to the disk; every change goes
back to the client.
"""

import ast
import hashlib
import keyword
import logging
import os
import threading

from pylsp_jsonrpc.exceptions import JsonRpcException
from rope.base.exceptions import RefactoringError

from rols import _utils, hookimpl, lsp
from rols.endpoint import check_request_cancelled
from rols.plugins import _rope_edits, _rope_utils
from rols.plugins._rope_task_handle import PylspTaskHandle
from rols.workspace import Document

from .actions import ACTIONS, BY_COMMAND, TRIGGER_AUTOMATIC, Request, point_for_range

log = logging.getLogger(__name__)

PLUGIN = "rope_refactor"


class StaleRequest(Exception):
    """The document changed after the code action was offered."""


@hookimpl
def rols_settings():
    return {"plugins": {PLUGIN: {"enabled": True, "disabled_actions": []}}}


@hookimpl
def rols_commands(config, workspace):
    return [action.command for action in ACTIONS]


def _digest(source):
    data = source.encode("utf-8", errors="surrogatepass")
    return hashlib.sha1(data, usedforsecurity=False).hexdigest()[:16]


def _client_resolves_edits(config):
    properties = (
        config.capabilities.get("textDocument", {})
        .get("codeAction", {})
        .get("resolveSupport", {})
        .get("properties", [])
    )
    return "edit" in properties


def _target(config, workspace, document):
    """Return ``(project, resource, text)`` if Rope can refactor ``document``.

    Rope needs a Python module inside the project folder that exists on
    disk; notebook cells and unsaved new files have none. ``text`` is the
    module as Rope reads it through the workspace overlay.
    """
    if type(document) is not Document:
        return None
    project = _rope_utils.get_project(config, workspace, document)
    if project is None:
        return None
    try:
        resource = _rope_utils.path_to_resource(project, document.path)
        if (
            resource is None
            or resource.project is not project
            or not resource.exists()
            or resource.is_folder()
            or not project.pycore.is_python_file(resource)
        ):
            return None
        text = resource.read()
    except Exception:
        log.debug("Rope cannot read %s", document.path, exc_info=True)
        return None
    if text != _rope_utils.normalize_newlines(document.source):
        return None
    return project, resource, text


@hookimpl
def rols_code_actions(config, workspace, document, range, context):
    settings = config.plugin_settings(PLUGIN, document_path=document.path)
    disabled = set(settings.get("disabled_actions") or [])
    context = context or {}
    only = context.get("only")

    target = _target(config, workspace, document)
    if target is None:
        return []
    project, resource, text = target
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []

    source = document.source
    start = _rope_utils.position_to_offset(source, range["start"])
    end = _rope_utils.position_to_offset(source, range["end"])
    start, end = min(start, end), max(start, end)
    request = Request(
        project=project,
        resource=resource,
        text=text,
        tree=tree,
        start=start,
        end=end,
        point=point_for_range(text, start, end),
        automatic=context.get("triggerKind") == TRIGGER_AUTOMATIC,
        only=only,
        diagnostics=context.get("diagnostics") or [],
        filename=os.path.basename(document.path),
    )
    base = {
        "document_uri": document.uri,
        "version": document.version,
        "digest": _digest(source),
    }
    resolve = _client_resolves_edits(config)
    document_changes = _rope_edits.supports_document_changes(config)

    code_actions = []
    for action in ACTIONS:
        if action.id in disabled:
            continue
        if only and not _utils.code_action_kind_matches(action.kind, only):
            continue
        try:
            offers = action.offers(request)
        except Exception:
            log.debug("Could not offer %s", action.id, exc_info=True)
            continue
        for offer in offers:
            code_action = {"title": offer.title, "kind": offer.kind}
            if offer.diagnostics:
                code_action["diagnostics"] = offer.diagnostics
            arguments = dict(base, title=offer.title, **offer.params)
            # An edit computed now is only safe if the client checks the
            # document version before applying it, except for organising
            # imports, which editors request just before saving.
            if offer.changes is not None and (
                document_changes or action.id == "organize_imports"
            ):
                try:
                    edit = _rope_edits.changeset_to_workspace_edit(
                        workspace,
                        offer.changes,
                        document_changes=document_changes,
                        first_uri=document.uri,
                    )
                except Exception:
                    log.debug("Could not convert %s", offer.title, exc_info=True)
                    continue
                if edit is None:
                    continue
                code_action["edit"] = edit
            elif resolve:
                code_action["data"] = dict(arguments, command=action.command)
            else:
                code_action["command"] = {
                    "title": offer.title,
                    "command": action.command,
                    "arguments": [arguments],
                }
            code_actions.append(code_action)
    return code_actions


_PARAMETERS = {
    "offset": int,
    "start": int,
    "end": int,
    "similar": bool,
    "global_": bool,
    "whole_project": bool,
    "local": bool,
}
_NAMES = ("name", "classname", "parameter")
_CHOICES = {
    "inline_kind": ("method", "variable", "parameter"),
    "generate_kind": ("variable", "function", "class"),
}


def _parameters(arguments, text):
    """Check the arguments a client sent back, and return them."""
    if not isinstance(arguments, dict):
        raise RefactoringError("The command needs a dict of arguments.")
    if not isinstance(arguments.get("digest"), str):
        raise RefactoringError("The command arguments have no document digest.")
    for key, value in arguments.items():
        expected = _PARAMETERS.get(key)
        if expected is not None:
            if type(value) is not expected:
                raise RefactoringError(f"Invalid {key!r} argument.")
            if expected is int and not 0 <= value <= len(text):
                raise RefactoringError(f"Argument {key!r} is out of range.")
        elif key in _NAMES:
            if (
                not isinstance(value, str)
                or not value.isidentifier()
                or keyword.iskeyword(value)
            ):
                raise RefactoringError(f"Invalid {key!r} argument.")
        elif key in _CHOICES and value not in _CHOICES[key]:
            raise RefactoringError(f"Invalid {key!r} argument.")
        elif key == "title" and not isinstance(value, str):
            raise RefactoringError("Invalid 'title' argument.")
    return arguments


def _check_modules_parse(project, name):
    """Refuse to change a name that a module Rope can't parse may use.

    The workspace project ignores syntax errors, so Rope would silently skip
    such a module and leave it using the old name (python-rope/rope#923).
    """
    for resource in project.get_python_files():
        try:
            source = resource.read()
        except Exception:
            continue
        if name not in source:
            continue
        try:
            ast.parse(source)
        except (SyntaxError, ValueError) as exc:
            line = getattr(exc, "lineno", None)
            where = f" on line {line}" if line else ""
            raise RefactoringError(
                f"{resource.path} has a syntax error{where} and may use "
                f"'{name}'. Fix it first, because Rope would skip that module."
            ) from exc


def _end_progress(task_handle):
    for job_set in task_handle.job_sets:
        report_iter = getattr(job_set, "_report_iter", None)
        if report_iter is not None:
            job_set._report_iter = None
            try:
                report_iter.__exit__(None, None, None)
            except Exception:
                log.debug("Could not end progress report", exc_info=True)


def _compute_edit(config, workspace, document, command, arguments):
    """Return the workspace edit for a code action the user picked."""
    action = BY_COMMAND[command]
    if not isinstance(arguments, dict):
        raise RefactoringError("The command needs a dict of arguments.")
    if document is None or arguments.get("document_uri") != document.uri:
        raise RefactoringError("The command doesn't name a document.")
    if not isinstance(arguments.get("digest"), str):
        raise RefactoringError("The command arguments have no document digest.")
    if _digest(document.source) != arguments["digest"]:
        raise StaleRequest(
            "The document has changed since the action was offered. "
            "Request the code action again."
        )
    target = _target(config, workspace, document)
    if target is None:
        raise RefactoringError("Rope cannot refactor this document.")
    project, resource, text = target
    params = _parameters(arguments, text)

    if action.is_cross_file(params):
        for name in action.names_used_elsewhere(params):
            _check_modules_parse(project, name)

    # Let Rope finish on the document-owning thread, then discard a cancelled
    # request's result. Its task handle deliberately never interrupts the work.
    task_handle = PylspTaskHandle(workspace, threading.Event())
    try:
        changes = action.changes(project, resource, params, task_handle)
    finally:
        _end_progress(task_handle)
    if changes is None:
        return None
    return _rope_edits.changeset_to_workspace_edit(
        workspace,
        changes,
        document_changes=_rope_edits.supports_document_changes(config),
        first_uri=document.uri,
    )


def _report_applied(workspace, title):
    def done(future):
        try:
            result = future.result()
        except Exception as exc:
            log.warning("Applying %r failed: %s", title, exc)
            return
        if isinstance(result, dict) and result.get("applied") is False:
            reason = result.get("failureReason") or "the client rejected the edit"
            workspace.show_message(
                f"Rope: could not apply {title!r}: {reason}",
                msg_type=lsp.MessageType.Warning,
            )

    return done


@hookimpl
def rols_execute_command(config, workspace, document, command, arguments):
    if command not in BY_COMMAND:
        return None
    first = arguments[0] if arguments else None
    try:
        edit = _compute_edit(config, workspace, document, command, first)
    except StaleRequest as exc:
        workspace.show_message(str(exc), msg_type=lsp.MessageType.Warning)
        return None
    except RefactoringError as exc:
        workspace.show_message(f"Rope: {exc}", msg_type=lsp.MessageType.Error)
        return None
    except Exception as exc:
        log.exception("Rope refactoring %s failed", command)
        workspace.show_message(f"Rope: {exc}", msg_type=lsp.MessageType.Error)
        return None
    check_request_cancelled()
    if edit is None:
        workspace.show_message(
            "Rope: nothing to change.", msg_type=lsp.MessageType.Info
        )
        return None
    title = first.get("title") if isinstance(first.get("title"), str) else command
    future = workspace.apply_edit(edit, label=title)
    if future is not None and hasattr(future, "add_done_callback"):
        future.add_done_callback(_report_applied(workspace, title))
    return None


@hookimpl
def rols_code_action_resolve(config, workspace, document, code_action):
    data = code_action.get("data")
    if not isinstance(data, dict) or data.get("command") not in BY_COMMAND:
        return None
    try:
        edit = _compute_edit(config, workspace, document, data["command"], data)
    except StaleRequest as exc:
        raise JsonRpcException(str(exc), code=lsp.ErrorCodes.ContentModified) from exc
    except Exception as exc:
        if not isinstance(exc, RefactoringError):
            log.exception("Rope refactoring %s failed", data["command"])
        raise JsonRpcException(
            f"Rope: {exc}", code=lsp.ErrorCodes.RequestFailed
        ) from exc
    check_request_cancelled()
    if edit is None:
        raise JsonRpcException(
            "Rope: nothing to change.", code=lsp.ErrorCodes.RequestFailed
        )
    resolved = dict(code_action)
    resolved["edit"] = edit
    return resolved
