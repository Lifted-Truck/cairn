"""Standing tests for locator scoping (D70) — "per claim 6" checked by position."""

from __future__ import annotations

import pytest

from cairn.locator import Unit, chain, check_scope, parse_locator

pytestmark = pytest.mark.layer0

UNITS = [
    Unit("claim 1", "D", 0, 100, None),
    Unit("claim 6", "D", 100, 200, "claim 1"),
    Unit("claim 9", "D", 200, 300, "claim 6"),
]


def test_a_locator_is_read_only_when_the_question_names_exactly_one_unit():
    """A question naming two units is a COMPARISON, and scoping it to the first would
    quietly answer half of it. No locator means no scoping — never a silently narrowed
    search."""
    assert parse_locator("What does claim 6 recite?") == "claim 6"
    assert parse_locator("the treatment system of claim 21") == "claim 21"
    assert parse_locator("in section 2, paragraph form") == "section 2"
    assert parse_locator("How does claim 6 differ from claim 9?") is None
    assert parse_locator("What is the exhaust fan speed?") is None


def test_the_dependency_chain_is_part_of_a_claim_s_scope():
    """A dependent claim incorporates its parent by reference, so an answer about
    claim 9 that cites claim 1 is on-target. Without the chain this check would reject
    the right answer — the failure mode that would make the whole check harmful."""
    assert [u.name for u in chain(UNITS, "claim 9")] == ["claim 9", "claim 6", "claim 1"]
    assert chain(UNITS, "claim 99") == []


def test_a_cyclic_dependency_terminates_instead_of_spinning():
    """A hand-corrected or malformed claim set is exactly where a cycle appears, and a
    broken chain is a fact about the document — reported, not crashed on."""
    cyc = [Unit("claim 2", "D", 0, 10, "claim 3"), Unit("claim 3", "D", 10, 20, "claim 2")]
    assert [u.name for u in chain(cyc, "claim 2")] == ["claim 2", "claim 3"]


def test_a_citation_from_the_parent_claim_is_in_scope():
    v = check_scope("claim 9", UNITS, [("D", 50)])          # inside claim 1
    assert v.ok and v.scope == ["claim 9", "claim 6", "claim 1"]


def test_a_citation_from_an_unrelated_unit_is_out_of_scope():
    """The failure this exists to catch: an answer to "per claim 9" evidenced from
    somewhere claim 9 does not reach."""
    v = check_scope("claim 6", UNITS, [("D", 250)])          # claim 9, not an ancestor
    assert v.resolved and not v.in_scope and not v.ok
    assert "not evidenced from where the question asked" in v.describe()


def test_context_citations_do_not_defeat_an_in_scope_answer():
    """At least one citation must be in scope, not all: an answer about claim 6 may
    legitimately cite the specification for context. The extras are still reported —
    "answered from claim 6 plus two spans elsewhere" is a different claim."""
    v = check_scope("claim 6", UNITS, [("D", 150), ("D", 900), ("D", 950)])
    assert v.ok and len(v.outside) == 2
    assert "further citation(s) outside it" in v.describe()


def test_an_unresolvable_unit_fails_rather_than_passing_quietly():
    """A question naming a claim this document does not have is not a question this
    document can answer. A check that cannot run must never read as a check that
    passed — the D65 lesson, applied to scope."""
    v = check_scope("claim 99", UNITS, [("D", 50)])
    assert not v.resolved and not v.ok
    assert "NOT FOUND" in v.describe()


def test_claim_units_carry_their_dependency_parent():
    from cairn.patents import claim_units
    text = ("What is claimed is:\n\n"
            "1. A system comprising a widget.\n\n"
            "2. The system of claim 1, further including a gadget.\n")
    us = {u.name: u for u in claim_units("D", text)}
    assert us["claim 1"].parent is None
    assert us["claim 2"].parent == "claim 1"
    assert text[us["claim 2"].char_start:us["claim 2"].char_end].startswith("2.")
