"""corpus_fit — the inventory of constants fitted to a particular corpus (RT-6, D42).

Every extraction constant in Cairn was fitted to **one 1995 mechanical patent**
(US5447630A) or **one Apple 10-K**, and each was discovered the same way: a human
noticed a miss. A second corpus will break constants nobody has yet identified *as*
constants — that is the whole risk this module exists to make visible.

The point is not documentation. It is that **a constant with no recorded provenance is
indistinguishable from a law.** So each one is declared here with the evidence that set
it and, crucially, its *falsifier*: the observation that would show it does not transfer.
A standing Layer-0 test compares each declared value against the live value in code, so:

  · changing a constant without updating its provenance FAILS the gate;
  · adding a new module-level constant to a fitted module without registering it FAILS
    the gate (see `tests/test_corpus_fit.py`).

That is L0010 applied to this project's own worst habit: a lesson recorded only in prose
gets re-learned. `scope` is the field to read first when pointing Cairn at a new corpus —
`corpus` means "expect this to be wrong until re-measured", not "probably fine".
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass


@dataclass(frozen=True)
class FittedConstant:
    """A tunable whose value came from evidence, with that evidence attached."""

    name: str          # dotted path as a human would grep for it
    # The value RECORDED here; a standing test asserts the code still matches it, so
    # retuning without updating the provenance fails the gate. `None` means
    # PROVENANCE-ONLY: the value is not pinned because it is an open-ended lexical set
    # that legitimately grows by evidence (a word list, a cue list). Pinning those would
    # make the gate fire on every legitimate addition and train everyone to update the
    # number without reading the reason — which is the failure this module prevents.
    # Scalars ARE pinned: a threshold that moves silently is precisely the danger.
    value: object
    scope: str         # corpus | domain | universal  (see module docstring)
    fitted_on: str     # the evidence that set it — never "seemed right"
    falsifier: str     # the observation that would show it does not transfer


# `scope` is a claim about generality, and it is the field a corpus-fitting run acts on:
#   corpus    — measured on ONE corpus. Re-measure before trusting it on another.
#   domain    — follows from a documented convention of the domain (e.g. a USPTO rule),
#               so it should transfer within that domain but not outside it.
#   universal — follows from arithmetic or geometry, not from any corpus.
CORPUS, DOMAIN, UNIVERSAL = "corpus", "domain", "universal"

FITTED: list[FittedConstant] = [
    FittedConstant(
        "patents.NUMERAL_DIGITS", 4, DOMAIN,
        "The figure-keyed 1000-series (FIG. 10 -> 1000/1010/1020) is standard in "
        "post-2000 software and electronics art; three digits could not express it, and "
        "on such a patent BOTH sides of the drawing/spec reconciliation come back empty "
        "so coverage reads clean over an empty map (D34).",
        "A patent reciting a five-digit reference numeral, or one whose numerals collide "
        "with four-digit quantities the unit guard does not catch. TESTED on US8046721B2 "
        "(2026-07-28): 13 four-digit numerals (1000-1108) extracted, all invisible under "
        "the pre-D34 cap; no 5+-digit shapes present. Transfers.",
    ),
    FittedConstant(
        "figures_map.MIN_LOCATABLE_NUMERAL", 10, CORPUS,
        "On US5447630A every sub-10 OCR read was noise (Julian: 'the OCR for figures "
        "lower than 10 are all nonsense'); sub-10 numerals are reported as text-only, "
        "tied to their figure but never located on a sheet (D30).",
        "A corpus whose single-digit numerals ARE reliably readable — likely any clean "
        "modern vector PDF rather than a 1990s raster scan. This is the constant most "
        "likely to be wrong on corpus #2, and it fails SILENTLY: it suppresses "
        "locations rather than producing wrong ones. US8046721B2 left it INERT (lowest "
        "numeral recited is 36), so it is still UNTESTED — inert is not validated.",
    ),
    FittedConstant(
        "figures_map.HEADER_BAND", 0.88, DOMAIN,
        "USPTO sheets carry a running header (patent number, date, 'Sheet N of M') whose "
        "digits are not reference numerals. 0.88 clears it on all 8 sheets of US5447630A.",
        "A sheet whose drawing extends into the top 12%, or a non-USPTO drawing set with "
        "no header band at all (the guard then silently discards real labels). CONFIRMED "
        "on US8046721B2 (D45): 0/16 sheets carry a running header, and the band deleted 13 "
        "spec-recited numerals (100, 200, 300, 400, 1002, …). The band is now applied only "
        "where a header is DETECTED per sheet, so it cannot fire without its precondition.",
    ),
    FittedConstant(
        "figures_map.FIGURE_CONTEXT_WINDOW", 2000, CORPUS,
        "Chars of specification context searched around a figure mention when attributing "
        "a numeral to a figure; fitted so US5447630A's numerals attribute correctly.",
        "A specification with longer per-figure passages, where 2000 chars truncates the "
        "discussion, or a terser one where it bleeds into the next figure's paragraph.",
    ),
    FittedConstant(
        "patents._CAPTION_GAP", 400, CORPUS,
        "Max chars between consecutive 'BRIEF DESCRIPTION OF THE DRAWINGS' captions when "
        "parsing the figure list; fitted to US5447630A's caption block.",
        "A patent with a long prose aside between two figure captions. FIRED on US8046721B2, "
        "but the diagnosis was elsewhere: `_FIG_CAPTION` could not match a RANGE caption "
        "('FIGS. 4A-4B illustrate'), which both lost those captions and inflated the gap "
        "to 450. After the D43 regex fix the largest in-run gap is 160, so 400 transfers. "
        "General lesson: a threshold that looks too tight may be measuring a parse "
        "failure upstream of it.",
    ),
    FittedConstant(
        "cues.CUE_WINDOW", 160, CORPUS,
        "Chars scanned around a cited atom for denial/hedge cues; the 500-char window "
        "originally tried produced false positives on US5447630A (see cues.py).",
        "A corpus whose refutation cues sit further from the figure they qualify.",
    ),
    FittedConstant(
        "support.THRESHOLD", 15.0, CORPUS,
        "BM25 support floor below which check_support returns 'insufficient'. Calibrated "
        "on the EDGAR golden set (D20) — a score threshold is scale-dependent on corpus "
        "length and term distribution, so it is corpus-fitted by construction.",
        "Any new corpus. A BM25 score is not comparable across corpora; this must be "
        "re-calibrated, and the risk-coverage curve RT-8 notes is how to price it. "
        "CONFIRMED on US8046721B2: 'how is the device unlocked' — the patent's entire subject "
        "— scores 4.56 against a 15.0 floor, so Cairn would FALSELY ABSTAIN on an "
        "answerable question. Does not transfer. RT-9 tracks the missing mechanism.",
    ),
    FittedConstant(
        "patents._ELEMENT_MAX_WORDS", 8, DOMAIN,
        "Word cap on the element phrase recovered for a pointer construction ('…as "
        "shown at 20'). The subject is bounded by the nearest sentence break or comma, "
        "which usually yields 2-5 words; when the pointer sits at the end of a long "
        "clause it yields the whole clause instead, and the tail is clipped. 8 is above "
        "every genuine element observed on US5447630A (longest: 'ceramic particulate "
        "\"scrubber\" or filter', 5 words).",
        "A specification whose element names genuinely run longer than 8 words — likely "
        "in chemical or biotech claims, where a single element can be a full reagent "
        "description. The clip is head-final, so an over-long name loses its qualifiers "
        "and keeps its head noun; the NUMERAL always survives, so the failure is a "
        "degraded label, never a dropped reference. Re-measure by listing the word "
        "counts of pointer-recovered elements on any new corpus.",
    ),
    FittedConstant(
        "figures_map.merge_same_spot_numerals(radius=)", 0.02, CORPUS,
        "Normalized distance under which two reads of the same label are ONE mark. The "
        "closest genuine same-token pair on US5447630A sits at 0.0202 — about 0.7 px of "
        "headroom above this value, which was never measured when it was chosen.",
        "Any denser sheet. Two real marks closer than 0.02 apart silently merge into "
        "one, and the survivor keeps only the higher confidence — the miss is invisible. "
        "The swarm flagged this as the sharpest untested constant in the repo. TESTED on "
        "US8046721B2 (D45): closest same-label pair 0.0272, i.e. +0.0072 headroom vs "
        "corpus 1's +0.0002. Transfers — the tightness is a property of corpus 1, not of "
        "the value. Still the constant to re-measure first on any denser sheet.",
    ),
    FittedConstant(
        "figures_map.is_fragment(radius=)", 0.025, CORPUS,
        "Box-overlap band for rejecting a tile-cut fragment ('12b' read as '1'). Fitted "
        "against US5447630A's tiled recovery pass (L0008).",
        "A sheet whose labels sit closer together than the fragment band, where a real "
        "short label is discarded as a fragment of its neighbour.",
    ),
    FittedConstant(
        "figures_map._same_spot_conflicts(radius=)", 0.01, CORPUS,
        "Positional-coincidence band for reporting two DIFFERENT labels read at one spot "
        "(one mark, two readings). Half the merge radius, which is an untested asymmetry.",
        "Its disagreement with the merge radius above: a pair 0.015 apart is neither "
        "merged as one mark nor reported as a conflict, so it is silently two marks.",
    ),
    FittedConstant(
        "ocr_patent_figures.ROTATIONS", (0, 90, 180, 270), UNIVERSAL,
        "Every quarter turn. Union rather than a chosen angle, because rotation is a "
        "per-glyph property, not a per-page one (D32).",
        "Nothing within quarter turns — but it does NOT address SKEW (1-5 degrees "
        "off-axis), which no rotation set fixes. Deskew is a separate lever.",
    ),
    FittedConstant(
        "figures_map._STROBOGRAMMATIC", {"0": "0", "1": "1", "6": "9", "8": "8", "9": "6"},
        DOMAIN,
        "Digits that stay legible upside down, used to reject 180-degree phantoms (D36). "
        "Deliberately conservative: 2/5/7 invert in some typefaces and not others.",
        "A typeface where 2/5/7 invert legibly — then real phantoms in those digits are "
        "admitted. Erring the other way would DELETE real labels, which is why the map "
        "is short rather than complete.",
    ),
    FittedConstant(
        "patents._NOT_ELEMENT", None, CORPUS,
        "Function words that cannot name a part. Grown by evidence twice: the base list, "
        "then `with below exceeding above near into onto through during per` after "
        "\"at temperatures exceeding 500\" bound 500 as a part with element phrase \"at "
        "temperatures exceeding\" (D34).",
        "A corpus using a function word not on this list before a numeral — the list is "
        "open-ended by construction, so absence of a flag proves nothing here.",
    ),
    FittedConstant(
        "patents._NOT_A_LABEL", None, DOMAIN,
        "Uppercase tokens that look like acronym labels but are not: "
        "FIG FIGS US NO PCT CIP, plus the unit acronyms CFM RPM PSI GPM seen on "
        "US5447630A's drawings.",
        "A domain with different unit acronyms (a chemical patent's ppm/pH, an electrical "
        "one's VAC/AWG) — each would be admitted as a reference label. CONFIRMED on "
        "US8046721B2, worse than predicted: 34 'labels' including CDMA GSM CMOS CPU GPS "
        "IEEE CODEC and the section headings BRIEF and FIELD. Does not transfer, and the "
        "fix is NOT a longer blocklist — `acronym_labels` has no frequency floor because "
        "DRAWINGS adjudicate, so it over-generates by design wherever no OCR'd sheets "
        "exist. It must not be consumed without drawing evidence (RT-9).",
    ),
    FittedConstant(
        "cues.DENIAL_CUES", None, CORPUS,
        "Lexical cues for a refuted-in-context citation. The provability swarm's standing "
        "conclusion is that cue-less refutation is permanently invisible to a "
        "deterministic check (D24-D27), so this list is a floor, never a guarantee.",
        "By design: any refutation phrased without a cue. That is not a bug to fix but "
        "the documented ceiling of the approach.",
    ),
    FittedConstant(
        "support.ABSENT_TAGS", None, CORPUS,
        "Tags marking an item as content-absent in the golden set; fitted to the EDGAR "
        "and patent golden sets' vocabulary.",
        "A golden set authored by someone else using different tags — which is exactly "
        "what the held-out set the landscape report recommends would be.",
    ),
    FittedConstant(
        "ocr_patent_figures._NOT_A_NUMERAL", None, CORPUS,
        "'0' is never a reference numeral on US5447630A — every read of it was a fragment "
        "of line art ('/0').",
        "A corpus that labels an element '0'. Unlikely by USPTO convention (numbering "
        "starts at 1 or higher) but not impossible.",
    ),
]

# Module-level names in the fitted modules that are deliberately NOT corpus-fitted, so
# the coverage test can tell "unregistered" from "not applicable". Each needs a reason.
NOT_FITTED: dict[str, str] = {
    "patents.AIA_DATE": "A statutory date (America Invents Act). A fact of law, not a "
                        "value tuned against a corpus — it changes by legislation only.",
    "ocr_patent_figures.ENGINE_READERS": "A dispatch table mapping engine name to reader "
                                         "function. Structure, not a tunable.",
    "ocr_patent_figures._HEADER_BAND": "Imported from figures_map.HEADER_BAND, which is "
                                       "registered — one fitted value, one definition.",
    "ocr_patent_figures._SAME_SPOT": "Derived from merge_same_spot_numerals' own default, "
                                     "which is registered.",
}


def live_value(const: FittedConstant) -> object:
    """Import and read the constant as the code currently defines it.

    Handles both module-level constants and keyword defaults
    (`module.function(kwarg=)`), because several fitted values are function defaults —
    which is exactly how they escaped notice as constants in the first place.
    """
    path, _, kwarg = const.name.partition("(")
    if kwarg:                                   # "module.func(radius=)"
        mod_name, _, rest = path.rpartition(".")
        fn = getattr(_import(mod_name), rest)
        key = kwarg.rstrip("=)")
        return inspect.signature(fn).parameters[key].default
    mod_name, _, attr = path.rpartition(".")
    return getattr(_import(mod_name), attr)


def _import(mod_name: str):
    import importlib
    for candidate in (f"cairn.{mod_name}", mod_name):
        try:
            return importlib.import_module(candidate)
        except ModuleNotFoundError:
            continue
    # Scripts are not a package; load by path so the registry can cover them too.
    import sys
    from pathlib import Path
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    import importlib as il
    return il.import_module(mod_name)


def drifted() -> list[str]:
    """Constants whose live value no longer matches the value recorded here.

    Non-empty means the registry is stale: someone retuned a constant without recording
    what evidence justified the change. That is the failure this module exists to catch.
    """
    out = []
    for c in FITTED:
        try:
            got = live_value(c)
        except Exception as e:  # noqa: BLE001 — an unresolvable name is itself drift
            out.append(f"{c.name}: could not read ({e})")
            continue
        if c.value is None:
            continue                     # provenance-only; see FittedConstant.value
        if got != c.value:
            out.append(f"{c.name}: code has {got!r}, registry records {c.value!r}")
    return out


def by_scope(scope: str) -> list[FittedConstant]:
    return [c for c in FITTED if c.scope == scope]
