"""Transport cancellation must not race document mutations."""

from concurrent.futures import Future
from threading import Event

import pytest

from rols.endpoint import OrderedEndpoint


def request(endpoint, number, method):
    endpoint.consume({"jsonrpc": "2.0", "id": number, "method": method})


def cancel(endpoint, params):
    endpoint.consume(
        {"jsonrpc": "2.0", "method": "$/cancelRequest", "params": params}
    )


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
    endpoint = OrderedEndpoint({"ping": lambda params: "pong"}, lambda _: finished.set())
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
