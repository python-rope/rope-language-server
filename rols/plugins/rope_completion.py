# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

import logging

from rope.contrib.codeassist import code_assist, sorted_proposals

from rols import _utils, hookimpl, lsp

log = logging.getLogger(__name__)

# Parameters that should never be offered as snippet tab-stops.
_SKIP_PARAMS = ("self", "cls")


@hookimpl
def rols_settings():
    # rope_completion is the native completion provider and is enabled by
    # default (replacing the legacy jedi-based completion).
    return {
        "plugins": {
            "rope_completion": {
                "enabled": True,
                "eager": False,
                "include_params": True,
            }
        }
    }


def _resolve_completion(completion, data, markup_kind):
    try:
        doc = _utils.format_docstring(data.get_doc(), markup_kind=markup_kind)
    except Exception as e:
        log.debug("Failed to resolve Rope completion: %s", e)
        doc = ""
    completion["detail"] = "{} {}".format(data.scope or "", data.name)
    completion["documentation"] = doc
    return completion


@hookimpl
def rols_completions(config, workspace, document, position):
    settings = config.plugin_settings("rope_completion", document_path=document.path)
    resolve_eagerly = settings.get("eager", False)

    # Rope is a bit rubbish at completing module imports, so we'll return None
    word = document.word_at_position(
        {
            # The -1 should really be trying to look at the previous word, but that might be quite expensive
            # So we only skip import completions when the cursor is one space after `import`
            "line": position["line"],
            "character": max(position["character"] - 1, 0),
        }
    )
    if word == "import":
        return None

    offset = document.offset_at_position(position)
    rope_config = config.settings(document_path=document.path).get("rope", {})

    completion_capabilities = config.capabilities.get("textDocument", {}).get(
        "completion", {}
    )
    item_capabilities = completion_capabilities.get("completionItem", {})
    snippet_support = item_capabilities.get("snippetSupport")
    supported_markup_kinds = item_capabilities.get("documentationFormat", ["markdown"])
    preferred_markup_kind = _utils.choose_markup_kind(supported_markup_kinds)

    should_include_params = settings.get("include_params", True)
    include_params = snippet_support and should_include_params

    try:
        rope_project = workspace._rope_project_builder(rope_config)
    except Exception as e:
        log.debug("Failed to build Rope project: %s", e)
        return []

    try:
        document_rope = document._rope_resource(rope_config)
    except Exception:
        # In-memory-only documents (e.g. notebook cells or transient temp
        # documents) have no on-disk resource. Code assist can still complete
        # from the source alone, so fall back to a resource-less request.
        document_rope = None

    try:
        definitions = code_assist(
            rope_project, document.source, offset, document_rope, maxfixes=3
        )
    except Exception as e:
        # Transient syntax errors can make code assist fail; degrade gracefully
        # instead of aborting the completion hook.
        log.debug("Failed to run Rope code assist: %s", e)
        return []

    definitions = sorted_proposals(definitions)
    new_definitions = []
    for d in definitions:
        item = {
            "label": d.name,
            "kind": _kind(d),
            "sortText": _sort_text(d),
            "data": {"doc_uri": document.uri},
        }
        if include_params:
            item.update(_snippet(d))
        if resolve_eagerly:
            item = _resolve_completion(item, d, preferred_markup_kind)
        new_definitions.append(item)

    # most recently retrieved completion items, used for resolution
    document.shared_data["LAST_ROPE_COMPLETIONS"] = {
        # label is the only required property; here it is assumed to be unique
        completion["label"]: (completion, data)
        for completion, data in zip(new_definitions, definitions)
    }

    definitions = new_definitions

    return definitions or None


@hookimpl
def rols_completion_item_resolve(config, completion_item, document):
    """Resolve formatted completion for given non-resolved completion"""
    shared_data = document.shared_data["LAST_ROPE_COMPLETIONS"].get(
        completion_item["label"]
    )

    completion_capabilities = config.capabilities.get("textDocument", {}).get(
        "completion", {}
    )
    item_capabilities = completion_capabilities.get("completionItem", {})
    supported_markup_kinds = item_capabilities.get("documentationFormat", ["markdown"])
    preferred_markup_kind = _utils.choose_markup_kind(supported_markup_kinds)

    if shared_data:
        completion, data = shared_data
        return _resolve_completion(completion, data, preferred_markup_kind)
    return completion_item


def _snippet(definition):
    """Build a parameter snippet for callable Rope proposals.

    Rope exposes the parameter names of functions and classes via the
    ``parameters`` property. We turn those into an LSP snippet with a
    tab-stop per parameter. Unlike Jedi, Rope does not tell us which
    parameters have default values, so as a best-effort we only skip the
    implicit ``self``/``cls`` parameters.
    """
    if definition.type not in ("function", "class"):
        return {}

    try:
        parameters = definition.parameters
    except Exception as e:
        log.debug("Failed to get Rope parameters: %s", e)
        parameters = None

    if not parameters:
        # Still emit an empty call with the cursor between the parentheses.
        return {
            "insertText": f"{definition.name}($0)",
            "insertTextFormat": lsp.InsertTextFormat.Snippet,
        }

    params = [p for p in parameters if p not in _SKIP_PARAMS]
    snippet = definition.name + "("
    snippet += ", ".join(f"${{{i}:{param}}}" for i, param in enumerate(params, start=1))
    snippet += ")$0"
    return {
        "insertText": snippet,
        "insertTextFormat": lsp.InsertTextFormat.Snippet,
    }


def _sort_text(definition):
    """Ensure builtins appear at the bottom.
    Description is of format <type>: <module>.<item>
    """
    if definition.name.startswith("_"):
        # It's a 'hidden' func, put it next last
        return "z" + definition.name
    if definition.scope == "builtin":
        return "y" + definition.name

    # Else put it at the front
    return "a" + definition.name


def _kind(d):
    """Return the LSP type"""
    # Keywords carry a ``None`` type in Rope, so key off the scope instead.
    if getattr(d, "scope", None) == "keyword":
        return lsp.CompletionItemKind.Keyword

    MAP = {
        "none": lsp.CompletionItemKind.Value,
        "type": lsp.CompletionItemKind.Class,
        "tuple": lsp.CompletionItemKind.Class,
        "dict": lsp.CompletionItemKind.Class,
        "dictionary": lsp.CompletionItemKind.Class,
        "function": lsp.CompletionItemKind.Function,
        "lambda": lsp.CompletionItemKind.Function,
        "generator": lsp.CompletionItemKind.Function,
        "class": lsp.CompletionItemKind.Class,
        "instance": lsp.CompletionItemKind.Reference,
        "method": lsp.CompletionItemKind.Method,
        "builtin": lsp.CompletionItemKind.Class,
        "builtinfunction": lsp.CompletionItemKind.Function,
        "module": lsp.CompletionItemKind.Module,
        "file": lsp.CompletionItemKind.File,
        "xrange": lsp.CompletionItemKind.Class,
        "slice": lsp.CompletionItemKind.Class,
        "traceback": lsp.CompletionItemKind.Class,
        "frame": lsp.CompletionItemKind.Class,
        "buffer": lsp.CompletionItemKind.Class,
        "dictproxy": lsp.CompletionItemKind.Class,
        "funcdef": lsp.CompletionItemKind.Function,
        "property": lsp.CompletionItemKind.Property,
        "import": lsp.CompletionItemKind.Module,
        "keyword": lsp.CompletionItemKind.Keyword,
        "constant": lsp.CompletionItemKind.Variable,
        "variable": lsp.CompletionItemKind.Variable,
        "value": lsp.CompletionItemKind.Value,
        "param": lsp.CompletionItemKind.Variable,
        "statement": lsp.CompletionItemKind.Keyword,
    }

    return MAP.get(d.type)
