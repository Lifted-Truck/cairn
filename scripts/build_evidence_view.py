#!/usr/bin/env python3
"""Generate the evidence-view GUI (ROADMAP M2-T7) → evidence_view.html.

Builds a handful of demonstration interactions over the golden set and renders
them to a single self-contained HTML page you open in a browser. The prose is
curated (from the golden answers) — the *live* agent composes it at M4 — but the
citations, highlights, verify status, and abstention spans are all real
deterministic output of the M1/M2 tools.

Usage:
  python scripts/build_evidence_view.py                 # curated demos → ./evidence_view.html
  python scripts/build_evidence_view.py --from-audit            # whole session → evidence_view.html
  python scripts/build_evidence_view.py --from-audit --latest   # just the most recent answer
  python scripts/build_evidence_view.py --from-audit --last 3 --out review.html

`--from-audit` rebuilds the view from a live Claude Code / Desktop session's audit
log (every presented `verify` becomes a card) — the bridge from working in Desktop
to reviewing the citations.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import _bootstrap  # noqa: F401  (puts src/ on sys.path)

from cairn.audit import AuditLog
from cairn.evidence_view import (
    Interaction,
    interactions_from_audit,
    render_evidence_view,
    sessions_from_audit,
)
from cairn.frame import Constraint, QuestionFrame
from cairn.ingest import DocumentStore
from cairn.retrieval import Retriever
from cairn.spans import SpanStore
from cairn.support import THRESHOLD, check_support
from cairn.verify import Answer, AtomBinding, DerivedAtom, Sentence, verify

ROOT = Path(__file__).resolve().parent.parent
DOC = "AAPL-10K-FY2024"
OUT = ROOT / "evidence_view.html"
AUDIT = ROOT / "audit_log" / "agent.jsonl"


def _patent_figure_context(store: SpanStore, store_dir: Path):
    """RT-4 payoff: if the store is a patent engagement with fetched sheets + an OCR
    manifest, build the FigurePanel catalog (one per OCR-assigned figure, showing its
    sheet) and the deterministic signals `relevant_figures` needs. Returns None for a
    non-patent / un-OCR'd store, so the main view stays inert (EDGAR unaffected)."""
    import base64
    import json

    from cairn.annotate import box_to_display
    from cairn.evidence_view import FigurePanel
    from cairn.figures_map import fig_to_sheets, load_manifest, numeral_sightings
    from cairn.patents import figure_references, parse_figures, reference_numerals

    fig_dir = store_dir.parent / "figures"
    if not ((fig_dir / "ocr_manifest.json").exists()
            and (fig_dir / "figures_manifest.json").exists()):
        return None
    ocr = load_manifest(store_dir)
    sheet_file = {s["page"]: fig_dir / s["file"]
                  for s in json.loads((fig_dir / "figures_manifest.json").read_text())["sheets"]}

    doc_id = next((d for d in store._docs if parse_figures(store.get_document(d))), None)
    if doc_id is None:
        return None
    text = store.get_document(doc_id)
    figs = parse_figures(text)
    caption = {f.number: f.description for f in figs}
    known_figs = sorted({f.number for f in figs} | {r.number for r in figure_references(text)})
    assigns = fig_to_sheets(ocr, known_figs)

    panels = []
    for a in assigns:
        img = sheet_file.get(a.page)
        if img is None:
            continue
        how = (f"located by OCR, conf {a.confidence}" if a.method == "ocr"
               else "assigned by elimination")
        uri = "data:image/png;base64," + base64.b64encode(img.read_bytes()).decode()
        # Every numeral OCR located on this sheet, converted ONCE here through the
        # tested box_to_display; the page only places what it is given (D66's lesson).
        marks = tuple(
            {"numeral": str(s.numeral), **box_to_display(*s.bbox)}
            for s in numeral_sightings(ocr) if s.page == a.page and s.bbox)
        panels.append(FigurePanel(f"FIG. {a.fig}",
                                  f"{caption.get(a.fig, '')} — sheet p.{a.page} ({how})",
                                  uri, marks))
    return {"panels": panels, "assigns": assigns,
            "sightings": numeral_sightings(ocr),
            "known_numerals": [n.number for n in reference_numerals(text)]}


def _attach_figures(interactions, store: SpanStore, ctx) -> None:
    """Set each interaction's `.figures` from the figures its cited spans point at
    (RT-4). Display-only (D21): nothing here is verified; a spurious panel is a glance."""
    from cairn.figures_map import relevant_figures
    for inter in interactions:
        if inter.answer is None:
            continue
        spans = []
        for s in inter.answer.sentences:
            for atom in list(s.atoms) + [o for d in s.derived for o in d.operands]:
                sp = store.span_containing(atom.doc_id, atom.char_start)
                if sp is not None:
                    spans.append(sp.text)
        inter.figures = [f"FIG. {n}" for n in relevant_figures(
            spans, ctx["assigns"], ctx["sightings"], ctx["known_numerals"])]
        # Which numerals to light on those sheets: the ones this interaction's own
        # cited text names. Anything else on the sheet stays placed but dark — the
        # reader is checking THIS citation, not taking inventory of the drawing.
        blob = " ".join(spans)
        inter.figure_numerals = sorted(
            {n for n in ctx["known_numerals"]
             if re.search(rf"(?<![\w.]){re.escape(str(n))}(?![\w])", blob)},
            key=lambda s: (len(str(s)), str(s)))


def build_from_audit(audit_path: Path, out: Path, last: int = 0,
                     session: int | None = None, list_sessions: bool = False,
                     store_dir: Path | None = None) -> int:
    store_dir = store_dir or ROOT / "corpus" / "store"
    store = SpanStore.from_store(DocumentStore(store_dir))
    fig_ctx = _patent_figure_context(store, Path(store_dir))
    fig_panels = fig_ctx["panels"] if fig_ctx else None
    if not audit_path.exists():
        print(f"No audit log at {audit_path} — run a live session first "
              "(or scripts/run_layer_e.py).")
        return 1
    entries = [e.payload for e in AuditLog(audit_path).entries()]

    if list_sessions or session is not None:         # RT-1: browse history per session
        groups = sessions_from_audit(entries, store)
        if list_sessions:
            print(f"{len(groups)} session(s) in {audit_path}:")
            for i, g in enumerate(groups, 1):
                ts = f"  {g['ts']}" if g["ts"] else ""
                print(f"  {i:>2}. {g['label']:<40}{ts}  ({len(g['interactions'])} presented)")
            print("render one:  --from-audit --session N")
            return 0
        idx = session - 1 if session > 0 else len(groups) + session  # -1 = last
        if not (0 <= idx < len(groups)):
            print(f"error: session {session} out of range (1–{len(groups)})")
            return 1
        g = groups[idx]
        title = f"CAIRN — session: {g['label']}" + (f" · {g['ts']}" if g["ts"] else "")
        if fig_ctx:
            _attach_figures(g["interactions"], store, fig_ctx)
        out.write_text(render_evidence_view(g["interactions"], store, title=title,
                                            figures=fig_panels), encoding="utf-8")
        print(f"OK — wrote {out} (session {idx + 1}/{len(groups)} "
              f"'{g['label']}', {len(g['interactions'])} interaction(s))")
        return 0

    interactions = interactions_from_audit(entries, store)
    if not interactions:
        print(f"No presented (verify-ok) interactions in {audit_path} — nothing to render.")
        return 1
    total = len(interactions)
    if last > 0:                       # most recent N (the audit log is cumulative)
        interactions = interactions[-last:]
    if fig_ctx:
        _attach_figures(interactions, store, fig_ctx)
    out.write_text(render_evidence_view(interactions, store, figures=fig_panels),
                   encoding="utf-8")
    scope = f" (latest {len(interactions)} of {total})" if len(interactions) != total else ""
    fig_note = f" · {len(fig_panels)} figure panels" if fig_panels else ""
    print(f"OK — wrote {out} ({len(interactions)} interaction(s){scope}{fig_note})")
    return 0

TOTAL_ASSETS = "Total assets $ 364,980 $ 352,583"
LIAB_EQUITY = "Total liabilities and shareholders’ equity $ 364,980 $ 352,583"
TERM_CUR = "Term debt 10,912 9,822"
TERM_NON = "Term debt 85,750 95,281"


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the CAIRN evidence-view GUI")
    ap.add_argument("--from-audit", nargs="?", const=str(AUDIT), default=None,
                    metavar="PATH", help="rebuild from a live session's audit log")
    ap.add_argument("--last", type=int, default=0, metavar="N",
                    help="with --from-audit, render only the last N interactions (0 = all)")
    ap.add_argument("--latest", action="store_true",
                    help="with --from-audit, render only the most recent interaction")
    ap.add_argument("--sessions", action="store_true",
                    help="with --from-audit, list the log's sessions (RT-1)")
    ap.add_argument("--session", type=int, default=None, metavar="N",
                    help="with --from-audit, render session N (1-based; -1 = last)")
    ap.add_argument("--store", default=None, metavar="DIR",
                    help="corpus store the log's citations resolve against "
                         "(default: the EDGAR reference store; set per engagement)")
    ap.add_argument("--out", default=str(OUT), help="output HTML path")
    ns = ap.parse_args()
    if ns.from_audit is not None:
        return build_from_audit(Path(ns.from_audit), Path(ns.out),
                                1 if ns.latest else ns.last,
                                session=ns.session, list_sessions=ns.sessions,
                                store_dir=Path(ns.store) if ns.store else None)

    store = SpanStore.from_store(DocumentStore(ROOT / "corpus" / "store"))
    retriever = Retriever(store)
    canonical = store.get_document(DOC)

    def bind(literal: str, line: str) -> AtomBinding:
        start, _ = store.resolve_quote(DOC, line)
        i = line.index(literal)
        return AtomBinding(literal, DOC, start + i, start + i + len(literal))

    def bind_nearest(literal: str, near: int) -> AtomBinding:
        """Bind to the occurrence of `literal` nearest `near` (D14 nearest substantiation)."""
        offs, i = [], canonical.find(literal)
        while i != -1:
            offs.append(i)
            i = canonical.find(literal, i + 1)
        best = min(offs, key=lambda o: abs(o - near))
        return AtomBinding(literal, DOC, best, best + len(literal))

    def top(q: str) -> float:
        hits = retriever.search(q, 1)
        return hits[0].score if hits else 0.0

    interactions: list[Interaction] = []

    # 1. Clean grounded lookup — figure AND the "as of" date are both bound; the date
    #    binds to the balance-sheet column header right above the figure (D14), not the cover.
    q1 = "What were Apple's total assets as of September 28, 2024?"
    fig = bind("364,980", TOTAL_ASSETS)
    a1 = Answer([Sentence(
        "Apple's total assets were $364,980 million as of September 28, 2024.",
        atoms=[fig, bind_nearest("September 28, 2024", fig.char_start)],
    )])
    interactions.append(Interaction(
        q1, "answer", answer=a1, verify=verify(a1, store),
        note="The figure and the period ('as of …') are each bound to a span.",
        trace=f"check_support top {top(q1):.0f} ≥ floor {THRESHOLD:.0f} → supported · "
              f"verify: 2/2 atoms resolved (figure + date)",
        frame=QuestionFrame(q1, [
            Constraint("metric", "Total assets"),
            Constraint("period", "September 28, 2024"),
            Constraint("entity", "Apple", required=False),
        ]),
    ))

    # 2. Derived answer — operands cited, the delta recomputed (not cited).
    q2 = "Did Apple's total assets increase from fiscal 2023 to 2024, and by how much?"
    a2 = Answer([Sentence(
        "Total assets increased by $12,397 million (from $352,583M to $364,980M).",
        derived=[DerivedAtom("12,397", "subtract",
                             [bind("364,980", TOTAL_ASSETS), bind("352,583", TOTAL_ASSETS)])],
    )])
    interactions.append(Interaction(
        q2, "answer", answer=a2, verify=verify(a2, store),
        note="The $12,397M delta is recomputed from both operands, never cited as a fact.",
        trace=f"check_support top {top(q2):.0f} ≥ floor {THRESHOLD:.0f} → supported · "
              f"the delta is recomputed from bound operands (see derivation ƒ below)",
        frame=QuestionFrame(q2, [Constraint("metric", "Total assets")]),
    ))

    # 3. Plural & ranked — both term-debt portions surfaced.
    q3 = "How much term debt does Apple carry?"
    a3 = Answer([Sentence(
        "Apple carries term debt in two portions: a current portion of $10,912 million "
        "and a non-current portion of $85,750 million.",
        atoms=[bind("10,912", TERM_CUR), bind("85,750", TERM_NON)],
    )])
    interactions.append(Interaction(
        q3, "answer", answer=a3, verify=verify(a3, store),
        note="One question, two valid figures — both surfaced and distinguished.",
        trace=f"check_support top {top(q3):.0f} ≥ floor {THRESHOLD:.0f} → supported · "
              f"two term-debt spans clear the floor (plural, ranked)",
        frame=QuestionFrame(q3, [Constraint("metric", "term debt")]),
    ))

    # 3b. The point of D13: verify can PASS while coverage FAILS. This answer cites a
    # span that really contains 364,980 — but it's the liabilities+equity total, not
    # assets. The figure is real; the cited span doesn't establish the question's metric.
    a_naive = Answer([Sentence(
        "Apple's total assets were $364,980 million.",
        atoms=[bind("364,980", LIAB_EQUITY)],
    )])
    interactions.append(Interaction(
        "What were Apple's total assets? (naive citation)",
        "answer", answer=a_naive, verify=verify(a_naive, store),
        note="The figure $364,980 is real and resolves — but the cited line is "
             "'Total liabilities and shareholders’ equity', not 'Total assets'.",
        trace="verify ✓ (364,980 resolves) BUT coverage ✗ — the cited span does not "
              "carry the question's metric. This is the gap D13 closes.",
        frame=QuestionFrame("total assets?", [Constraint("metric", "Total assets")]),
    ))

    # 4. Abstain — content absent (deterministic, D12).
    ceo_q = "What was the total compensation of Apple's CEO in fiscal 2024?"
    g011 = check_support(ceo_q, retriever)
    g011_top = g011.closest[0].score if g011.closest else 0.0
    interactions.append(Interaction(
        ceo_q, "abstain",
        reason="Executive compensation is disclosed in the DEF 14A proxy, not the 10-K.",
        closest=g011.closest,
        trace=f"check_support top {g011_top:.0f} < floor {THRESHOLD:.0f} → insufficient "
              f"(deterministic content-absence abstention, D12)",
    ))

    # 5. Abstain — right metric, wrong period (agent reasoning, D12).
    q5 = "total assets December 28 2024"
    interactions.append(Interaction(
        "What were Apple's total assets as of December 28, 2024?",
        "abstain",
        reason="The requested date (December 28, 2024) is outside this filing's coverage "
               "(FY2024 ended September 28, 2024). The September figure is NOT the answer.",
        closest=retriever.search(q5, 2),
        trace=f"check_support top {top(q5):.0f} ≥ floor {THRESHOLD:.0f} → supported, "
              f"BUT the agent abstains on the period mismatch (semantic trap, D12 → Layer-E)",
    ))

    # 6. Grounded correction (D16) — the premise is false, so present a refutation that
    #    CITES the contradicting figures (not a silent abstention).
    q6 = "Why did Apple's total assets decline in fiscal 2024?"
    a6 = Answer([Sentence(
        "Apple's total assets did not decline in fiscal 2024 — they rose from $352,583 "
        "million (FY2023) to $364,980 million (FY2024).",
        atoms=[bind("352,583", TOTAL_ASSETS), bind("364,980", TOTAL_ASSETS)],
    )])
    interactions.append(Interaction(
        q6, "correction", answer=a6, verify=verify(a6, store),
        note="False premise → grounded correction: the cited figures show the value rose.",
        trace="agent rejects the false premise and cites the contradicting figures "
              "(grounded correction, D16); both atoms verify against the balance sheet.",
    ))

    out = Path(ns.out)
    out.write_text(render_evidence_view(interactions, store), encoding="utf-8")
    print(f"OK — wrote {out} ({len(interactions)} interactions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
