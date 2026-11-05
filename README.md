# Rope language server

A Python 3.9+ implementation of the
[Language Server Protocol](https://microsoft.github.io/language-server-protocol/)
using [Rope](https://github.com/python-rope/rope) for completion, renaming,
definitions, hover, references, signature help, symbols and
[refactoring code actions](docs/refactoring.md).

Development and issue tracking are on
[Codefloe](https://codefloe.com/mcepl/rope-language-server), with a
[GitHub mirror](https://github.com/python-rope/rope-language-server).
See the [CI runs](https://codefloe.com/mcepl/rope-language-server/actions) for
current test results.

## Installation

Use distribution packages where available, or install with pip:

```sh
python3 -m pip install rope-language-server
rols --help
```

Configure your editor to launch `rols`. It communicates over standard input and
output by default. The libraries you want Rope to analyse must be available to
the Python interpreter running `rols`.

The following optional providers are loaded when their dependencies are installed.
Some require explicit enabling in the editor's settings:

- [Pyflakes](https://github.com/PyCQA/pyflakes) detects errors.
- [McCabe](https://github.com/PyCQA/mccabe) checks complexity.
- [pycodestyle](https://github.com/PyCQA/pycodestyle) checks style.
- [pydocstyle](https://github.com/PyCQA/pydocstyle) checks docstring style and is disabled by default.
- [autopep8](https://github.com/hhatto/autopep8) formats code.
- [YAPF](https://github.com/google/yapf) formats code and takes precedence over autopep8.
- [flake8](https://github.com/pycqa/flake8) checks errors and style and is disabled by default.
- [pylint](https://github.com/PyCQA/pylint) checks code and is disabled by default.

Install a provider with the matching extra, for example:

```sh
python3 -m pip install "rope-language-server[yapf]"
```

Install all optional linting and formatting providers with:

```sh
python3 -m pip install "rope-language-server[all]"
```

### Third-party plugins

These integrations are useful references for additional tools:

- [Mypy integration](https://github.com/python-lsp/pylsp-mypy) for type checking.
- [python-lsp-isort](https://github.com/chantera/python-lsp-isort) for sorting imports with [isort](https://github.com/PyCQA/isort).
- [python-lsp-black](https://github.com/python-lsp/python-lsp-black) for formatting with [Black](https://github.com/psf/black).
- [pyls-memestra](https://github.com/QuantStack/pyls-memestra) for detecting deprecated APIs.
- [python-lsp-ruff](https://github.com/python-lsp/python-lsp-ruff) for linting with [Ruff](https://github.com/astral-sh/ruff).

Installing a plugin written for another server does not automatically make it
available here. Rope language server discovers plugins through the `rols`
entry-point group and uses `rols_*` hooks. Plugins must implement that interface.
See the [built-in plugins](rols/plugins), [hook specifications](rols/hookspecs.py)
and [entry-point declarations](pyproject.toml) for examples.

## Configuration

Pass settings from your editor under the `rols` namespace. The available options
are documented in [CONFIGURATION.md](CONFIGURATION.md). For example, to enable
[Rope autoimport](docs/autoimport.md):

```json
{
  "rols": {
    "plugins": {
      "rope_autoimport": {
        "enabled": true
      }
    }
  }
}
```

The server also reads configuration for its linting tools:

- `pycodestyle` reads `~/.config/pycodestyle`, `setup.cfg`, `tox.ini` and `pycodestyle.cfg`.
- `flake8` reads `.flake8`, `setup.cfg` and `tox.ini` in the project.

The default configuration source is `pycodestyle`. To use `flake8`:

1. Install the `flake8` extra.
2. Disable `rols.plugins.pycodestyle.enabled`, `rols.plugins.mccabe.enabled` and
   `rols.plugins.pyflakes.enabled` to avoid duplicate diagnostics.
3. Set `rols.plugins.flake8.enabled` to `true`.
4. Set `rols.configurationSources` to `["flake8"]`.

See the tools' own documentation for their configuration-file options:

- [flake8 configuration](https://flake8.pycqa.org/en/latest/user/configuration.html)
- [pycodestyle configuration](https://pycodestyle.pycqa.org/en/latest/intro.html#configuration)

Settings are merged in this order, with later values overriding earlier ones:
plugin defaults and initialisation options, editor settings, user configuration
files, then project configuration files.

For example, pycodestyle ignores can be set in the editor with
`rols.plugins.pycodestyle.ignore`, or in `~/.config/pycodestyle` or a project
configuration file:

```ini
[pycodestyle]
ignore = E226,E302,E41
```

### WebSockets

Install the [WebSockets](https://websockets.readthedocs.io/en/stable/) extra and
start the server with a port number:

```sh
python3 -m pip install "rope-language-server[websockets]"
rols --ws --port 2087
```

## LSP features

- Completion
- [Autoimport](docs/autoimport.md), disabled by default
- Code linting
- Code actions
- Renaming
- Signature help
- Go to definition
- Hover
- Find references
- Document symbols
- Document formatting
- Code folding
- Multiple workspaces

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for checkout and editor setup. Install the
development dependencies using distribution packages, or use an editable pip
installation:

```sh
python3 -m pip install -e ".[all,websockets,test]"
```

Run the checkout directly with logging:

```sh
python3 -m rols -v --log-file /tmp/rols.log   # Info-level logging
python3 -m rols -vv --log-file /tmp/rols.log  # Debug-level logging
```

Run the test suite:

```sh
python3 -m pytest
```

Use the same Black version as CI to avoid formatting differences between releases:

```sh
python3 -m pip install black==25.11.0
python3 -m black .
```

Check formatting without changing files:

```sh
python3 -m black --check .
```

After changing the configuration schema, regenerate its Markdown documentation:

```sh
python3 scripts/jsonschema2md.py rols/config/schema.json CONFIGURATION.md
```

For cancellation and responsiveness checks, see
[docs/cancellation-testing.md](docs/cancellation-testing.md).

## Licence

This project is available under the [MIT licence](LICENSE).
