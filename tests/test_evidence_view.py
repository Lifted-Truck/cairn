"""Standing tests for the interactive parallel evidence view (ROADMAP M2-T7, D8, D15).

The document is clean by default; clicking a card lights only that interaction's
evidence (highlights in both panes + per-cluster boxes). Tests pin the static
structure the JS drives: kinded doc marks own an interaction (data-int), the same
label reads in both panes, cluster data + card ids are wired, and a cited claim
links to a real mark.
"""

import re
from dataclasses import replace
from pathlib import Path

import pytest

from cairn.evidence_view import Interaction, render_evidence_view
from cairn.frame import Constraint, QuestionFrame
from cairn.ingest import DocumentStore
from cairn.spans import SpanStore
from cairn.verify import Answer, AtomBinding, Sentence, verify

ROOT = Path(__file__).resolve().parent.parent
DOC = "AAPL-10K-FY2024"
TOTAL_ASSETS = "Total assets $ 364,980 $ 352,583"


@pytest.fixture(scope="module")
def store() -> SpanStore:
    ds = DocumentStore(ROOT / "corpus" / "store")
    if DOC not in ds.list_docs():
        pytest.skip("corpus not ingested — run scripts/ingest_corpus.py")
    return SpanStore.from_store(ds)


def _bind(store, literal, line):
    start, _ = store.resolve_quote(DOC, line)
    i = line.index(literal)
    return AtomBinding(literal, DOC, start + i, start + i + len(literal),
                       store._docs[DOC].content_hash)


def _atom_json(a) -> dict:
    """The wire form of a binding — including the corpus hash it was made against,
    which D65 makes load-bearing rather than optional."""
    return {"text": a.text, "doc_id": a.doc_id, "char_start": a.char_start,
            "char_end": a.char_end, "content_hash": a.content_hash}


def _clean(store, frame=None) -> Interaction:
    ans = Answer([Sentence("Total assets were $364,980 million.",
                           atoms=[_bind(store, "364,980", TOTAL_ASSETS)])])
    return Interaction("Total assets?", "answer", answer=ans, verify=verify(ans, store),
                       frame=frame)


def test_full_document_renders_with_kinded_marks(store):
    html = render_evidence_view([_clean(store)], store)
    assert html.startswith("<!doctype html")
    assert 'class="docbody"' in html
    assert len(html) > 100_000  # the whole canonical doc is in the pane
    assert re.search(r'<mark class="m k-fig" id="[^"]+" data-int="i0">364,980</mark>', html)


def test_document_is_clean_by_default(store):
    """Nothing is lit or boxed until a card is clicked (no static `on`/`bx`)."""
    html = render_evidence_view([_clean(store)], store)
    assert "mark.m.on" in html  # the CSS rule exists
    assert 'class="m k-fig on"' not in html and "docln bx" not in html  # but nothing lit yet


def test_interaction_wiring_is_present(store):
    html = render_evidence_view([_clean(store)], store)
    assert "const CLUSTERS = " in html                          # cluster data for the box JS
    assert re.search(r'<section class="card answer" id="i0">', html)  # card carries kind + id
    assert 'data-int="i0"' in html                              # marks own their interaction


def test_cited_claim_links_to_a_real_mark(store):
    html = render_evidence_view([_clean(store)], store)
    target = re.search(r'data-target="([^"]+)"', html)
    assert target and f'id="{target.group(1)}"' in html
    assert "✓ verify" in html


def test_question_label_highlighted_in_both_panes(store):
    """D13 visualized + cross-column: the label marks the document AND the response."""
    frame = QuestionFrame("q", [Constraint("metric", "Total assets")])
    html = render_evidence_view([_clean(store, frame)], store)
    doc, _, cards = html.partition('<main class="cards">')
    assert re.search(r'<mark class="m k-lbl"[^>]*>Total assets</mark>', doc)   # left
    assert '<mark class="qlbl">Total assets</mark>' in cards                   # right


def test_unbound_claim_is_withheld_not_merely_flagged(store):
    """A figure bound to nothing is the shape a confabulated number takes, so the
    answer is WITHHELD, not presented with a warning beside it. Flagging and
    presenting still puts the number in front of a reader under a green badge."""
    ans = Answer([Sentence("Total assets were $999,999 million.", atoms=[])])
    inter = Interaction("Total assets?", "answer", answer=ans, verify=verify(ans, store))
    html = render_evidence_view([inter], store)
    assert '<span class="badge unverified">' in html      # not the `answer` badge
    assert '<span class="badge answer">' not in html
    assert "999,999" in html and "unbound" in html        # named, so it is reviewable
    assert "data-target=" not in html                     # and links nowhere


def test_a_stale_offset_withholds_the_answer_and_says_where_the_quote_really_is(store):
    """Defect B, made a standing test.

    The view filtered on the LOGGED `ok`, re-ran verify, printed the failure — and
    still drew the green badge with highlights at the stale offsets. On the first
    engagement every one of 61 atoms had drifted, so each card boxed a real quote
    around unrelated text. That is indistinguishable from fabrication to a reader,
    and it is the reason a genuine prior-art citation was reported as invented.
    """
    real = _bind(store, "364,980", TOTAL_ASSETS)
    stale = replace(real, char_start=real.char_start - 137,     # the observed drift
                    char_end=real.char_end - 137)
    ans = Answer([Sentence("Total assets were $364,980 million.", atoms=[stale])])
    inter = Interaction("Total assets?", "answer", answer=ans, verify=verify(ans, store))
    html = render_evidence_view([inter], store)

    assert '<span class="badge unverified">' in html
    assert '<span class="badge answer">' not in html
    assert 'class="m k-fig"' not in html, "a stale offset must paint no highlight"
    assert "mismatch" in html
    # The distinction a reviewer actually needs: stale pointer, not invented quote.
    assert "the quote is real, the offset is not" in html


def test_abstention_shows_closest_spans(store):
    from cairn.retrieval import Retriever
    from cairn.support import check_support
    res = check_support("What is Apple's customer churn rate?", Retriever(store))
    inter = Interaction("churn?", "abstain", reason="insufficient", closest=res.closest)
    html = render_evidence_view([inter], store)
    assert "abstain" in html and "insufficient" in html


def test_derived_value_shows_its_equation(store):
    from cairn.verify import DerivedAtom
    sent = Sentence(
        "Total assets rose by $12,397 million (from $352,583M to $364,980M).",
        derived=[DerivedAtom("12,397", "subtract",
                             [_bind(store, "364,980", TOTAL_ASSETS),
                              _bind(store, "352,583", TOTAL_ASSETS)])],
    )
    ans = Answer([sent])
    inter = Interaction("delta?", "answer", answer=ans, verify=verify(ans, store))
    html = render_evidence_view([inter], store)
    assert "364,980 − 352,583 = 12,397" in html
    assert 'title="364,980 − 352,583 = 12,397"' in html
    assert "✓ recomputed" in html


def test_render_is_deterministic(store):
    a = render_evidence_view([_clean(store)], store)
    b = render_evidence_view([_clean(store)], store)
    assert a == b


def test_interactions_from_audit_rebuilds_presented(store):
    """The Desktop bridge: a real session's audit log → evidence-view interactions."""
    from cairn.evidence_view import interactions_from_audit

    atom = _bind(store, "364,980", TOTAL_ASSETS)
    answer_json = {"sentences": [{
        "text": "Apple's total assets were $364,980 million.",
        "atoms": [_atom_json(atom)],
    }]}
    frame = {"question": "What were Apple's total assets?",
             "constraints": [{"role": "metric", "text": "total assets"}]}
    entries = [
        {"kind": "check_support", "query": "apple total assets fiscal 2024",
         "status": "supported"},
        {"kind": "verify", "ok": True, "answer": answer_json, "frame": frame},
        {"kind": "check_support", "query": "CEO pay?",
         "status": "insufficient"},  # abstain → dropped from the view
    ]
    inters = interactions_from_audit(entries, store)
    assert len(inters) == 1                                   # only the presented one
    assert inters[0].question == "What were Apple's total assets?"  # the record's OWN frame
    assert inters[0].verify is not None and inters[0].verify.ok    # verify re-run, resolves


def test_the_question_comes_from_the_record_never_from_a_neighbour(store):
    """The attribution defect, made a standing test.

    Carrying the last `check_support` query forward mislabelled all 23 records of the
    first engagement — 18 showed a BM25 query where the question belonged, and 3 put an
    answer under an unrelated earlier question. Both are wrong on a surface a client
    signs, and the second is the dangerous one: nothing on the card reveals that the
    question above it belongs to a different interaction.
    """
    from cairn.evidence_view import interactions_from_audit

    atom = _bind(store, "364,980", TOTAL_ASSETS)
    answer_json = {"sentences": [{
        "text": "Apple's total assets were $364,980 million.",
        "atoms": [_atom_json(atom)],
    }]}
    entries = [
        {"kind": "check_support", "query": "executive compensation table",
         "status": "supported"},                       # a DIFFERENT, earlier question
        {"kind": "verify", "ok": True, "answer": answer_json,
         "frame": {"question": "What were Apple's total assets?", "constraints": []}},
    ]
    q = interactions_from_audit(entries, store)[0].question
    assert q == "What were Apple's total assets?"
    assert "executive compensation" not in q, "a neighbour's query must never be shown"


def test_a_frameless_record_labels_its_fallback_as_a_query(store):
    """Pre-D13 records carry no frame. The nearest query is all that survives, so it is
    shown — but never dressed up as the question, because a retrieval string presented
    as a reviewer's question misrepresents what was asked."""
    from cairn.evidence_view import interactions_from_audit

    atom = _bind(store, "364,980", TOTAL_ASSETS)
    entries = [
        {"kind": "check_support", "query": "apple total assets", "status": "supported"},
        {"kind": "verify", "ok": True, "answer": {"sentences": [{
            "text": "Apple's total assets were $364,980 million.",
            "atoms": [_atom_json(atom)]}]}},
    ]
    q = interactions_from_audit(entries, store)[0].question
    assert "not logged" in q and "apple total assets" in q

    # …and with nothing to fall back to, it says so rather than inventing one.
    bare = interactions_from_audit([entries[1]], store)[0].question
    assert bare == "(question not in log)"


def test_correction_renders_distinctly(store):
    """A grounded correction (D16) presents: its own badge/colour + highlighted spans."""
    ans = Answer([Sentence(
        "Total assets did not decline — they rose from $352,583M to $364,980M.",
        atoms=[_bind(store, "352,583", TOTAL_ASSETS), _bind(store, "364,980", TOTAL_ASSETS)],
    )])
    inter = Interaction("Why did total assets decline?", "correction",
                        answer=ans, verify=verify(ans, store))
    html = render_evidence_view([inter], store)
    assert '<section class="card correction" id="i0">' in html   # distinct card class
    assert '<span class="badge correction">' in html             # distinct badge
    assert "--corr:" in html and ".card.correction.active" in html  # its own colour
    assert re.search(r'<mark class="m k-fig"[^>]*>364,980</mark>', html)  # spans highlight


def test_from_audit_tags_outcome(store):
    """interactions_from_audit reads the logged D16 outcome → the card's kind."""
    from cairn.evidence_view import interactions_from_audit

    atom = _bind(store, "352,583", TOTAL_ASSETS)
    answer_json = {"sentences": [{
        "text": "Total assets rose to $364,980M (from $352,583M).",
        "atoms": [_atom_json(atom)],
    }]}
    entries = [
        {"kind": "check_support", "query": "Why did total assets decline?",
         "status": "supported"},
        {"kind": "verify", "ok": True, "answer": answer_json, "outcome": "correction"},
    ]
    inters = interactions_from_audit(entries, store)
    assert len(inters) == 1 and inters[0].kind == "correction"


def test_table_figure_lights_its_column_header(store):
    """A cited table figure also highlights its column's period header (D13)."""
    ans = Answer([Sentence("Total assets were $364,980 million.",
                           atoms=[_bind(store, "364,980", TOTAL_ASSETS)])])
    inter = Interaction("total assets?", "answer", answer=ans, verify=verify(ans, store))
    html = render_evidence_view([inter], store)
    # 364,980 is the FY2024 (first) column → its header is September 28, 2024
    assert re.search(r'<mark class="m k-lbl"[^>]*>September 28, 2024</mark>', html)


def test_refuse_renders_distinctly(store):
    """D22: a refusal-to-adjudicate is its own kind — distinct badge/colour from abstain."""
    from cairn.retrieval import Retriever
    inter = Interaction(
        "Is claim 1 valid?", "refuse",
        reason="Refusal to adjudicate (D10): validity is a professional's conclusion; "
               "the located evidence is offered for that review.",
        closest=Retriever(store).search("total assets", 1),
    )
    html = render_evidence_view([inter], store)
    assert '<section class="card refuse" id="i0">' in html
    assert '<span class="badge refuse">refuse</span>' in html
    assert "--refuse:" in html and ".card.refuse.active" in html   # its own colour


def test_sessions_from_audit_groups_by_marker(store):
    """RT-1: session_start markers delimit history; pre-marker entries stay browsable."""
    from cairn.evidence_view import sessions_from_audit
    from cairn.session import session_start_record

    atom = _bind(store, "364,980", TOTAL_ASSETS)
    ans = {"sentences": [{"text": "Total assets were $364,980 million.",
                          "atoms": [{"text": atom.text, "doc_id": atom.doc_id,
                                     "char_start": atom.char_start,
                                     "char_end": atom.char_end}]}]}
    def _frame(q):
        return {"question": q, "constraints": []}

    entries = [
        {"kind": "check_support", "query": "pre-marker q", "status": "supported"},
        {"kind": "verify", "ok": True, "answer": ans,                # unmarked preamble
         "frame": _frame("What did the preamble ask?")},
        session_start_record("morning review", "2026-07-06T09:00:00"),
        {"kind": "check_support", "query": "total assets", "status": "supported"},
        {"kind": "verify", "ok": True, "answer": ans,
         "frame": _frame("What were total assets?")},
        session_start_record("afternoon", "2026-07-06T14:00:00"),   # empty session kept
    ]
    groups = sessions_from_audit(entries, store)
    assert [g["label"] for g in groups] == ["(unmarked)", "morning review", "afternoon"]
    assert [len(g["interactions"]) for g in groups] == [1, 1, 0]
    assert groups[1]["ts"] == "2026-07-06T09:00:00"
    assert groups[1]["interactions"][0].question == "What were total assets?"
    # A session boundary also ends a query's reach: the preamble's question stays put.
    assert groups[0]["interactions"][0].question == "What did the preamble ask?"


# --- RT-4: companion figures in the document view ---

_STUB_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwC"
             "AAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


def test_figures_render_and_wire_to_the_interaction(store):
    from cairn.evidence_view import FigurePanel
    inter = _clean(store)
    inter.figures = ["FIG. 4"]
    figs = [FigurePanel("FIG. 4", "a disassembled separator", _STUB_PNG),
            FigurePanel("FIG. 5", "a side cross-section", _STUB_PNG)]
    html = render_evidence_view([inter], store, figures=figs)
    # the strip and both panels render, inside the document pane (before .docbody)
    assert '<div class="figstrip">' in html
    assert html.index('class="figstrip"') < html.index('class="docbody"')
    assert 'data-fig="FIG. 4"' in html and 'data-fig="FIG. 5"' in html
    assert _STUB_PNG in html                             # embedded, self-contained
    # only the interaction's own figure is wired (FIG. 4, not FIG. 5)
    assert re.search(r'const FIGMAP = \{[^}]*"i0":\s*\["FIG\. 4"\]', html)
    assert '.figpanel.on { display:block; }' in html    # revealed only when active


def test_figures_absent_leaves_the_view_unchanged(store):
    """No figures passed → no strip, empty FIGMAP — the EDGAR/default path is inert."""
    html = render_evidence_view([_clean(store)], store)
    assert '<div class="figstrip">' not in html         # the CSS rule may exist; the div must not
    assert "const FIGMAP = {};" in html


def test_interaction_figure_not_in_catalog_is_dropped(store):
    """An interaction naming a figure the caller didn't supply is filtered, not faked."""
    from cairn.evidence_view import FigurePanel
    inter = _clean(store)
    inter.figures = ["FIG. 4", "FIG. 99"]               # 99 has no panel
    html = render_evidence_view([inter], store,
                                figures=[FigurePanel("FIG. 4", "cap", _STUB_PNG)])
    assert re.search(r'"i0":\s*\["FIG\. 4"\]', html)    # 99 dropped
    assert "FIG. 99" not in html


def test_denial_cue_advisory_renders_non_blocking(tmp_path):
    """D24: a cited span carrying a span-local denial cue gets the advisory line —
    while verify stays ✓ (it gates nothing). Built on a synthetic store so the
    fixture is hermetic."""
    from cairn.ingest import DocumentStore
    from cairn.ingest.files import ingest_paths

    doc_text = ("Financial note.\n"
                "When speaking of total assets and liabilities, the number $2,000,000 has "
                "been claimed, but in fact this is incorrect when accounting for the "
                "revaluation.\n")
    src = tmp_path / "note.txt"
    src.write_text(doc_text, encoding="utf-8")
    store_dir = tmp_path / "store"
    ingest_paths([str(src)], store_dir, kind="filing")
    s = SpanStore.from_store(DocumentStore(store_dir))
    text = s.get_document("note")
    off = text.index("2,000,000")
    ans = Answer([Sentence("Total assets and liabilities are $2,000,000.",
                           atoms=[AtomBinding("2,000,000", "note", off, off + 9,
                                              s._docs["note"].content_hash)])])
    inter = Interaction("What are the total assets and liabilities?", "answer",
                        answer=ans, verify=verify(ans, s))
    html = render_evidence_view([inter], s)
    assert "✓ verify" in html                              # NOT blocked — advisory only
    assert "denial/correction cue in cited span" in html
    assert "“incorrect”" in html and "(advisory, D24)" in html


def test_no_cue_no_advisory(store):
    """Benign citations stay clean — no advisory noise on the normal path."""
    html = render_evidence_view([_clean(store)], store)
    assert "denial/correction cue" not in html
