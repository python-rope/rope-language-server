# Using Rope in editors and IDEs

Rope language server (`rols`) lets any editor with a Language Server Protocol
(LSP) client use Rope's Python features. It runs as a standalone language server;
it is not a plugin for `python-lsp-server` (`pylsp`). Install it with
`python3 -m pip install rope-language-server`, then configure your editor's LSP
client to launch `rols`. See the [installation and configuration
instructions](https://codefloe.com/mcepl/rope-language-server) for details.

The language server uses the Python interpreter that starts `rols`. Install
project dependencies into that environment if you want Rope to resolve them.
For supported features, see the
[LSP feature list](https://codefloe.com/mcepl/rope-language-server#lsp-features),
[refactoring](refactoring.md), and [autoimport](autoimport.md).

## Editors with LSP support

An LSP client can connect to `rols` over standard input and output. The exact
configuration depends on the editor and its LSP client. Follow that client's
instructions for registering a server command, and set the command to `rols`.

Common LSP clients include:

- **Vim and Neovim:** use an LSP client such as
  [nvim-lspconfig](https://github.com/neovim/nvim-lspconfig) for Neovim.
- **Emacs:** use [Eglot](https://github.com/joaotavora/eglot) or
  [lsp-mode](https://github.com/emacs-lsp/lsp-mode).
- **Sublime Text:** use the
  [LSP package](https://github.com/sublimelsp/LSP).
- **Visual Studio Code and VSCodium:** use an extension that can register a
  custom language server. Configure it to launch `rols` for Python files.
- Other editors with an LSP client can use the same command.

`rols` does not use the plugin system of `pylsp`. Installing a plugin for
`python-lsp-server`, including `pylsp-rope`, does not add that plugin's features
to `rols`. See the README's
[third-party plugin notes](https://codefloe.com/mcepl/rope-language-server#third-party-plugins)
for compatible integrations.

## Other Rope integrations

These projects provide Rope features through editor plugins or command-line
tools rather than through `rols`. Their setup and feature sets differ from the
language server.

| Project | Editors or use | Notes |
|---|---|---|
| [python-lsp-server](https://github.com/python-lsp/python-lsp-server) with [pylsp-rope](https://github.com/python-rope/pylsp-rope) | Any editor with an LSP client | A separate LSP server and plugin. Do not install `pylsp-rope` expecting it to extend `rols`. |
| [ropevim](https://github.com/python-rope/ropevim) | Vim | Rope's reference Vim plugin. |
| [python-mode](https://github.com/python-mode/python-mode) | Vim | A Vim plugin with Rope support. |
| [ropify](https://github.com/niqodea/ropify) | Neovim and command line | A command-line wrapper with Neovim bindings. |
| [ropemacs](https://github.com/python-rope/ropemacs) | Emacs | Rope's reference Emacs plugin. |
| [elpy](https://github.com/jorgenschaefer/elpy) | Emacs | Python development environment with Rope integration. |
| [traad](https://github.com/abingham/traad) | Emacs | Rope integration. Check the project for current status. |
| [LSP-pylsp](https://github.com/sublimelsp/LSP-pylsp) | Sublime Text | Sublime LSP integration for `pylsp`. |
| [PyRefactor](https://github.com/dnatag/PyRefactor) | Sublime Text | Rope-based refactoring plugin. |
| [SublimeRope](https://github.com/JulianEberius/SublimeRope) | Sublime Text | Rope plugin. |
| [SublimePythonIDE](https://github.com/JulianEberius/SublimePythonIDE) | Sublime Text | Python IDE plugin with Rope support. |
| [kak-rope](https://pypi.org/project/kak-rope/) | Kakoune | Rope integration for Kakoune. |
| [lapce-python](https://github.com/superlou/lapce-python) | Lapce | Python support for Lapce. |
| [vscode-python](https://github.com/microsoft/vscode-python) | VS Code | The extension removed its native Rope integration in favour of language-server support. |
| [roper](https://pypi.org/project/roper/) | Command line | Run without installing with `uvx roper --help`. |
| [ropecli](https://github.com/aevri/ropecli) | Command line | Command-line interface for Rope. |
| [asunder](https://github.com/lalmei/asunder) | Command line | Command-line tool for Rope. |
| [pymv](https://github.com/Ridecell/pymv) | Command line | Moves Python modules. |

Other integrations listed in the Rope wiki include
[ide-python](https://atom.io/packages/ide-python) for Atom,
[RopeMate](https://github.com/JulianEberius/RopeMate.tmbundle) for TextMate, and
[ropeide](https://github.com/python-rope/ropeide), a standalone IDE. The Atom
editor and `ropeide` are no longer maintained; RopeMate also appears inactive.
The wiki also lists Spyder and Eric but does not give a specific Rope
integration for either. Check each project's own documentation and activity
before choosing an older integration.

This page replaces the Rope wiki's [editor integration
list](https://github.com/python-rope/rope/wiki/How-to-use-Rope-in-my-IDE-or-Text-editor%3F).
That list covers more integrations; please send corrections or additions for
this page to the rope-language-server project.
