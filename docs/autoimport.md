# Autoimport for Rope language server

## Enable autoimport

Rope is a base dependency; no separate autoimport plugin is needed:

```sh
python3 -m pip install rope-language-server
```

Set `rols.plugins.rope_autoimport.enabled` to `true` in your editor's settings.
This enables both completions and code actions. Disable either independently with
`rols.plugins.rope_autoimport.completions.enabled` or
`rols.plugins.rope_autoimport.code_actions.enabled`.

For the settings structure, see the README's
[configuration section](https://codefloe.com/mcepl/rope-language-server#configuration)
and the
[configuration reference](https://codefloe.com/mcepl/rope-language-server/src/branch/main/CONFIGURATION.md).

## Startup

When autoimport is enabled, the server builds a SQLite database for the project
and installed Python packages. By default, it is stored in
`.ropeproject/autoimport.db`. The Rope folder can be changed with
`rols.rope.ropeFolder`; `rols.plugins.rope_autoimport.memory` selects an in-memory
database instead.

Initial indexing can take tens of seconds in an environment with many modules.
While indexing is active, autoimport returns no suggestions; the native completion
provider remains available. Later indexing runs reuse cached external packages.

## Usage

Autoimport suggests imports for modules, functions, classes and other names in the
project and on Python's module path. The libraries you want to import must be
available to the Python interpreter running `rols`.

Each completion includes an additional text edit to insert the selected import.
Code actions offer import quick fixes based on undefined-name diagnostics.
Imports are inserted into the document's import group. An import-sorting tool can
apply your preferred ordering afterwards. See the
[third-party plugin notes](https://codefloe.com/mcepl/rope-language-server#third-party-plugins)
before installing an integration written for another server.

## Credits

- The original autoimport plugin was written by @bagel897.
- [lyz-code/autoimport](https://github.com/lyz-code/autoimport) provided inspiration.
- [Rope](https://github.com/python-rope/rope), especially @lieryan, provided the autoimport implementation.
- [Pyright](https://github.com/Microsoft/pyright) informed the language-server integration.
