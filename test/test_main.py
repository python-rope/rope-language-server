# Copyright 2024- Python Language Server Contributors.

import argparse
import json
import logging
import logging.handlers
import sys
from unittest import mock

import pytest

from rols import __main__


def test_add_arguments_defaults():
    parser = argparse.ArgumentParser()
    __main__.add_arguments(parser)

    args = parser.parse_args([])
    assert args.tcp is False
    assert args.ws is False
    assert args.host == "127.0.0.1"
    assert args.port == 2087
    assert args.check_parent_process is True
    assert args.verbose == 0
    assert args.log_config is None
    assert args.log_file is None


def test_add_arguments_custom_flags():
    parser = argparse.ArgumentParser()
    __main__.add_arguments(parser)

    args = parser.parse_args(
        [
            "--tcp",
            "--host",
            "0.0.0.0",
            "--port",
            "3000",
            "-vv",
            "--no-check-parent-process",
            "--log-file",
            "/tmp/test.log",
        ]
    )
    assert args.tcp is True
    assert args.host == "0.0.0.0"
    assert args.port == 3000
    assert args.verbose == 2
    assert args.check_parent_process is False
    assert args.log_file == "/tmp/test.log"


def test_add_arguments_version():
    parser = argparse.ArgumentParser()
    __main__.add_arguments(parser)

    with pytest.raises(SystemExit):
        parser.parse_args(["-V"])


def test_configure_logger_verbose_levels():
    orig_level = logging.root.level
    try:
        __main__._configure_logger(verbose=0)
        assert logging.root.level == logging.WARNING

        __main__._configure_logger(verbose=1)
        assert logging.root.level == logging.INFO

        __main__._configure_logger(verbose=2)
        assert logging.root.level == logging.DEBUG
    finally:
        logging.root.setLevel(orig_level)


def test_configure_logger_log_file(tmp_path):
    log_file = tmp_path / "server.log"
    orig_handlers = list(logging.root.handlers)
    try:
        __main__._configure_logger(verbose=0, log_file=str(log_file))

        matching_handlers = [
            h
            for h in logging.root.handlers
            if isinstance(h, logging.handlers.RotatingFileHandler)
            and h.baseFilename == str(log_file)
        ]
        assert matching_handlers
    finally:
        for h in list(logging.root.handlers):
            if h not in orig_handlers:
                logging.root.removeHandler(h)
                h.close()


def test_configure_logger_log_config(tmp_path):
    cfg_file = tmp_path / "log_config.json"
    cfg = {
        "version": 1,
        "disable_existing_loggers": False,
        "root": {"level": "INFO"},
    }
    cfg_file.write_text(json.dumps(cfg))
    orig_level = logging.root.level
    try:
        with mock.patch("logging.config.dictConfig") as mock_dict_config:
            __main__._configure_logger(verbose=1, log_config=str(cfg_file))
            mock_dict_config.assert_called_once_with(cfg)
            assert logging.root.level == logging.INFO
    finally:
        logging.root.setLevel(orig_level)


def test_main_tcp_dispatch(monkeypatch):
    mock_tcp = mock.MagicMock()
    monkeypatch.setattr(__main__, "start_tcp_lang_server", mock_tcp)
    monkeypatch.setattr("sys.argv", ["rols", "--tcp", "--port", "1234"])

    __main__.main()
    mock_tcp.assert_called_once_with(
        "127.0.0.1", 1234, True, __main__.RopeLanguageServer
    )


def test_main_ws_dispatch(monkeypatch):
    mock_ws = mock.MagicMock()
    monkeypatch.setattr(__main__, "start_ws_lang_server", mock_ws)
    monkeypatch.setattr("sys.argv", ["rols", "--ws", "--port", "4321"])

    __main__.main()
    mock_ws.assert_called_once_with(4321, True, __main__.RopeLanguageServer)


def test_main_stdio_dispatch(monkeypatch):
    mock_io = mock.MagicMock()
    monkeypatch.setattr(__main__, "start_io_lang_server", mock_io)
    monkeypatch.setattr("sys.argv", ["rols"])
    monkeypatch.setattr(sys, "stdin", mock.MagicMock(buffer=mock.MagicMock()))
    monkeypatch.setattr(sys, "stdout", mock.MagicMock(buffer=mock.MagicMock()))

    __main__.main()
    mock_io.assert_called_once()
    assert mock_io.call_args[0][2] is True
    assert mock_io.call_args[0][3] == __main__.RopeLanguageServer
