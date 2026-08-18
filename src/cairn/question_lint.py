"""question_lint — check a question BEFORE it is asked, deterministically (D83).

Cairn's other checks run on the way out: is this citation real, does it cover the
question, which reading did we mean. This one runs on the way *in*, and it exists
because of what D82 measured — across twelve patent queries, eleven of thirteen
unmatched terms were **vocabulary the document does not use**: "wattage" against "400
Watt magnetrons", "patentable" against "what is claimed". Those queries did not fail
loudly. They ranked nothing and looked like an answer-free corpus.

Three rules from Julian's rulings (flag, never rewrite; deterministic; in the tool
surface, not the Skill):

  · **The question as asked is what gets recorded and answered.** A linter that
    rewrote a client's question would change what was asked, and the Record of Inquiry
    has to show the original. Every finding is an annotation.
  · **Detection is deterministic** — token membership in the corpus vocabulary,
    locator resolution against real units, and closed-class cue matching. No model, and
    therefore no judgment to audit.
  · **Nothing is blocked.** A finding is advice. The one thing a linter must never do
    is refuse a question that would have been answerable, and it cannot tell.

What it deliberately does NOT do: decide whether a question is *good*. "Is this vague?"
is a judgment, and it belongs to the agent at Layer-E, measured rather than gated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ABSENT_TERMS = "absent_terms"       # words no passage contains — the D82 finding
NO_LOCATOR = "unresolvable_locator"  # names a unit this document does not have
ADJUDICATION = "asks_for_a_ruling"   # asks for a legal conclusion (D10/D22)
COMPOUND = "compound_question"       # two questions in one; partial is the honest answer

_SEVERITY = {ABSENT_TERMS: 1, NO_LOCATOR: 1, ADJUDICATION: 2, COMPOUND: 3}


@dataclass(frozen=True)
class Finding:
    """One thing worth knowing before the question is run."""

    kind: str
    message: str              # what is wrong, in the asker's language
    terms: tuple[str, ...] = ()   # the specific words or units at issue

    @property
    def severity(self) -> int:
        return _SEVERITY.get(self.kind, 9)


# Asking for a legal conclusion is a REFUSE outcome (D22), not a defect — but knowing
# before the search runs is worth saying, because the honest answer is "located, not
# adjudicated" and the asker may want to rephrase toward what Cairn can do.
_RULING = re.compile(
    r"\b(patentab(?:le|ility)|novel(?:ty)?|obvious(?:ness)?|invalid(?:ate|ity)?|"
    r"infring(?:e|es|ing|ement)|freedom.to.operate|enforceab(?:le|ility)|"
    r"anticipated|prior.art.against|claim.construction|means.plus.function)\b",
    re.IGNORECASE)

# Two questions joined into one. "and" alone is far too common to mean this, so the
# signal is a second INTERROGATIVE after a conjunction — "what wattage… and who
# manufactures them?" — which is the shape `partial` exists to answer honestly.
# Pronouns and question-shape words a document has no reason to contain. Kept HERE and
# not added to `retrieval.STOPWORDS`: that set is part of the evidence path, and
# widening it would move every BM25 score and the calibration fitted to them (D82). A
# cosmetic fix to a linter must not become a silent retrieval change.
_NOT_CONTENT = frozenset(
    "it its they them their he she his her we us our you your i me my one ones "
    "there here thing things something anything please tell show give find".split())

_SECOND_ASK = re.compile(
    r"\b(?:and|or|also)\b[^,?]{0,40}\b(who|what|when|where|which|how|why|whether|does|"
    r"is|are|do)\b", re.IGNORECASE)


def lint(question: str, *, vocabulary: frozenset[str] | set[str] = frozenset(),
         units: list | None = None) -> list[Finding]:
    """Findings for a question, most consequential first. Empty means nothing to say.

    `vocabulary` is the corpus's token set (from `retrieval.tokenize`); `units` the
    addressable units (`locator.units_for`). Both optional — a caller with neither still
    gets the cue-based rules, and no rule ever fires on missing evidence.
    """
    from .locator import chain, parse_locator
    from .retrieval import STOPWORDS, tokenize

    out: list[Finding] = []
    q = question or ""

    if vocabulary:
        absent = [w for w in dict.fromkeys(tokenize(q))
                  if w not in STOPWORDS and w not in _NOT_CONTENT
                  and not w.isdigit() and w not in vocabulary]
        if absent:
            one = len(absent) == 1
            out.append(Finding(
                ABSENT_TERMS,
                f"No passage contains {'this word' if one else 'these words'}, so "
                f"{'it contributes' if one else 'they contribute'} nothing to the "
                f"ranking. The document may use different wording for the same thing — "
                f"that is the usual reason, not that the subject is missing.",
                tuple(absent)))

    loc = parse_locator(q)
    if loc and units is not None and not chain(units, loc):
        out.append(Finding(
            NO_LOCATOR,
            f"This question is scoped to “{loc}”, which this document does not have. "
            f"An answer cannot be evidenced from a unit that is not here.",
            (loc,)))

    m = _RULING.search(q)
    if m:
        out.append(Finding(
            ADJUDICATION,
            "This asks for a legal conclusion. Cairn locates and evidences; it does not "
            "adjudicate novelty, validity, infringement or claim construction (D10), so "
            "the honest outcome is a refusal that hands you what it found.",
            (m.group(0),)))

    if _SECOND_ASK.search(q):
        out.append(Finding(
            COMPOUND,
            "This reads as two questions in one. Cairn can answer the part it has and "
            "flag the rest as out of corpus (a `partial`), but asking them separately "
            "gives each its own evidence and its own outcome.",
            ()))

    return sorted(out, key=lambda f: f.severity)
