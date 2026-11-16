# Copyright 2026- Python Language Server Contributors (Rope backend).
# Adapted from pylsp-rope (https://github.com/python-rope/pylsp-rope),
# Copyright (c) 2021 Lie Ryan, MIT licence; see LICENSES/pylsp-rope.txt.

"""The Rope refactorings offered as code actions.

Each action decides from a :class:`Request` whether it can be offered, and
later computes the Rope change set from the parameters it stored in the
offer. The parameters travel to the client and back, either as command
arguments or as ``codeAction/resolve`` data, so they only contain JSON
values: offsets into Rope's text and the names chosen when offering.
"""

import ast
import keyword
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from rope.base import evaluate, pyobjects
from rope.base.exceptions import RefactoringError
from rope.contrib import generate
from rope.refactor import (
    extract,
    functionutils,
    importutils,
    inline,
    introduce_parameter,
    localtofield,
    method_object,
    usefunction,
)

from rols.plugins import _rope_utils

log = logging.getLogger(__name__)

TRIGGER_AUTOMATIC = 2
_IDENTIFIER = re.compile(r"[^\W\d]\w*")
_DEF_NAME = re.compile(r"(?:async\s+)?def\s+(\w+)")


@dataclass
class Request:
    """What a ``textDocument/codeAction`` request asks about."""

    project: Any
    resource: Any
    text: str  # the module as Rope sees it, with ``\n`` line endings
    tree: ast.Module
    start: int  # the requested range, as offsets into ``text``
    end: int
    point: Optional[int]  # offset of the identifier under the cursor
    automatic: bool  # requested without user action, e.g. for a lightbulb
    only: Optional[list]
    diagnostics: list
    filename: str

    @property
    def selection(self):
        return self.text[self.start : self.end]

    def wants(self, kind):
        """Whether ``context.only`` asks for ``kind`` explicitly."""
        return bool(self.only) and any(
            kind == wanted or kind.startswith(wanted + ".") for wanted in self.only
        )


@dataclass
class Offer:
    title: str
    kind: str
    params: dict
    # Set when the edit is computed while offering the action.
    changes: Any = None
    diagnostics: list = field(default_factory=list)


class Action:
    """A family of related code actions backed by one Rope refactoring."""

    id: str
    command: str
    kind: str

    def offers(self, request):  # pragma: no cover - interface
        raise NotImplementedError

    def changes(self, project, resource, params, task_handle):  # pragma: no cover
        raise NotImplementedError

    def is_cross_file(self, params):
        """Whether the refactoring may change modules that use a name."""
        return False

    def names_used_elsewhere(self, params):
        """Names that other modules must mention for the change to touch them."""
        return []


# Helpers


def identifier_at(text, offset):
    """Return ``(name, start, end)`` for the identifier at ``offset``, if any.

    An offset just after the last character of a name also counts, because
    that is where the cursor sits after typing it.
    """
    start = offset
    while start > 0 and (text[start - 1].isalnum() or text[start - 1] == "_"):
        start -= 1
    end = offset
    while end < len(text) and (text[end].isalnum() or text[end] == "_"):
        end += 1
    word = text[start:end]
    if not word or not _IDENTIFIER.fullmatch(word) or keyword.iskeyword(word):
        return None
    return word, start, end


def point_for_range(text, start, end):
    """Return the offset that point-based refactorings should act on.

    That is the start of the range when the range is empty, lies within one
    identifier, or runs from the cursor to the end of its line, as some Vim
    clients send it. Any other selection is not a point, so it does not
    offer inline, generate and similar actions for its first word.
    """
    if start == end:
        return start
    selection = text[start:end]
    if selection.endswith("\n"):
        selection = selection[:-1]
    if "\n" in selection:
        return None
    found = identifier_at(text, start)
    if found and found[1] <= start and end <= found[2]:
        return start
    if end == len(text) or text[end - 1] == "\n" or text[end] == "\n":
        return start
    return None


def fresh_name(text, base):
    """Return ``base``, or ``base_2``, ``base_3``..., unused in ``text``.

    Rope doesn't refuse a new name that is already in use
    (python-rope/rope#924), so avoid every identifier in the module.
    """
    used = set(_IDENTIFIER.findall(text))
    if base not in used and not keyword.iskeyword(base):
        return base
    number = 2
    while f"{base}_{number}" in used:
        number += 1
    return f"{base}_{number}"


def camel_case(name):
    parts = [part for part in name.split("_") if part]
    return "".join(part[0].upper() + part[1:] for part in parts) or "MethodObject"


def def_name_at(request, offset):
    """Return the function definition whose name contains ``offset``."""
    line_starts = [0]
    for match in re.finditer("\n", request.text):
        line_starts.append(match.end())
    for node in ast.walk(request.tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        line_start = line_starts[node.lineno - 1]
        line_end = request.text.find("\n", line_start)
        line = request.text[line_start : line_end if line_end >= 0 else None]
        match = _DEF_NAME.match(line, node.col_offset)
        if match and match.start(1) <= offset - line_start <= match.end(1):
            return node
    return None


def new_contents(changes):
    return [change.new_contents for change in changes.changes]


def parses(changes):
    for change in changes.changes:
        if getattr(change, "new_contents", None) is None:
            return False
        if change.resource.name.endswith((".py", ".pyi")):
            try:
                ast.parse(change.new_contents)
            except (SyntaxError, ValueError):
                return False
    return True


def scope_kind_at(project, resource, offset):
    scope = project.get_pymodule(resource).get_scope()
    return scope.get_inner_scope_for_offset(offset).get_kind()


def try_changes(make):
    """Return the change set from ``make()``, or ``None`` if Rope can't do it."""
    try:
        changes = make()
    except Exception as exc:  # Rope raises many kinds of errors here.
        log.debug("Rope refused the refactoring: %s", exc)
        return None
    if changes is None or not changes.changes or not parses(changes):
        return None
    return changes


# Extract


class _Extract(Action):
    kind = "refactor.extract"
    rope_class = None
    noun = ""
    base_name = ""

    def selection_ok(self, request):
        return bool(request.selection.strip())

    def offers(self, request):
        if request.automatic or not self.selection_ok(request):
            return []
        start, end = request.start, request.end
        try:
            scope = scope_kind_at(
                request.project,
                request.resource,
                start + len(request.selection) - len(request.selection.lstrip()),
            )
        except Exception:
            return []
        if not self.scope_ok(scope):
            return []
        name = fresh_name(request.text, self.base_name)

        def compute(similar, global_):
            return try_changes(
                lambda: self.rope_class(
                    request.project, request.resource, start, end
                ).get_changes(name, similar=similar, global_=global_)
            )

        plain = compute(False, False)
        if plain is None:
            return []
        params = {"start": start, "end": end, "name": name}
        offers = [
            Offer(
                f"Extract {self.noun}",
                self.kind,
                dict(params, similar=False, global_=False),
                changes=plain,
            )
        ]
        similar = compute(True, False)
        has_similar = similar is not None and new_contents(similar) != new_contents(
            plain
        )
        if has_similar:
            offers.append(
                Offer(
                    f"Extract {self.noun} including similar statements",
                    self.kind,
                    dict(params, similar=True, global_=False),
                    changes=similar,
                )
            )
        if scope == "Function":
            for similar_flag in (False, True) if has_similar else (False,):
                changes = compute(similar_flag, True)
                if changes is None:
                    continue
                suffix = " including similar statements" if similar_flag else ""
                offers.append(
                    Offer(
                        f"Extract global {self.noun}{suffix}",
                        self.kind,
                        dict(params, similar=similar_flag, global_=True),
                        changes=changes,
                    )
                )
        return offers

    def scope_ok(self, scope):
        return True

    def changes(self, project, resource, params, task_handle):
        return self.rope_class(
            project, resource, params["start"], params["end"]
        ).get_changes(
            params["name"], similar=params["similar"], global_=params["global_"]
        )


class ExtractMethod(_Extract):
    id = "extract_method"
    command = "rols.refactor.extract.method"
    rope_class = extract.ExtractMethod
    noun = "method"
    base_name = "extracted_method"

    def scope_ok(self, scope):
        # Rope defines a function extracted from a class body after the
        # class, which raises NameError (python-rope/rope#825).
        return scope != "Class"


class ExtractVariable(_Extract):
    id = "extract_variable"
    command = "rols.refactor.extract.variable"
    rope_class = extract.ExtractVariable
    noun = "variable"
    base_name = "extracted_variable"

    def selection_ok(self, request):
        selection = request.selection.strip()
        if not selection:
            return False
        try:
            ast.parse(selection, mode="eval")
        except (SyntaxError, ValueError):
            return False
        return True


# Inline


def _is_risky_method(pyfunction):
    """Methods that inline method gets wrong (python-rope/rope#742 and others)."""
    name = pyfunction.get_name()
    if name.startswith("__") and name.endswith("__"):
        return True
    for decorator in pyfunction.decorators or []:
        try:
            if "abstractmethod" in ast.unparse(decorator):
                return True
        except Exception:
            pass
    parent = pyfunction.parent
    if isinstance(parent, pyobjects.PyClass):
        try:
            for superclass in parent.get_superclasses():
                if name in superclass.get_attributes():
                    return True
        except Exception:
            return True
    return False


def _has_default(pyname):
    try:
        pymodule, lineno = pyname.get_definition_location()
        scope = pymodule.get_scope().get_inner_scope_for_line(lineno)
        arguments = functionutils.DefinitionInfo.read(scope.pyobject).args_with_defaults
        return arguments[pyname.index][1] is not None
    except Exception:
        return False


class Inline(Action):
    id = "inline"
    command = "rols.refactor.inline"
    kind = "refactor.inline"

    def offers(self, request):
        if request.point is None:
            return []
        found = identifier_at(request.text, request.point)
        if found is None:
            return []
        name, offset, _ = found
        try:
            refactoring = inline.create_inline(
                request.project, request.resource, offset
            )
        except Exception as exc:
            log.debug("Rope refused inline: %s", exc)
            return []
        kind = refactoring.get_kind()
        params = {"offset": offset, "name": name, "inline_kind": kind}
        offer = Offer(f"Inline {kind} '{name}'", self.kind, params)
        if kind == "method":
            if _is_risky_method(refactoring.pyfunction):
                return []
        elif kind == "parameter":
            # Inlining a parameter moves its default value into the calls.
            if not _has_default(refactoring.pyname):
                return []
        elif kind == "variable" and self._is_local(refactoring, request.resource):
            if request.automatic:
                return []
            changes = try_changes(
                lambda: refactoring.get_changes(resources=[request.resource])
            )
            if changes is None:
                return []
            offer.changes = changes
            params["local"] = True
        return [offer]

    @staticmethod
    def _is_local(refactoring, resource):
        try:
            pymodule, lineno = refactoring.pyname.get_definition_location()
            scope = pymodule.get_scope().get_inner_scope_for_line(lineno)
            return (
                scope.get_kind() == "Function" and pymodule.get_resource() == resource
            )
        except Exception:
            return False

    def is_cross_file(self, params):
        return not params.get("local", False)

    def names_used_elsewhere(self, params):
        return [params["name"]]

    def changes(self, project, resource, params, task_handle):
        refactoring = inline.create_inline(project, resource, params["offset"])
        if refactoring.get_kind() != params["inline_kind"]:
            raise RefactoringError("The name under the cursor has changed.")
        if params.get("local"):
            return refactoring.get_changes(resources=[resource])
        return refactoring.get_changes(task_handle=task_handle)


# Use function


class UseFunction(Action):
    id = "use_function"
    command = "rols.refactor.use_function"
    kind = "refactor"

    def offers(self, request):
        if request.point is None or def_name_at(request, request.point) is None:
            return []
        name, offset, _ = identifier_at(request.text, request.point)
        try:
            usefunction.UseFunction(request.project, request.resource, offset)
        except Exception as exc:
            log.debug("Rope refused use function: %s", exc)
            return []
        params = {"offset": offset, "name": name}
        return [
            Offer(
                f"Use function '{name}'", self.kind, dict(params, whole_project=True)
            ),
            Offer(
                f"Use function '{name}' in this file",
                self.kind,
                dict(params, whole_project=False),
            ),
        ]

    def is_cross_file(self, params):
        return params["whole_project"]

    def names_used_elsewhere(self, params):
        return [params["name"]]

    def changes(self, project, resource, params, task_handle):
        refactoring = usefunction.UseFunction(project, resource, params["offset"])
        resources = None if params["whole_project"] else [resource]
        return refactoring.get_changes(resources=resources, task_handle=task_handle)


# Rewrites in the current module


class MethodToMethodObject(Action):
    id = "method_to_method_object"
    command = "rols.refactor.method_to_method_object"
    kind = "refactor.rewrite"

    def offers(self, request):
        if request.automatic or request.point is None:
            return []
        if def_name_at(request, request.point) is None:
            return []
        name, offset, _ = identifier_at(request.text, request.point)
        try:
            refactoring = method_object.MethodObject(
                request.project, request.resource, offset
            )
        except Exception as exc:
            log.debug("Rope refused method object: %s", exc)
            return []
        if refactoring.resource != request.resource:
            return []
        classname = fresh_name(request.text, camel_case(name))
        changes = try_changes(lambda: refactoring.get_changes(classname))
        if changes is None:
            return []
        return [
            Offer(
                f"Convert '{name}' to method object",
                self.kind,
                {"offset": offset, "classname": classname},
                changes=changes,
            )
        ]

    def changes(self, project, resource, params, task_handle):
        return method_object.MethodObject(
            project, resource, params["offset"]
        ).get_changes(params["classname"])


class LocalToField(Action):
    id = "local_to_field"
    command = "rols.refactor.local_to_field"
    kind = "refactor.rewrite"

    def offers(self, request):
        if request.automatic or request.point is None:
            return []
        found = identifier_at(request.text, request.point)
        if found is None:
            return []
        name, offset, _ = found
        if self._field_exists(request, offset, name):
            return []
        changes = try_changes(
            lambda: localtofield.LocalToField(
                request.project, request.resource, offset
            ).get_changes()
        )
        if changes is None:
            return []
        return [
            Offer(
                f"Convert local variable '{name}' to field",
                self.kind,
                {"offset": offset},
                changes=changes,
            )
        ]

    @staticmethod
    def _field_exists(request, offset, name):
        """Rope doesn't check whether the class already has the attribute."""
        try:
            pymodule = request.project.get_pymodule(request.resource)
            pyname = evaluate.eval_location(pymodule, offset)
            definition_module, lineno = pyname.get_definition_location()
            scope = definition_module.get_scope().get_inner_scope_for_line(lineno)
            class_scope = scope.parent
            return class_scope is None or name in class_scope.pyobject
        except Exception:
            return True

    def changes(self, project, resource, params, task_handle):
        return localtofield.LocalToField(
            project, resource, params["offset"]
        ).get_changes()


class IntroduceParameter(Action):
    id = "introduce_parameter"
    command = "rols.refactor.introduce_parameter"
    kind = "refactor"

    def offers(self, request):
        if request.automatic or request.point is None:
            return []
        found = identifier_at(request.text, request.point)
        if found is None:
            return []
        name, offset, _ = found
        if def_name_at(request, offset) is not None:
            return []
        try:
            refactoring = introduce_parameter.IntroduceParameter(
                request.project, request.resource, offset
            )
        except Exception as exc:
            log.debug("Rope refused introduce parameter: %s", exc)
            return []
        if self._defined_inside(refactoring, request):
            return []
        parameter = fresh_name(request.text, name.lower())
        changes = try_changes(lambda: refactoring.get_changes(parameter))
        if changes is None:
            return []
        return [
            Offer(
                f"Introduce parameter for '{name}'",
                self.kind,
                {"offset": offset, "parameter": parameter},
                changes=changes,
            )
        ]

    @staticmethod
    def _defined_inside(refactoring, request):
        """Whether the name is defined in the function that would get the parameter.

        A parameter's default is evaluated when the function is defined, so
        it can only refer to names from outside the function.
        """
        try:
            module, lineno = refactoring.pyname.get_definition_location()
        except Exception:
            return True
        if module is None or module.get_resource() != request.resource:
            return False
        scope = refactoring.pyfunction.get_scope()
        return lineno is None or scope.get_start() <= lineno <= scope.get_end()

    def changes(self, project, resource, params, task_handle):
        return introduce_parameter.IntroduceParameter(
            project, resource, params["offset"]
        ).get_changes(params["parameter"])


# Organise imports


def _has_string_annotations(tree):
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, ast.arg):
            annotations.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations.append(node.annotation)
        for annotation in annotations:
            if annotation is None:
                continue
            for inner in ast.walk(annotation):
                if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                    return True
    return False


def _keeps_noqa_imports(old, new):
    kept = set(new.splitlines())
    for line in old.splitlines():
        stripped = line.strip()
        if "noqa" in line and stripped.startswith(("import ", "from ")):
            if line not in kept:
                return False
    return True


def _defines_all(tree):
    """Whether the module explicitly assigns its public exports."""
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in targets
        ):
            return True
    return False


class OrganizeImports(Action):
    id = "organize_imports"
    command = "rols.source.organize_imports"
    kind = "source.organizeImports"

    def offers(self, request):
        if request.automatic and not request.wants(self.kind):
            return []
        # Rope removes imports that are only re-exported or only used in
        # string annotations (python-rope/rope#368, #369).
        if request.filename == "__init__.py" and not _defines_all(request.tree):
            return []
        if _has_string_annotations(request.tree):
            return []
        changes = try_changes(
            lambda: importutils.ImportOrganizer(request.project).organize_imports(
                request.resource
            )
        )
        if changes is None or not _keeps_noqa_imports(
            request.text, changes.changes[0].new_contents
        ):
            return []
        return [Offer("Organise imports", self.kind, {}, changes=changes)]

    def changes(self, project, resource, params, task_handle):
        return importutils.ImportOrganizer(project).organize_imports(resource)


# Generate


class Generate(Action):
    id = "generate"
    command = "rols.quickfix.generate"
    kind = "quickfix"
    generate_kinds = ("variable", "function", "class")

    def offers(self, request):
        if request.point is None:
            return []
        found = identifier_at(request.text, request.point)
        if found is None:
            return []
        name, offset, end = found
        try:
            pymodule = request.project.get_pymodule(request.resource)
            if evaluate.eval_location(pymodule, offset) is not None:
                return []
        except Exception:
            return []
        offers = []
        for generate_kind in self.generate_kinds:
            try:
                generate.create_generate(
                    generate_kind, request.project, request.resource, offset
                )
            except Exception as exc:
                log.debug("Rope refused generate %s: %s", generate_kind, exc)
                return []
            offers.append(
                Offer(
                    f"Generate {generate_kind} '{name}'",
                    self.kind,
                    {"offset": offset, "generate_kind": generate_kind},
                    diagnostics=_diagnostics_at(request, offset, end),
                )
            )
        return offers

    def changes(self, project, resource, params, task_handle):
        if params["generate_kind"] not in self.generate_kinds:
            raise RefactoringError("Unsupported kind of generated code.")
        return generate.create_generate(
            params["generate_kind"], project, resource, params["offset"]
        ).get_changes()


def _diagnostics_at(request, start, end):
    line = request.text.count("\n", 0, start)
    line_start = request.text.rfind("\n", 0, start) + 1
    first = _rope_utils.utf16_length(request.text[line_start:start])
    last = _rope_utils.utf16_length(request.text[line_start:end])
    found = []
    for diagnostic in request.diagnostics or []:
        try:
            diag_start = diagnostic["range"]["start"]
            diag_end = diagnostic["range"]["end"]
        except (KeyError, TypeError):
            continue
        if diag_start.get("line") != line:
            continue
        if (
            diag_start.get("character", 0) <= last
            and diag_end.get("character", 0) >= first
        ):
            found.append(diagnostic)
    return found


ACTIONS = [
    ExtractMethod(),
    ExtractVariable(),
    Inline(),
    UseFunction(),
    MethodToMethodObject(),
    LocalToField(),
    IntroduceParameter(),
    OrganizeImports(),
    Generate(),
]
BY_COMMAND = {action.command: action for action in ACTIONS}
