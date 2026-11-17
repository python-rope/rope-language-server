# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021-2025 Python Language Server Contributors.
# Copyright 2026- Rope Language Server Contributors.
# Parts adapted from pylsp-rope (https://github.com/python-rope/pylsp-rope),
# Copyright (c) 2021 Lie Ryan, MIT licence; see LICENSES/pylsp-rope.txt.

"""Let Rope see the editor's unsaved buffers.

Rope reads every module through ``project.fscommands.read()``. The
:class:`WorkspaceFileCommands` wrapper returns the text of a document that
is open in the workspace and falls back to the file on disk otherwise.
"""

import logging
import os

from rope.base import fscommands

log = logging.getLogger(__name__)


def path_key(path):
    """Return a key that identifies ``path`` regardless of spelling."""
    try:
        path = os.path.realpath(path)
    except (OSError, ValueError):
        pass
    return os.path.normcase(os.path.normpath(path))


def encode_source(source):
    """Encode ``source`` the way Rope expects to find it on disk.

    Rope decodes file data using any PEP 263 coding declaration, so the text
    must be encoded with that declaration too. An unknown declaration would
    raise ``LookupError`` (python-rope/rope#83); use UTF-8 instead.
    """
    try:
        return fscommands.unicode_to_file_data(source)
    except (LookupError, UnicodeError):
        return source.encode("utf-8", errors="surrogatepass")


class WorkspaceFileCommands:
    """Rope fscommands that serve open documents instead of the disk.

    Every other operation is delegated to the fscommands Rope would have
    chosen for the project root, so version-control aware moves keep working
    if anything ever writes through Rope.
    """

    def __init__(self, workspace, root):
        self._workspace = workspace
        self._delegate = fscommands.create_fscommands(root)

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    def create_file(self, path):
        return self._delegate.create_file(path)

    def create_folder(self, path):
        return self._delegate.create_folder(path)

    def move(self, path, new_location):
        return self._delegate.move(path, new_location)

    def remove(self, path):
        return self._delegate.remove(path)

    def write(self, path, data):
        return self._delegate.write(path, data)

    def read(self, path):
        source = self._workspace._rope_overlay_source(path)
        if source is None:
            read = getattr(self._delegate, "read", None)
            if read is not None:
                return read(path)
            with open(path, "rb") as handle:
                return handle.read()
        return encode_source(source)
