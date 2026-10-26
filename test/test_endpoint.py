"""Transport cancellation must not race document mutations."""

import os
import socket
from concurrent.futures import Future
from queue import Queue
from threading import Event, Thread, get_ident
from types import SimpleNamespace

import pytest

from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter

from rols.endpoint import OrderedEndpoint
from rols.python_lsp import RopeLanguageServer


def request(endpoint, number, method):
    endpoint.consume({"jsonrpc": "2.0", "id": number, "method": method})


def cancel(endpoint, params):
    endpoint.consume({"jsonrpc": "2.0", "method": "$/cancelRequest", "params": params})


def test_cancel_queued_request_preserves_notification_order():
    entered, release, finished = Event(), Event(), Event()
    calls, responses = [], []

    def slow(params):
        entered.set()
        assert release.wait(5)
        return "slow"

    def change(params):
        calls.append("change")

    def obsolete(params):
        calls.append("obsolete")

    def following(params):
        calls.append("following")
        return list(calls)

    def receive(message):
        responses.append(message)
        if message["id"] == 3:
            finished.set()

    endpoint = OrderedEndpoint(
        {"slow": slow, "change": change, "obsolete": obsolete, "following": following},
        receive,
    )
    try:
        request(endpoint, 1, "slow")
        assert entered.wait(5)
        request(endpoint, 2, "obsolete")
        endpoint.consume({"jsonrpc": "2.0", "method": "change"})
        cancel(endpoint, {"id": 2})
        cancel(endpoint, {"id": 1})  # Running work is not interrupted.
        request(endpoint, 3, "following")
        release.set()
        assert finished.wait(5)
        assert calls == ["change", "following"]
        assert [response["id"] for response in responses] == [1, 2, 3]
        assert responses[1]["error"]["code"] == -32800
    finally:
        release.set()
        endpoint.shutdown()


@pytest.mark.parametrize("params", [None, {}, [], {"id": []}, {"id": True}])
def test_malformed_and_late_cancellation(params):
    finished = Event()
    endpoint = OrderedEndpoint(
        {"ping": lambda params: "pong"}, lambda _: finished.set()
    )
    try:
        cancel(endpoint, params)
        cancel(endpoint, {"id": "unknown"})
        request(endpoint, 1, "ping")
        assert finished.wait(5)
    finally:
        endpoint.shutdown()


def test_cancelled_async_future_gets_error_response():
    future = Future()
    ready, finished = Event(), Event()
    responses = []

    def receive(message):
        responses.append(message)
        finished.set()

    endpoint = OrderedEndpoint(
        {"async": lambda params: future, "barrier": lambda params: ready.set()},
        receive,
    )
    try:
        request(endpoint, 1, "async")
        endpoint.consume({"jsonrpc": "2.0", "method": "barrier"})
        assert ready.wait(5)
        cancel(endpoint, {"id": 1})
        assert finished.wait(5)
        assert responses[0]["error"]["code"] == -32800
    finally:
        endpoint.shutdown()


def test_streamed_backlog_skips_cancelled_requests():
    """Drain obsolete completions without losing ordered document changes."""
    entered, release, exited = Event(), Event(), Event()
    responses = Queue()
    calls = []
    versions = []

    def completion(params):
        calls.append(params["version"])
        if params["version"] == 0:
            entered.set()
            assert release.wait(10)
        return list(versions)

    server_socket, client_socket = socket.socketpair()
    server_rx = server_socket.makefile("rb")
    server_tx = server_socket.makefile("wb")
    client_rx = client_socket.makefile("rb")
    client_tx = client_socket.makefile("wb")
    endpoint = OrderedEndpoint(
        {
            "textDocument/completion": completion,
            "textDocument/didChange": lambda params: versions.append(params["version"]),
            "exit": lambda params: exited.set(),
        },
        JsonRpcStreamWriter(server_tx).write,
    )
    server_thread = Thread(
        target=JsonRpcStreamReader(server_rx).listen,
        args=(endpoint.consume,),
        daemon=True,
    )
    client_thread = Thread(
        target=JsonRpcStreamReader(client_rx).listen,
        args=(responses.put,),
        daemon=True,
    )
    writer = JsonRpcStreamWriter(client_tx)

    def send(method, params, request_id=None):
        message = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            message["id"] = request_id
        writer.write(message)

    server_thread.start()
    client_thread.start()
    try:
        send("textDocument/completion", {"version": 0}, 0)
        assert entered.wait(5)
        for version in range(1, 201):
            send("textDocument/didChange", {"version": version})
            send("textDocument/completion", {"version": version}, version)
            send("$/cancelRequest", {"id": version})
        # A response must bypass the blocked worker. Use it as a transport
        # barrier to prove all preceding cancellations have been consumed.
        barrier = endpoint.request("client/barrier")
        barrier_request = responses.get(timeout=5)
        writer.write({"jsonrpc": "2.0", "id": barrier_request["id"], "result": None})
        assert barrier.result(timeout=5) is None
        send("textDocument/completion", {"version": 201}, 201)
        release.set()
        results = [responses.get(timeout=10) for _ in range(202)]
        assert [result["id"] for result in results] == list(range(202))
        assert all(result["error"]["code"] == -32800 for result in results[1:-1])
        assert results[-1]["result"] == list(range(1, 201))
        assert calls == [0, 201]
        send("exit", {})
        assert exited.wait(5)
    finally:
        release.set()
        for connection in (server_socket, client_socket):
            connection.shutdown(socket.SHUT_RDWR)
        server_thread.join(timeout=5)
        client_thread.join(timeout=5)
        endpoint.shutdown()
        for stream in (server_rx, server_tx, client_rx, client_tx):
            stream.close()
        server_socket.close()
        client_socket.close()
    assert not server_thread.is_alive()
    assert not client_thread.is_alive()


@pytest.mark.parametrize(
    ("send_shutdown", "send_exit"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_transport_exit_drains_work_before_closing_workspace(send_shutdown, send_exit):
    entered, release = Event(), Event()
    calls = []
    read_fd, write_fd = os.pipe()
    server = RopeLanguageServer(os.fdopen(read_fd, "rb"), None, consumer=lambda _: None)
    server._hook = lambda *args, **kwargs: []
    server.workspaces["test"] = SimpleNamespace(
        close=lambda: calls.append(("close", get_ident()))
    )

    def slow(params):
        entered.set()
        assert release.wait(5)
        calls.append(("request", get_ident()))

    server._dispatchers.append({"test/slow": slow})
    thread = Thread(target=server.start, daemon=True)
    thread.start()
    try:
        with os.fdopen(write_fd, "wb") as stream:
            writer = JsonRpcStreamWriter(stream)
            writer.write({"jsonrpc": "2.0", "id": 1, "method": "test/slow"})
            assert entered.wait(5)
            if send_shutdown:
                writer.write({"jsonrpc": "2.0", "id": 2, "method": "shutdown"})
            if send_exit:
                writer.write({"jsonrpc": "2.0", "method": "exit"})
        # EOF can arrive while a request or shutdown is still executing.
        release.set()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert [name for name, _ in calls] == ["request", "close"]
        assert calls[0][1] == calls[1][1]
        assert server._shutdown
    finally:
        release.set()
        thread.join(timeout=5)


def test_client_response_bypasses_blocked_handler():
    finished = Event()
    endpoint = None

    def receive(message):
        if "method" in message:
            endpoint.consume({"jsonrpc": "2.0", "id": message["id"], "result": "pong"})
        else:
            assert message["result"] == "pong"
            finished.set()

    def handler(params):
        return endpoint.request("client/ping").result(timeout=5)

    endpoint = OrderedEndpoint({"ping": handler}, receive)
    try:
        request(endpoint, 1, "ping")
        assert finished.wait(5)
    finally:
        endpoint.shutdown()
