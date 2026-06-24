"""Render Prompty-format prompt templates into system/user messages.

Prompt files use YAML front-matter, ``system:``/``user:`` sections, and ``{{placeholder}}``
substitutions. This module actually performs that substitution (the previous version shipped
the raw file, leaving placeholders unfilled), enforcing the prompt/payload contract by failing
loudly on an unknown placeholder.
"""

from __future__ import annotations

import json
import re
from typing import Any

_PLACEHOLDER = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def _strip_front_matter(text: str) -> str:
    if text.lstrip().startswith("---"):
        stripped = text.lstrip()
        end = stripped.find("\n---", 3)
        if end != -1:
            newline = stripped.find("\n", end + 1)
            return stripped[newline + 1 :] if newline != -1 else ""
    return text


def _split_sections(body: str) -> tuple[str, str]:
    """Split a prompt body into (system, user) on line-leading section labels."""
    system_match = re.search(r"^system:\s*$", body, re.MULTILINE)
    user_match = re.search(r"^user:\s*$", body, re.MULTILINE)
    if system_match and user_match:
        system = body[system_match.end() : user_match.start()].strip()
        user = body[user_match.end() :].strip()
        return system, user
    # No explicit sections: treat the whole body as the system prompt.
    return body.strip(), ""


def _substitute(text: str, context: dict[str, Any]) -> str:
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in context:
            missing.append(key)
            return match.group(0)
        value = context[key]
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, indent=2)

    rendered = _PLACEHOLDER.sub(replace, text)
    if missing:
        raise ValueError(f"Prompt placeholders missing from context: {sorted(set(missing))}")
    return rendered


def render_prompt(template: str, context: dict[str, Any]) -> tuple[str, str]:
    """Return rendered (system, user) messages for a Prompty template."""
    body = _strip_front_matter(template)
    system, user = _split_sections(body)
    return _substitute(system, context), _substitute(user, context)
