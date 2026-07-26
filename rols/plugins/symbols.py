# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.
# Copyright 2024- Python Language Server Contributors (Rope backend).

"""Document symbols.

This is implemented on top of the standard library ``ast`` module rather than
Rope. Rope eagerly resolves imports while enumerating the names defined in a
module, which raises for unresolvable (e.g. relative) imports in in-memory
buffers that have no on-disk location. Walking the AST directly avoids that
fragility, needs no extra dependency and yields precise definition ranges.
"""

import ast
import logging

from rols import hookimpl
from rols.lsp import SymbolKind

log = logging.getLogger(__name__)


@hookimpl
def rols_document_symbols(config, workspace, document):
    symbols_settings = config.plugin_settings("jedi_symbols")
    all_scopes = symbols_settings.get("all_scopes", True)
    add_import_symbols = symbols_settings.get("include_import_symbols", True)

    try:
        tree = ast.parse(document.source)
    except SyntaxError as e:
        log.debug("Failed to parse document for symbols: %s", e)
        return []

    symbols = []
    _visit_body(
        tree.body,
        container=None,
        in_class=False,
        document=document,
        symbols=symbols,
        all_scopes=all_scopes,
        add_import_symbols=add_import_symbols,
    )
    return symbols


def _visit_body(
    body, container, in_class, document, symbols, all_scopes, add_import_symbols
):
    for node in body:
        _visit_node(
            node,
            container=container,
            in_class=in_class,
            document=document,
            symbols=symbols,
            all_scopes=all_scopes,
            add_import_symbols=add_import_symbols,
        )


def _visit_node(
    node, container, in_class, document, symbols, all_scopes, add_import_symbols
):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        if not add_import_symbols:
            return
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            if name == "*":
                continue
            _add(symbols, name, container, SymbolKind.Module, node, document)
        return

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        kind = SymbolKind.Method if in_class else SymbolKind.Function
        _add(symbols, node.name, container, kind, node, document)
        if all_scopes:
            _visit_body(
                node.body,
                container=node.name,
                in_class=False,
                document=document,
                symbols=symbols,
                all_scopes=all_scopes,
                add_import_symbols=add_import_symbols,
            )
        return

    if isinstance(node, ast.ClassDef):
        _add(symbols, node.name, container, SymbolKind.Class, node, document)
        if all_scopes:
            _visit_body(
                node.body,
                container=node.name,
                in_class=True,
                document=document,
                symbols=symbols,
                all_scopes=all_scopes,
                add_import_symbols=add_import_symbols,
            )
        return

    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            _visit_target(target, container, in_class, document, symbols)
        return


def _visit_target(target, container, in_class, document, symbols):
    if isinstance(target, ast.Name):
        if target.id == "_":
            return
        kind = SymbolKind.Field if in_class else SymbolKind.Variable
        _add(symbols, target.id, container, kind, target, document)
    elif (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        # ``self.x = ...`` inside a method is a field of the enclosing class.
        _add(symbols, target.attr, container, SymbolKind.Field, target, document)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for element in target.elts:
            _visit_target(element, container, in_class, document, symbols)


def _add(symbols, name, container, kind, node, document):
    symbols.append(
        {
            "name": name,
            "containerName": container,
            "location": {
                "uri": document.uri,
                "range": _range(node),
            },
            "kind": kind,
        }
    )


def _range(node):
    start_line = node.lineno - 1
    start_char = node.col_offset
    end_line = getattr(node, "end_lineno", node.lineno) - 1
    end_char = getattr(node, "end_col_offset", node.col_offset)
    return {
        "start": {"line": start_line, "character": start_char},
        "end": {"line": end_line, "character": end_char},
    }
