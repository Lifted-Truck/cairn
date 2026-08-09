"""verify — the deterministic atom resolver (ROADMAP M2-T1, D9; invariant I1).

The agent composes an answer and binds each **load-bearing atom** (a figure,
percentage, date, named entity) to a specific source location
`(doc_id, char_start, char_end)`. `verify` confirms, deterministically:

  1. each bound atom's slice at that offset equals the atom literal (exact, with
     defined whitespace normalization), and the doc hash matches (I3);
  2. **independent extraction** — verify re-scans the answer text for load-bearing
     figures and requires every one to be bound, so a confabulated number can't
     hide in untagged prose;
  3. **derived** values (a computed delta) aren't cited directly — they declare
     operands (each a bound atom) + an operation that verify recomputes.

The agent **parameterizes** (supplies atoms + bindings); it never **authors** this
resolver (oracle-is-sacred). `verify` confirms a citation is *real and located* —
not that it *entails* the claim (existence ≠ support; entailment is judged offline
at Layer-E). Pure and deterministic; corpus-agnostic. Result persistence is wired
to the audit log at M3.
"""

from __future__ import annotations

import datetime
import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .ingest.document import content_hash
from .spans import SpanError, SpanStore

# Load-bearing atoms that MUST be bound (extending D9's taxonomy):
#  - figures: comma-grouped numbers (optionally parenthesized-negative) or percentages.
#    Lookarounds keep "100" from matching inside "100,544".
#  - dates: "Month DD, YYYY" — the period a financial fact is "as of" is itself a
#    claim and must be grounded (a reviewer caught an ungrounded "as of <date>").
# Bare years / single integers and named entities remain not-independently-required
# (verified when bound); the patent domain pack adds claim-term/numeral extractors.
_FIGURE = re.compile(r"\(?\d{1,3}(?:,\d{3})+\)?|\b\d+(?:\.\d+)?%")
_DATE = re.compile(r"\b[A-Z][a-z]+ \d{1,2}, \d{4}\b")
_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def salient_tokens(text: str) -> set[str]:
    """The load-bearing atoms in a string: figures (parens stripped) + full dates."""
    toks = {m.group(0).strip("()") for m in _FIGURE.finditer(text)}
    toks |= {m.group(0) for m in _DATE.finditer(text)}
    return toks


def salient_counts(text: str) -> Counter[str]:
    """Load-bearing atoms WITH multiplicity (D37).

    Coverage was computed as a set difference, so one binding discharged every
    occurrence of a figure in a sentence: "Total assets were 364,980 and total
    liabilities were also 364,980" passed with a single binding and reported no unbound
    atoms — the second assertion, about a different metric, was an ungrounded claim that
    `verify` blessed. Multiplicity is what makes N assertions require N bindings.
    """
    c = Counter(m.group(0).strip("()") for m in _FIGURE.finditer(text))
    c.update(m.group(0) for m in _DATE.finditer(text))
    return c


def numeric_core(text: str) -> str | None:
    """The figure token inside a literal, normalized for comparison ('$ 364,980' → '364,980')."""
    m = _FIGURE.search(text)
    return m.group(0).strip("()") if m else None


def to_number(text: str) -> float:
    """Parse an accounting figure to a number: '(19,154)' → -19154, '$ 364,980' → 364980."""
    neg = "(" in text and ")" in text
    digits = _NUM.search(text.replace(",", ""))
    if not digits:
        raise ValueError(f"no number in {text!r}")
    val = float(digits.group(0))
    return -abs(val) if neg else val


def _decimals(text: str) -> int:
    """Decimal places written in the asserted result — sets the recompute tolerance."""
    m = re.search(r"\.(\d+)", text.replace(",", ""))
    return len(m.group(1)) if m else 0


@dataclass(frozen=True)
class AtomBinding:
    """A load-bearing atom bound to an exact source location."""

    text: str          # the literal the agent asserts appears at the location
    doc_id: str
    char_start: int
    char_end: int
    content_hash: str | None = None  # the doc hash the binding was made against (drift check)


@dataclass(frozen=True)
class DerivedAtom:
    """A computed value: not cited directly; recomputed from bound operands."""

    text: str                       # the derived figure as written ("12,397")
    operation: str                  # "subtract" | "sum"
    operands: list[AtomBinding]


_OP_SYMBOL = {
    "subtract": " − ", "sum": " + ", "multiply": " × ", "divide": " ÷ ", "ratio": " ÷ ",
}


def equation(d: DerivedAtom) -> str:
    """Human-readable derivation, e.g. '364,980 − 352,583 = 12,397'."""
    if d.operation == "percent_change" and len(d.operands) == 2:
        new, old = d.operands[0].text, d.operands[1].text
        return f"({new} − {old}) / {old} × 100 = {d.text}"
    if d.operation == "within_range" and len(d.operands) == 3:
        v, lo, hi = (o.text for o in d.operands)
        return f"{lo} ≤ {v} ≤ {hi} → {d.text}"
    if d.operation in _REL_SYMBOL:
        return _REL_SYMBOL[d.operation].join(o.text for o in d.operands) + f" → {d.text}"
    sym = _OP_SYMBOL.get(d.operation, f" {d.operation} ")
    lhs = sym.join(o.text for o in d.operands)
    return f"{lhs} = {d.text}"


@dataclass(frozen=True)
class Sentence:
    text: str
    atoms: list[AtomBinding] = field(default_factory=list)
    derived: list[DerivedAtom] = field(default_factory=list)


@dataclass(frozen=True)
class Answer:
    sentences: list[Sentence]


@dataclass
class AtomVerdict:
    binding: AtomBinding
    status: str            # ok | mismatch | out_of_range | stale_hash
    found: str | None      # what the slice actually contained


@dataclass
class SentenceVerdict:
    text: str
    atom_verdicts: list[AtomVerdict]
    derived_ok: list[bool]
    unbound_figures: list[str]      # figures in the text with no binding/derivation
    ok: bool


@dataclass
class VerifyResult:
    sentences: list[SentenceVerdict]
    ok: bool

    def unbound(self) -> list[str]:
        return [f for s in self.sentences for f in s.unbound_figures]


_OPS = {
    "subtract": lambda xs: xs[0] - sum(xs[1:]),
    "sum": sum,
    "multiply": math.prod,
    "divide": lambda xs: xs[0] / xs[1],
    "ratio": lambda xs: xs[0] / xs[1],
    "percent_change": lambda xs: (xs[0] - xs[1]) / xs[1] * 100,
    # VER-1 additions. Each stays a pure recomputation from CITED operands — the result
    # is declared and recomputed, never itself cited (D9).
    "percent": lambda xs: xs[0] / xs[1] * 100,      # x as a percentage OF y
    "min": min,
    "max": max,
    "average": lambda xs: sum(xs) / len(xs),
    # `count` counts the operands the agent CITED, which is the honest reading: it is a
    # claim about the evidence assembled, not a search of the document. An incomplete
    # citation set yields a wrong count, and that is visible — the operands are listed.
    "count": lambda xs: float(len(xs)),
    # `round` is identity here: the tolerance comparison below already rounds the
    # recomputation to the precision the agent wrote, so asserting "approximately 12.4"
    # from 12.437 verifies without a second rounding rule to keep in step.
    "round": lambda xs: xs[0],
}

# Relational checks (D19): each recomputes a NUMERIC relation between cited operands
# and confirms the agent's asserted true/false. `within_range` is value-low-high.
# **Boundary (D10): these verify arithmetic, not legal status** — a value being
# "within range" is a numeric fact, NOT an infringement/novelty/validity conclusion;
# the agent must not phrase the boolean as adjudication (refusal class, Layer-E).
_BOOL_OPS = {
    "gt": lambda xs: xs[0] > xs[1],
    "ge": lambda xs: xs[0] >= xs[1],
    "lt": lambda xs: xs[0] < xs[1],
    "le": lambda xs: xs[0] <= xs[1],
    "eq": lambda xs: xs[0] == xs[1],
    "within_range": lambda xs: xs[1] <= xs[0] <= xs[2],   # value, low, high (inclusive)
}
_REL_SYMBOL = {"gt": " > ", "ge": " ≥ ", "lt": " < ", "le": " ≤ ", "eq": " = "}

# Date arithmetic (VER-1). Separate from `_OPS` because the operands are DATES, and
# `to_number` would reject them — so these dispatch before any numeric parsing.
#
# **Boundary (D10), and it is a sharp one here.** A duration is not a term. `date_delta`
# returns the number of days between two cited dates and nothing more: patent term
# involves adjustments, extensions, terminal disclaimers and maintenance status, none of
# which are arithmetic. Computing 7,300 days between two dates is evidence; calling it
# "the patent expires in 2033" is adjudication, and the tool refuses that rather than
# deriving it.
_DATE_OPS = {
    "date_delta": lambda ds: float((ds[0] - ds[1]).days),
}

# Full names AND the conventional abbreviations, matched WHOLE. An earlier cut truncated
# the month to three characters, which made "Septober 4, 2024" a valid September date —
# a parser that accepts a string nobody wrote is worse than one that rejects a date
# somebody did, because the first fails silently.
_MONTHS: dict[str, int] = {}
for _i, _full in enumerate(
        ["january", "february", "march", "april", "may", "june",
         "july", "august", "september", "october", "november", "december"], start=1):
    _MONTHS[_full] = _i
    _MONTHS[_full[:3]] = _i
_MONTHS["sept"] = 9


def to_date(text: str) -> datetime.date:
    """Parse a cited date literal ("September 28, 2024") to a date.

    Deliberately narrow: it accepts the shape `_DATE` already recognises as a salient
    atom, so anything `verify` treats as a bindable date is exactly what this parses. A
    looser parser would accept strings the rest of the system does not consider dates.
    """
    m = re.match(r"\s*([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})\s*$", text)
    if not m:
        raise ValueError(f"not a date literal: {text!r}")
    mon = _MONTHS.get(m.group(1).lower())
    if mon is None:
        raise ValueError(f"unknown month in {text!r}")
    return datetime.date(int(m.group(3)), mon, int(m.group(2)))

# Version of the derived-operation set (D18/D19); stamped into records (TC-2) and
# bumped when the set changes, so a derivation's record says which ops verified it.
OPS_VERSION = "2"   # VER-1 widened the set (D59)


def _parse_bool(text: str) -> bool:
    t = text.strip().lower()
    if t in ("true", "yes"):
        return True
    if t in ("false", "no"):
        return False
    raise ValueError(f"not a boolean result: {text!r}")


def _normalize(s: str) -> str:
    return " ".join(s.split())


def _resolve(binding: AtomBinding, store: SpanStore) -> AtomVerdict:
    if binding.content_hash is not None:
        current = content_hash(store.get_document(binding.doc_id))
        if binding.content_hash != current:
            return AtomVerdict(binding, "stale_hash", None)
    try:
        slice_ = store.get_span(binding.doc_id, binding.char_start, binding.char_end)
    except SpanError:
        return AtomVerdict(binding, "out_of_range", None)
    ok = _normalize(slice_) == _normalize(binding.text)
    return AtomVerdict(binding, "ok" if ok else "mismatch", slice_)


# --- JSON (the MCP wire form) <-> the structured model -------------------------
# Shared by the tool registry (tools.py) and the replay layer (session.py) so the
# answer-with-tags contract is parsed in exactly one place.

def _atom_from_json(d: dict) -> AtomBinding:
    return AtomBinding(
        text=d["text"],
        doc_id=d["doc_id"],
        char_start=d["char_start"],
        char_end=d["char_end"],
        content_hash=d.get("content_hash"),
    )


def answer_from_json(d: dict) -> Answer:
    """Build an `Answer` from the wire payload (`{"sentences": [...]}`)."""
    sentences: list[Sentence] = []
    for s in d["sentences"]:
        atoms = [_atom_from_json(x) for x in s.get("atoms", [])]
        derived = [
            DerivedAtom(
                text=x["text"],
                operation=x["operation"],
                operands=[_atom_from_json(o) for o in x["operands"]],
            )
            for x in s.get("derived", [])
        ]
        sentences.append(Sentence(text=s["text"], atoms=atoms, derived=derived))
    return Answer(sentences)


def result_to_json(r: VerifyResult) -> dict:
    """Serialize a `VerifyResult` to a JSON-able dict (the tool's return shape)."""
    return {
        "ok": r.ok,
        "unbound": r.unbound(),
        "sentences": [
            {
                "text": s.text,
                "ok": s.ok,
                "unbound_figures": s.unbound_figures,
                "atoms": [
                    {
                        "text": v.binding.text,
                        "doc_id": v.binding.doc_id,
                        "char_start": v.binding.char_start,
                        "char_end": v.binding.char_end,
                        "status": v.status,
                        "found": v.found,
                    }
                    for v in s.atom_verdicts
                ],
                "derived_ok": s.derived_ok,
            }
            for s in r.sentences
        ],
    }


def verify(answer: Answer, store: SpanStore) -> VerifyResult:
    """Resolve every atom + derivation; flag unbound figures. I1/I3 enforced."""
    sentence_verdicts: list[SentenceVerdict] = []
    for sent in answer.sentences:
        atom_verdicts = [_resolve(a, store) for a in sent.atoms]

        derived_ok: list[bool] = []
        for d in sent.derived:
            ops = [_resolve(o, store) for o in d.operands]
            if not all(v.status == "ok" for v in ops):
                derived_ok.append(False)
                continue
            try:
                if d.operation in _DATE_OPS:
                    # Dates first: `to_number` would reject them, so numeric parsing
                    # cannot come before this branch.
                    dates = [to_date(o.text) for o in d.operands]
                    got = _DATE_OPS[d.operation](dates)
                    derived_ok.append(abs(got - to_number(d.text)) < 1e-9)
                    continue
                nums = [to_number(o.text) for o in d.operands]
                if d.operation in _OPS:
                    # Numeric (D18): match the recompute to the asserted result at the
                    # precision the agent wrote — exact for integers, rounded for %/ratio.
                    expected = _OPS[d.operation](nums)
                    derived_ok.append(
                        abs(round(expected, _decimals(d.text)) - to_number(d.text)) < 1e-9
                    )
                elif d.operation in _BOOL_OPS:
                    # Relational (D19): confirm the asserted true/false (a numeric fact).
                    derived_ok.append(_BOOL_OPS[d.operation](nums) == _parse_bool(d.text))
                else:
                    derived_ok.append(False)
            except (ValueError, ZeroDivisionError, IndexError):
                derived_ok.append(False)

        # Independent extraction: every load-bearing atom (figure or date) in the
        # prose must be covered by a binding/derivation, or it is flagged unbound.
        # Counted, not set-differenced (D37): a figure asserted twice in one sentence
        # needs two bindings, or the second assertion is ungrounded prose that the
        # first citation silently vouches for.
        covered: Counter[str] = Counter()
        for a in sent.atoms:
            covered += salient_counts(a.text)
        for d in sent.derived:
            covered += salient_counts(d.text)
            for o in d.operands:
                covered += salient_counts(o.text)
        unbound = sorted((salient_counts(sent.text) - covered).elements())

        ok = (
            all(v.status == "ok" for v in atom_verdicts)
            and all(derived_ok)
            and not unbound
        )
        sentence_verdicts.append(
            SentenceVerdict(sent.text, atom_verdicts, derived_ok, unbound, ok)
        )

    return VerifyResult(sentence_verdicts, all(s.ok for s in sentence_verdicts))
