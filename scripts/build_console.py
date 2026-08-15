#!/usr/bin/env python3
"""Build the Cairn console — one frame around every surface (RT-10, D48).

Runs whichever generators apply to this store, then writes an `index.html` that carries
the corpus's state above all of them. Panes with nothing to show say what is missing and
why, rather than being hidden — a stage that silently disappears is indistinguishable from
one that has no findings.

    python scripts/build_console.py --store corpus/store --audit audit_log/agent.jsonl \\
        --on 2026-07-28 --out console/

Opens with `open console/index.html`. No server; every page inside is self-contained and
still works on its own if opened directly.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import _bootstrap  # noqa: F401  (puts src/ on sys.path)

from cairn.adjudicate_pane import render as adjudicate_pane
from cairn.annotate_pane import render as annotate_pane
from cairn.calibration import describe as describe_calibration
from cairn.calibration import load as load_calibration
from cairn.console import ConsoleState, Pane, render
from cairn.contract import CONTRACT_VERSION
from cairn.corpus_pane import render as corpus_pane
from cairn.ingest import DocumentStore
from cairn.locate_pane import render as locate_pane
from cairn.review_queue import build as build_queue

ROOT = Path(__file__).resolve().parent.parent


def _ambiguities_for(store_dir: Path, doc_id: str, adj_path: Path) -> list:
    """Open questions of MEANING (D77) — where two mechanisms disagree about a token.

    Read from the same reconciliation the location queue uses, minus anything the
    reviewer has already ruled on, so the panel is a view over outstanding work while
    the rulings themselves live in the append-only log.
    """
    from cairn.adjudication import AdjudicationLog
    from cairn.ambiguity import collect, resolutions
    from cairn.figures_map import (
        fig_to_sheets,
        load_manifest,
        numeral_coverage,
        numeral_sightings,
    )
    from cairn.patents import (
        figure_references,
        numeral_mentions,
        parse_figures,
        reference_numerals,
    )
    from cairn.spans import SpanStore

    store = SpanStore.from_store(DocumentStore(store_dir))
    text = store.get_document(doc_id)
    manifest = load_manifest(store_dir)
    sightings = numeral_sightings(manifest)
    assigns = fig_to_sheets(manifest, [f.number for f in parse_figures(text)])
    cov = numeral_coverage(reference_numerals(text), text, figure_references(text),
                           assigns, sightings)
    log = AdjudicationLog(adj_path)
    done = set(resolutions(log)) if adj_path.exists() else set()
    return collect(text=text, mentions=numeral_mentions(text), coverage=cov,
                   assignments=assigns, resolved=done)


def _queue_for(store_dir: Path, doc_id: str, adjudicated: set[str]) -> list:
    """The outstanding worklist, from the same reconciliation the Drawings pane shows."""
    from cairn.figures_map import (
        fig_to_sheets,
        load_manifest,
        numeral_coverage,
        numeral_sightings,
    )
    from cairn.patents import figure_references, parse_figures, reference_numerals
    from cairn.spans import SpanStore

    store = SpanStore.from_store(DocumentStore(store_dir))
    text = store.get_document(doc_id)
    manifest = load_manifest(store_dir)
    sightings = numeral_sightings(manifest)
    figs = parse_figures(text)
    assignments = fig_to_sheets(manifest, [f.number for f in figs])
    cov = numeral_coverage(reference_numerals(text), text, figure_references(text),
                           assignments, sightings)
    return build_queue(cov, sightings, adjudicated=adjudicated)


def _run(script: str, args: list[str]) -> bool:
    """Run a generator. Returns whether it produced its page.

    Failures are reported and survived, not raised: a console missing one pane is far
    more useful than no console, and the pane will say what went wrong.
    """
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        first = (r.stderr or r.stdout).strip().splitlines()
        print(f"  ✗ {script}: {first[-1] if first else 'failed'}")
    return r.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the Cairn console (RT-10)")
    ap.add_argument("--store", required=True)
    ap.add_argument("--audit", required=True)
    ap.add_argument("--doc", help="document id — enables the patent panes")
    ap.add_argument("--on", required=True, metavar="YYYY-MM-DD")
    ap.add_argument("--engagement")
    ap.add_argument("--reviewer", help="who will be recording judgments — must match "
                                       "the --reviewer passed to serve_console.py")
    ap.add_argument("--out", default="console")
    ns = ap.parse_args()

    out = Path(ns.out)
    out.mkdir(parents=True, exist_ok=True)
    store_dir = Path(ns.store)
    doc_store = DocumentStore(store_dir)
    ids = doc_store.list_docs()

    # The panes state who they will record as; the SERVER decides whether they can. If
    # the two disagree the endpoint refuses and the page shows that error, which is the
    # safe direction — but a page claiming read-only while the server would record is not,
    # so the identity is threaded through rather than hardcoded to None.
    judged_on = ns.on
    print(f"building console for {len(ids)} document(s) → {out}/")

    # --from-audit takes the LOG PATH as its value; passing it as a bare flag silently
    # fell through to the demo path and its hardcoded EDGAR document.
    ok_evidence = _run("build_evidence_view.py",
                       ["--store", ns.store, "--from-audit", ns.audit,
                        "--out", str(out / "evidence.html")])
    ok_record = _run("build_review_report.py",
                     ["--store", ns.store, "--audit", ns.audit, "--on", ns.on,
                      *(["--engagement", ns.engagement] if ns.engagement else []),
                      "--out", str(out / "record.html")])
    ok_figures = False
    fig_dir = store_dir.parent / "figures"
    if ns.doc and (fig_dir / "ocr_manifest.json").exists():
        ok_figures = _run("patent_figures_view.py",
                          ["--store", ns.store, "--doc", ns.doc,
                           "--out", str(out / "figures.html")])

    # Adjudications and outstanding flags ride in the header, so they cannot scroll away.
    adjudications, adj_ids = 0, set()
    adj_path = fig_dir / "adjudications.jsonl"
    if adj_path.exists():
        from cairn.adjudication import AdjudicationLog
        log = AdjudicationLog(adj_path)
        log.verify_chain()
        effective = log.effective()
        adjudications = len(effective)
        # A judged item leaves the QUEUE but never the record — the id is the queue's
        # item_id, which is stable across rebuilds so a judgment keeps pointing at it.
        adj_ids = {a.adj_id.split("::")[0] for a in effective}

    # The queue is derived from the same reconciliation the Drawings pane reports, so a
    # tally there and a worklist here can never disagree.
    ambiguities = []
    queue = []
    if ok_figures:
        try:
            queue = _queue_for(store_dir, ns.doc, adj_ids)
            ambiguities = _ambiguities_for(store_dir, ns.doc, adj_path)
        except Exception as e:                    # noqa: BLE001 — reported, not fatal
            print(f"  ✗ review queue: {type(e).__name__}: {e}")

    # One place decides the verdict and one place phrases it (D53) — three copies of
    # this branch is how a store came to read "calibrated" here while the report said
    # "non-separable".
    rec = load_calibration(store_dir)
    calibration, is_calibrated = describe_calibration(
        store_dir, ids, [doc_store.load(d).content_hash for d in ids])

    # Corpus-scoped constants this corpus has not exercised either way. "Inert is not
    # validated" (D43) — reported so a reviewer knows what is untested here, not merely
    # what failed.
    from cairn.corpus_fit import CORPUS, by_scope
    untested = [(c.name, c.falsifier.split(".")[0][:150] + ".")
                for c in by_scope(CORPUS)][:8]
    n_sheets = 0
    if (fig_dir / "ocr_manifest.json").exists():
        import json as _j
        n_sheets = len(_j.loads((fig_dir / "ocr_manifest.json")
                                .read_text(encoding="utf-8"))["pages"])
    (out / "corpus.html").write_text(corpus_pane(
        doc_ids=ids, hashes={d: doc_store.load(d).content_hash for d in ids},
        sizes={d: len(doc_store.load(d).canonical_text) for d in ids},
        calibration=calibration, calibrated=is_calibrated,
        stale=bool(rec and not rec.separable),
        fitted_untested=untested, sheets=n_sheets, adjudications=adjudications,
        ambiguities=len(ambiguities),
        chain_ok=True), encoding="utf-8")

    panes = [
        Pane("corpus", "Corpus", "what are we searching?", "corpus.html", ""),
        Pane("locate", "Locate", "ask, and find or abstain", "locate.html",
             ""),
        Pane("evidence", "Evidence", "show the work and its limits",
             "evidence.html" if ok_evidence else None,
             "The evidence view could not be generated for this store."),
        Pane("figures", "Drawings", "located reference numerals",
             "figures.html" if ok_figures else None,
             "No OCR manifest for this store, so there are no drawing sheets to show. "
             "Run scripts/fetch_patent_figures.py then scripts/ocr_patent_figures.py, and "
             "pass --doc." if not ok_figures else ""),
        Pane("adjudicate", f"Adjudicate{f' ({len(queue)})' if queue else ''}",
             "the reviewer writes back", "adjudicate.html" if ok_figures else None,
             "The review queue is built from the drawings reconciliation, and this store "
             "has no OCR manifest. Judgments can still be recorded with "
             "scripts/adjudicate.py."),
        Pane("annotate", "Mark a sheet", "assert what OCR missed",
             "annotate.html" if ok_figures else None,
             "Marking a sheet needs drawing sheets, and this store has none."),
        Pane("record", "Record", "the signable deliverable",
             "record.html" if ok_record else None,
             "The record of inquiry could not be generated for this store."),
    ]

    state = ConsoleState(
        engagement=ns.engagement or store_dir.parent.name,
        doc_ids=ids, calibration=calibration, calibrated=is_calibrated,
        contract=CONTRACT_VERSION, adjudications=adjudications,
        generated_on=ns.on, panes=panes)

    # The Locate pane is static HTML that CALLS the real tools; it needs
    # scripts/serve_console.py running, and says so itself when it cannot reach one.
    (out / "locate.html").write_text(
        locate_pane(calibrated=rec is not None, calibration=calibration), encoding="utf-8")
    if ok_figures:
        # Sheets are copied INTO the console directory rather than served from the
        # engagement dir: the server is confined to one root (D49), and widening that to
        # reach client material would trade a containment guarantee for a copy.
        sheets_dir = out / "sheets"
        sheets_dir.mkdir(exist_ok=True)
        sheets = []
        import shutil

        from cairn.annotate import box_to_display
        from cairn.figures_map import load_manifest as _load_merged
        # The MERGED manifest, so reviewer marks appear beside OCR ones and can be
        # revised in turn — a human judgment is evidence, not a separate layer.
        manifest = _load_merged(store_dir)
        for pg in manifest["pages"]:
            src = fig_dir / pg["file"]
            if not src.exists():
                continue
            shutil.copy2(src, sheets_dir / pg["file"])
            marks = []
            for n in pg.get("numerals", []):
                d = box_to_display(n.get("x", 0), n.get("y", 0),
                                   n.get("w", 0.02), n.get("h", 0.02))
                marks.append({**d, "numeral": str(n["numeral"]),
                              "x": n.get("x", 0), "y": n.get("y", 0),
                              "human": n.get("method") == "human",
                              "by": n.get("by"), "on": n.get("on"),
                              "engines": ",".join(n.get("engines", []))})
            sheets.append({"page": pg["page"], "file": pg["file"],
                           "figures": ",".join(f["fig"] for f in pg.get("fig_labels", [])),
                           "marks": marks})
        (out / "annotate.html").write_text(
            annotate_pane(sheets, reviewer=ns.reviewer, on=judged_on), encoding="utf-8")
        # The same sheets the annotate pane uses, keyed by page: the adjudicate queue
        # shows a zoomed crop per row, so "is 20 really drawn here?" is answerable
        # where it is asked rather than in another pane.
        (out / "adjudicate.html").write_text(
            adjudicate_pane(queue, reviewer=ns.reviewer, on=judged_on,
                            sheet_files={s["page"]: s["file"] for s in sheets},
                            ambiguities=ambiguities),
            encoding="utf-8")
    (out / "index.html").write_text(render(state), encoding="utf-8")
    built = [p.label for p in panes if p.page]
    print(f"\nOK — {out / 'index.html'}")
    print(f"  panes with content: {', '.join(built) or 'none'}")
    print(f"  placeholders      : {', '.join(p.label for p in panes if not p.page)}")
    print(f"  calibration       : {'recorded' if rec else 'ABSENT — stated in the header'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
