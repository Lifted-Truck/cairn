"""Standing tests for the review queue and adjudicate pane (RT-7b, D50)."""

from __future__ import annotations

import re
from dataclasses import dataclass

import pytest

from cairn.adjudicate_pane import render as pane
from cairn.review_queue import build, summary

pytestmark = pytest.mark.layer0


@dataclass
class _Cov:
    drawn_not_recited: list
    recited_not_drawn: list
    figure_mismatches: list
    likely_misreads: list


@dataclass
class _Sighting:
    numeral: str
    page: int
    bbox: tuple


def _cov(**kw):
    base = dict(drawn_not_recited=[], recited_not_drawn=[], figure_mismatches=[],
                likely_misreads=[])
    base.update(kw)
    return _Cov(**base)


def test_the_queue_is_ranked_by_consequence_not_by_count():
    """A located mark the spec never mentions outranks a recited one OCR could not find:
    the first may ASSERT something the document does not support (the wrong-place class),
    the second only withholds a location."""
    q = build(_cov(drawn_not_recited=["99"], recited_not_drawn=["12", "14", "16"]),
              [_Sighting("99", 8, (0.5, 0.4, 0.02, 0.02))])
    assert q[0].kind == "drawn_not_recited"
    assert [i.kind for i in q[1:]] == ["recited_not_drawn"] * 3
    assert q[0].rank < q[1].rank


def test_a_judged_item_leaves_the_queue_but_the_judgment_is_not_deleted():
    """The queue is a view over OUTSTANDING work; the record lives forever elsewhere."""
    cov = _cov(drawn_not_recited=["99", "88"])
    s = [_Sighting("99", 8, (0.5, 0.4, 0, 0)), _Sighting("88", 8, (0.1, 0.2, 0, 0))]
    assert len(build(cov, s)) == 2
    left = build(cov, s, adjudicated={"drawn_not_recited:99"})
    assert [i.label for i in left] == ["88"]


def test_item_ids_are_stable_so_a_judgment_keeps_pointing_at_its_item():
    a = build(_cov(drawn_not_recited=["99"]), [_Sighting("99", 8, (0.5, 0.4, 0, 0))])
    b = build(_cov(drawn_not_recited=["99"]), [_Sighting("99", 8, (0.5, 0.4, 0, 0))])
    assert a[0].item_id == b[0].item_id == "drawn_not_recited:99"


def test_the_queue_carries_the_position_so_a_reviewer_can_go_look():
    q = build(_cov(drawn_not_recited=["99"]), [_Sighting("99", 8, (0.5, 0.4, 0, 0))])
    assert (q[0].page, q[0].x, q[0].y) == (8, 0.5, 0.4)


def test_summary_counts_by_kind():
    q = build(_cov(drawn_not_recited=["99"], recited_not_drawn=["12"]),
              [_Sighting("99", 8, (0, 0, 0, 0))])
    assert summary(q) == {"drawn_not_recited": 1, "recited_not_drawn": 1}


def _text(p: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p))


def test_the_pane_offers_no_bulk_accept_and_preselects_nothing():
    """A queue that can be cleared without reading it produces a record saying a human
    looked when none did — worse than no record at all."""
    q = build(_cov(drawn_not_recited=["99", "88"]),
              [_Sighting("99", 8, (0.5, 0.4, 0, 0)), _Sighting("88", 8, (0.1, 0.2, 0, 0))])
    page = pane(q, reviewer="J. Smith", on="2026-07-28")
    # Structural, not string-sniffing: an earlier version of this test failed on the
    # word "pre-selected" in the page's own explanation of why nothing is pre-selected.
    assert "<input" not in page, "no checkboxes to tick through"
    assert "checked" not in re.sub(r"<p[^>]*>.*?</p>", "", page, flags=re.S), \
        "no element carries a checked attribute"
    # Every decision is per item: two items, two full sets of buttons.
    assert page.count("data-kind='confirm'") == 2
    assert page.count("data-kind='refute'") == 2


def test_a_server_without_a_reviewer_renders_read_only():
    """Provenance comes from who started the session, never from whoever has the tab
    open, so a nameless server must not offer to record."""
    page = pane([], reviewer=None, on=None)
    assert "Read-only" in page
    assert "--reviewer" in page


def test_an_empty_queue_is_not_called_a_clean_bill_of_health():
    text = _text(pane([], reviewer="J. Smith", on="2026-07-28"))
    assert "Nothing outstanding" in text
    assert "not a clean bill of health" in text
    assert "invisible to all of them" in text


def test_each_located_row_shows_the_sheet_where_the_question_is_asked():
    """"Is 20 really drawn here?" is unanswerable from a description. Before this the
    queue asked exactly that and showed nothing, leaving the reviewer to open the
    Drawings pane and find the spot by eye for every row — which invites judging the
    description of the evidence instead of the evidence."""
    q = build(_cov(drawn_not_recited=["20"]),
              [_Sighting("20", 2, (0.4836, 0.2567, 0.018, 0.012))])
    page = pane(q, reviewer="J. Smith", on="2026-07-28",
                sheet_files={2: "drawings-page-2.png"})
    assert "class='crop'" in page
    assert "data-file='drawings-page-2.png'" in page
    # The ring's centre in DISPLAY space, not the raw manifest corner: manifest y is
    # measured from the bottom to the box's lower edge (annotate.box_to_display).
    assert "data-x='0.492600'" in page       # 0.4836 + 0.018/2
    assert "data-y='0.737300'" in page       # 1 - (0.2567 + 0.012) + 0.012/2
    assert "sheets/" in page, "the crop reads the sheet copied beside the console"


def test_a_row_with_no_location_never_frames_empty_space():
    """A recited-not-drawn flag has no coordinates by construction — that absence IS the
    finding. It must never get a crop: an empty frame reads as "looked here, found
    nothing", which asserts a location the system does not have. It states the absence,
    and (D75) offers a surface to supply what OCR missed."""
    q = build(_cov(recited_not_drawn=["77"]), [])
    page = pane(q, reviewer="J. Smith", on="2026-07-28", sheet_files={2: "p2.png"})
    assert "class='crop'" not in page
    assert "Not located by OCR on any sheet" in page


def test_the_crop_is_omitted_when_the_sheet_image_is_missing():
    """Sheets are optional (an engagement may have text only). No image, no frame."""
    q = build(_cov(drawn_not_recited=["20"]),
              [_Sighting("20", 2, (0.48, 0.25, 0.02, 0.01))])
    page = pane(q, reviewer="J. Smith", on="2026-07-28", sheet_files={})
    assert "class='crop'" not in page
    assert "no sheet image available for page 2" in page


def test_an_unlocated_numeral_gets_a_surface_to_draw_it_on():
    """D75: a `recited_not_drawn` row says the spec recites a numeral OCR could not
    find on any sheet. An OCR miss and a drawing omission are indistinguishable from
    there (D10) and only a human can tell them apart by looking — so this is the row
    that most needs a drawing surface, and it was the one row that had none. Telling
    the reviewer "not located" and stopping sent them to another pane to do the one
    thing the row is asking for."""
    q = build(_cov(recited_not_drawn=["77"]), [])
    page = pane(q, reviewer="J. Smith", on="2026-08-15",
                sheet_files={2: "p2.png", 3: "p3.png"})
    assert "class='locate'" in page
    assert "data-file='p2.png'" in page and "data-file='p3.png'" in page   # any sheet
    assert "Record this location" in page
    assert "box_px" in page, "the box is sent as pixels; Python does the conversion (D51)"


def test_no_sheets_means_no_drawing_surface_and_says_why():
    """With no drawings available there is nothing to draw on, and the row says that
    rather than offering a control that cannot work."""
    q = build(_cov(recited_not_drawn=["77"]), [])
    page = pane(q, reviewer="J. Smith", on="2026-08-15", sheet_files={})
    assert "class='locate'" not in page
    assert "no drawing sheets are available" in page
