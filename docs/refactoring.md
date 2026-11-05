# Rope refactorings

Rope language server offers Rope's refactorings as code actions. They are enabled
by default and need no other plugin. Every change goes back to the editor as a
workspace edit, so nothing is written to disk until you save, and you can undo it
in the editor like any other edit.

## Actions

Request code actions in your editor with the cursor on a name, or with a
selection for the extract actions.

| Action | Kind | Where | Files changed |
|---|---|---|---|
| Extract method | `refactor.extract` | A selection of whole statements or an expression | Current |
| Extract variable | `refactor.extract` | A selection that is an expression | Current |
| Inline method, variable or parameter | `refactor.inline` | The name of a function, a variable assigned once, or a parameter with a default | Current, or all that use the name |
| Use function | `refactor` | The name in a `def` line of a module-level function | Current, or all modules |
| Convert to method object | `refactor.rewrite` | The name in a `def` line | Current |
| Convert local variable to field | `refactor.rewrite` | A local variable of a method | Current |
| Introduce parameter | `refactor` | A name inside a function that is defined outside it | Current |
| Organise imports | `source.organizeImports` | Anywhere | Current |
| Generate variable, function or class | `quickfix` | An undefined name | Current, or the module named before the dot |

Some actions have variants:

- Both extract actions offer "including similar statements" when the module has
  other copies of the selected code, and "global" when the selection is inside a
  function, to define the new function or variable at module level.
- Use function can replace matching code in the whole project or in the current
  file only.

Rope cannot ask you for names, so the server chooses them: `extracted_method`,
`extracted_variable`, the selected name in lower case for a new parameter, and the
function name in CamelCase for a method object. A number is added if the name is
already used in the module. Rename the result afterwards if you want a different
name.

Generating modules and packages, and moving code between modules, are not
offered.

## Selections and the cursor

The extract actions use the selection and are not offered for an empty range.

The other actions act on the name at the cursor. They are offered when the
range:

- is empty, as Neovim sends it when nothing is selected;
- lies within one name;
- runs from the cursor to the end of the line, as some Vim clients send it.

A selection of an expression or of several lines does not offer them, so a
selected block does not also produce, for example, "Inline" for its first word.

## When actions are not offered

An action is only offered when Rope can perform it. In addition, the server does
not offer:

- any action for a module with a syntax error, for a notebook cell, or for a file
  that is outside the workspace folder or not saved to disk yet;
- actions that need the changes computed in advance when the editor asks
  automatically, for example to show a light bulb (`triggerKind` 2). They appear
  when you request code actions yourself;
- an action whose result would not parse.

Some restrictions work around Rope bugs and will go when Rope fixes them:

- Extract method is not offered in a class body
  ([rope#825](https://github.com/python-rope/rope/issues/825)).
- Inline method is not offered for special methods, abstract methods and methods
  that override a base class method
  ([rope#742](https://github.com/python-rope/rope/issues/742),
  [rope#744](https://github.com/python-rope/rope/issues/744),
  [rope#828](https://github.com/python-rope/rope/issues/828)).
- Organise imports is not offered in a package's `__init__.py` without `__all__`,
  in modules with string annotations, or when it would remove an import marked
  with `# noqa`
  ([rope#368](https://github.com/python-rope/rope/issues/368),
  [rope#369](https://github.com/python-rope/rope/issues/369)).
- Refactorings that change other modules are refused if a module that mentions
  the name has a syntax error, because Rope would skip it and leave it using the
  old name ([rope#923](https://github.com/python-rope/rope/issues/923)).

## How edits reach the editor

The server picks the first way the editor supports:

1. If the editor accepts versioned edits (`workspace.workspaceEdit.documentChanges`)
   and the server already computed the change to decide whether to offer the
   action, the code action carries the edit. The editor refuses it if the
   document changed in the meantime.
2. If the editor can resolve code actions (`codeAction.resolveSupport` with
   `edit`), the server computes the edit in `codeAction/resolve`.
3. Otherwise the code action runs a `rols.refactor.*` command, and the server
   sends the edit with `workspace/applyEdit`.

Organise imports always carries its edit, so editors can apply it on save.

Each action records a digest of the document. If the document changed after the
action was offered, the server refuses to run it, with a warning message or a
`ContentModified` error for `codeAction/resolve`. Request the code actions again.

Errors from Rope are shown as messages, or returned as `RequestFailed` errors from
`codeAction/resolve`. They do not stop the server.

## Configuration

To turn the actions off, set `rols.plugins.rope_refactor.enabled` to `false`. To
hide some of them, list their IDs in `rols.plugins.rope_refactor.disabled_actions`:

```json
{
  "rols": {
    "plugins": {
      "rope_refactor": {
        "disabled_actions": ["introduce_parameter", "organize_imports"]
      }
    }
  }
}
```

The IDs are `extract_method`, `extract_variable`, `inline`, `use_function`,
`method_to_method_object`, `local_to_field`, `introduce_parameter`,
`organize_imports` and `generate`. See also the
[configuration reference](https://codefloe.com/mcepl/rope-language-server/src/branch/main/CONFIGURATION.md).

## Limitations

- Rope works with the contents of open documents, including unsaved changes, and
  with the files on disk for everything else.
- Positions count Unicode code points, not the UTF-16 code units of the LSP
  default, as everywhere in the server. Lines with characters outside the Basic
  Multilingual Plane can be off by one.
- A refactoring that has started cannot be interrupted. Requests are handled one
  at a time, so a large inline or Use function across a big project delays later
  requests until it finishes.

## Coexistence with autoimport

The [autoimport](autoimport.md) quick fixes and Generate are both offered for an
undefined name. Autoimport needs a diagnostic for the name; Generate needs only
the cursor. Use `context.only` in the editor, for example `quickfix` or
`refactor`, to see one group of actions.

## Credits

The action list, titles and parts of the code come from
[pylsp-rope](https://github.com/python-rope/pylsp-rope) by Lie Ryan, released
under the MIT licence (see [LICENSES/pylsp-rope.txt](../LICENSES/pylsp-rope.txt)).
