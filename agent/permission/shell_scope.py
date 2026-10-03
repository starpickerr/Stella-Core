"""Parse explicit shell file targets for the unified policy engine."""

from __future__ import annotations

import os
import re
import shlex
from typing import Optional, Sequence

_DESTINATION_ONLY_COMMANDS = frozenset({"cp", "copy", "rsync", "install", "ln", "unzip", "tar", "zip"})
_PATH_MUTATING_COMMANDS = frozenset({
    "rm", "rmdir", "unlink", "mv", "cp", "rsync", "install", "dd", "truncate", "shred",
    "ln", "mkdir", "touch", "chmod", "chown", "chgrp", "chflags", "tee", "sed",
    "zip", "unzip", "tar", "gzip", "gunzip", "del", "erase", "move", "copy",
    "ren", "rename", "md", "rd",
})
_SEPARATORS = frozenset({";", "&&", "||", "|", "&", "|&", "(", ")", "{", "}", "\n"})
_WRAPPERS = frozenset({"env", "nohup", "time", "timeout", "nice", "ionice", "stdbuf", "xargs", "command", "builtin", "exec", "watch", "setsid"})
_OPERATORS = set("<>&|;()")


def _operator(token: str) -> bool:
    return bool(token) and all(char in _OPERATORS for char in token)


def _parse_segments(command: str) -> Optional[list[list[str]]]:
    lexer = shlex.shlex(command or "", posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in _SEPARATORS:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _command_name(tokens: Sequence[str]) -> tuple[Optional[str], list[str]]:
    args = list(tokens)
    while args:
        head = args[0]
        if _operator(head) or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", head):
            args.pop(0)
            continue
        name = os.path.basename(head).lower().removesuffix(".exe")
        if name in _WRAPPERS:
            args.pop(0)
            while args and args[0].startswith("-"):
                args.pop(0)
            continue
        return name, args[1:]
    return None, []


def _redirect_targets(tokens: Sequence[str]) -> list[str]:
    targets = []
    for index, token in enumerate(tokens):
        if ">" not in token or not _operator(token) or index + 1 >= len(tokens):
            continue
        target = tokens[index + 1]
        if "&" in token and (target.isdigit() or target == "-"):
            continue
        if not _operator(target):
            targets.append(target)
    return targets


def _positional_paths(args: Sequence[str]) -> list[str]:
    out = []
    skip = False
    for index, token in enumerate(args):
        if skip:
            skip = False
            continue
        if _operator(token):
            skip = True
            continue
        if token.startswith("-"):
            continue
        next_token = args[index + 1] if index + 1 < len(args) else None
        if token.isdigit() and next_token and _operator(next_token):
            continue
        out.append(token)
    return out
