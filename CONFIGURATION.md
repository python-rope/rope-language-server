# Python Language Server Configuration
This server can be configured using the `workspace/didChangeConfiguration` method. Each configuration option is described below. Note, a value of `null` means that we do not set a value and thus use the plugin's default value.

| **Configuration Key** | **Type** | **Description** | **Default** 
|----|----|----|----|
| `rols.configurationSources` | `array` of unique `string` (one of: `'pycodestyle'`, `'flake8'`) items | List of configuration sources to use. | `["pycodestyle"]` |
| `rols.plugins.autopep8.enabled` | `boolean` | Enable or disable the plugin (disabling required to use `yapf`). | `true` |
| `rols.plugins.flake8.config` | `string` | Path to the config file that will be the authoritative config source. | `null` |
| `rols.plugins.flake8.enabled` | `boolean` | Enable or disable the plugin. | `false` |
| `rols.plugins.flake8.exclude` | `array` of `string` items | List of files or directories to exclude. | `[]` |
| `rols.plugins.flake8.extendIgnore` | `array` of `string` items | List of errors and warnings to append to ignore list. | `[]` |
| `rols.plugins.flake8.extendSelect` | `array` of `string` items | List of errors and warnings to append to select list. | `[]` |
| `rols.plugins.flake8.executable` | `string` | Path to the flake8 executable. | `"flake8"` |
| `rols.plugins.flake8.filename` | `string` | Only check for filenames matching the patterns in this list. | `null` |
| `rols.plugins.flake8.hangClosing` | `boolean` | Hang closing bracket instead of matching indentation of opening bracket's line. | `null` |
| `rols.plugins.flake8.ignore` | `array` of `string` items | List of errors and warnings to ignore (or skip). | `[]` |
| `rols.plugins.flake8.maxComplexity` | `integer` | Maximum allowed complexity threshold. | `null` |
| `rols.plugins.flake8.maxLineLength` | `integer` | Maximum allowed line length for the entirety of this run. | `null` |
| `rols.plugins.flake8.indentSize` | `integer` | Set indentation spaces. | `null` |
| `rols.plugins.flake8.perFileIgnores` | `array` of `string` items | A pairing of filenames and violation codes that defines which violations to ignore in a particular file, for example: `["file_path.py:W305,W304"]`). | `[]` |
| `rols.plugins.flake8.select` | `array` of unique `string` items | List of errors and warnings to enable. | `null` |
| `rols.plugins.jedi_hover.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.plugins.jedi_references.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.plugins.jedi_signature_help.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.plugins.jedi_symbols.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.plugins.jedi_symbols.all_scopes` | `boolean` | If True lists the names of all scopes instead of only the module namespace. | `true` |
| `rols.plugins.jedi_symbols.include_import_symbols` | `boolean` | If True includes symbols imported from other libraries. | `true` |
| `rols.plugins.mccabe.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.plugins.mccabe.threshold` | `integer` | The minimum threshold that triggers warnings about cyclomatic complexity. | `15` |
| `rols.plugins.preload.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.plugins.preload.modules` | `array` of unique `string` items | List of modules to import on startup | `[]` |
| `rols.plugins.pycodestyle.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.plugins.pycodestyle.exclude` | `array` of unique `string` items | Exclude files or directories which match these patterns. | `[]` |
| `rols.plugins.pycodestyle.filename` | `array` of unique `string` items | When parsing directories, only check filenames matching these patterns. | `[]` |
| `rols.plugins.pycodestyle.select` | `array` of unique `string` items | Select errors and warnings | `null` |
| `rols.plugins.pycodestyle.ignore` | `array` of unique `string` items | Ignore errors and warnings | `[]` |
| `rols.plugins.pycodestyle.hangClosing` | `boolean` | Hang closing bracket instead of matching indentation of opening bracket's line. | `null` |
| `rols.plugins.pycodestyle.maxLineLength` | `integer` | Set maximum allowed line length. | `null` |
| `rols.plugins.pycodestyle.indentSize` | `integer` | Set indentation spaces. | `null` |
| `rols.plugins.pydocstyle.enabled` | `boolean` | Enable or disable the plugin. | `false` |
| `rols.plugins.pydocstyle.convention` | `string` (one of: `'pep257'`, `'numpy'`, `'google'`, `None`) | Choose the basic list of checked errors by specifying an existing convention. | `null` |
| `rols.plugins.pydocstyle.addIgnore` | `array` of unique `string` items | Ignore errors and warnings in addition to the specified convention. | `[]` |
| `rols.plugins.pydocstyle.addSelect` | `array` of unique `string` items | Select errors and warnings in addition to the specified convention. | `[]` |
| `rols.plugins.pydocstyle.ignore` | `array` of unique `string` items | Ignore errors and warnings | `[]` |
| `rols.plugins.pydocstyle.select` | `array` of unique `string` items | Select errors and warnings | `null` |
| `rols.plugins.pydocstyle.match` | `string` | Check only files that exactly match the given regular expression; default is to match files that don't start with 'test_' but end with '.py'. | `"(?!test_).*\\.py"` |
| `rols.plugins.pydocstyle.matchDir` | `string` | Search only dirs that exactly match the given regular expression; default is to match dirs which do not begin with a dot. | `"[^\\.].*"` |
| `rols.plugins.pyflakes.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.plugins.pylint.enabled` | `boolean` | Enable or disable the plugin. | `false` |
| `rols.plugins.pylint.args` | `array` of non-unique `string` items | Arguments to pass to pylint. | `[]` |
| `rols.plugins.pylint.executable` | `string` | Executable to run pylint with. Enabling this will run pylint on unsaved files via stdin. Can slow down workflow. Only works with python3. | `null` |
| `rols.plugins.rope_autoimport.enabled` | `boolean` | Enable or disable autoimport. If false, neither completions nor code actions are enabled. If true, the respective features can be enabled or disabled individually. | `false` |
| `rols.plugins.rope_autoimport.completions.enabled` | `boolean` | Enable or disable autoimport completions. | `true` |
| `rols.plugins.rope_autoimport.code_actions.enabled` | `boolean` | Enable or disable autoimport code actions (e.g. for quick fixes). | `true` |
| `rols.plugins.rope_autoimport.memory` | `boolean` | Make the autoimport database memory only. Drastically increases startup time. | `false` |
| `rols.plugins.rope_completion.enabled` | `boolean` | Enable or disable the plugin. This is the native Rope-based completion provider, enabled by default. | `true` |
| `rols.plugins.rope_completion.include_params` | `boolean` | Auto-completes methods and classes with tabstops for each parameter. | `true` |
| `rols.plugins.rope_completion.eager` | `boolean` | Resolve documentation and detail eagerly. | `false` |
| `rols.plugins.yapf.enabled` | `boolean` | Enable or disable the plugin. | `true` |
| `rols.rope.extensionModules` | `string` | Builtin and c-extension modules that are allowed to be imported and inspected by rope. | `null` |
| `rols.rope.ropeFolder` | `array` of unique `string` items | The name of the folder in which rope stores project configurations and data.  Pass `null` for not using such a folder at all. | `null` |
| `rols.signature.formatter` | `string` (one of: `'black'`, `None`) | Formatter to use for reformatting signatures in docstrings. | `"black"` |
| `rols.signature.include_docstring` | `boolean` | Include signature docstring. | `true` |
| `rols.signature.line_length` | `integer` | Maximum line length in signatures. | `88` |

This documentation was generated from `rols/config/schema.json`. Please do not edit this file directly.
