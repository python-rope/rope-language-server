# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

"""pytest configuration"""

import logging

import pytest

from rols.__main__ import LOG_FORMAT

logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)


pytest_plugins = ["test.fixtures"]


@pytest.fixture(autouse=True)
def _isolate_user_config(monkeypatch, tmp_path):
    """Isolate tests from the developer's real user-level configuration.

    Linter config sources (e.g. flake8) read ``$XDG_CONFIG_HOME`` and the home
    directory, so a real ``~/.config/flake8`` would otherwise leak into the
    tests and make their outcome depend on the machine they run on.
    """
    fake_home = tmp_path / "home"
    fake_config = fake_home / ".config"
    fake_config.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake_config))
