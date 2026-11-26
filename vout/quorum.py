"""Slovak municipal council quorum & voting evaluation engine.

All calculations use strict integer arithmetic (zero floating-point rounding risk)
according to verified statutes in knowledge/domain-rules.md:
- Act No. 369/1990 Coll. on Municipal Establishment (§ 12, § 13, § 18a, § 20a, § 20b)
- Act No. 401/1990 Coll. on the City of Košice (§ 8a, § 14, § 16, § 18)
- Act No. 138/1991 Coll. on Municipal Property (§ 6a, § 9, § 9a, § 9aa)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

QuorumType = Literal[
    "majority_present",
    "majority_all",
    "three_fifths_present",
    "three_fifths_all",
]

QUORUM_LABELS: dict[str, dict[str, str]] = {
    "majority_present": {
        "label": "Nadpolovičná väčšina prítomných",
        "short": "> 1/2 prítomných",
        "legal_hint": "Štandardné uznesenia, schválenie programu bez zmeny, procedurálne návrhy (§ 12 ods. 7 zák. 369/1990)",
    },
    "majority_all": {
        "label": "Nadpolovičná väčšina všetkých poslancov",
        "short": "> 1/2 všetkých",
        "legal_hint": "Zmena návrhu programu (§ 12 ods. 5), hlavný kontrolór (§ 18a), zmluvy obcí (§ 20a/b), zrušenie OVS (§ 9a ods. 7)",
    },
    "three_fifths_present": {
        "label": "Trojpätinová (3/5) väčšina prítomných",
        "short": "3/5 prítomných",
        "legal_hint": "Prijatie všeobecne záväzného nariadenia – VZN (§ 12 ods. 7 zák. 369/1990)",
    },
    "three_fifths_all": {
        "label": "Trojpätinová (3/5) väčšina všetkých poslancov",
        "short": "3/5 všetkých",
        "legal_hint": "Prelomenie veta starostu (§ 13 ods. 8), prevod/nájom majetku z osobitného zreteľa (§ 9a, § 9aa zák. 138/1991), koncesie",
    },
}

VALID_QUORUM_TYPES = tuple(QUORUM_LABELS.keys())
VALID_VOTE_CHOICES = ("for", "against", "abstain")
VALID_BALLOT_STATES = ("for", "against", "abstain", "not_voted", "absent")


def min_present_for_quorum(total_councilors: int) -> int:
    """Uznášaniaschopnosť: nadpolovičná väčšina všetkých poslancov (§ 12 ods. 7)."""
    if total_councilors < 1:
        raise ValueError("total_councilors must be >= 1")
    return (total_councilors // 2) + 1


def is_quorate(total_councilors: int, present_count: int) -> bool:
    """Returns True if council is quorate (uznášaniaschopné)."""
    return present_count >= min_present_for_quorum(total_councilors)


def required_votes_for(quorum_type: str, total_councilors: int, present_count: int) -> int:
    """Exact integer threshold of 'FOR' votes required to pass."""
    if quorum_type not in QUORUM_LABELS:
        raise ValueError(f"Unknown quorum_type: {quorum_type}")
    if total_councilors < 1:
        raise ValueError("total_councilors must be >= 1")
    if present_count < 0 or present_count > total_councilors:
        raise ValueError(f"present_count ({present_count}) out of range 0..{total_councilors}")

    if quorum_type == "majority_present":
        return (present_count // 2) + 1
    if quorum_type == "majority_all":
        return (total_councilors // 2) + 1
    if quorum_type == "three_fifths_present":
        # ceil(3 * present / 5) using pure integer math
        return (3 * present_count + 4) // 5 if present_count > 0 else 1
    if quorum_type == "three_fifths_all":
        # ceil(3 * total / 5) using pure integer math
        return (3 * total_councilors + 4) // 5
    raise ValueError(f"Unhandled quorum_type: {quorum_type}")


@dataclass(frozen=True)
class VoteOutcome:
    quorum_met: bool
    min_present: int
    required_for: int
    passed: bool
    verdict_sk: str
    reason_sk: str


def evaluate_vote(
    quorum_type: str,
    total_councilors: int,
    present_count: int,
    for_count: int,
) -> VoteOutcome:
    """Evaluate a vote strictly according to SR statutory quorum rules."""
    min_present = min_present_for_quorum(total_councilors)
    quorum_met = present_count >= min_present
    req_for = required_votes_for(quorum_type, total_councilors, present_count)

    if not quorum_met:
        return VoteOutcome(
            quorum_met=False,
            min_present=min_present,
            required_for=req_for,
            passed=False,
            verdict_sk="NEUZNÁŠANIASCHOPNÉ",
            reason_sk=(
                f"Prítomných {present_count} z {total_councilors} poslancov "
                f"(na uznášaniaschopnosť treba najmenej {min_present})."
            ),
        )

    passed = for_count >= req_for
    q_label = QUORUM_LABELS[quorum_type]["label"]
    if passed:
        return VoteOutcome(
            quorum_met=True,
            min_present=min_present,
            required_for=req_for,
            passed=True,
            verdict_sk="SCHVÁLENÉ",
            reason_sk=f"ZA: {for_count} / potrebných: {req_for} ({q_label}).",
        )
    return VoteOutcome(
        quorum_met=True,
        min_present=min_present,
        required_for=req_for,
        passed=False,
        verdict_sk="NESCHVÁLENÉ",
        reason_sk=f"ZA: {for_count} / potrebných: {req_for} ({q_label}).",
    )
