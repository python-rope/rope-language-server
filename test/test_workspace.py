# Copyright 2017 Palantir Technologies, Inc.
import os
import pathlib

import pytest

from rols import uris

DOC_URI = uris.from_fs_path(__file__)
NOTEBOOK_URI = uris.from_fs_path("notebook_uri")


def path_as_uri(path):
    return pathlib.Path(os.path.abspath(path)).as_uri()


def test_local(rols) -> None:
    """Since the workspace points to the test directory"""
    assert rols.workspace.is_local()


def test_put_document(rols) -> None:
    rols.workspace.put_document(DOC_URI, "content")
    assert DOC_URI in rols.workspace._docs


def test_put_notebook_document(rols) -> None:
    rols.workspace.put_notebook_document(DOC_URI, "jupyter-notebook", [])
    assert DOC_URI in rols.workspace._docs


def test_put_cell_document(rols) -> None:
    rols.workspace.put_cell_document(DOC_URI, NOTEBOOK_URI, "python", "content")
    assert DOC_URI in rols.workspace._docs


def test_get_document(rols) -> None:
    rols.workspace.put_document(DOC_URI, "TEXT")
    assert rols.workspace.get_document(DOC_URI).source == "TEXT"


def test_get_missing_document(tmpdir, rols) -> None:
    source = "TEXT"
    doc_path = tmpdir.join("test_document.py")
    doc_path.write(source)
    doc_uri = uris.from_fs_path(str(doc_path))
    assert rols.workspace.get_document(doc_uri).source == "TEXT"


def test_rm_document(rols) -> None:
    rols.workspace.put_document(DOC_URI, "TEXT")
    assert rols.workspace.get_document(DOC_URI).source == "TEXT"
    rols.workspace.rm_document(DOC_URI)
    assert rols.workspace.get_document(DOC_URI)._source is None


@pytest.mark.parametrize(
    "metafiles", [("setup.py",), ("pyproject.toml",), ("setup.py", "pyproject.toml")]
)
def test_non_root_project(rols, metafiles) -> None:
    repo_root = os.path.join(rols.workspace.root_path, "repo-root")
    os.mkdir(repo_root)
    project_root = os.path.join(repo_root, "project-root")
    os.mkdir(project_root)

    for metafile in metafiles:
        with open(os.path.join(project_root, metafile), "w+", encoding="utf-8") as f:
            f.write("# " + metafile)

    test_uri = uris.from_fs_path(os.path.join(project_root, "hello/test.py"))
    rols.workspace.put_document(test_uri, "assert True")
    test_doc = rols.workspace.get_document(test_uri)
    assert project_root in rols.workspace.source_roots(test_doc.path)


def test_root_project_with_no_setup_py(rols) -> None:
    """Default to workspace root."""
    workspace_root = rols.workspace.root_path
    test_uri = uris.from_fs_path(os.path.join(workspace_root, "hello/test.py"))
    rols.workspace.put_document(test_uri, "assert True")
    test_doc = rols.workspace.get_document(test_uri)
    assert workspace_root in rols.workspace.source_roots(test_doc.path)


def test_multiple_workspaces_from_initialize(rols_w_workspace_folders) -> None:
    rols, workspace_folders = rols_w_workspace_folders

    assert len(rols.workspaces) == 2

    folders_uris = [uris.from_fs_path(str(folder)) for folder in workspace_folders]

    for folder_uri in folders_uris:
        assert folder_uri in rols.workspaces

    assert folders_uris[0] == rols.root_uri

    # Create file in the first workspace folder.
    file1 = workspace_folders[0].join("file1.py")
    file1.write("import os")
    msg1 = {"uri": path_as_uri(str(file1)), "version": 1, "text": "import os"}

    rols.m_text_document__did_open(textDocument=msg1)
    assert msg1["uri"] in rols.workspace._docs
    assert msg1["uri"] in rols.workspaces[folders_uris[0]]._docs

    # Create file in the second workspace folder.
    file2 = workspace_folders[1].join("file2.py")
    file2.write("import sys")
    msg2 = {"uri": path_as_uri(str(file2)), "version": 1, "text": "import sys"}

    rols.m_text_document__did_open(textDocument=msg2)
    assert msg2["uri"] not in rols.workspace._docs
    assert msg2["uri"] in rols.workspaces[folders_uris[1]]._docs


def test_multiple_workspaces(tmpdir, rols) -> None:
    workspace1_dir = tmpdir.mkdir("workspace1")
    workspace2_dir = tmpdir.mkdir("workspace2")
    file1 = workspace1_dir.join("file1.py")
    file2 = workspace2_dir.join("file1.py")
    file1.write("import os")
    file2.write("import sys")

    msg = {"uri": path_as_uri(str(file1)), "version": 1, "text": "import os"}

    rols.m_text_document__did_open(textDocument=msg)
    assert msg["uri"] in rols.workspace._docs

    added_workspaces = [
        {"uri": path_as_uri(str(x))} for x in (workspace1_dir, workspace2_dir)
    ]
    event = {"added": added_workspaces, "removed": []}
    rols.m_workspace__did_change_workspace_folders(event)

    for workspace in added_workspaces:
        assert workspace["uri"] in rols.workspaces

    workspace1_uri = added_workspaces[0]["uri"]
    assert msg["uri"] not in rols.workspace._docs
    assert msg["uri"] in rols.workspaces[workspace1_uri]._docs

    msg = {"uri": path_as_uri(str(file2)), "version": 1, "text": "import sys"}
    rols.m_text_document__did_open(textDocument=msg)

    workspace2_uri = added_workspaces[1]["uri"]
    assert msg["uri"] in rols.workspaces[workspace2_uri]._docs

    event = {"added": [], "removed": [added_workspaces[0]]}
    rols.m_workspace__did_change_workspace_folders(event)
    assert workspace1_uri not in rols.workspaces


def test_multiple_workspaces_wrong_removed_uri(rols, tmpdir) -> None:
    workspace = {"uri": str(tmpdir.mkdir("Test123"))}
    event = {"added": [], "removed": [workspace]}
    rols.m_workspace__did_change_workspace_folders(event)
    assert workspace["uri"] not in rols.workspaces


def test_root_workspace_changed(rols, tmpdir) -> None:
    test_uri = str(tmpdir.mkdir("Test123"))
    rols.root_uri = test_uri
    rols.workspace._root_uri = test_uri

    workspace1 = {"uri": test_uri}
    workspace2 = {"uri": str(tmpdir.mkdir("NewTest456"))}

    event = {"added": [workspace2], "removed": [workspace1]}
    rols.m_workspace__did_change_workspace_folders(event)

    assert workspace2["uri"] == rols.workspace._root_uri
    assert workspace2["uri"] == rols.root_uri


def test_root_workspace_not_changed(rols, tmpdir) -> None:
    # removed uri != root_uri
    test_uri_1 = str(tmpdir.mkdir("Test12"))
    rols.root_uri = test_uri_1
    rols.workspace._root_uri = test_uri_1
    workspace1 = {"uri": str(tmpdir.mkdir("Test1234"))}
    workspace2 = {"uri": str(tmpdir.mkdir("NewTest456"))}
    event = {"added": [workspace2], "removed": [workspace1]}
    rols.m_workspace__did_change_workspace_folders(event)
    assert test_uri_1 == rols.workspace._root_uri
    assert test_uri_1 == rols.root_uri
    # empty 'added' list
    test_uri_2 = str(tmpdir.mkdir("Test123"))
    new_root_uri = workspace2["uri"]
    rols.root_uri = test_uri_2
    rols.workspace._root_uri = test_uri_2
    workspace1 = {"uri": test_uri_2}
    event = {"added": [], "removed": [workspace1]}
    rols.m_workspace__did_change_workspace_folders(event)
    assert new_root_uri == rols.workspace._root_uri
    assert new_root_uri == rols.root_uri
    # empty 'removed' list
    event = {"added": [workspace1], "removed": []}
    rols.m_workspace__did_change_workspace_folders(event)
    assert new_root_uri == rols.workspace._root_uri
    assert new_root_uri == rols.root_uri
    # 'added' list has no 'uri'
    workspace2 = {"TESTuri": "Test1234"}
    event = {"added": [workspace2], "removed": [workspace1]}
    rols.m_workspace__did_change_workspace_folders(event)
    assert new_root_uri == rols.workspace._root_uri
    assert new_root_uri == rols.root_uri


def test_root_workspace_removed(tmpdir, rols) -> None:
    workspace1_dir = tmpdir.mkdir("workspace1")
    workspace2_dir = tmpdir.mkdir("workspace2")
    root_uri = rols.root_uri

    # Add workspaces to the rols
    added_workspaces = [
        {"uri": path_as_uri(str(x))} for x in (workspace1_dir, workspace2_dir)
    ]
    event = {"added": added_workspaces, "removed": []}
    rols.m_workspace__did_change_workspace_folders(event)

    # Remove the root workspace
    removed_workspaces = [{"uri": root_uri}]
    event = {"added": [], "removed": removed_workspaces}
    rols.m_workspace__did_change_workspace_folders(event)

    # Assert that the first of the workspaces (in alphabetical order) is now
    # the root workspace
    assert rols.root_uri == path_as_uri(str(workspace1_dir))
    assert rols.workspace._root_uri == path_as_uri(str(workspace1_dir))


@pytest.mark.skipif(os.name == "nt", reason="Fails on Windows")
def test_workspace_loads_pycodestyle_config(rols, tmpdir) -> None:
    workspace1_dir = tmpdir.mkdir("Test123")
    rols.root_uri = str(workspace1_dir)
    rols.workspace._root_uri = str(workspace1_dir)

    # Test that project settings are loaded
    workspace2_dir = tmpdir.mkdir("NewTest456")
    cfg = workspace2_dir.join("pycodestyle.cfg")
    cfg.write("[pycodestyle]\nmax-line-length = 1000")

    workspace1 = {"uri": str(workspace1_dir)}
    workspace2 = {"uri": str(workspace2_dir)}

    event = {"added": [workspace2], "removed": [workspace1]}
    rols.m_workspace__did_change_workspace_folders(event)

    seetings = rols.workspaces[str(workspace2_dir)]._config.settings()
    assert seetings["plugins"]["pycodestyle"]["maxLineLength"] == 1000

    # Test that project settings prevail over server ones.
    server_settings = {"rols": {"plugins": {"pycodestyle": {"maxLineLength": 10}}}}
    rols.m_workspace__did_change_configuration(server_settings)
    assert seetings["plugins"]["pycodestyle"]["maxLineLength"] == 1000

    # Test switching to another workspace with different settings
    workspace3_dir = tmpdir.mkdir("NewTest789")
    cfg1 = workspace3_dir.join("pycodestyle.cfg")
    cfg1.write("[pycodestyle]\nmax-line-length = 20")

    workspace3 = {"uri": str(workspace3_dir)}

    event = {"added": [workspace3], "removed": [workspace2]}
    rols.m_workspace__did_change_workspace_folders(event)

    seetings = rols.workspaces[str(workspace3_dir)]._config.settings()
    assert seetings["plugins"]["pycodestyle"]["maxLineLength"] == 20


def test_settings_of_added_workspace(rols, tmpdir) -> None:
    test_uri = str(tmpdir.mkdir("Test123"))
    rols.root_uri = test_uri
    rols.workspace._root_uri = test_uri

    # Set some settings for the server.
    server_settings = {
        "rols": {"plugins": {"jedi": {"environment": "/usr/bin/python3"}}}
    }
    rols.m_workspace__did_change_configuration(server_settings)

    # Create a new workspace.
    workspace1 = {"uri": str(tmpdir.mkdir("NewTest456"))}
    event = {"added": [workspace1]}
    rols.m_workspace__did_change_workspace_folders(event)

    # Assert settings are inherited from the server config.
    workspace1_object = rols.workspaces[workspace1["uri"]]
    workspace1_jedi_settings = workspace1_object._config.plugin_settings("jedi")
    assert workspace1_jedi_settings == server_settings["rols"]["plugins"]["jedi"]


def test_no_progress_without_capability(workspace, consumer) -> None:
    workspace._config.capabilities["window"] = {"workDoneProgress": False}

    with workspace.report_progress("some_title"):
        pass

    assert len(consumer.call_args_list) == 0


def test_progress_simple(workspace, consumer) -> None:
    workspace._config.capabilities["window"] = {"workDoneProgress": True}

    with workspace.report_progress("some_title"):
        pass

    init_call, *progress_calls = consumer.call_args_list

    assert init_call[0][0]["method"] == "window/workDoneProgress/create"

    # same method for all calls
    assert all(
        call[0][0]["method"] == "$/progress" for call in progress_calls
    ), consumer.call_args_list

    # same token used in all calls
    assert (
        len(
            {call[0][0]["params"]["token"] for call in progress_calls}
            | {init_call[0][0]["params"]["token"]}
        )
        == 1
    )

    assert [call[0][0]["params"]["value"] for call in progress_calls] == [
        {"kind": "begin", "title": "some_title"},
        {"kind": "end"},
    ]


@pytest.mark.parametrize("exc", [Exception("something"), TimeoutError()])
def test_progress_initialization_fails_but_is_skipped(
    workspace, consumer, endpoint, exc
) -> None:
    def failing_token_initialization(self, *_args, **_kwargs):
        raise exc

    endpoint._dispatcher.m_window__work_done_progress__create = (
        failing_token_initialization
    )

    workspace._config.capabilities["window"] = {"workDoneProgress": True}

    with workspace.report_progress("some_title", skip_token_initialization=True):
        pass

    # we only see the failing token initialization call, no other calls
    progress_calls = consumer.call_args_list
    assert all(call[0][0]["method"] == "$/progress" for call in progress_calls)
    assert len({call[0][0]["params"]["token"] for call in progress_calls}) == 1
    assert [call[0][0]["params"]["value"] for call in progress_calls] == [
        {"kind": "begin", "title": "some_title"},
        {"kind": "end"},
    ]


def test_progress_with_percent(workspace, consumer) -> None:
    workspace._config.capabilities["window"] = {"workDoneProgress": True}

    with workspace.report_progress(
        "some_title", "initial message", percentage=1
    ) as progress_message:
        progress_message("ten", 10)
        progress_message("fifty", 50)
        progress_message("ninety", 90)

    init_call, *progress_calls = consumer.call_args_list

    assert init_call[0][0]["method"] == "window/workDoneProgress/create"

    # same method for all progress calls
    assert all(call[0][0]["method"] == "$/progress" for call in progress_calls)

    # same token used in all calls
    assert (
        len(
            {call[0][0]["params"]["token"] for call in progress_calls}
            | {init_call[0][0]["params"]["token"]}
        )
        == 1
    )

    assert [call[0][0]["params"]["value"] for call in progress_calls] == [
        {
            "kind": "begin",
            "message": "initial message",
            "percentage": 1,
            "title": "some_title",
        },
        {"kind": "report", "message": "ten", "percentage": 10},
        {"kind": "report", "message": "fifty", "percentage": 50},
        {"kind": "report", "message": "ninety", "percentage": 90},
        {"kind": "end"},
    ]


def test_progress_with_exception(workspace, consumer) -> None:
    workspace._config.capabilities["window"] = {"workDoneProgress": True}

    class DummyError(Exception):
        pass

    try:
        with workspace.report_progress("some_title"):
            raise DummyError("something")
    except DummyError:
        # we're using a specific exception class here so
        # any other exceptions happening in progress
        # reporting would correctly be raised in the
        # test.
        pass

    init_call, *progress_calls = consumer.call_args_list
    assert init_call[0][0]["method"] == "window/workDoneProgress/create"

    # same method for all calls
    assert all(call[0][0]["method"] == "$/progress" for call in progress_calls)

    # same token used in all calls
    assert (
        len(
            {call[0][0]["params"]["token"] for call in progress_calls}
            | {init_call[0][0]["params"]["token"]}
        )
        == 1
    )

    assert [call[0][0]["params"]["value"] for call in progress_calls] == [
        {"kind": "begin", "title": "some_title"},
        {"kind": "end"},
    ]
