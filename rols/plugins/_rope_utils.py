# Copyright 2024- Python Language Server Contributors.

"""Shared helpers for the Rope-based language features.

These utilities centralise the boilerplate needed to talk to Rope from the
individual plugins: building a project, resolving the on-disk resource for a
document (falling back gracefully for in-memory documents such as notebook
cells) and translating between Rope's character offsets and LSP positions.
"""

import logging

from rols import uris

log = logging.getLogger(__name__)


def get_project(config, workspace, document):
    """Build the Rope project for the given document.

    Returns ``None`` if the project cannot be built.
    """
    rope_config = config.settings(document_path=document.path).get("rope", {})
    try:
        return workspace._rope_project_builder(rope_config)
    except Exception as e:  # pragma: no cover - defensive
        log.debug("Failed to build Rope project: %s", e)
        return None


def get_resource(project, document):
    """Resolve the Rope resource backing ``document`` within ``project``.

    In-memory-only documents (notebook cells, transient temp documents) or
    documents that live outside the project root have no usable on-disk
    resource; ``None`` is returned in that case so callers can fall back to a
    source-only request.
    """
    if project is None:
        return None

    from rope.base import libutils

    try:
        resource = libutils.path_to_resource(project, document.path)
    except Exception:
        return None

    if resource is None or not resource.exists():
        return None

    # Only use the on-disk resource when its contents match the in-memory
    # document. Rope resolves same-module definitions/occurrences from the
    # resource on disk, so a stale buffer (unsaved edits, or a transient test
    # document whose path points elsewhere) would yield mismatched offsets.
    # Falling back to ``None`` keeps Rope working from the provided source.
    try:
        if resource.read() != document.source:
            return None
    except Exception:
        return None

    return resource


def offset_to_position(source, offset):
    """Convert a 0-based character offset in ``source`` to an LSP position."""
    line = source.count("\n", 0, offset)
    last_newline = source.rfind("\n", 0, offset)
    character = offset - (last_newline + 1)
    return {"line": line, "character": character}


def region_to_range(source, start, end):
    """Convert a ``(start, end)`` offset region to an LSP range."""
    return {
        "start": offset_to_position(source, start),
        "end": offset_to_position(source, end),
    }


def resource_source(resource, document):
    """Return the source code for ``resource``.

    Falls back to the document source when the resource is ``None`` (i.e. the
    location lives in the current in-memory module) or cannot be read.
    """
    if resource is None:
        return document.source
    try:
        return resource.read()
    except Exception:
        return document.source


def resource_uri(resource, document):
    """Return the document URI for ``resource``.

    Falls back to the current document URI for in-memory resources.
    """
    if resource is None:
        return document.uri
    try:
        return uris.from_fs_path(resource.real_path)
    except Exception:
        return document.uri
