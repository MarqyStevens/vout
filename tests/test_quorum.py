"""Unit tests for Slovak statutory quorum rules (verified against knowledge/domain-rules.md)."""

import pytest

from vout.quorum import (
    evaluate_vote,
    is_quorate,
    min_present_for_quorum,
    required_votes_for,
)


# Exact verification table for 13 councilors (MČ Košice-Dargovských hrdinov)
# Columns: (present, quorate, maj_present, maj_all, tf_present, tf_all)
FURCA_13_TABLE = [
    (6, False, 4, 7, 4, 8),
    (7, True, 4, 7, 5, 8),
    (8, True, 5, 7, 5, 8),
    (9, True, 5, 7, 6, 8),
    (10, True, 6, 7, 6, 8),
    (11, True, 6, 7, 7, 8),
    (12, True, 7, 7, 8, 8),
    (13, True, 7, 7, 8, 8),
]


@pytest.mark.parametrize("present,quorate,mp,ma,tfp,tfa", FURCA_13_TABLE)
def test_furca_13_councilors_quorum_table(present, quorate, mp, ma, tfp, tfa):
    total = 13
    assert min_present_for_quorum(total) == 7
    assert is_quorate(total, present) is quorate
    assert required_votes_for("majority_present", total, present) == mp
    assert required_votes_for("majority_all", total, present) == ma
    assert required_votes_for("three_fifths_present", total, present) == tfp
    assert required_votes_for("three_fifths_all", total, present) == tfa


def test_non_quorate_never_passes_even_unanimous():
    outcome = evaluate_vote("majority_present", total_councilors=13, present_count=6, for_count=6)
    assert outcome.quorum_met is False
    assert outcome.passed is False
    assert outcome.verdict_sk == "NEUZNÁŠANIASCHOPNÉ"


def test_boundary_pass_and_fail_majority_present():
    # 10 present -> need 6
    assert evaluate_vote("majority_present", 13, 10, 5).passed is False
    assert evaluate_vote("majority_present", 13, 10, 6).passed is True


def test_boundary_three_fifths_present_vzn():
    # 12 present -> 3/5 of 12 = 7.2 -> need 8 (NOT 7!)
    assert evaluate_vote("three_fifths_present", 13, 12, 7).passed is False
    assert evaluate_vote("three_fifths_present", 13, 12, 8).passed is True


def test_boundary_three_fifths_all_special_property():
    # 13 total, 7 present -> 3/5 of 13 = 7.8 -> need 8 (impossible with only 7 present!)
    assert evaluate_vote("three_fifths_all", 13, 7, 7).passed is False
    # 8 present, 8 for -> passes
    assert evaluate_vote("three_fifths_all", 13, 8, 8).passed is True


@pytest.mark.parametrize(
    "total,min_p,tf_all",
    [
        (3, 2, 2),
        (5, 3, 3),
        (7, 4, 5),
        (9, 5, 6),
        (11, 6, 7),
        (13, 7, 8),
        (15, 8, 9),
        (25, 13, 15),
        (41, 21, 25),
    ],
)
def test_various_slovak_municipality_sizes(total, min_p, tf_all):
    assert min_present_for_quorum(total) == min_p
    assert required_votes_for("three_fifths_all", total, total) == tf_all
