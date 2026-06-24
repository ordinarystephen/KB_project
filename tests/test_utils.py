"""Unit tests for the YAML, prompt-rendering, and status helpers."""

from pathlib import Path

import pytest

from app.services.prompt_utils import render_prompt
from app.services.status import is_approved, next_status, stage_hint
from app.services.yaml_utils import load_yaml, save_yaml

PROMPT = """---
name: example
inputs:
  a: {type: string}
---

system:
Hello {{a}} with {{obj}}.

user:
Do {{a}} now.
"""


def test_render_prompt_substitutes_and_splits_sections() -> None:
    system, user = render_prompt(PROMPT, {"a": "world", "obj": {"k": 1}})
    assert system.startswith("Hello world with")
    assert '"k": 1' in system
    assert user.strip() == "Do world now."


def test_render_prompt_raises_on_missing_placeholder() -> None:
    with pytest.raises(ValueError):
        render_prompt("system:\nNeed {{missing}}\n\nuser:\nx", {})


def test_yaml_round_trip(tmp_path: Path) -> None:
    payload = {"a": [1, 2], "b": {"c": "d"}, "page": None}
    path = save_yaml(tmp_path / "nested" / "doc.yaml", payload)
    assert load_yaml(path) == payload


def test_status_state_machine() -> None:
    assert next_status("draft") == "verified"
    assert next_status("verified") == "enriched"
    assert next_status("enriched") == "approved"
    assert next_status("approved") is None
    assert is_approved("approved") and not is_approved("draft")
    assert stage_hint("draft").action == "Verify"
