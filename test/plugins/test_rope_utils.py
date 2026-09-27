# Copyright 2024- Python Language Server Contributors.

import os
from unittest import mock

import pytest

from rols import uris
from rols.plugins import _rope_utils
from rols.workspace import Document


@pytest.fixture
def sample_doc(workspace):
    doc_uri = uris.from_fs_path(os.path.join(workspace.root_path, "test_doc.py"))
    return Document(doc_uri, workspace, "line1\nline2\nline3\n")


def test_get_project(config, workspace, sample_doc):
    project = _rope_utils.get_project(config, workspace, sample_doc)
    assert project is not None


def test_get_resource_none_project(sample_doc):
    assert _rope_utils.get_resource(None, sample_doc) is None


def test_get_resource_path_to_resource_exception(config, workspace, sample_doc):
    project = _rope_utils.get_project(config, workspace, sample_doc)
    with mock.patch(
        "rols.plugins._rope_utils.path_to_resource", side_effect=RuntimeError
    ):
        assert _rope_utils.get_resource(project, sample_doc) is None


def test_get_resource_none_or_not_exists(config, workspace, sample_doc):
    project = _rope_utils.get_project(config, workspace, sample_doc)

    with mock.patch("rols.plugins._rope_utils.path_to_resource", return_value=None):
        assert _rope_utils.get_resource(project, sample_doc) is None

    mock_resource = mock.Mock()
    mock_resource.exists.return_value = False
    with mock.patch(
        "rols.plugins._rope_utils.path_to_resource", return_value=mock_resource
    ):
        assert _rope_utils.get_resource(project, sample_doc) is None


def test_get_resource_stale_content_or_read_error(config, workspace, sample_doc):
    project = _rope_utils.get_project(config, workspace, sample_doc)

    mock_resource = mock.Mock()
    mock_resource.exists.return_value = True
    mock_resource.read.return_value = "different source"
    with mock.patch(
        "rols.plugins._rope_utils.path_to_resource", return_value=mock_resource
    ):
        assert _rope_utils.get_resource(project, sample_doc) is None

    mock_resource.read.side_effect = OSError("Read failed")
    with mock.patch(
        "rols.plugins._rope_utils.path_to_resource", return_value=mock_resource
    ):
        assert _rope_utils.get_resource(project, sample_doc) is None


def test_get_resource_matching_content(config, workspace, sample_doc):
    project = _rope_utils.get_project(config, workspace, sample_doc)

    mock_resource = mock.Mock()
    mock_resource.exists.return_value = True
    mock_resource.read.return_value = sample_doc.source
    with mock.patch(
        "rols.plugins._rope_utils.path_to_resource", return_value=mock_resource
    ):
        assert _rope_utils.get_resource(project, sample_doc) is mock_resource


def test_path_to_resource_none_project():
    assert _rope_utils.path_to_resource(None, "/path/to/file.py") is None


def test_path_to_resource_project_root():
    mock_project = mock.Mock()
    mock_project.address = "/path/to/project"
    _rope_utils.path_to_resource(mock_project, "/path/to/project")
    mock_project.get_resource.assert_called_once_with("")


def test_path_to_resource_inside_project():
    mock_project = mock.Mock()
    mock_project.address = "/path/to/project"
    target_path = os.path.join("/path/to/project", "sub", "mod.py")
    _rope_utils.path_to_resource(mock_project, target_path)
    mock_project.get_resource.assert_called_once_with(os.path.join("sub", "mod.py"))


def test_path_to_resource_outside_project():
    mock_project = mock.Mock()
    mock_project.address = "/path/to/project"
    with mock.patch("rope.base.project.get_no_project") as mock_get_no_project:
        mock_no_proj = mock.Mock()
        mock_get_no_project.return_value = mock_no_proj
        _rope_utils.path_to_resource(mock_project, "/outside/file.py")
        mock_get_no_project.assert_called_once()
        mock_no_proj.get_resource.assert_called_once_with("/outside/file.py")


def test_offset_to_position():
    source = "abc\ndefgh\nijk"
    assert _rope_utils.offset_to_position(source, 0) == {"line": 0, "character": 0}
    assert _rope_utils.offset_to_position(source, 2) == {"line": 0, "character": 2}
    assert _rope_utils.offset_to_position(source, 4) == {"line": 1, "character": 0}
    assert _rope_utils.offset_to_position(source, 7) == {"line": 1, "character": 3}


def test_region_to_range():
    source = "abc\ndefgh\nijk"
    expected = {
        "start": {"line": 0, "character": 1},
        "end": {"line": 1, "character": 2},
    }
    assert _rope_utils.region_to_range(source, 1, 6) == expected


def test_resource_source(sample_doc):
    assert _rope_utils.resource_source(None, sample_doc) == sample_doc.source

    mock_resource = mock.Mock()
    mock_resource.read.return_value = "resource code"
    assert _rope_utils.resource_source(mock_resource, sample_doc) == "resource code"

    mock_resource.read.side_effect = Exception("failed to read")
    assert _rope_utils.resource_source(mock_resource, sample_doc) == sample_doc.source


def test_resource_uri(sample_doc):
    assert _rope_utils.resource_uri(None, sample_doc) == sample_doc.uri

    mock_resource = mock.Mock()
    mock_resource.real_path = "/path/to/resource.py"
    assert _rope_utils.resource_uri(mock_resource, sample_doc) == uris.from_fs_path(
        "/path/to/resource.py"
    )

    failing_resource = mock.Mock()
    type(failing_resource).real_path = mock.PropertyMock(
        side_effect=Exception("real_path error")
    )
    assert _rope_utils.resource_uri(failing_resource, sample_doc) == sample_doc.uri
