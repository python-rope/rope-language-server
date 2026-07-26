# Copyright 2017-2020 Palantir Technologies, Inc.
# Copyright 2021- Python Language Server Contributors.

from rols import hookspec


@hookspec
def rols_code_actions(config, workspace, document, range, context):
    pass


@hookspec
def rols_code_lens(config, workspace, document) -> None:
    pass


@hookspec
def rols_commands(config, workspace) -> None:
    """The list of command strings supported by the server.

    Returns:
        List[str]: The supported commands.
    """


@hookspec
def rols_completions(config, workspace, document, position, ignored_names) -> None:
    pass


@hookspec(firstresult=True)
def rols_completion_item_resolve(config, workspace, document, completion_item) -> None:
    pass


@hookspec
def rols_definitions(config, workspace, document, position) -> None:
    pass


@hookspec
def rols_dispatchers(config, workspace) -> None:
    pass


@hookspec
def rols_document_did_open(config, workspace, document) -> None:
    pass


@hookspec
def rols_document_did_save(config, workspace, document) -> None:
    pass


@hookspec
def rols_document_highlight(config, workspace, document, position) -> None:
    pass


@hookspec
def rols_document_symbols(config, workspace, document) -> None:
    pass


@hookspec(firstresult=True)
def rols_execute_command(config, workspace, command, arguments) -> None:
    pass


@hookspec
def rols_experimental_capabilities(config, workspace) -> None:
    pass


@hookspec
def rols_folding_range(config, workspace, document) -> None:
    pass


@hookspec(firstresult=True)
def rols_format_document(config, workspace, document, options) -> None:
    pass


@hookspec(firstresult=True)
def rols_format_range(config, workspace, document, range, options) -> None:
    pass


@hookspec(firstresult=True)
def rols_hover(config, workspace, document, position) -> None:
    pass


@hookspec
def rols_initialize(config, workspace) -> None:
    pass


@hookspec
def rols_initialized() -> None:
    pass


@hookspec
def rols_lint(config, workspace, document, is_saved) -> None:
    pass


@hookspec
def rols_references(config, workspace, document, position, exclude_declaration) -> None:
    pass


@hookspec(firstresult=True)
def rols_rename(config, workspace, document, position, new_name) -> None:
    pass


@hookspec
def rols_settings(config) -> None:
    pass


@hookspec(firstresult=True)
def rols_signature_help(config, workspace, document, position) -> None:
    pass


@hookspec
def rols_workspace_configuration_changed(config, workspace) -> None:
    pass


@hookspec
def rols_shutdown(config, workspace) -> None:
    pass
