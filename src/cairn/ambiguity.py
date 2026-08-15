"""ambiguity — the interpretive questions only a human can close (D77).

Everything else in Cairn answers "is this citation real and located?". This module
asks a different question: **"which reading of this did we mean?"** — and it never
answers it. It surfaces the fork, shows the evidence on both sides, proposes the
reading the deterministic signals favour, and waits.

Why it exists. The drawing/spec reconciliation and the figure overlay both have to
decide what a number *is*: reference numeral 20 (a ceramic scrubber) and the "20" in
"a maximum diameter of 20 inches" are the same three glyphs and different facts. The
code used to guess silently and present the guess with the visual authority of
evidence. A guess a human could settle in two seconds was instead being made by a
regex, invisibly, on the grounding path.

The shape of the fix, and its boundary:

  · **Detection is deterministic.** Every ambiguity here comes from two mechanisms
    disagreeing about the same token — not from a model's impression that something
    looks unclear. It is reproducible, and it is auditable by re-running.
  · **The proposal is a recommendation, and is labelled one.** `Ambiguity.proposed`
    names the reading the evidence favours and `rationale` says why. It is never
    applied on its own; nothing downstream reads it.
  · **The resolution is a human judgment**, recorded in the same append-only
    adjudication log as every other reviewer decision (`target_kind="ambiguity"`),
    where `supersede_ok=False` keeps a machine from ever displacing it (D47).
  · **Unresolved is a stated condition, never a block** (Julian's ruling): the header
    and the Record carry the count, and an affected answer is marked provisional.
    Blocking would make the honest state the expensive one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Ambiguity kinds, most consequential first — the same ranking discipline the review
# queue uses, and for the same reason: a list not ordered by cost is read top-down and
# abandoned halfway.
NUMERAL_SENSE = "numeral_sense"        # is this token a part number or a measurement?
OCR_CONFLICT = "ocr_conflict"          # two engines, two readings, nothing reconciled
FIGURE_GUESS = "figure_guess"          # a sheet paired to a figure by elimination
ELEMENT_PHRASE = "element_phrase"      # the parser took a clause for a part name

_RANK = {NUMERAL_SENSE: 1, OCR_CONFLICT: 2, FIGURE_GUESS: 3, ELEMENT_PHRASE: 4}


@dataclass(frozen=True)
class Option:
    """One reading on offer, with what recommends it."""

    value: str                # the reading, e.g. "reference numeral" / "measurement"
    rationale: str            # the evidence for it, in the reviewer's language


@dataclass(frozen=True)
class Ambiguity:
    """A fork in interpretation, with the evidence for each branch."""

    amb_id: str               # stable across rebuilds, so a resolution keeps pointing at it
    kind: str
    label: str                # the token or object at issue ("20", "FIG. 6")
    question: str             # what the reviewer is being asked, in their words
    detail: str               # why it is ambiguous
    options: tuple[Option, ...]
    proposed: str = ""        # the value the evidence favours — a recommendation only
    where: dict = field(default_factory=dict)   # doc_id/offsets or page, for the target

    @property
    def rank(self) -> int:
        return _RANK.get(self.kind, 9)


# A unit immediately after a number makes it a measurement, not a part. Kept in step
# with `patents._UNIT_AFTER` deliberately — two answers to "is this a quantity?" is how
# the two halves of this check would drift apart.
def _quantity_uses(text: str, label: str) -> list[int]:
    from .patents import _UNIT_AFTER
    out = []
    for m in re.finditer(rf"(?<![\w.]){re.escape(label)}(?![\w])", text):
        if _UNIT_AFTER.match(text[m.end():m.end() + 14]):
            out.append(m.start())
    return out


def _excerpt(text: str, pos: int, width: int = 90) -> str:
    lo, hi = max(0, pos - width // 2), min(len(text), pos + width // 2)
    return ("…" if lo else "") + " ".join(text[lo:hi].split()) + ("…" if hi < len(text) else "")


def numeral_sense(text: str, mentions) -> list[Ambiguity]:
    """A token recited as a reference numeral AND used as a measurement elsewhere.

    This is the case that produced a visibly wrong highlight: numeral 20 is a ceramic
    scrubber, and "a maximum diameter of 20 inches" is a dimension, and the overlay lit
    the scrubber because the answer contained "20". The guards now separate the two
    automatically (D76) — this surfaces the collision anyway, because the separation is
    a rule about the immediate next word and a reviewer who knows the document can
    confirm in a glance what a rule can only infer.
    """
    recited = {m.number: m for m in mentions}
    out: list[Ambiguity] = []
    for label, first in sorted(recited.items(), key=lambda kv: (len(kv[0]), kv[0])):
        uses = _quantity_uses(text, label)
        if not uses:
            continue
        out.append(Ambiguity(
            amb_id=f"{NUMERAL_SENSE}:{label}",
            kind=NUMERAL_SENSE,
            label=label,
            question=f"Does “{label}” mean the part, or a measurement?",
            detail=(f"“{label}” is recited as a reference numeral "
                    f"(“{first.element}”) and also appears {len(uses)} time(s) as a "
                    f"quantity. Cairn separates them by the word that follows the "
                    f"number; you can separate them by knowing the document."),
            options=(
                Option("both", f"“{label}” is the part “{first.element}” where recited "
                               f"as such, and a measurement where a unit follows — the "
                               f"reading Cairn applies now"),
                Option("part only", f"every “{label}” in this document refers to the "
                                    f"part; the quantity readings are wrong"),
                Option("measurement only", f"“{label}” is never a reference numeral "
                                           f"here; the recitation was misparsed"),
            ),
            proposed="both",
            where={"numeral": label, "char_start": first.char_start,
                   "char_end": first.char_end,
                   "recited_as": _excerpt(text, first.char_start),
                   "quantity_as": _excerpt(text, uses[0])},
        ))
    return out


def ocr_conflict(coverage) -> list[Ambiguity]:
    """Two engines read one mark differently and the text favours neither.

    **This is the one kind that carries no recommendation, and that is the point.**
    "Unresolved" here means precisely that the specification ties neither reading to
    that figure — so there is no deterministic signal to recommend from, and offering
    one would manufacture confidence in the single case defined by its absence. The
    panel's whole claim is that it shows forks honestly; a fork with a fabricated
    favourite would be the first thing to break that.

    The record's fields are `read_as` / `actually`, ordered by OCR confidence for an
    unresolved pair — NOT by which the text recites, because for these neither is.
    """
    out = []
    for m in getattr(coverage, "likely_misreads", []) or []:
        if not m.get("unresolved"):
            continue
        lower, higher = str(m.get("read_as", "")), str(m.get("actually", ""))
        if not lower or not higher:
            continue
        page = m.get("page")
        pair = sorted((lower, higher), key=lambda s: (len(s), s))
        out.append(Ambiguity(
            amb_id=f"{OCR_CONFLICT}:p{page}:{pair[0]}-{pair[1]}",
            kind=OCR_CONFLICT,
            label=f"{pair[0]} / {pair[1]}",
            question=f"Is this mark “{pair[0]}” or “{pair[1]}”?",
            detail=m.get("message", "Two readings of one mark; nothing reconciled them."),
            options=(
                Option(higher, "the reading with the higher OCR confidence"),
                Option(lower, "the reading with the lower OCR confidence"),
                Option("neither", "both engines misread it; the mark is something else"),
            ),
            proposed="",          # deliberately none — see the docstring
            where={"page": page, "readings": [lower, higher],
                   "bbox": m.get("bbox")},
        ))
    return out


def figure_guess(assignments) -> list[Ambiguity]:
    """A figure paired to a sheet because one of each was left over — not because a
    label was read. Flagged in the Drawings pane since RT-4 and never asked about, so
    the guess has been carried forward as though it were an observation."""
    from .figures_map import ELIMINATION
    out = []
    for a in assignments:
        if a.method != ELIMINATION:
            continue
        out.append(Ambiguity(
            amb_id=f"{FIGURE_GUESS}:{a.fig}",
            kind=FIGURE_GUESS,
            label=f"FIG. {a.fig}",
            question=f"Is FIG. {a.fig} the drawing on sheet p.{a.page}?",
            detail=(f"No FIG label was read on sheet p.{a.page}. This pairing is by "
                    f"elimination — exactly one figure and one sheet were left over — "
                    f"which is a deduction about what remains, not a reading of the "
                    f"sheet."),
            options=(Option("yes", f"sheet p.{a.page} does show FIG. {a.fig}"),
                     Option("no", "the pairing is wrong; this figure is elsewhere")),
            proposed="yes",
            where={"fig": a.fig, "page": a.page},
        ))
    return out


def element_phrase(mentions) -> list[Ambiguity]:
    """A numeral whose element name is still a sentence fragment after reduction.

    Judged by `nounphrase.is_name` rather than by LENGTH. A word count flagged long but
    perfectly good names ("primary and secondary liquid outlet pipes") while passing
    short broken ones ("include a", "by a motor") — it measured the wrong property. What
    matters is whether the phrase ends in something that can head a noun phrase.
    """
    from .nounphrase import is_name
    seen: dict[str, object] = {}
    for m in mentions:
        seen.setdefault(m.number, m)
    out = []
    for label, m in sorted(seen.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if is_name(m.element):
            continue
        out.append(Ambiguity(
            amb_id=f"{ELEMENT_PHRASE}:{label}",
            kind=ELEMENT_PHRASE,
            label=label,
            question=f"What is “{label}” actually called?",
            detail=(f"The parser read the element as “{m.element}”, which is a sentence "
                    f"fragment rather than a part name — the numeral is located "
                    f"correctly, but this is the name the legend shows."),
            options=(Option(m.element, "keep the parsed phrase"),
                     Option("(correct it)", "type the part's real name")),
            proposed="(correct it)",
            where={"numeral": label, "char_start": m.char_start, "char_end": m.char_end},
        ))
    return out


TARGET_KIND = "ambiguity"


def resolutions(log) -> dict[str, str]:
    """`amb_id` → the reading the reviewer chose, from the adjudication log.

    Only judgments whose `target_kind` is `ambiguity` are read — the log carries
    marks-on-sheets rulings too, and a consumer that reads another kind's records will
    act on an assertion nobody made.
    """
    out: dict[str, str] = {}
    for a in log.effective():
        if a.target_kind != TARGET_KIND:
            continue
        reading = (a.value or {}).get("reading")
        if reading:
            out[a.target.get("amb_id", a.adj_id.split("::")[0])] = reading
    return out


def excluded_numerals(resolved: dict[str, str]) -> set[str]:
    """Numerals a reviewer has ruled are *never* reference numerals here.

    The feedback path for the case that started this: if "20" is a measurement in this
    document and not a part, the figure overlay must stop offering to light it. A
    ruling that changes nothing downstream is a ruling the reviewer will stop making.
    """
    return {amb_id.split(":", 1)[1] for amb_id, reading in resolved.items()
            if amb_id.startswith(f"{NUMERAL_SENSE}:") and reading == "measurement only"}


def collect(*, text: str = "", mentions=(), coverage=None, assignments=(),
            resolved: set[str] | None = None) -> list[Ambiguity]:
    """Every outstanding ambiguity, most consequential first.

    `resolved` holds `amb_id`s already ruled on — the panel is a view over OUTSTANDING
    work, while the rulings themselves live forever in the adjudication log. Clearing
    an item never clears the record of clearing it.
    """
    done = resolved or set()
    found: list[Ambiguity] = []
    if text and mentions:
        found += numeral_sense(text, mentions)
        found += element_phrase(mentions)
    if coverage is not None:
        found += ocr_conflict(coverage)
    if assignments:
        found += figure_guess(assignments)
    return sorted((a for a in found if a.amb_id not in done),
                  key=lambda a: (a.rank, len(a.label), a.label))
