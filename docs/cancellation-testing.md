# Testing cancellation and responsiveness

Issue [#6](https://codefloe.com/mcepl/rope-language-server/issues/6) concerns
cancellation while synchronous requests hold up the server. Cancellation can skip
queued requests, but cannot interrupt a Rope operation that has already started.

## Automated tests

From an environment with the project and its test dependencies installed:

```sh
python3 -m pytest -q -o addopts='' test/test_endpoint.py
python3 -m pytest -q -o addopts=''
```

The streamed backlog test uses framed JSON-RPC messages over a socket pair. It
blocks the first completion, queues 200 document changes and cancelled
completions, then requests one final completion. A client response provides a
transport barrier before releasing the blocked handler. Assertions check that:

- Only the initial and final completion handlers execute.
- Every cancelled queued request receives error code `-32800`.
- All document changes execute in order before the final completion.
- Client responses bypass the blocked worker.
- The transport reader threads terminate.

Other endpoint tests cover malformed cancellations, cancelled futures, and
workspace cleanup after EOF or an exit notification, with or without a preceding
shutdown request. Cleanup must happen once, after pending work, on the same thread
as document operations.

## Headless Neovim test

With Neovim and the project's Python dependencies installed, run from the checkout:

```sh
nvim --headless -u NONE -l scripts/stress_cancellation.lua
```

The script uses Neovim's built-in LSP client, without user configuration or editor
plugins. Set `PYTHON` to select a Python executable. Set `ROLS_STRESS_DIR` to select
a directory for the sample files and server log. By default these are retained in
`/tmp/rols-cancellation-stress-<pid>`.

The script enables Rope completion and autoimport, makes 100 buffer edits and
completion requests, and cancels each request immediately. It waits for every
request to be acknowledged and checks that a subsequent completion is nonempty.
It then switches buffers, checks hover, and requests graceful shutdown with a
second burst of requests pending. The server must exit with code zero.

Neovim suppresses completion callbacks for `RequestCancelled` responses. The
script checks removal from the client's request table rather than waiting for
those callbacks. Its output includes the number acknowledged, the number of
normal completion callbacks, final completion latency, exit code, and log path.
Inspect the server log for exceptions as well as checking the script's exit code.

For comparison, run the same script and Python dependencies from a baseline
checkout. One small-file run on the original baseline `a29daf4` took about 828 ms
for the final completion and logged 100 unknown-cancellation warnings. Runs with
the ordered endpoint took about 14 to 31 ms. These are individual smoke-test
results, not a performance guarantee or a substitute for testing large projects.

## Interactive follow-up

Headless Neovim exercises a real editor's LSP client, but not a user's completion
menu, plugins, or typing patterns. In a representative project, also try rapid
typing and deletion with the usual completion setup, request hover and definition
while completion is busy, switch files, and close the editor with work pending.
Check that the latest result arrives after typing stops and no server processes
remain after exit. Record project size, editor configuration, and whether initial
autoimport indexing had finished when comparing results.
