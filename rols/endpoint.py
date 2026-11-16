"""Keep transport control messages responsive without concurrent Rope calls."""

import logging
from concurrent.futures import ThreadPoolExecutor
from contextvars import ContextVar
from threading import Event, Lock, get_ident

from pylsp_jsonrpc.endpoint import CANCEL_METHOD, Endpoint
from pylsp_jsonrpc.exceptions import JsonRpcRequestCancelled

log = logging.getLogger(__name__)
_request_cancelled = ContextVar("request_cancelled", default=None)


def check_request_cancelled():
    """Let a synchronous handler discard work before returning or applying it."""
    cancelled = _request_cancelled.get()
    if cancelled is not None and cancelled.is_set():
        raise JsonRpcRequestCancelled()


class OrderedEndpoint(Endpoint):
    """Dispatch ordinary messages in order; bypass the queue for transport control.

    Cancellation skips queued requests. Running Rope operations must finish,
    since interrupting them or running document mutations alongside them is unsafe.
    Synchronous handlers can check cancellation before sending their results.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._worker_id = None
        self._messages = ThreadPoolExecutor(
            max_workers=1, initializer=self._remember_worker
        )
        self._pending = {}
        self._pending_lock = Lock()

    def consume(self, message):
        if message.get("jsonrpc") != "2.0":
            return super().consume(message)
        if message.get("method") == CANCEL_METHOD and "id" not in message:
            return self._handle_notification(CANCEL_METHOD, message.get("params"))
        if "method" not in message:
            # A handler may be waiting for a response to a server request.
            return super().consume(message)

        if message.get("method") == "exit":
            # Close input on the reader thread, not while it holds a read lock.
            self.run_on_worker(lambda: None)
            return super().consume(message)

        request_id = message.get("id")
        state = Event()
        with self._pending_lock:
            if "id" in message:
                self._pending[request_id] = state
            self._messages.submit(self._consume_ordered, message, state)

    def _consume_ordered(self, message, state):
        token = _request_cancelled.set(state)
        try:
            if state.is_set():
                self._consumer(
                    {
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "error": JsonRpcRequestCancelled().to_dict(),
                    }
                )
            else:
                super().consume(message)
        finally:
            _request_cancelled.reset(token)
            with self._pending_lock:
                if "id" in message:
                    self._pending.pop(message["id"], None)

    def _handle_notification(self, method, params):
        if method != CANCEL_METHOD:
            return super()._handle_notification(method, params)
        if (
            not isinstance(params, dict)
            or not isinstance(params.get("id"), (str, int))
            or isinstance(params["id"], bool)
        ):
            log.debug("Ignoring malformed cancellation: %r", params)
            return
        request_id = params["id"]
        with self._pending_lock:
            state = self._pending.get(request_id)
            if state is not None:
                state.set()
        # Late cancellations are normal; Future.cancel cannot interrupt work.
        future = self._client_request_futures.get(request_id)
        if future is not None:
            future.cancel()

    def _request_callback(self, request_id):
        callback = super()._request_callback(request_id)

        def completed(future):
            if not future.cancelled():
                return callback(future)
            self._client_request_futures.pop(request_id, None)
            self._consumer(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": JsonRpcRequestCancelled().to_dict(),
                }
            )

        return completed

    def _remember_worker(self):
        self._worker_id = get_ident()

    def run_on_worker(self, callback):
        """Finish queued messages before cleanup on the document-owning thread."""
        if get_ident() == self._worker_id:
            return callback()
        return self._messages.submit(callback).result()

    def shutdown(self):
        self._messages.shutdown(wait=get_ident() != self._worker_id)
        super().shutdown()
