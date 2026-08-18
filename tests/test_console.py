"""Standing tests for the console frame (RT-10, D48)."""

from __future__ import annotations

import re

import pytest

from cairn.console import ConsoleState, Pane, render

pytestmark = pytest.mark.layer0


def _state(**kw):
    base = dict(engagement="Test", doc_ids=["D1"], calibration="Floor 15.1, calibrated.",
                calibrated=True, contract="1.2", adjudications=2, generated_on="2026-07-28",
                panes=[Pane("evidence", "Evidence", "show the work", "evidence.html"),
                       Pane("locate", "Locate", "ask", None, "not built yet")])
    base.update(kw)
    return ConsoleState(**base)


def _text(page: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))


def test_an_uncalibrated_corpus_is_stated_in_the_persistent_header():
    """D33's rule, architecturally: a caveat that scrolls away is a caveat that did not
    work. The header sits above every pane, so an uncalibrated floor — which skews toward
    refusing answerable questions, and therefore reads as diligence — cannot be missed by
    a reviewer who never opens a settings tab."""
    page = render(_state(calibrated=False,
                         calibration="This corpus has NO calibration record — abstentions "
                                     "here are unreliable."))
    header = page[:page.index("<main")]
    assert "NO calibration record" in header
    assert "NOT calibrated" in header
    assert 'class="cal warn"' in header


def test_a_calibrated_corpus_does_not_cry_wolf():
    header = render(_state())[:render(_state()).index("<main")]
    assert 'class="cal ok"' in header
    assert "NOT calibrated" not in header


def test_absent_panes_say_what_is_missing_rather_than_disappearing():
    """A stage that silently vanishes is indistinguishable from one with no findings."""
    page = render(_state())
    assert "not built yet" in _text(page)
    assert "data-pane='locate'" in page, "the tab stays visible, dimmed"
    assert "class='dim'" in page


def test_every_pane_has_a_body_and_the_first_available_one_shows():
    page = render(_state())
    for key in ("evidence", "locate"):
        assert f"id='pane-{key}'" in page
    assert "id='pane-evidence'><iframe" in page, "the first available pane shows"
    assert "id='pane-locate' hidden" in page


def test_reviewer_judgments_are_visible_without_opening_a_pane():
    page = render(_state(adjudications=7))
    assert "7" in _text(page[:page.index("<main")])


def test_engagement_text_is_escaped():
    page = render(_state(engagement="<script>alert(1)</script>"))
    assert "<script>alert(1)</script>" not in page.replace("&lt;script&gt;", "")
    assert "&lt;script&gt;" in page


def test_the_locate_pane_is_a_search_box_and_says_so():
    """D81: it used to report a support VERDICT. On this corpus the floor does not
    separate answerable questions from content-absent ones, so the verdict carried almost
    no information and nearly every query a reviewer typed came back as an abstention. A
    pane whose main output is a refusal the header already calls unreliable is worse than
    no pane."""
    from cairn.locate_pane import render as locate
    page = locate()
    text = _text(page)
    assert "does not decide" in text and "never abstains" in text
    # Structural, not string-sniffing: the page explains the OLD behaviour in its
    # footnote, so searching the prose for "supported" finds the explanation and fails.
    # What must be gone is the CALL that produced a verdict.
    assert "status === 'supported'" not in page
    assert "d.supporting" not in page and "d.closest" not in page


def test_the_locate_pane_runs_the_real_retrieval_not_a_second_one():
    """A second BM25 in JavaScript would be a second oracle that can drift, in a system
    whose claim is that the same corpus and query give the same result (I6)."""
    from cairn.locate_pane import render as locate
    page = locate()
    assert "tool/search_corpus" in page
    assert "tool/check_support" not in page, "the floor is no longer applied here"


def test_the_locate_pane_fetches_span_text_through_the_verifying_accessor():
    """The text a reviewer reads is fetched via get_span, which re-verifies the document
    hash (I3) — so it is exactly what verification would confirm, not a cached copy."""
    from cairn.locate_pane import render as locate
    assert "tool/get_span" in locate()


def test_the_open_pane_survives_a_refresh():
    """D81: rebuilding after every ruling is the normal rhythm, so landing back on the
    first tab each time is a tax on the loop. The open pane rides in the URL hash."""
    from cairn.console import ConsoleState, Pane
    from cairn.console import render as console
    page = console(ConsoleState(
        engagement="e", doc_ids=["D"], calibration="c", calibrated=True,
        contract="2.1", generated_on="2026-08-15",
        panes=[Pane("corpus", "Corpus", "s", "corpus.html", ""),
               Pane("adjudicate", "Adjudicate", "s", "adjudicate.html", "")]))
    assert "history.replaceState" in page
    assert "location.hash" in page
