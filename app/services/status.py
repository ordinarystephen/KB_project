"""Per-policy KB lifecycle state machine and human-action hints.

The ``status`` field inside each ``*.kb.yaml`` IS the state machine. Humans advance it via an app
button or by editing the line directly; no files are moved. This module is the single source of
truth shared by the Streamlit app (context hints) and ``docs/RUNBOOK.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUS_ORDER = ("draft", "verified", "enriched", "approved")


@dataclass(frozen=True)
class StageHint:
    status: str
    look_at: str
    action: str
    do: str
    becomes: str | None


_HINTS = {
    "draft": StageHint(
        status="draft",
        look_at="the first-pass rules in the KB",
        action="Verify",
        do="Run Part 2 (Verify) to check the draft against the source policy.",
        becomes="verified",
    ),
    "verified": StageHint(
        status="verified",
        look_at="verifications/<slug>.verification.json (gaps found vs. source)",
        action="Enrich",
        do="Read the verification report, then run Part 3 (Enrich) to gap-fill the KB.",
        becomes="enriched",
    ),
    "enriched": StageHint(
        status="enriched",
        look_at="follow_up_items[] in the KB",
        action="Approve",
        do="Resolve/edit the follow_up_items, then Approve to lock the KB for consolidation.",
        becomes="approved",
    ),
    "approved": StageHint(
        status="approved",
        look_at="nothing — the KB is locked",
        action="(none)",
        do="This KB is eligible for Part 4 consolidation. No further per-policy action.",
        becomes=None,
    ),
}


def stage_hint(status: str) -> StageHint:
    """Return the human-action hint for a status (unknown statuses map to draft)."""
    return _HINTS.get(status, _HINTS["draft"])


def next_status(status: str) -> str | None:
    """Return the status reached by completing the current stage's action."""
    return stage_hint(status).becomes


def is_approved(status: str) -> bool:
    return status == "approved"
