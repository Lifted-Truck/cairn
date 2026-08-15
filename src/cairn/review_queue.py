"""review_queue — what still needs a human, ranked by consequence (RT-7b, D50).

The discrepancy checks already exist; what did not exist was a **worklist**. A reviewer
faced with a tally ("13 figure mismatches") has no way to act on it item by item, and no
way to record that they looked. So this turns the reconciliation into a queue where every
row is one decision, and every decision becomes an append-only judgment (D47).

**Ranked by consequence, not by count.** The ordering is a claim about what costs most to
get wrong:

  1. `drawn_not_recited` — the tool located a mark the specification never mentions. If it
     is an artifact, something is asserted on a drawing that the document does not support,
     and that is the wrong-place class Cairn exists to prevent. Highest cost.
  2. `figure_mismatch` — recited for FIG. N, located on a different sheet. Either the
     location or the attribution is wrong; both mislead a reader following a citation.
  3. `unresolved_conflict` — one mark, two engines, two readings, unreconciled. A human
     eye settles it in seconds and nothing else can.
  4. `recited_not_drawn` — the spec recites it, OCR found it nowhere. Usually an OCR miss,
     sometimes genuinely undrawn. Low cost because it errs toward *absence*: it withholds
     a location rather than asserting a wrong one.

An empty queue is not a clean bill of health, and the pane says so: these checks compare
drawings against the specification, so anything absent from both is invisible to all of
them (D33's rule, at item level).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueItem:
    """One thing a human should look at, and enough context to decide without leaving."""

    item_id: str          # stable across rebuilds, so a judgment keeps pointing at it
    kind: str             # drawn_not_recited | figure_mismatch | unresolved_conflict | …
    rank: int             # 1 = most consequential
    label: str            # the numeral or marker at issue
    page: int | None
    x: float | None       # manifest coords: BOTTOM-left origin, x/y = the box's lower-left
    y: float | None
    w: float | None
    h: float | None
    question: str         # what the reviewer is being asked, in their words
    detail: str           # the evidence behind the flag


_RANK = {
    "drawn_not_recited": 1,
    "figure_mismatch": 2,
    "unresolved_conflict": 3,
    "recited_not_drawn": 4,
}


def _where(sightings, label: str):
    """The first located position of a label, for a reviewer who wants to look at it.

    Returns `(page, x, y, w, h)` — the whole box, not just its corner. The width and
    height are what let a display centre be computed through `annotate.box_to_display`,
    the tested half of the y-flip pair; without them a consumer has to guess at the
    flip, and the first one that did put its crop on the wrong part of the sheet.
    """
    for s in sightings:
        if str(s.numeral) == str(label):
            bb = getattr(s, "bbox", None) or (None, None, None, None)
            return (getattr(s, "page", None), bb[0], bb[1], bb[2], bb[3])
    return None, None, None, None, None


def build(coverage, sightings, *, adjudicated: set[str] | None = None) -> list[QueueItem]:
    """The worklist, most consequential first, minus anything already judged.

    `adjudicated` holds the `item_id`s a reviewer has already ruled on — the queue is a
    view over *outstanding* work, while the judgments themselves live forever in the
    append-only log. Clearing an item never deletes the record of clearing it.
    """
    done = adjudicated or set()
    items: list[QueueItem] = []

    for label in getattr(coverage, "drawn_not_recited", []):
        page, x, y, w, h = _where(sightings, label)
        items.append(QueueItem(
            f"drawn_not_recited:{label}", "drawn_not_recited", _RANK["drawn_not_recited"],
            str(label), page, x, y, w, h,
            f"Is “{label}” really drawn here?",
            "Located on a sheet but never recited in the specification. If the tool "
            "misread a mark, refuting it removes a location the document does not support."))

    for m in getattr(coverage, "figure_mismatches", []):
        label = m.get("numeral", "?")
        page, x, y, w, h = _where(sightings, label)
        items.append(QueueItem(
            f"figure_mismatch:{label}", "figure_mismatch", _RANK["figure_mismatch"],
            str(label), page, x, y, w, h,
            f"Where does “{label}” actually appear?",
            m.get("message", "Recited for one figure, located on another sheet.")))

    for m in getattr(coverage, "likely_misreads", []):
        if not m.get("unresolved"):
            continue
        label = m.get("numeral", "?")
        page, x, y, w, h = _where(sightings, label)
        items.append(QueueItem(
            f"unresolved_conflict:{label}", "unresolved_conflict",
            _RANK["unresolved_conflict"], str(label), page, x, y, w, h,
            f"Which reading of this mark is right — “{label}” or the alternative?",
            m.get("message", "Two engines read one mark differently and nothing "
                             "reconciled them.")))

    for label in getattr(coverage, "recited_not_drawn", []):
        items.append(QueueItem(
            f"recited_not_drawn:{label}", "recited_not_drawn", _RANK["recited_not_drawn"],
            str(label), None, None, None, None, None,
            f"Can you see “{label}” on a sheet?",
            "The specification recites it; OCR located it nowhere. Usually an OCR miss — "
            "confirming it needs the position, so use the Drawings pane to find it first."))

    live = [i for i in items if i.item_id not in done]
    return sorted(live, key=lambda i: (i.rank, i.label))


def summary(items: list[QueueItem]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i.kind] = out.get(i.kind, 0) + 1
    return out
