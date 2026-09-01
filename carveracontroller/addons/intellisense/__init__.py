"""G-code / MDI IntelliSense backed by the firmware command reference."""

from carveracontroller.addons.intellisense.engine import (
    SUGGESTION_LIMIT,
    Command,
    CommandCatalog,
    Parameter,
    ParsedCommand,
    ParsedLine,
    ResolvedDefault,
    analyze_mdi_input,
    explain_line,
    explain_signature,
    get_catalog,
    highlight_mdi_line,
    parse_line,
    resolve_param_default,
)

__all__ = [
    "SUGGESTION_LIMIT",
    "Command",
    "CommandCatalog",
    "Parameter",
    "ParsedCommand",
    "ParsedLine",
    "ResolvedDefault",
    "analyze_mdi_input",
    "explain_line",
    "explain_signature",
    "get_catalog",
    "highlight_mdi_line",
    "parse_line",
    "resolve_param_default",
]
