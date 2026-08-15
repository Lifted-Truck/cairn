"""locator — resolve "per claim 6" / "in section 2" to a span range, and check a
citation actually came from there (D70).

The gap this closes. A question that names where its answer lives ("what does claim 6
recite?") carries a constraint the coverage check could not verify, because coverage
asks whether a constraint's literal appears in the cited text — and **a unit never names
itself**: claim 6's text says "of claim 1", never "claim 6". So the frame convention was
to mark such a constraint `required: false` and let the binding's location stand in for
it, unchecked. That is exactly the shape of an unenforced guarantee: the most locatable
part of the question was the one part nothing confirmed.

A locator is verifiable by *position* rather than by text. Resolve the named unit to its
char range, walk its dependency chain (claim 6 depends on claim 1, so claim 1's language
is legitimately part of claim 6's scope), and check the citation lands inside it.

**Why the chain matters and is not pedantry.** A dependent claim incorporates its parent
by reference, so an answer about claim 6 that cites claim 1 is correct, not off-target.
Without the chain this check would reject the right answer.

Corpus-agnostic by construction: `Unit` carries only a name, a range and a parent. The
per-kind extraction is routed here (patents supply claims) so a corpus swap adds an
extractor rather than touching the checker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "per claim 6", "of claim 1", "in section 2", "under paragraph 4(a)". The unit WORD is
# captured so a patent's claims and a contract's sections use one mechanism.
_LOCATOR = re.compile(
    r"\b(?:per|of|in|under|from|within|according to)?\s*"
    r"\b(claim|section|paragraph|article|clause)\s+"
    r"(\d{1,3}[a-zA-Z]?(?:\([a-z0-9]+\))?)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Unit:
    """A named, addressable region of a document, and the unit it incorporates."""

    name: str                 # canonical + lowercase: "claim 6"
    doc_id: str
    char_start: int
    char_end: int
    parent: str | None = None  # "claim 1" for a dependent claim; None for independent


def canonical(kind: str, number: str) -> str:
    return f"{kind.lower()} {number.lower()}"


def parse_locator(text: str) -> str | None:
    """The unit a question names, or None. First match wins — a question naming two
    units ("how does claim 6 differ from claim 9?") is a comparison, and scoping it to
    the first would quietly answer half the question. Callers get None-safe behaviour:
    no locator means no locator check, never a silently narrowed search."""
    hits = _LOCATOR.findall(text or "")
    if len(hits) != 1:
        return None
    kind, number = hits[0]
    return canonical(kind, number)


def chain(units: list[Unit], name: str) -> list[Unit]:
    """The named unit followed by its ancestors, nearest first. Empty if unknown.

    Cycle-safe: a malformed dependency ("claim 3 of claim 3", or a mutual pair) would
    otherwise spin forever, and a hand-corrected claim set is exactly where that shows
    up. Seen units stop the walk rather than raising — a broken chain is a fact about
    the document, and the caller's job is to report it, not to crash on it.
    """
    by_name = {u.name: u for u in units}
    out: list[Unit] = []
    seen: set[str] = set()
    cur = by_name.get(name)
    while cur is not None and cur.name not in seen:
        seen.add(cur.name)
        out.append(cur)
        cur = by_name.get(cur.parent) if cur.parent else None
    return out


def contains(units: list[Unit], doc_id: str, pos: int) -> bool:
    """Does any unit in this (already-resolved) list contain the offset?"""
    return any(u.doc_id == doc_id and u.char_start <= pos < u.char_end for u in units)


def units_for(doc) -> list[Unit]:
    """Addressable units of a document, by corpus kind.

    The routing seam: `patents` knows how to read claims, this module knows how to check
    them, and neither knows about the other's internals. A corpus that declares no kind
    (or an unknown one) yields no units, so the locator check reports "unresolvable"
    rather than inventing a scope — an unknown unit must never silently pass.
    """
    kind = (getattr(doc, "metadata", None) or {}).get("kind")
    if kind == "patent":
        from .patents import claim_units
        return claim_units(doc.doc_id, doc.canonical_text)
    return []


@dataclass(frozen=True)
class ScopeVerdict:
    """Whether a citation came from the unit the question named."""

    locator: str                # "claim 6"
    resolved: bool              # the unit exists in this document
    in_scope: bool              # at least one cited atom lies inside the chain
    scope: list[str]            # the chain, e.g. ["claim 6", "claim 1"]
    outside: list[str]          # cited positions that fell outside it, for the reader

    @property
    def ok(self) -> bool:
        return self.resolved and self.in_scope

    def describe(self) -> str:
        if not self.resolved:
            return (f"{self.locator}: NOT FOUND in this document — the question names a "
                    f"unit that does not exist here, so nothing was scoped to it")
        where = " → ".join(self.scope)
        if not self.in_scope:
            return (f"{self.locator}: no cited span lies within {where} — the answer may "
                    f"be right, but it is not evidenced from where the question asked")
        extra = f"; {len(self.outside)} further citation(s) outside it" if self.outside else ""
        return f"{self.locator}: cited from within {where}{extra}"


def check_scope(locator: str, units: list[Unit], cited: list[tuple[str, int]]) -> ScopeVerdict:
    """`cited` is (doc_id, char_start) per bound atom.

    Satisfied when **at least one** citation lies in the chain, not all of them: an
    answer about claim 6 may legitimately cite the specification for context, and
    demanding every atom be in-scope would reject good answers. The out-of-scope
    citations are still listed rather than dropped — "answered from claim 6 plus three
    spans elsewhere" is a different claim from "answered from claim 6", and the reader
    is owed the difference.
    """
    resolved = chain(units, locator)
    if not resolved:
        return ScopeVerdict(locator, False, False, [], [])
    inside = [c for c in cited if contains(resolved, *c)]
    outside = [f"{d} @{p}" for d, p in cited if (d, p) not in set(inside)]
    return ScopeVerdict(locator, True, bool(inside), [u.name for u in resolved], outside)
