# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021-2025 Python Language Server Contributors.
# Copyright 2026- Rope Language Server Contributors.
# Some sample code is adapted from the pylsp-rope test fixtures
# (https://github.com/python-rope/pylsp-rope), Copyright (c) 2021 Lie Ryan,
# MIT licence; see LICENSES/pylsp-rope.txt.

"""Rope refactoring code actions, exercised through JSON-RPC."""

import ast
import os
import threading
import time
from unittest.mock import patch

import pytest
from pylsp_jsonrpc.exceptions import JsonRpcException
from rope.base.exceptions import RefactoringError

from rols import uris
from rols.lsp import ErrorCodes, MessageType
from rols.plugins.rope_autoimport import AutoimportCache
from rols.plugins.rope_refactor import actions as refactor_actions
from test.test_utils import (
    CALL_TIMEOUT_IN_SECONDS,
    ClientServerPair,
    RecordingClient,
    apply_workspace_edit,
)

# Client capability profiles
COMMANDS_ONLY = {}
DOCUMENT_CHANGES = {"workspace": {"workspaceEdit": {"documentChanges": True}}}
RESOLVE = {"textDocument": {"codeAction": {"resolveSupport": {"properties": ["edit"]}}}}

SIMPLE = """\
import sys


def main():
    a = int(sys.stdin.read())
    b = 20
    print(a + b)
    c = a + b


a, b = 30, 40
print(a + b)
"""

HELPER = """\
def helper(x):
    return x * 2


print(helper(3))
"""

USES_HELPER = """\
from helper_mod import helper

print(helper(5))
"""


def pos(line, character):
    return {"line": line, "character": character}


def rng(start_line, start_char, end_line=None, end_char=None):
    if end_line is None:
        end_line, end_char = start_line, start_char
    return {"start": pos(start_line, start_char), "end": pos(end_line, end_char)}


class Session:
    """A server with a recording client, initialised for ``root``."""

    def __init__(self, client, server, root):
        self.client = client
        self.server = server
        self.root = root

    def request(self, method, params):
        return self.client._endpoint.request(method, params).result(
            timeout=CALL_TIMEOUT_IN_SECONDS
        )

    def notify(self, method, params):
        self.client._endpoint.notify(method, params)

    def write(self, name, text):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        return uris.from_fs_path(path)

    def open(self, name, text, version=1, on_disk=None):
        uri = self.write(name, text if on_disk is None else on_disk)
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "python",
                    "version": version,
                    "text": text,
                }
            },
        )
        return uri

    def change(self, uri, text, version):
        self.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}],
            },
        )

    def code_actions(self, uri, range_, **context):
        context.setdefault("diagnostics", [])
        return self.request(
            "textDocument/codeAction",
            {"textDocument": {"uri": uri}, "range": range_, "context": context},
        )

    def edit_for(self, action):
        """Return the WorkspaceEdit the client would apply for ``action``."""
        if "edit" in action:
            return action["edit"]
        if "data" in action:
            return self.request("codeAction/resolve", action)["edit"]
        self.client.edit_applied.clear()
        command = action["command"]
        result = self.request(
            "workspace/executeCommand",
            {"command": command["command"], "arguments": command["arguments"]},
        )
        assert result is None
        assert self.client.edit_applied.wait(
            CALL_TIMEOUT_IN_SECONDS
        ), self.client.messages
        return self.client.applied_edits[-1]["edit"]


@pytest.fixture
def session_factory(tmp_path):
    pairs = []
    autoimport_cache = AutoimportCache()
    patches = [
        patch("rols.plugins.rope_autoimport.cache", autoimport_cache),
        patch.object(autoimport_cache, "reload_cache"),
    ]
    for item in patches:
        item.start()

    def make(capabilities=COMMANDS_ONLY, settings=None, root=None, **initialize):
        pair = ClientServerPair(client_cls=RecordingClient)
        pairs.append(pair)
        root = str(root or tmp_path)
        params = {
            "rootUri": uris.from_fs_path(root),
            "capabilities": capabilities,
            "initializationOptions": {"rols": settings or {}},
        }
        params.update(initialize)
        session = Session(pair.client, pair.server, root)
        pair.server.lint = lambda *args, **kwargs: None
        session.request("initialize", params)
        session.notify("initialized", {})
        return session

    yield make

    for pair in pairs:
        pair.client._endpoint.request("shutdown").result(
            timeout=CALL_TIMEOUT_IN_SECONDS
        )
        pair.client._endpoint.notify("exit")
    for item in patches:
        item.stop()


def titles(actions):
    return [action["title"] for action in actions]


def find(actions, title):
    matching = [action for action in actions if action["title"] == title]
    assert matching, titles(actions)
    return matching[0]


def assert_parses(text):
    ast.parse(text)


# Capabilities


def test_capabilities_advertise_kinds_resolve_and_commands(session_factory):
    session = session_factory()
    capabilities = session.server.capabilities()
    provider = capabilities["codeActionProvider"]
    assert provider["resolveProvider"] is True
    assert {"quickfix", "refactor.extract", "source.organizeImports"} <= set(
        provider["codeActionKinds"]
    )
    commands = capabilities["executeCommandProvider"]["commands"]
    assert "rols.refactor.extract.method" in commands
    assert "rols.refactor.inline" in commands


# Delivery: commands, resolve and eager edits


@pytest.mark.parametrize(
    "capabilities, delivery",
    [(COMMANDS_ONLY, "command"), (RESOLVE, "data"), (DOCUMENT_CHANGES, "edit")],
)
def test_extract_variable(session_factory, capabilities, delivery):
    session = session_factory(capabilities)
    uri = session.open("simple.py", SIMPLE)
    line = SIMPLE.splitlines()[6]
    start = line.index("a + b")
    actions = session.code_actions(uri, rng(6, start, 6, start + 5))
    action = find(actions, "Extract variable")
    assert action["kind"] == "refactor.extract"
    assert delivery in action
    new = apply_workspace_edit({uri: SIMPLE}, session.edit_for(action))[uri]
    assert "    extracted_variable = a + b\n    print(extracted_variable)\n" in new
    assert new.count("a + b") == 3
    assert_parses(new)


def test_extract_similar_and_global_variants(session_factory):
    session = session_factory(DOCUMENT_CHANGES)
    uri = session.open("simple.py", SIMPLE)
    start = SIMPLE.splitlines()[6].index("a + b")
    actions = session.code_actions(uri, rng(6, start, 6, start + 5))
    assert {
        "Extract method",
        "Extract method including similar statements",
        "Extract global method",
        "Extract global method including similar statements",
        "Extract variable",
        "Extract variable including similar statements",
        "Extract global variable",
        "Extract global variable including similar statements",
    } <= set(titles(actions))
    action = find(actions, "Extract variable including similar statements")
    new = apply_workspace_edit({uri: SIMPLE}, action["edit"])[uri]
    assert new.count("a + b") == 2
    assert_parses(new)


def test_extract_method_whole_line(session_factory):
    session = session_factory()
    uri = session.open("simple.py", SIMPLE)
    actions = session.code_actions(uri, rng(5, 0, 6, 0))
    new = apply_workspace_edit(
        {uri: SIMPLE}, session.edit_for(find(actions, "Extract method"))
    )[uri]
    assert "    b = extracted_method()\n" in new
    assert "def extracted_method():\n    b = 20\n    return b\n" in new
    assert_parses(new)


def test_extract_uses_a_fresh_name(session_factory):
    source = "def extracted_method():\n    pass\n\n\ndef f(a):\n    return a + 1\n"
    session = session_factory()
    uri = session.open("m.py", source)
    start = source.index("a + 1")
    line = source.count("\n", 0, start)
    column = start - source.rfind("\n", 0, start) - 1
    actions = session.code_actions(uri, rng(line, column, line, column + 5))
    new = apply_workspace_edit(
        {uri: source}, session.edit_for(find(actions, "Extract method"))
    )[uri]
    assert "def extracted_method_2(a):" in new
    assert "def extracted_method():" in new


def test_extract_not_offered_for_bad_selections(session_factory):
    session = session_factory()
    uri = session.open("simple.py", SIMPLE)
    line = SIMPLE.splitlines()[6]
    # Part of an expression, and an empty range
    for range_ in (
        rng(6, line.index("a +"), 6, line.index("a +") + 3),
        rng(6, line.index("a + b"), 6, line.index("a + b")),
    ):
        actions = session.code_actions(uri, range_)
        assert not [t for t in titles(actions) if t.startswith("Extract")]


def test_extract_method_not_offered_in_class_body(session_factory):
    # Rope would define the function after the class (python-rope/rope#825).
    source = 'class TSV:\n    delimiter = "\\t"\n'
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(1, 16, 1, 20))
    assert "Extract method" not in titles(actions)
    assert "Extract variable" in titles(actions)


def test_automatic_requests_skip_computed_actions(session_factory):
    session = session_factory()
    uri = session.open("simple.py", SIMPLE)
    start = SIMPLE.splitlines()[6].index("a + b")
    actions = session.code_actions(uri, rng(6, start, 6, start + 5), triggerKind=2)
    assert not [t for t in titles(actions) if t.startswith("Extract")]


# Unsaved documents


def test_refactoring_uses_unsaved_buffer(session_factory):
    session = session_factory()
    on_disk = "def f():\n    return 1\n"
    uri = session.open("m.py", on_disk)
    unsaved = "def f():\n    total = 40 + 2\n    return total\n"
    session.change(uri, unsaved, 2)
    actions = session.code_actions(uri, rng(2, 12))
    action = find(actions, "Inline variable 'total'")
    new = apply_workspace_edit({uri: unsaved}, session.edit_for(action))[uri]
    assert new == "def f():\n    return 40 + 2\n"


def test_crlf_document(session_factory):
    session = session_factory(DOCUMENT_CHANGES)
    source = SIMPLE.replace("\n", "\r\n")
    uri = session.open("simple.py", source)
    start = SIMPLE.splitlines()[6].index("a + b")
    actions = session.code_actions(uri, rng(6, start, 6, start + 5))
    new = apply_workspace_edit(
        {uri: source}, find(actions, "Extract variable")["edit"]
    )[uri]
    assert (
        new
        == apply_workspace_edit(
            {uri: source}, find(actions, "Extract variable")["edit"]
        )[uri]
    )
    assert "\n" not in new.replace("\r\n", "")
    assert "    extracted_variable = a + b\r\n" in new


@pytest.mark.parametrize("capabilities", [COMMANDS_ONLY, RESOLVE, DOCUMENT_CHANGES])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_extract_after_astral_character(session_factory, capabilities, newline):
    session = session_factory(capabilities)
    source = f'def f():{newline}    return ("🦊", 40 + 2){newline}'
    uri = session.open("m.py", source)
    line = source.splitlines()[1]
    start = len(line[: line.index("40 + 2")].encode("utf-16-le")) // 2
    action = find(
        session.code_actions(uri, rng(1, start, 1, start + 6)), "Extract variable"
    )
    new = apply_workspace_edit({uri: source}, session.edit_for(action))[uri]
    assert f"    extracted_variable = 40 + 2{newline}" in new
    assert f'    return ("🦊", extracted_variable){newline}' in new
    assert_parses(new)


# Inline


def test_inline_method_across_unsaved_modules(session_factory):
    session = session_factory(DOCUMENT_CHANGES)
    helper_uri = session.open("helper_mod.py", HELPER)
    user = USES_HELPER + "print(helper(7))\n"
    user_uri = session.open("user.py", user, on_disk=USES_HELPER)
    actions = session.code_actions(helper_uri, rng(0, 5))
    action = find(actions, "Inline method 'helper'")
    assert "command" in action
    edit = session.edit_for(action)
    versions = {
        change["textDocument"]["uri"]: change["textDocument"]["version"]
        for change in edit["documentChanges"]
    }
    assert versions == {helper_uri: 1, user_uri: 1}
    new = apply_workspace_edit({helper_uri: HELPER, user_uri: user}, edit)
    assert new[helper_uri] == "print(3 * 2)\n"
    assert new[user_uri] == "print(5 * 2)\nprint(7 * 2)\n"


def test_inline_refused_when_another_module_does_not_parse(session_factory):
    session = session_factory()
    helper_uri = session.open("helper_mod.py", HELPER)
    session.write("broken.py", "from helper_mod import helper\nhelper(4)\nif\n")
    actions = session.code_actions(helper_uri, rng(0, 5))
    command = find(actions, "Inline method 'helper'")["command"]
    session.client.message_shown.clear()
    session.request(
        "workspace/executeCommand",
        {"command": command["command"], "arguments": command["arguments"]},
    )
    assert session.client.message_shown.wait(CALL_TIMEOUT_IN_SECONDS)
    message = session.client.messages[-1]
    assert message["type"] == MessageType.Error
    assert "broken.py has a syntax error" in message["message"]
    assert session.client.applied_edits == []


def test_inline_parameter_default(session_factory):
    source = "def f(a, b=2):\n    return a + b\n\n\nprint(f(1))\n"
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(0, 9))
    new = apply_workspace_edit(
        {uri: source}, session.edit_for(find(actions, "Inline parameter 'b'"))
    )[uri]
    assert new == "def f(a, b=2):\n    return a + b\n\n\nprint(f(1, 2))\n"


@pytest.mark.parametrize(
    "source, line, character",
    [
        # A parameter without a default
        ("def f(a):\n    return a\n", 0, 6),
        # Not a name at all
        ("x = 1\nprint(x)\n", 1, 2),
        # A dunder method (python-rope/rope#742, #750, #758)
        ("class A:\n    def __eq__(self, o):\n        return True\n", 1, 9),
        # An abstract method (python-rope/rope#744)
        (
            "import abc\n\n\nclass A:\n    @abc.abstractmethod\n"
            "    def tag(self):\n        return 1\n",
            5,
            9,
        ),
        # A method that overrides a base class method (python-rope/rope#828)
        (
            "class W(list):\n    def append(self, o):\n"
            "        super().append(o)\n\n\nW().append(1)\n",
            1,
            9,
        ),
    ],
)
def test_inline_not_offered(session_factory, source, line, character):
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(line, character))
    assert not [t for t in titles(actions) if t.startswith("Inline")]


# Use function, method object, local to field and introduce parameter


def test_use_function_across_modules(session_factory):
    session = session_factory()
    source = "def square(p):\n    return p ** 2\n\n\nprint(4 ** 2)\n"
    other = "from m import square\n\nprint(3 ** 2)\n"
    uri = session.open("m.py", source)
    other_uri = session.write("other.py", other)
    actions = session.code_actions(uri, rng(0, 6))
    edit = session.edit_for(find(actions, "Use function 'square'"))
    new = apply_workspace_edit({uri: source, other_uri: other}, edit)
    assert new[uri].endswith("print(square(4))\n")
    assert new[other_uri].endswith("square(3))\n")
    assert_parses(new[other_uri])

    actions = session.code_actions(uri, rng(0, 6))
    edit = session.edit_for(find(actions, "Use function 'square' in this file"))
    assert set(edit["changes"]) == {uri}


def test_use_function_only_on_definition_name(session_factory):
    session = session_factory()
    source = "def square(p):\n    return p ** 2\n\n\nprint(square(4))\n"
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(4, 7))
    assert not [t for t in titles(actions) if t.startswith("Use function")]


def test_method_to_method_object(session_factory):
    source = "def compute_total(a, b):\n    return a + b\n"
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(0, 6))
    new = apply_workspace_edit(
        {uri: source},
        session.edit_for(find(actions, "Convert 'compute_total' to method object")),
    )[uri]
    assert "return ComputeTotal(a, b)()" in new
    assert "class ComputeTotal(object):" in new
    assert_parses(new)


def test_local_to_field(session_factory):
    source = (
        "class A:\n    def method(self):\n        local_var = 10\n"
        "        return local_var\n"
    )
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(2, 10))
    new = apply_workspace_edit(
        {uri: source},
        session.edit_for(find(actions, "Convert local variable 'local_var' to field")),
    )[uri]
    assert "self.local_var = 10" in new
    assert "return self.local_var" in new


def test_local_to_field_not_offered_outside_methods(session_factory):
    source = "def f():\n    local_var = 10\n    return local_var\n"
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(1, 6))
    assert not [t for t in titles(actions) if "to field" in t]


def test_introduce_parameter(session_factory):
    source = "LIMIT = 3\n\n\ndef f(a):\n    return a + LIMIT\n"
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(4, 16))
    new = apply_workspace_edit(
        {uri: source},
        session.edit_for(find(actions, "Introduce parameter for 'LIMIT'")),
    )[uri]
    assert "def f(a, limit=LIMIT):\n    return a + limit\n" in new


def test_introduce_parameter_not_offered_for_local_names(session_factory):
    source = "def f(a):\n    b = a\n    return b\n"
    session = session_factory()
    uri = session.open("m.py", source)
    for character in (11, 14):
        actions = session.code_actions(uri, rng(2, character))
        assert not [t for t in titles(actions) if t.startswith("Introduce")]


# Organise imports


def test_organise_imports(session_factory):
    source = "import sys\nimport os\n\nprint(os.name)\n"
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(3, 0), only=["source.organizeImports"])
    assert titles(actions) == ["Organise imports"]
    new = apply_workspace_edit({uri: source}, actions[0]["edit"])[uri]
    assert "import sys" not in new
    assert "import os" in new


@pytest.mark.parametrize(
    "name, source",
    [
        # Re-exports in a package without __all__ (python-rope/rope#368)
        ("pkg/__init__.py", "from pkg.impl import thing\n"),
        # Comments, strings and other scopes do not define module exports.
        (
            "pkg/__init__.py",
            "# TODO: define __all__\nfrom pkg.impl import thing\n",
        ),
        (
            "pkg/__init__.py",
            '"""Exports will eventually use __all__."""\nfrom pkg.impl import thing\n',
        ),
        (
            "pkg/__init__.py",
            "from pkg.impl import thing\ndef f():\n    __all__ = []\n",
        ),
        (
            "pkg/__init__.py",
            "from pkg.impl import thing\n__all__: list\n",
        ),
        # Names used only in string annotations (python-rope/rope#369)
        ("m.py", "from os import PathLike\n\n\ndef f(p: 'PathLike'):\n    pass\n"),
        # Unused imports the user keeps on purpose (python-rope/rope#368)
        ("m.py", "import signal  # noqa: F401\nimport os\n\nprint(os.name)\n"),
        # Nothing to do
        ("m.py", "import os\n\n\nprint(os.name)\n"),
    ],
)
def test_organise_imports_not_offered(session_factory, name, source):
    session = session_factory()
    session.write("pkg/impl.py", "def thing():\n    pass\n")
    uri = session.open(name, source)
    actions = session.code_actions(uri, rng(0, 0), only=["source"])
    assert actions == []


@pytest.mark.parametrize(
    "assignment", ["__all__ = ['thing']", "__all__: list = ['thing']"]
)
def test_organise_imports_with_explicit_exports(session_factory, assignment):
    session = session_factory()
    session.write("pkg/impl.py", "def thing():\n    pass\n")
    source = f"import sys\nfrom pkg.impl import thing\n\n{assignment}\n"
    uri = session.open("pkg/__init__.py", source)
    action = find(
        session.code_actions(uri, rng(0, 0), only=["source"]), "Organise imports"
    )
    new = apply_workspace_edit({uri: source}, session.edit_for(action))[uri]
    assert "from pkg.impl import thing" in new
    assert assignment in new
    assert "import sys" not in new


# Generate


def test_generate(session_factory):
    source = "def f():\n    return 1\n\n\nprint(undef_name(1))\n"
    session = session_factory()
    uri = session.open("m.py", source)
    diagnostic = {
        "range": rng(4, 6, 4, 16),
        "message": "undefined name 'undef_name'",
        "source": "pyflakes",
    }
    actions = session.code_actions(uri, rng(4, 8), diagnostics=[diagnostic])
    generated = [a for a in actions if a["title"].startswith("Generate")]
    assert titles(generated) == [
        "Generate variable 'undef_name'",
        "Generate function 'undef_name'",
        "Generate class 'undef_name'",
    ]
    assert all(a["kind"] == "quickfix" for a in generated)
    assert generated[1]["diagnostics"] == [diagnostic]
    new = apply_workspace_edit({uri: source}, session.edit_for(generated[1]))[uri]
    assert "def undef_name(arg0):\n    pass\n" in new
    assert_parses(new)


def test_generate_matches_utf16_diagnostic(session_factory):
    session = session_factory()
    source = 'print("🦊🦊🦊", x())\n'
    uri = session.open("m.py", source)
    start = len(source[: source.index("x()")].encode("utf-16-le")) // 2
    diagnostic = {"range": rng(0, start, 0, start + 1), "message": "undefined name 'x'"}
    actions = session.code_actions(uri, rng(0, start), diagnostics=[diagnostic])
    action = find(actions, "Generate function 'x'")
    assert action["diagnostics"] == [diagnostic]
    new = apply_workspace_edit({uri: source}, session.edit_for(action))[uri]
    assert "def x():\n    pass\n" in new
    assert_parses(new)


def test_generate_into_another_module(session_factory):
    source = "import other\n\nother.new_function()\n"
    session = session_factory()
    other_uri = session.write("other.py", "VALUE = 1\n")
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(2, 8))
    edit = session.edit_for(find(actions, "Generate function 'new_function'"))
    assert set(edit["changes"]) == {other_uri}
    new = apply_workspace_edit({other_uri: "VALUE = 1\n"}, edit)[other_uri]
    assert "def new_function():\n    pass\n" in new


def test_generate_not_offered_for_defined_names(session_factory):
    session = session_factory()
    uri = session.open("simple.py", SIMPLE)
    actions = session.code_actions(uri, rng(5, 4))
    assert not [t for t in titles(actions) if t.startswith("Generate")]


# Ranges and documents that get no actions

POINT_ACTIONS = ("Inline", "Generate", "Introduce", "Convert", "Use function")


@pytest.mark.parametrize(
    "range_, offered",
    [
        (rng(1, 5), True),  # empty range on `total`
        (rng(1, 5, 1, 8), True),  # inside the identifier
        (rng(1, 4, 1, 9), True),  # the identifier
        (rng(1, 5, 1, 18), True),  # from the cursor to the end of the line
        (rng(1, 4, 1, 16), False),  # an expression-like selection
        (rng(1, 0, 3, 0), False),  # several lines
    ],
)
def test_range_forms_for_point_actions(session_factory, range_, offered):
    source = "def f():\n    total = 40 + 2\n    return total\n"
    session = session_factory()
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, range_)
    found = "Inline variable 'total'" in titles(actions)
    assert found is offered, titles(actions)


def test_no_actions_for_syntax_errors(session_factory):
    session = session_factory()
    uri = session.open("m.py", "def f(:\n    x = 1\n")
    assert session.code_actions(uri, rng(1, 4)) == []


def test_no_actions_outside_the_project(session_factory, tmp_path):
    session = session_factory(root=tmp_path / "project")
    os.makedirs(tmp_path / "project")
    path = tmp_path / "elsewhere.py"
    path.write_text("x = 1\nprint(x)\n")
    uri = uris.from_fs_path(str(path))
    session.notify(
        "textDocument/didOpen",
        {
            "textDocument": {
                "uri": uri,
                "languageId": "python",
                "version": 1,
                "text": "x = 1\nprint(x)\n",
            }
        },
    )
    assert session.code_actions(uri, rng(1, 6)) == []


def test_disabled_actions(session_factory):
    session = session_factory(
        settings={"plugins": {"rope_refactor": {"disabled_actions": ["inline"]}}}
    )
    source = "def f():\n    total = 40 + 2\n    return total\n"
    uri = session.open("m.py", source)
    actions = session.code_actions(uri, rng(2, 12))
    assert not [t for t in titles(actions) if t.startswith("Inline")]


def test_plugin_can_be_disabled(session_factory):
    session = session_factory(
        settings={"plugins": {"rope_refactor": {"enabled": False}}}
    )
    uri = session.open("simple.py", SIMPLE)
    start = SIMPLE.splitlines()[6].index("a + b")
    assert session.code_actions(uri, rng(6, start, 6, start + 5)) == []


# Errors and stale requests


def test_stale_command_is_refused(session_factory):
    session = session_factory()
    source = "def f():\n    total = 40 + 2\n    return total\n"
    uri = session.open("m.py", source)
    command = find(session.code_actions(uri, rng(2, 12)), "Inline variable 'total'")[
        "command"
    ]
    session.change(uri, source + "\n", 2)
    session.client.message_shown.clear()
    session.request(
        "workspace/executeCommand",
        {"command": command["command"], "arguments": command["arguments"]},
    )
    assert session.client.message_shown.wait(CALL_TIMEOUT_IN_SECONDS)
    assert session.client.messages[-1]["type"] == MessageType.Warning
    assert "has changed" in session.client.messages[-1]["message"]
    assert session.client.applied_edits == []


def test_stale_resolve_is_content_modified(session_factory):
    session = session_factory(RESOLVE)
    source = "def f():\n    total = 40 + 2\n    return total\n"
    uri = session.open("m.py", source)
    action = find(session.code_actions(uri, rng(2, 12)), "Inline variable 'total'")
    session.change(uri, source + "\n", 2)
    with pytest.raises(JsonRpcException) as error:
        session.request("codeAction/resolve", action)
    assert error.value.code == ErrorCodes.ContentModified


def test_execution_error_is_reported_and_server_keeps_working(session_factory):
    session = session_factory()
    uri = session.open("simple.py", SIMPLE)
    start = SIMPLE.splitlines()[6].index("a + b")
    action = find(
        session.code_actions(uri, rng(6, start, 6, start + 5)), "Extract variable"
    )
    command = action["command"]
    session.client.message_shown.clear()
    with patch.object(
        refactor_actions.ExtractVariable,
        "changes",
        side_effect=RefactoringError("some refactoring error"),
    ):
        assert (
            session.request(
                "workspace/executeCommand",
                {"command": command["command"], "arguments": command["arguments"]},
            )
            is None
        )
    assert session.client.message_shown.wait(CALL_TIMEOUT_IN_SECONDS)
    assert session.client.messages[-1] == {
        "type": MessageType.Error,
        "message": "Rope: some refactoring error",
    }
    assert "Extract variable" in titles(
        session.code_actions(uri, rng(6, start, 6, start + 5))
    )


def test_resolve_error_is_request_failed(session_factory):
    session = session_factory(RESOLVE)
    uri = session.open("simple.py", SIMPLE)
    start = SIMPLE.splitlines()[6].index("a + b")
    action = find(
        session.code_actions(uri, rng(6, start, 6, start + 5)), "Extract variable"
    )
    with patch.object(
        refactor_actions.ExtractVariable,
        "changes",
        side_effect=RefactoringError("some refactoring error"),
    ):
        with pytest.raises(JsonRpcException) as error:
            session.request("codeAction/resolve", action)
    assert error.value.code == ErrorCodes.RequestFailed


@pytest.mark.parametrize(
    "key, value",
    [
        ("start", -1),
        ("start", "0"),
        ("name", "x = 1; import os"),
        ("similar", "yes"),
    ],
)
def test_invalid_command_arguments(session_factory, key, value):
    session = session_factory()
    uri = session.open("simple.py", SIMPLE)
    start = SIMPLE.splitlines()[6].index("a + b")
    action = find(
        session.code_actions(uri, rng(6, start, 6, start + 5)), "Extract variable"
    )
    command = action["command"]
    arguments = dict(command["arguments"][0], **{key: value})
    session.client.message_shown.clear()
    session.request(
        "workspace/executeCommand",
        {"command": command["command"], "arguments": [arguments]},
    )
    assert session.client.message_shown.wait(CALL_TIMEOUT_IN_SECONDS)
    assert session.client.messages[-1]["type"] == MessageType.Error
    assert session.client.applied_edits == []


def test_rejected_edit_is_reported(session_factory):
    session = session_factory()
    session.client.apply_result = {"applied": False, "failureReason": "read-only"}
    source = "def f():\n    total = 40 + 2\n    return total\n"
    uri = session.open("m.py", source)
    command = find(session.code_actions(uri, rng(2, 12)), "Inline variable 'total'")[
        "command"
    ]
    session.client.message_shown.clear()
    session.request(
        "workspace/executeCommand",
        {"command": command["command"], "arguments": command["arguments"]},
    )
    assert session.client.message_shown.wait(CALL_TIMEOUT_IN_SECONDS)
    assert "read-only" in session.client.messages[-1]["message"]


# Coexistence with autoimport and the ordered endpoint


def test_coexists_with_autoimport_and_only_filter(session_factory):
    session = session_factory(
        settings={"plugins": {"rope_autoimport": {"enabled": True}}}
    )

    def index_os():
        autoimport = session.server.workspace._rope_autoimport(
            session.server.config.settings().get("rope", {}), memory=True
        )
        autoimport.generate_modules_cache(modules=["os"], single_thread=True)

    session.server._endpoint.run_on_worker(index_os)
    source = "def f():\n    return os.path.join('a', 'b')\n"
    uri = session.open("m.py", source)
    diagnostic = {"range": rng(1, 11, 1, 13), "message": "undefined name 'os'"}
    actions = session.code_actions(uri, rng(1, 12), diagnostics=[diagnostic])
    assert "import os" in titles(actions)
    assert "Generate variable 'os'" in titles(actions)

    actions = session.code_actions(
        uri, rng(1, 12), diagnostics=[diagnostic], only=["refactor"]
    )
    assert "import os" not in titles(actions)
    assert not [t for t in titles(actions) if t.startswith("Generate")]

    actions = session.code_actions(
        uri, rng(1, 12), diagnostics=[diagnostic], only=["quickfix"]
    )
    assert "import os" in titles(actions)
    assert all(action["kind"] == "quickfix" for action in actions)


def test_cancelled_queued_command_sends_no_edit(session_factory):
    session = session_factory()
    source = "def f():\n    total = 40 + 2\n    return total\n"
    uri = session.open("m.py", source)
    command = find(session.code_actions(uri, rng(2, 12)), "Inline variable 'total'")[
        "command"
    ]
    started = threading.Event()
    release = threading.Event()

    def blocking_hover(**_kwargs):
        started.set()
        release.wait(CALL_TIMEOUT_IN_SECONDS)
        return {"contents": ""}

    session.server.m_text_document__hover = blocking_hover
    hover = session.client._endpoint.request(
        "textDocument/hover", {"textDocument": {"uri": uri}, "position": pos(0, 0)}
    )
    assert started.wait(CALL_TIMEOUT_IN_SECONDS)
    generate_id = session.client._endpoint._id_generator
    session.client._endpoint._id_generator = lambda: "queued-command"
    try:
        queued = session.client._endpoint.request(
            "workspace/executeCommand",
            {"command": command["command"], "arguments": command["arguments"]},
        )
    finally:
        session.client._endpoint._id_generator = generate_id
    session.notify("$/cancelRequest", {"id": "queued-command"})
    # Release the worker only once the server has seen the cancellation.
    endpoint = session.server._endpoint
    deadline = time.monotonic() + CALL_TIMEOUT_IN_SECONDS
    while time.monotonic() < deadline:
        with endpoint._pending_lock:
            state = endpoint._pending.get("queued-command")
            if state is not None and state.is_set():
                break
        time.sleep(0.01)
    release.set()
    hover.result(timeout=CALL_TIMEOUT_IN_SECONDS)
    with pytest.raises(JsonRpcException) as error:
        queued.result(timeout=CALL_TIMEOUT_IN_SECONDS)
    assert error.value.code == ErrorCodes.RequestCancelled
    # A later request is answered, so the cancelled one was skipped.
    session.code_actions(uri, rng(2, 12))
    assert session.client.applied_edits == []


@pytest.mark.parametrize("capabilities", [COMMANDS_ONLY, RESOLVE])
def test_cancelled_running_refactoring_sends_no_edit(session_factory, capabilities):
    session = session_factory(capabilities)
    uri = session.open("helper_mod.py", HELPER)
    action = find(session.code_actions(uri, rng(0, 5)), "Inline method 'helper'")
    if "data" in action:
        method, params = "codeAction/resolve", action
    else:
        command = action["command"]
        method = "workspace/executeCommand"
        params = {"command": command["command"], "arguments": command["arguments"]}
    endpoint = session.server._endpoint
    entered, release, completed, cancelled = (threading.Event() for _ in range(4))
    original_changes = refactor_actions.Inline.changes
    original_notification = endpoint._handle_notification

    def slow_changes(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        changes = original_changes(*args, **kwargs)
        completed.set()
        return changes

    def observe_cancel(method, params):
        original_notification(method, params)
        if method == "$/cancelRequest" and params.get("id") == "running-refactoring":
            cancelled.set()

    with (
        patch.object(refactor_actions.Inline, "changes", slow_changes),
        patch.object(endpoint, "_handle_notification", observe_cancel),
        patch.object(
            session.server.workspace,
            "apply_edit",
            wraps=session.server.workspace.apply_edit,
        ) as apply_edit,
    ):
        with patch.object(
            session.client._endpoint,
            "_id_generator",
            return_value="running-refactoring",
        ):
            pending = session.client._endpoint.request(method, params)
        try:
            assert entered.wait(5)
            session.notify("$/cancelRequest", {"id": "running-refactoring"})
            assert cancelled.wait(5)
            # Document mutations stay queued while Rope finishes its work.
            session.change(uri, HELPER + "\n", 2)
            assert session.server.workspace.get_document(uri).source == HELPER
            assert not completed.is_set()
            assert not pending.done()
        finally:
            release.set()
        with pytest.raises(JsonRpcException) as error:
            pending.result(timeout=CALL_TIMEOUT_IN_SECONDS)
        assert error.value.code == ErrorCodes.RequestCancelled
        assert completed.is_set()
        apply_edit.assert_not_called()

    # Cancellation does not leak into later requests or lose queued changes.
    action = find(session.code_actions(uri, rng(0, 5)), "Inline method 'helper'")
    assert session.server.workspace.get_document(uri).source == HELPER + "\n"
    assert session.client.applied_edits == []
    assert session.edit_for(action)


def test_command_routed_to_the_documents_workspace(session_factory, tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    session = session_factory(
        root=first,
        workspaceFolders=[
            {"uri": uris.from_fs_path(str(first)), "name": "first"},
            {"uri": uris.from_fs_path(str(second)), "name": "second"},
        ],
    )
    session.root = str(second)
    helper_uri = session.open("helper_mod.py", HELPER)
    user_uri = session.write("user.py", USES_HELPER)
    command = find(
        session.code_actions(helper_uri, rng(0, 5)), "Inline method 'helper'"
    )["command"]
    edit = session.edit_for({"command": command})
    assert set(edit["changes"]) == {helper_uri, user_uri}
