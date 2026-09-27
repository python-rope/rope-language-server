# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

import os
import sys
import time

import pytest
from flaky import flaky
from pylsp_jsonrpc.exceptions import JsonRpcMethodNotFound

from test.test_utils import ClientServerPair, send_initialize_request

RUNNING_IN_CI = bool(os.environ.get("CI"))

CALL_TIMEOUT_IN_SECONDS = 10


@pytest.fixture
def client_exited_server() -> None:
    """A fixture that sets up a client/server pair that support checking parent process aliveness
    and assert the server has already exited
    """
    client_server_pair_obj = ClientServerPair(True, True)

    yield client_server_pair_obj

    assert client_server_pair_obj.server_process.is_alive() is False


@flaky(max_runs=10, min_passes=1)
@pytest.mark.skipif(sys.platform == "darwin", reason="Too flaky on Mac")
def test_initialize(client_server_pair) -> None:
    client, _ = client_server_pair
    response = client._endpoint.request(
        "initialize",
        {"rootPath": os.path.dirname(__file__), "initializationOptions": {}},
    ).result(timeout=CALL_TIMEOUT_IN_SECONDS)
    assert "capabilities" in response


@flaky(max_runs=10, min_passes=1)
@pytest.mark.skipif(
    not sys.platform.startswith("Linux"), reason="Skipped on win and flaky on mac"
)
def test_exit_with_parent_process_died(
    client_exited_server,
) -> None:
    # language server should have already exited before responding
    lsp_server, mock_process = (
        client_exited_server.client,
        client_exited_server.server_process,
    )
    # with pytest.raises(Exception):
    lsp_server._endpoint.request(
        "initialize",
        {
            "processId": mock_process.pid,
            "rootPath": os.path.dirname(__file__),
            "initializationOptions": {},
        },
    ).result(timeout=CALL_TIMEOUT_IN_SECONDS)

    mock_process.terminate()
    time.sleep(CALL_TIMEOUT_IN_SECONDS)
    assert not client_exited_server.client_thread.is_alive()


@flaky(max_runs=10, min_passes=1)
@pytest.mark.skipif(sys.platform.startswith("linux"), reason="Fails on linux")
def test_not_exit_without_check_parent_process_flag(
    client_server_pair,
) -> None:
    client, _ = client_server_pair
    response = send_initialize_request(client)
    assert "capabilities" in response


@flaky(max_runs=10, min_passes=1)
def test_missing_message(client_server_pair) -> None:
    client, _ = client_server_pair
    with pytest.raises(JsonRpcMethodNotFound):
        client._endpoint.request("unknown_method").result(
            timeout=CALL_TIMEOUT_IN_SECONDS
        )


from unittest import mock


def test_server_consume(rols):
    mock_msg = {"jsonrpc": "2.0", "method": "dummy"}
    with mock.patch.object(rols._endpoint, "consume") as mock_consume:
        rols.consume(mock_msg)
        mock_consume.assert_called_once_with(mock_msg)


def test_server_getitem_dispatchers(rols):
    fake_dispatcher = {"custom_method": lambda: "custom_result"}
    rols._dispatchers = [fake_dispatcher]
    assert rols["custom_method"]() == "custom_result"

    with pytest.raises(KeyError):
        _ = rols["non_existent_method"]


def test_server_getitem_after_shutdown(rols):
    rols._shutdown = True
    handler = rols["some_method"]
    res = handler({})
    assert res["error"]["code"] == -32600
    assert "Requests after shutdown are not valid" in res["error"]["message"]


def test_server_hook_without_config(rols):
    rols.config = None
    assert rols._hook("rols_initialize") == []


def test_server_m_initialized(rols):
    with mock.patch.object(rols, "_hook") as mock_hook:
        rols.m_initialized()
        mock_hook.assert_called_once_with("rols_initialized")


def test_server_text_document_methods(rols, doc):
    doc_uri = doc.uri
    # did_open
    rols.m_text_document__did_open(
        textDocument={"uri": doc_uri, "text": doc.source, "version": 1}
    )
    assert doc_uri in rols.workspace.documents

    # did_change
    change_event = {"range": None, "text": "new source text"}
    rols.m_text_document__did_change(
        textDocument={"uri": doc_uri, "version": 2},
        contentChanges=[change_event],
    )
    assert rols.workspace.get_document(doc_uri).source == "new source text"

    # did_save
    with mock.patch.object(rols, "document_did_save") as mock_save:
        rols.m_text_document__did_save(textDocument={"uri": doc_uri})
        mock_save.assert_called_once_with(doc_uri)

    # code_action & code_lens
    with mock.patch.object(rols, "code_actions", return_value=[]) as mock_ca:
        res = rols.m_text_document__code_action(
            textDocument={"uri": doc_uri}, range={}, context={}
        )
        assert res == []
        mock_ca.assert_called_once_with(doc_uri, {}, {})

    with mock.patch.object(rols, "code_lens", return_value=[]) as mock_cl:
        res = rols.m_text_document__code_lens(textDocument={"uri": doc_uri})
        assert res == []
        mock_cl.assert_called_once_with(doc_uri)

    # document_highlight, hover, document_symbol
    with mock.patch.object(rols, "highlight", return_value=[]) as mock_hl:
        rols.m_text_document__document_highlight(
            textDocument={"uri": doc_uri}, position={"line": 0, "character": 0}
        )
        mock_hl.assert_called_once_with(doc_uri, {"line": 0, "character": 0})

    with mock.patch.object(rols, "hover", return_value={"contents": ""}) as mock_h:
        rols.m_text_document__hover(
            textDocument={"uri": doc_uri}, position={"line": 0, "character": 0}
        )
        mock_h.assert_called_once_with(doc_uri, {"line": 0, "character": 0})

    with mock.patch.object(rols, "document_symbols", return_value=[]) as mock_sym:
        rols.m_text_document__document_symbol(textDocument={"uri": doc_uri})
        mock_sym.assert_called_once_with(doc_uri)

    # formatting, range_formatting
    with mock.patch.object(rols, "format_document", return_value=None) as mock_fmt:
        rols.m_text_document__formatting(textDocument={"uri": doc_uri}, options={})
        mock_fmt.assert_called_once_with(doc_uri, {})

    with mock.patch.object(rols, "format_range", return_value=None) as mock_rng_fmt:
        rols.m_text_document__range_formatting(
            textDocument={"uri": doc_uri}, range={}, options={}
        )
        mock_rng_fmt.assert_called_once_with(doc_uri, {}, {})

    # rename, folding_range, signature_help
    with mock.patch.object(rols, "rename", return_value=None) as mock_rn:
        rols.m_text_document__rename(
            textDocument={"uri": doc_uri},
            position={"line": 0, "character": 0},
            newName="bar",
        )
        mock_rn.assert_called_once_with(doc_uri, {"line": 0, "character": 0}, "bar")

    with mock.patch.object(rols, "folding", return_value=[]) as mock_fold:
        rols.m_text_document__folding_range(textDocument={"uri": doc_uri})
        mock_fold.assert_called_once_with(doc_uri)

    with mock.patch.object(rols, "signature_help", return_value=None) as mock_sig:
        rols.m_text_document__signature_help(
            textDocument={"uri": doc_uri}, position={"line": 0, "character": 0}
        )
        mock_sig.assert_called_once_with(doc_uri, {"line": 0, "character": 0})

    # references
    with mock.patch.object(rols, "references", return_value=[]) as mock_refs:
        rols.m_text_document__references(
            textDocument={"uri": doc_uri},
            position={"line": 0, "character": 0},
            context={"includeDeclaration": False},
        )
        mock_refs.assert_called_once_with(doc_uri, {"line": 0, "character": 0}, True)

    # did_close
    rols.m_text_document__did_close(textDocument={"uri": doc_uri})
    assert doc_uri not in rols.workspace.documents


def test_server_workspace_methods(rols):
    # execute_command
    with mock.patch.object(rols, "execute_command", return_value="done") as mock_exec:
        assert rols.m_workspace__execute_command("my_cmd", [1, 2]) == "done"
        mock_exec.assert_called_once_with("my_cmd", [1, 2])

    # did_change_configuration
    with mock.patch.object(rols, "_hook") as mock_hook:
        rols.m_workspace__did_change_configuration({"rols": {"plugins": {}}})
        mock_hook.assert_called_with("rols_workspace_configuration_changed")

    # did_change_watched_files with python files
    with mock.patch.object(rols, "lint"):
        rols.m_workspace__did_change_watched_files(
            changes=[{"uri": "file:///path/to/mod.py", "type": 1}]
        )
        # did_change_watched_files with non-py files
        rols.m_workspace__did_change_watched_files(
            changes=[{"uri": "file:///path/to/other.txt", "type": 1}]
        )
        # did_change_watched_files with config files
        mock_settings = mock.MagicMock()
        with mock.patch.object(rols.config, "settings", mock_settings):
            rols.m_workspace__did_change_watched_files(
                changes=[{"uri": "file:///path/to/.flake8", "type": 1}]
            )
            mock_settings.cache_clear.assert_called_once()


def test_server_helpers():
    from rols.python_lsp import flatten, merge

    assert flatten([[1, 2], [3], []]) == [1, 2, 3]
    assert merge([{"a": 1}, {"b": 2}, {"a": 3}]) == {"a": 3, "b": 2}
