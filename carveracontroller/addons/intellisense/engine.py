"""Load, parse, and explain firmware commands from commands.json."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Reversible
from dataclasses import dataclass, field
from typing import Any

from carveracontroller.CNC import (
    GCODE_DEFAULT_COLORS,
    M118_HIGHLIGHT_STOP,
    PARENPAT,
    SEMIPAT,
    escape_gcode_markup,
    highlight_gcode_line,
)

COMMANDS_PATH = os.path.join(os.path.dirname(__file__), "commands.json")
SUGGESTION_LIMIT = 12

_GM_TOKEN_RE = re.compile(r"^([GMgm])(\d+)(?:\.(\d+))?$")
_WORD_RE = re.compile(r"([A-Za-z])\s*([-+]?(?:\d+\.?\d*|\.\d+))")
_GCODE_TOKEN_RE = re.compile(r"^[A-Za-z][-+]?(?:\d+\.?\d*|\.\d+)$")
_MOTION_COMMANDS = frozenset({"G0", "G1", "G2", "G3"})
_BARE_MOTION_WORDS = frozenset({"X", "Y", "Z", "A", "B", "C", "U", "V", "W", "I", "J", "K", "R"})
_LETTER_CATEGORY = {
    "G": "g_command",
    "M": "m_command",
    "X": "coordinate",
    "Y": "coordinate",
    "Z": "coordinate",
    "A": "coordinate",
    "B": "coordinate",
    "C": "coordinate",
    "F": "feedrate",
    "S": "spindle",
    "T": "tool",
    "N": "line_number",
}


@dataclass(frozen=True)
class Parameter:
    name: str
    required: bool
    description: str
    default: Any = None
    unit: str | None = None
    default_source: str | None = None


@dataclass(frozen=True)
class Command:
    name: str
    type: str
    description: str
    parameters: dict[str, Parameter]
    notes: str | None = None

    @property
    def is_word_command(self) -> bool:
        return self.type in ("gcode", "mcode")


@dataclass(frozen=True)
class ResolvedDefault:
    value: Any
    source: str | None = None
    from_settings: bool = False


@dataclass
class ParsedCommand:
    command: Command
    params: dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedLine:
    raw: str
    commands: list[ParsedCommand] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    prefix: str = ""
    params: dict[str, str] = field(default_factory=dict)
    modal_note: str | None = None


@dataclass(frozen=True)
class MdiAnalysis:
    mode: str  # "empty" | "suggest" | "params"
    token: str
    suggestions: tuple[Command, ...] = ()
    parsed: ParsedLine | None = None


class CommandCatalog:
    def __init__(self, commands: dict[str, Command], names: tuple[str, ...]):
        self._commands = commands
        self._names = names

    @classmethod
    def from_path(cls, path: str = COMMANDS_PATH) -> CommandCatalog:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CommandCatalog:
        commands: dict[str, Command] = {}
        for raw_name, raw_cmd in (payload.get("commands") or {}).items():
            command = _command_from_raw(raw_name, raw_cmd or {})
            commands[command.name] = command
            normalized = normalize_command_token(raw_name)
            if normalized and normalized not in commands:
                commands[normalized] = command
        names = tuple(sorted({cmd.name for cmd in commands.values()}, key=_name_sort_key))
        return cls(commands, names)

    def lookup(self, token: str) -> Command | None:
        if not token:
            return None
        exact = self._commands.get(token)
        if exact:
            return exact
        normalized = normalize_command_token(token)
        if normalized:
            return self._commands.get(normalized)
        return self._commands.get(token.upper()) or self._commands.get(token.lower())

    def suggest(self, prefix: str, limit: int = SUGGESTION_LIMIT) -> list[Command]:
        if not prefix:
            return []
        raw = prefix.strip()
        if not raw:
            return []
        raw_lower = raw.lower()
        raw_upper = raw.upper()
        normalized = normalize_command_token(raw)
        matches: list[Command] = []
        seen: set[str] = set()
        for name in self._names:
            command = self._commands[name]
            if command.name in seen:
                continue
            name_lower = command.name.lower()
            if (
                command.name.startswith(raw_upper)
                or name_lower.startswith(raw_lower)
                or (normalized and (command.name == normalized or command.name.startswith(normalized)))
            ):
                matches.append(command)
                seen.add(command.name)
        matches.sort(key=lambda cmd: _suggest_sort_key(cmd.name, raw, normalized))
        return matches[:limit]


_catalog: CommandCatalog | None = None


def get_catalog() -> CommandCatalog:
    global _catalog
    if _catalog is None:
        _catalog = CommandCatalog.from_path()
    return _catalog


def normalize_command_token(token: str) -> str | None:
    text = (token or "").strip()
    if not text:
        return None
    gm = _normalize_gm(text)
    if gm:
        return gm
    if text.startswith("$"):
        return "$" + text[1:].upper()
    return text.lower()


def parse_line(line: str, catalog: CommandCatalog | None = None) -> ParsedLine:
    catalog = catalog or get_catalog()
    raw = line.rstrip("\r\n")
    code = _strip_comments(raw).strip()
    if not code:
        return ParsedLine(raw=raw)

    first = code.split(None, 1)[0]
    command = catalog.lookup(first)
    if command and _is_passthrough_command(command):
        return _parse_passthrough(raw, code, command)

    if first.startswith("$"):
        command = catalog.lookup(first.split("=", 1)[0])
        if command and not command.is_word_command:
            return _parse_shell(raw, code, catalog, command)

    if _looks_like_gcode(code):
        parsed = _parse_gcode(raw, code, catalog)
        if parsed.commands or parsed.unknown or parsed.params:
            return parsed

    if command and not command.is_word_command:
        return _parse_shell(raw, code, catalog, command)

    gcode_parsed = _parse_gcode(raw, code, catalog)
    if gcode_parsed.commands or gcode_parsed.params:
        return gcode_parsed
    return ParsedLine(raw=raw, prefix=first, unknown=[first] if first else [])


def analyze_mdi_input(text: str, catalog: CommandCatalog | None = None) -> MdiAnalysis:
    catalog = catalog or get_catalog()
    line = _active_mdi_line(text)
    if not line.strip():
        return MdiAnalysis(mode="empty", token="")

    token, has_trailer = _first_token(line)
    if not token:
        return MdiAnalysis(mode="empty", token="")

    suggestions = tuple(catalog.suggest(token))
    exact = catalog.lookup(token)
    complete = _command_name_complete(exact, suggestions, has_trailer)
    if complete and exact:
        return MdiAnalysis(mode="params", token=token, suggestions=suggestions, parsed=parse_line(line, catalog))
    if suggestions:
        return MdiAnalysis(mode="suggest", token=token, suggestions=suggestions)
    return MdiAnalysis(mode="empty", token=token)


def resolve_param_default(param: Parameter, settings: dict[str, Any] | None = None) -> ResolvedDefault | None:
    settings = settings or {}
    source = param.default_source
    if source:
        value = settings.get(source)
        if value is not None and str(value).strip() != "":
            return ResolvedDefault(value=value, source=source, from_settings=True)
        fallback = param.default
        if fallback is not None and str(fallback) != source:
            return ResolvedDefault(value=fallback, source=source, from_settings=False)
        return ResolvedDefault(value=None, source=source, from_settings=False)
    if param.default is not None:
        return ResolvedDefault(value=param.default, source=None, from_settings=False)
    return None


def explain_line(
    line: str,
    *,
    catalog: CommandCatalog | None = None,
    settings: dict[str, Any] | None = None,
    colors: dict[str, str] | None = None,
    preceding_lines: Iterable[str] | None = None,
) -> str | None:
    catalog = catalog or get_catalog()
    parsed = parse_line(line, catalog)
    if not parsed.commands:
        parsed = _apply_modal_motion(parsed, preceding_lines or (), catalog)
    if not parsed.commands:
        return None
    return _format_explanation(parsed, settings or {}, colors, include_omitted=False)


def explain_signature(
    command: Command,
    *,
    parsed: ParsedLine | None = None,
    settings: dict[str, Any] | None = None,
    colors: dict[str, str] | None = None,
) -> str:
    provided = {}
    if parsed:
        for item in parsed.commands:
            if item.command.name == command.name:
                provided = item.params
                break
    parsed_cmd = ParsedCommand(command=command, params=provided)
    return _format_explanation(
        ParsedLine(raw=command.name, commands=[parsed_cmd]), settings or {}, colors, include_omitted=True
    )


def highlight_param_name(name: str, colors: dict[str, str] | None = None) -> str:
    effective = {**GCODE_DEFAULT_COLORS, **(colors or {})}
    letter = name[:1].upper()
    if name.startswith("-") or len(name) > 1:
        category = "parameter"
    else:
        category = _LETTER_CATEGORY.get(letter, "parameter")
    hex_color = effective.get(category, "#C8C8C8")
    return f"[color={hex_color}]{escape_gcode_markup(name)}[/color]"


def highlight_mdi_line(line: str, colors: dict[str, str] | None = None, catalog: CommandCatalog | None = None) -> str:
    """Highlight a sent MDI line, including SimpleShell commands."""
    token, _has_trailer = _first_token(line)
    if not token:
        return highlight_gcode_line(line, colors)
    catalog = catalog or get_catalog()
    command = catalog.lookup(token)
    if command is not None and not command.is_word_command:
        return _highlight_shell_line(line, colors)
    return highlight_gcode_line(line, colors)


def _highlight_shell_line(line: str, colors: dict[str, str] | None) -> str:
    match = re.match(r"^(\s*)(\S+)(.*)$", line)
    if not match:
        return highlight_gcode_line(line, colors)
    lead, raw_name, rest = match.groups()
    effective = {**GCODE_DEFAULT_COLORS, **(colors or {})}
    command_color = effective.get("shell_command", GCODE_DEFAULT_COLORS["shell_command"])
    flag_color = effective.get("parameter", "#9CDCFE")
    parts = [
        escape_gcode_markup(lead),
        f"[color={command_color}]{escape_gcode_markup(raw_name)}[/color]",
    ]
    for piece in re.finditer(r"(\s+)|(\S+)", rest):
        space, tok = piece.group(1), piece.group(2)
        if space:
            parts.append(escape_gcode_markup(space))
            continue
        if tok.startswith("-"):
            parts.append(f"[color={flag_color}]{escape_gcode_markup(tok)}[/color]")
        elif _GCODE_TOKEN_RE.fullmatch(tok):
            parts.append(highlight_gcode_line(tok, colors))
        else:
            parts.append(escape_gcode_markup(tok))
    return "".join(parts)


def _command_from_raw(name: str, raw_cmd: dict[str, Any]) -> Command:
    parameters = {}
    for param_name, raw_param in (raw_cmd.get("parameters") or {}).items():
        raw_param = raw_param or {}
        parameters[param_name] = Parameter(
            name=param_name,
            required=bool(raw_param.get("required")),
            description=str(raw_param.get("description") or ""),
            default=raw_param.get("default"),
            unit=raw_param.get("unit"),
            default_source=raw_param.get("default_source"),
        )
    notes = raw_cmd.get("notes")
    return Command(
        name=name,
        type=str(raw_cmd.get("type") or ""),
        description=str(raw_cmd.get("description") or ""),
        parameters=parameters,
        notes=str(notes) if notes else None,
    )


def _normalize_gm(token: str) -> str | None:
    match = _GM_TOKEN_RE.fullmatch(token.strip())
    if not match:
        return None
    letter = match.group(1).upper()
    whole = str(int(match.group(2)))
    frac = match.group(3)
    if frac is None:
        return f"{letter}{whole}"
    frac = frac.rstrip("0") or "0"
    return f"{letter}{whole}.{frac}"


def _name_sort_key(name: str) -> tuple:
    match = _GM_TOKEN_RE.fullmatch(name)
    if match:
        frac = match.group(3)
        number = float(f"{int(match.group(2))}.{frac}") if frac is not None else float(int(match.group(2)))
        return (0, match.group(1).upper(), number, name)
    if name.startswith("$"):
        return (1, name.upper(), 0, name)
    return (2, name.lower(), 0, name)


def _suggest_sort_key(name: str, _prefix: str, normalized: str | None) -> tuple:
    exact = 0 if normalized and name == normalized else 1
    return (exact, *_name_sort_key(name))


def _strip_comments(line: str) -> str:
    text = PARENPAT.sub("", line)
    text = SEMIPAT.sub("", text)
    m118 = M118_HIGHLIGHT_STOP.search(text)
    if m118:
        text = text[: m118.end()]
    return text


def _looks_like_gcode(code: str) -> bool:
    tokens = code.split()
    if not tokens:
        return False
    first = tokens[0]
    if first.startswith("$"):
        return False
    if _normalize_gm(first) or _GCODE_TOKEN_RE.fullmatch(first):
        return True
    return all(_GCODE_TOKEN_RE.fullmatch(tok) or tok.startswith("$") for tok in tokens)


def _parse_gcode(raw: str, code: str, catalog: CommandCatalog) -> ParsedLine:
    words: list[tuple[str, str]] = []
    for match in _WORD_RE.finditer(code.replace("\t", " ")):
        words.append((match.group(1).upper(), match.group(2)))

    commands: list[Command] = []
    params: dict[str, str] = {}
    unknown: list[str] = []
    for letter, value in words:
        if letter in ("G", "M"):
            token = f"{letter}{value}"
            command = catalog.lookup(token)
            if command:
                commands.append(command)
            else:
                unknown.append(token)
            continue
        if letter == "N":
            continue
        params[letter] = value

    if not commands:
        prefix = code.split(None, 1)[0] if code else ""
        return ParsedLine(raw=raw, unknown=unknown, prefix=prefix, params=params)

    owners: dict[str, int] = {}
    for index, command in enumerate(commands):
        for name in command.parameters:
            key = name.upper() if len(name) == 1 else name
            if key in params:
                owners[key] = index

    grouped: dict[int, dict[str, str]] = {index: {} for index in range(len(commands))}
    leftover = dict(params)
    for key, value in list(leftover.items()):
        owner = owners.get(key)
        if owner is None:
            continue
        grouped[owner][key] = value
        leftover.pop(key)
    if leftover and commands:
        grouped[len(commands) - 1].update(leftover)

    parsed_commands = [
        ParsedCommand(command=command, params=grouped.get(index, {})) for index, command in enumerate(commands)
    ]
    return ParsedLine(raw=raw, commands=parsed_commands, unknown=unknown)


def _parse_shell(raw: str, code: str, _catalog: CommandCatalog, command: Command) -> ParsedLine:
    tokens = code.split()
    provided: dict[str, str] = {}
    flags = {name for name in command.parameters if name.startswith("-")}
    letter_params = {name.upper(): name for name in command.parameters if len(name) == 1 and not name.startswith("-")}
    positionals = [
        spec
        for name, spec in command.parameters.items()
        if not name.startswith("-") and not (len(name) == 1 and name.isalpha())
    ]
    leftovers: list[str] = []

    for token in tokens[1:]:
        if token in flags:
            provided[token] = ""
            continue
        word = _WORD_RE.fullmatch(token)
        if word:
            letter = word.group(1).upper()
            if letter in letter_params:
                provided[letter_params[letter]] = word.group(2)
                continue
        leftovers.append(token)

    if "axis" in command.parameters:
        axis_bits = [tok for tok in leftovers if _GCODE_TOKEN_RE.fullmatch(tok)]
        leftovers = [tok for tok in leftovers if not _GCODE_TOKEN_RE.fullmatch(tok)]
        if axis_bits:
            provided["axis"] = " ".join(axis_bits)
        positionals = [spec for spec in positionals if spec.name != "axis"]

    required = [spec for spec in positionals if spec.required]
    if len(leftovers) == len(required) and len(leftovers) != len(positionals):
        targets = required
    else:
        targets = positionals

    unused = []
    for token, spec in zip(leftovers, targets):
        provided[spec.name] = token
    if len(leftovers) > len(targets):
        unused.extend(leftovers[len(targets) :])

    return ParsedLine(raw=raw, commands=[ParsedCommand(command=command, params=provided)], unknown=unused)


def _is_passthrough_command(command: Command) -> bool:
    return command.is_word_command and tuple(command.parameters) == ("command",)


def _parse_passthrough(raw: str, code: str, command: Command) -> ParsedLine:
    parts = code.split(None, 1)
    remainder = parts[1] if len(parts) == 2 else ""
    params = {"command": remainder} if remainder else {}
    return ParsedLine(raw=raw, commands=[ParsedCommand(command=command, params=params)])


def _active_mdi_line(text: str) -> str:
    if not text:
        return ""
    return text.split("\n")[-1]


def _first_token(line: str) -> tuple[str, bool]:
    match = re.match(r"\s*(\S*)(\s*)", line)
    if not match:
        return "", False
    return match.group(1), bool(match.group(2))


def _command_name_complete(exact: Command | None, suggestions: tuple[Command, ...], has_trailer: bool) -> bool:
    if exact is None:
        return False
    if has_trailer:
        return True
    longer = [cmd for cmd in suggestions if cmd.name != exact.name]
    return not longer


def _apply_modal_motion(parsed: ParsedLine, preceding_lines: Iterable[str], catalog: CommandCatalog) -> ParsedLine:
    if not _is_bare_motion_line(parsed):
        return parsed
    motion = _last_motion_command(preceding_lines, catalog)
    if motion is None:
        return parsed
    return ParsedLine(
        raw=parsed.raw,
        commands=[ParsedCommand(command=motion, params=dict(parsed.params))],
        unknown=parsed.unknown,
        prefix=parsed.prefix,
        params=parsed.params,
        modal_note=f"This is a modal movement based on the previous {motion.name} command.",
    )


def _is_bare_motion_line(parsed: ParsedLine) -> bool:
    if parsed.commands:
        return False
    return any(name.upper() in _BARE_MOTION_WORDS for name in parsed.params)


def _last_motion_command(lines: Iterable[str], catalog: CommandCatalog) -> Command | None:
    # Reversible collections are expected in chronological order. One-shot
    # iterables may provide nearest-first lines to avoid copying large files.
    nearest_first = reversed(lines) if isinstance(lines, Reversible) else iter(lines)
    for line in nearest_first:
        parsed = parse_line(line, catalog)
        motion = None
        for item in parsed.commands:
            if item.command.name in _MOTION_COMMANDS:
                motion = item.command
        if motion is not None:
            return motion
    return None


def _format_explanation(
    parsed: ParsedLine,
    settings: dict[str, Any],
    colors: dict[str, str] | None,
    *,
    include_omitted: bool,
) -> str:
    blocks: list[str] = []

    for item in parsed.commands:
        command = item.command
        title = highlight_mdi_line(command.name, colors)
        blocks.append(f"{title}  {escape_gcode_markup(command.description)}")
        if parsed.modal_note:
            blocks.append(escape_gcode_markup(parsed.modal_note))
        if command.notes:
            blocks.append(escape_gcode_markup(command.notes))

        rows = _parameter_rows(command, item.params, settings, colors, include_omitted=include_omitted)
        if rows:
            blocks.append("")
            blocks.extend(rows)
        blocks.append("")

    return "\n".join(blocks).rstrip()


def _parameter_rows(
    command: Command,
    provided: dict[str, str],
    settings: dict[str, Any],
    colors: dict[str, str] | None,
    *,
    include_omitted: bool,
) -> list[str]:
    rows: list[str] = []
    seen: set[str] = set()

    for name, spec in command.parameters.items():
        value = _provided_value(provided, name)
        if value is None and not include_omitted and not _param_has_default(spec):
            continue
        seen.add(name.upper())
        rows.append(_format_param_row(spec, value, settings, colors))

    if include_omitted:
        return rows

    for name, value in provided.items():
        if name.upper() in seen:
            continue
        fake = Parameter(name=name, required=False, description="")
        rows.append(_format_param_row(fake, value, settings, colors))
    return rows


def _param_has_default(spec: Parameter) -> bool:
    return spec.default_source is not None or spec.default is not None


def _provided_value(provided: dict[str, str], name: str) -> str | None:
    if name in provided:
        return provided[name]
    if name.upper() in provided:
        return provided[name.upper()]
    if name.lower() in provided:
        return provided[name.lower()]
    return None


def _format_param_row(
    spec: Parameter,
    value: str | None,
    settings: dict[str, Any],
    colors: dict[str, str] | None,
) -> str:
    name_hl = highlight_param_name(spec.name, colors)
    bits = [name_hl]
    if value not in (None, ""):
        bits.append(f"= {escape_gcode_markup(str(value))}")
    elif spec.required:
        bits.append("(required)")

    resolved = resolve_param_default(spec, settings)
    extra: list[str] = []
    if value in (None, "") and resolved is not None:
        default_text = _format_default(resolved, spec)
        if default_text:
            extra.append(default_text)
    elif spec.unit and value not in (None, ""):
        extra.append(spec.unit)

    if spec.description:
        extra.append(spec.description)

    line = " ".join(bits)
    if extra:
        line = f"{line}  —  {escape_gcode_markup(' · '.join(extra))}"
    return line


def _format_default(resolved: ResolvedDefault, spec: Parameter) -> str:
    if resolved.value is None:
        return ""
    formatted = _format_default_value(resolved.value)
    if spec.unit:
        formatted = f"{formatted} {spec.unit}"
    return f"default {formatted}"


def _format_default_value(value: Any) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return format(value, "g")
    return str(value).strip()
