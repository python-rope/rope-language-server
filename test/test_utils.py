# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

import multiprocessing
import os
import sys
import threading
import time
from threading import Thread
from typing import Any
from unittest import mock

from docstring_to_markdown import UnknownFormatError
from flaky import flaky

from rols import _utils
from rols.lsp import NotebookCellKind
from rols.python_lsp import RopeLanguageServer, start_io_lang_server

CALL_TIMEOUT_IN_SECONDS = 120


def send_notebook_did_open(client, cells: list[str]) -> None:
    """
    Sends a notebookDocument/didOpen notification with the given python cells.

    The notebook has the uri "notebook_uri" and the cells have the uris
    "cell_1_uri", "cell_2_uri", etc.
    """
    client._endpoint.notify(
        "notebookDocument/didOpen", notebook_with_python_cells(cells)
    )


def notebook_with_python_cells(cells: list[str]):
    """
    Create a notebook document with the given python cells.

    The notebook has the uri "notebook_uri" and the cells have the uris
    "cell_1_uri", "cell_2_uri", etc.
    """
    return {
        "notebookDocument": {
            "uri": "notebook_uri",
            "notebookType": "jupyter-notebook",
            "cells": [
                {
                    "kind": NotebookCellKind.Code,
                    "document": f"cell_{i + 1}_uri",
                }
                for i in range(len(cells))
            ],
        },
        "cellTextDocuments": [
            {
                "uri": f"cell_{i + 1}_uri",
                "languageId": "python",
                "text": cell,
            }
            for i, cell in enumerate(cells)
        ],
    }


def send_initialize_request(client, initialization_options: dict[str, Any] = None):
    return client._endpoint.request(
        "initialize",
        {
            "processId": 1234,
            "rootPath": os.path.dirname(__file__),
            "initializationOptions": initialization_options,
        },
    ).result(timeout=CALL_TIMEOUT_IN_SECONDS)


def start(obj) -> None:
    obj.start()


def apply_text_edits(text, edits):
    """Apply LSP text edits the way an editor does."""
    lines = text.splitlines(True)

    def offset(position):
        if position["line"] >= len(lines):
            return len(text)
        line = lines[position["line"]]
        prefix = line.encode("utf-16-le")[: 2 * position["character"]]
        column = len(prefix.decode("utf-16-le", errors="ignore"))
        return sum(len(line) for line in lines[: position["line"]]) + column

    for edit in sorted(
        edits,
        key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]),
        reverse=True,
    ):
        start = offset(edit["range"]["start"])
        end = offset(edit["range"]["end"])
        text = text[:start] + edit["newText"] + text[end:]
    return text


def apply_workspace_edit(texts, edit):
    """Apply a WorkspaceEdit to ``texts``, a dict of URI to text."""
    texts = dict(texts)
    if "documentChanges" in edit:
        for change in edit["documentChanges"]:
            uri = change["textDocument"]["uri"]
            texts[uri] = apply_text_edits(texts[uri], change["edits"])
    else:
        for uri, edits in edit["changes"].items():
            texts[uri] = apply_text_edits(texts[uri], edits)
    return texts


class RecordingClient(RopeLanguageServer):
    """A fake editor that records the requests the server sends to it.

    It accepts every ``workspace/applyEdit`` request with ``apply_result``.
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.apply_result = {"applied": True}
        self.applied_edits = []
        self.edit_applied = threading.Event()
        self.messages = []
        self.message_shown = threading.Event()

    def m_workspace__apply_edit(self, edit=None, label=None, **_kwargs):
        self.applied_edits.append({"edit": edit, "label": label})
        self.edit_applied.set()
        return self.apply_result

    def m_window__show_message(self, type=None, message=None, **_kwargs):
        self.messages.append({"type": type, "message": message})
        self.message_shown.set()

    def m_window__log_message(self, **_kwargs):
        pass

    def m_window__work_done_progress__create(self, **_kwargs):
        return None

    def m_text_document__publish_diagnostics(self, **_kwargs):
        pass


class ClientServerPair:
    """
    A class to setup a client/server pair.

    args:
        start_server_in_process: if True, the server will be started in a process.
        check_parent_process: if True, the server_process will check if the parent process is alive.
    """

    def __init__(
        self,
        start_server_in_process=False,
        check_parent_process=False,
        client_cls=RopeLanguageServer,
    ) -> None:
        # Client to Server pipe
        csr, csw = os.pipe()
        # Server to client pipe
        scr, scw = os.pipe()

        if start_server_in_process:
            ParallelKind = self._get_parallel_kind()
            self.server_process = ParallelKind(
                target=start_io_lang_server,
                args=(
                    os.fdopen(csr, "rb"),
                    os.fdopen(scw, "wb"),
                    check_parent_process,
                    RopeLanguageServer,
                ),
            )
            self.server_process.start()
        else:
            self.server = RopeLanguageServer(os.fdopen(csr, "rb"), os.fdopen(scw, "wb"))
            self.server_thread = Thread(target=start, args=[self.server])
            self.server_thread.start()

        self.client = client_cls(os.fdopen(scr, "rb"), os.fdopen(csw, "wb"))
        self.client_thread = Thread(target=start, args=[self.client])
        self.client_thread.start()

    def _get_parallel_kind(self):
        if os.name == "nt":
            return Thread

        if sys.version_info[:2] >= (3, 8):
            return multiprocessing.get_context("fork").Process

        return multiprocessing.Process


@flaky(max_runs=6, min_passes=1)
def test_debounce() -> None:
    interval = 0.1
    obj = mock.Mock()

    @_utils.debounce(0.1)
    def call_m():
        obj()

    assert not obj.mock_calls

    call_m()
    call_m()
    call_m()
    assert not obj.mock_calls

    time.sleep(interval * 2)
    assert len(obj.mock_calls) == 1

    call_m()
    time.sleep(interval * 2)
    assert len(obj.mock_calls) == 2


@flaky(max_runs=6, min_passes=1)
def test_debounce_keyed_by() -> None:
    interval = 0.1
    obj = mock.Mock()

    @_utils.debounce(0.1, keyed_by="key")
    def call_m(key):
        obj(key)

    assert not obj.mock_calls

    call_m(1)
    call_m(2)
    call_m(3)
    assert not obj.mock_calls

    time.sleep(interval * 2)
    obj.assert_has_calls(
        [
            mock.call(1),
            mock.call(2),
            mock.call(3),
        ],
        any_order=True,
    )
    assert len(obj.mock_calls) == 3

    call_m(1)
    call_m(1)
    call_m(1)
    time.sleep(interval * 2)
    assert len(obj.mock_calls) == 4


def test_list_to_string() -> None:
    assert _utils.list_to_string("string") == "string"
    assert _utils.list_to_string(["a", "r", "r", "a", "y"]) == "a,r,r,a,y"


def test_find_parents(tmpdir) -> None:
    subsubdir = tmpdir.ensure_dir("subdir", "subsubdir")
    path = subsubdir.ensure("path.py")
    test_cfg = tmpdir.ensure("test.cfg")

    assert _utils.find_parents(tmpdir.strpath, path.strpath, ["test.cfg"]) == [
        test_cfg.strpath
    ]


def test_find_parents_cross_mount(tmpdir, monkeypatch) -> None:
    """find_parents returns [] when root and path are on different mounts (Windows UNC)."""
    import unittest.mock as mock

    subsubdir = tmpdir.ensure_dir("subdir", "subsubdir")
    path = subsubdir.ensure("path.py")

    with mock.patch(
        "os.path.relpath",
        side_effect=ValueError(
            "path is on mount 'C:', start on mount '\\\\unc\\share'"
        ),
    ):
        result = _utils.find_parents(tmpdir.strpath, path.strpath, ["test.cfg"])

    assert result == []


def test_merge_dicts() -> None:
    assert _utils.merge_dicts(
        {"a": True, "b": {"x": 123, "y": {"hello": "world"}}},
        {"a": False, "b": {"y": [], "z": 987}},
    ) == {"a": False, "b": {"x": 123, "y": [], "z": 987}}


def test_clip_column() -> None:
    assert _utils.clip_column(0, [], 0) == 0
    assert _utils.clip_column(2, ["123"], 0) == 2
    assert _utils.clip_column(3, ["123"], 0) == 3
    assert _utils.clip_column(5, ["123"], 0) == 3
    assert _utils.clip_column(0, ["\n", "123"], 0) == 0
    assert _utils.clip_column(1, ["\n", "123"], 0) == 0
    assert _utils.clip_column(2, ["123\n", "123"], 0) == 2
    assert _utils.clip_column(3, ["123\n", "123"], 0) == 3
    assert _utils.clip_column(4, ["123\n", "123"], 1) == 3


def test_signature_formatter_uses_black() -> None:
    assert set(_utils.formatters) == {"black", "ruff"}
    assert _utils.convert_signatures_to_markdown(
        ["example(value:int=1)->str"], {}
    ) == _utils.wrap_signature("example(value: int = 1) -> str")


def test_signature_formatter_skips_dotted_calltips() -> None:
    formatter = _utils.formatters["black"]
    with (
        mock.patch.object(
            type(formatter), "is_installed", new_callable=mock.PropertyMock
        ) as installed,
        mock.patch.object(formatter, "format") as format_code,
    ):
        installed.return_value = True
        assert _utils.format_signature("platform.system()", {}, "black") == (
            "platform.system()"
        )
        format_code.assert_not_called()


def test_signature_formatter_uses_ruff() -> None:
    formatter = _utils.formatters["ruff"]
    assert formatter.command == ["ruff", "format"]
    with (
        mock.patch.object(
            type(formatter), "is_installed", new_callable=mock.PropertyMock
        ) as installed,
        mock.patch.object(formatter, "format") as format_code,
    ):
        installed.return_value = True
        format_code.return_value = "def example(value: int = 1) -> str:\n    pass"
        assert _utils.convert_signatures_to_markdown(
            ["example(value:int=1)->str"], {"formatter": "ruff", "line_length": 100}
        ) == _utils.wrap_signature("example(value: int = 1) -> str")
        format_code.assert_called_once_with(
            "def example(value:int=1)->str:\n    pass", line_length=100
        )


def test_signature_formatter_can_be_disabled() -> None:
    signature = "example(value:int=1)->str"
    assert _utils.convert_signatures_to_markdown(
        [signature], {"formatter": None}
    ) == _utils.wrap_signature(signature)


@mock.patch("docstring_to_markdown.convert")
def test_format_docstring_valid_rst_signature(mock_convert) -> None:
    """Test that a valid RST docstring includes the function signature."""
    docstring = """A function docstring.

    Parameters
    ----------
    a : str, something
    """

    # Mock the return value to avoid depedency on the real thing
    mock_convert.return_value = """A function docstring.

    #### Parameters

    - `a`: str, something
    """

    markdown = _utils.format_docstring(
        docstring,
        "markdown",
        ["something(a: str) -> str"],
    )["value"]

    assert markdown.startswith(
        _utils.wrap_signature("something(a: str) -> str"),
    )


@mock.patch("docstring_to_markdown.convert", side_effect=UnknownFormatError)
def test_format_docstring_invalid_rst_signature(_) -> None:
    """Test that an invalid RST docstring includes the function signature."""
    docstring = """A function docstring.

    Parameters
    ----------
    a : str, something
    """

    markdown = _utils.format_docstring(
        docstring,
        "markdown",
        ["something(a: str) -> str"],
    )["value"]

    assert markdown.startswith(
        _utils.wrap_signature("something(a: str) -> str"),
    )
