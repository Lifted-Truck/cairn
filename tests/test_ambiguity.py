"""Standing tests for the interpretation queue (D77).

Cairn's other checks ask "is this citation real and located?". These ask "which
reading did we mean?" — and never answer it: detection is deterministic, the proposal
is labelled a recommendation, and the resolution is a human judgment.
"""

from __future__ import annotations

import pytest

from cairn.ambiguity import (
    NUMERAL_SENSE,
    collect,
    excluded_numerals,
    numeral_sense,
)
from cairn.patents import numeral_mentions

pytestmark = pytest.mark.layer0

TEXT = (
    "DESCRIPTION\n"
    "A ceramic scrubber 20 is provided downstream of the reactor.\n"
    "The upper chamber 80 has a maximum diameter of 20 inches.\n"
    "\nWhat is claimed is:\n\n1. A system.\n"
)


def test_a_token_that_is_both_a_part_and_a_measurement_is_surfaced():
    """The case that produced a visibly wrong highlight: reference numeral 20 is a
    ceramic scrubber, and "a maximum diameter of 20 inches" is a dimension. Same three
    glyphs, different facts — and the code used to pick one silently."""
    ambs = numeral_sense(TEXT, numeral_mentions(TEXT))
    a = next(x for x in ambs if x.label == "20")
    assert a.kind == NUMERAL_SENSE
    assert "scrubber" in a.where["recited_as"]
    assert "inches" in a.where["quantity_as"]
    assert {o.value for o in a.options} == {"both", "part only", "measurement only"}


def test_the_proposal_is_a_recommendation_and_never_a_default():
    """Nothing is applied until a human chooses. A recommendation that quietly acts is
    the machine deciding, which is the whole thing this panel exists to stop."""
    a = next(x for x in numeral_sense(TEXT, numeral_mentions(TEXT)) if x.label == "20")
    assert a.proposed == "both"
    # …and the proposal is one of the offered readings, never a fourth thing.
    assert a.proposed in {o.value for o in a.options}


def test_a_number_used_only_as_a_measurement_raises_no_question():
    """No recitation, no fork: a bare quantity was never a candidate reference numeral,
    so surfacing it would be noise in a queue whose value is that it is short."""
    text = ("DESCRIPTION\nThe flow is 45 gallons per minute.\n"
            "\nWhat is claimed is:\n\n1. A system.\n")
    assert numeral_sense(text, numeral_mentions(text)) == []


def test_a_resolved_ambiguity_leaves_the_queue_but_can_still_be_read_back():
    ambs = collect(text=TEXT, mentions=numeral_mentions(TEXT))
    assert any(a.amb_id == f"{NUMERAL_SENSE}:20" for a in ambs)
    left = collect(text=TEXT, mentions=numeral_mentions(TEXT),
                   resolved={f"{NUMERAL_SENSE}:20"})
    assert all(a.amb_id != f"{NUMERAL_SENSE}:20" for a in left)


def test_ruling_a_token_a_measurement_feeds_back_and_stops_it_being_lit():
    """A ruling that changes nothing downstream is a ruling the reviewer stops making.
    "20 is never a part here" must remove it from what the figure overlay offers."""
    assert excluded_numerals({f"{NUMERAL_SENSE}:20": "measurement only"}) == {"20"}
    assert excluded_numerals({f"{NUMERAL_SENSE}:20": "both"}) == set()


def test_only_ambiguity_rulings_are_read_back_as_readings(tmp_path):
    """One log, several target kinds. A consumer that reads another kind's records acts
    on an assertion nobody made — the guard that also keeps a figure ruling from
    injecting a numeral onto a sheet."""
    from cairn.adjudication import Adjudication, AdjudicationLog
    from cairn.ambiguity import TARGET_KIND, resolutions

    log = AdjudicationLog(tmp_path / "adj.jsonl")
    log.append(Adjudication(
        adj_id=f"{NUMERAL_SENSE}:20::correct::2026-08-15", kind="correct",
        target_kind=TARGET_KIND, target={"amb_id": f"{NUMERAL_SENSE}:20"},
        value={"reading": "measurement only"}, by="J. Smith", on="2026-08-15"))
    log.append(Adjudication(                       # a marks-on-sheets ruling, not a reading
        adj_id="drawn_not_recited:99::refute::2026-08-15", kind="refute",
        target_kind="figure-numeral", target={"page": 2, "numeral": "99"},
        by="J. Smith", on="2026-08-15"))

    got = resolutions(log)
    assert got == {f"{NUMERAL_SENSE}:20": "measurement only"}


def test_a_figure_ruling_never_injects_a_numeral_onto_the_sheet(tmp_path):
    """The guard the shared log made necessary: confirming "FIG. 6 is on sheet p.7"
    must not add a mark called "6" to that sheet."""
    from cairn.adjudication import Adjudication, AdjudicationLog
    from cairn.ambiguity import FIGURE_GUESS, TARGET_KIND
    from cairn.figures_map import apply_adjudications

    log = AdjudicationLog(tmp_path / "adjudications.jsonl")
    log.append(Adjudication(
        adj_id=f"{FIGURE_GUESS}:6::confirm::2026-08-15", kind="confirm",
        target_kind=TARGET_KIND, target={"amb_id": f"{FIGURE_GUESS}:6", "fig": "6",
                                         "page": 7},
        value={"reading": "yes"}, by="J. Smith", on="2026-08-15"))
    man = {"pages": [{"page": 7, "numerals": []}]}
    assert apply_adjudications(man, tmp_path)["pages"][0]["numerals"] == []
