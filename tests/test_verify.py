"""Standing tests for verify — the atom resolver (ROADMAP M2-T1, D9, I1).

Covers the AC: a planted unbound claim is flagged; a clean answer passes; the
result is a complete record. Plus mismatch, derived recomputation, hash-drift
(I3), and out-of-range bindings.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from cairn.ingest import DocumentStore
from cairn.spans import SpanStore
from cairn.verify import Answer, AtomBinding, DerivedAtom, Sentence, verify

ROOT = Path(__file__).resolve().parent.parent
DOC_ID = "AAPL-10K-FY2024"
TOTAL_ASSETS = "Total assets $ 364,980 $ 352,583"


@pytest.fixture(scope="module")
def store() -> SpanStore:
    ds = DocumentStore(ROOT / "corpus" / "store")
    if DOC_ID not in ds.list_docs():
        pytest.skip("corpus not ingested — run scripts/ingest_corpus.py")
    return SpanStore.from_store(ds)


def bind(
    store: SpanStore, literal: str, line: str, *, content_hash: str | None = None
) -> AtomBinding:
    """Bind a figure to its exact offset within a (uniquely resolvable) line.

    Defaults the corpus hash to the store's own, because that is now what a real
    binding carries (D65): `get_span`/`get_document` return the hash they read
    against, and a binding without one is unverifiable rather than merely unchecked.
    Tests that exercise drift pass an explicit wrong hash.
    """
    line_start, _ = store.resolve_quote(DOC_ID, line)
    idx = line.index(literal)
    start = line_start + idx
    if content_hash is None:
        content_hash = store._docs[DOC_ID].content_hash
    return AtomBinding(literal, DOC_ID, start, start + len(literal), content_hash)


def test_clean_answer_passes(store):
    h = store._docs[DOC_ID].content_hash
    ans = Answer([
        Sentence(
            "Apple's total assets were $364,980 million.",
            atoms=[bind(store, "364,980", TOTAL_ASSETS, content_hash=h)],
        )
    ])
    result = verify(ans, store)
    assert result.ok
    assert result.sentences[0].atom_verdicts[0].status == "ok"
    assert not result.unbound()


def test_planted_unbound_claim_is_flagged(store):
    """The AC: a figure asserted with no binding cannot slip through."""
    ans = Answer([Sentence("Apple's total assets were $999,999 million.", atoms=[])])
    result = verify(ans, store)
    assert not result.ok
    assert "999,999" in result.unbound()


def test_wrong_offset_is_mismatch(store):
    """Binding the figure to the wrong column (352,583's slot) is caught."""
    good = bind(store, "364,980", TOTAL_ASSETS)
    wrong = replace(good, char_start=good.char_start + 10, char_end=good.char_end + 10)
    ans = Answer([Sentence("Total assets were $364,980 million.", atoms=[wrong])])
    result = verify(ans, store)
    assert not result.ok
    assert result.sentences[0].atom_verdicts[0].status == "mismatch"


def test_stale_hash_is_flagged(store):
    """A binding made against a different doc version (hash) is rejected (I3)."""
    real = bind(store, "364,980", TOTAL_ASSETS)
    stale = AtomBinding(
        real.text, real.doc_id, real.char_start, real.char_end, content_hash="0" * 64
    )
    ans = Answer([Sentence("Total assets were $364,980 million.", atoms=[stale])])
    result = verify(ans, store)
    assert not result.ok
    assert result.sentences[0].atom_verdicts[0].status == "stale_hash"


def test_an_unhashed_binding_fails_rather_than_skipping_the_drift_check(store):
    """D65: I3 is enforced, not offered.

    The hash comparison used to run only `if binding.content_hash is not None`, so a
    binding that omitted the hash silently skipped the corpus-drift guarantee. On the
    first engagement it was omitted 61 times out of 61 — the check was never once
    exercised on real work — and when the corpus moved, every offset went stale in
    silence and the console presented genuine quotes boxed around unrelated text.

    A check that cannot run is a check that failed. The bindings above still pass
    because a real one now carries the hash `get_span`/`get_document` returned; this
    one omits it and must not resolve.
    """
    real = bind(store, "364,980", TOTAL_ASSETS)
    unhashed = replace(real, content_hash=None)
    ans = Answer([Sentence("Total assets were $364,980 million.", atoms=[unhashed])])
    result = verify(ans, store)
    assert not result.ok, "an unverifiable binding must not read as verified"
    assert result.sentences[0].atom_verdicts[0].status == "unhashed"


def test_the_read_tools_hand_back_a_hash_a_binding_can_carry(tmp_path):
    """The other half of D65, and the reason the check went unused for so long: no read
    tool returned a corpus hash, so an agent had nothing to bind with. The field was
    unreachable, not merely unpopular — a guarantee nothing could satisfy."""
    from cairn.ingest.document import make_document
    from cairn.ingest.store import DocumentStore
    from cairn.tools import default_registry

    ds = DocumentStore(tmp_path / "store")
    doc = make_document("D1", "Total assets were 364,980 million at year end.")
    ds.write(doc)
    reg = default_registry(tmp_path / "store", audit_path=None)

    span = reg["get_span"].handler({"doc_id": "D1", "start": 0, "end": 12})
    whole = reg["get_document"].handler({"doc_id": "D1"})
    assert span["content_hash"] == whole["content_hash"] == doc.content_hash

    # …and a binding built from that read verifies end to end.
    off = doc.canonical_text.index("364,980")
    out = reg["verify"].handler({"answer": {"sentences": [{
        "text": "Total assets were 364,980 million.",
        "atoms": [{"text": "364,980", "doc_id": "D1", "char_start": off,
                   "char_end": off + 7, "content_hash": span["content_hash"]}]}]}})
    assert out["ok"] is True


def test_out_of_range_is_flagged(store):
    n = len(store.get_document(DOC_ID))
    h = store._docs[DOC_ID].content_hash
    ans = Answer([Sentence("x $1,234 y",
                           atoms=[AtomBinding("1,234", DOC_ID, n + 1, n + 6, h)])])
    result = verify(ans, store)
    assert result.sentences[0].atom_verdicts[0].status == "out_of_range"


def test_derived_value_recomputes(store):
    """G005: the $12,397M delta is recomputed from bound operands, not cited."""
    sent = Sentence(
        "Total assets increased by $12,397 million (from $352,583M to $364,980M).",
        derived=[DerivedAtom(
            "12,397", "subtract",
            [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS)],
        )],
    )
    result = verify(Answer([sent]), store)
    assert result.ok
    assert not result.unbound()


def test_wrong_derived_value_is_flagged(store):
    sent = Sentence(
        "Total assets increased by $12,398 million (from $352,583M to $364,980M).",
        derived=[DerivedAtom(
            "12,398", "subtract",
            [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS)],
        )],
    )
    result = verify(Answer([sent]), store)
    assert not result.ok


def test_equation_renders_the_derivation(store):
    from cairn.verify import DerivedAtom, equation
    d = DerivedAtom("12,397", "subtract",
                    [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS)])
    assert equation(d) == "364,980 − 352,583 = 12,397"


COVER_PERIOD = "For the fiscal year ended September 28, 2024"


def test_unbound_date_is_flagged(store):
    """A period ('as of <date>') is load-bearing — an ungrounded date is flagged."""
    sent = Sentence(
        "Total assets as of September 28, 2024 were $364,980 million.",
        atoms=[bind(store, "364,980", TOTAL_ASSETS)],  # figure bound, date is NOT
    )
    result = verify(Answer([sent]), store)
    assert not result.ok
    assert "September 28, 2024" in result.unbound()


def test_bound_date_passes(store):
    sent = Sentence(
        "Total assets as of September 28, 2024 were $364,980 million.",
        atoms=[
            bind(store, "364,980", TOTAL_ASSETS),
            bind(store, "September 28, 2024", COVER_PERIOD),
        ],
    )
    result = verify(Answer([sent]), store)
    assert result.ok
    assert not result.unbound()


def test_percent_change_recomputes(store):
    """VER-1: percent change recomputed from operands, matched at the written precision."""
    sent = Sentence(
        "Total assets grew 3.5% from fiscal 2023 to 2024.",
        derived=[DerivedAtom(
            "3.5%", "percent_change",
            [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS)],
        )],
    )
    assert verify(Answer([sent]), store).ok


def test_ratio_recompute_respects_written_precision(store):
    """1.035161… rounds to the asserted precision: 1.035 passes, 1.03 does not."""
    ops = [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS)]
    good = Sentence("The ratio is 1.035.", derived=[DerivedAtom("1.035", "ratio", ops)])
    bad = Sentence("The ratio is 1.03.", derived=[DerivedAtom("1.03", "ratio", ops)])
    assert verify(Answer([good]), store).ok
    assert not verify(Answer([bad]), store).ok


def test_new_op_equations(store):
    from cairn.verify import equation
    ops = [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS)]
    assert equation(DerivedAtom("Z", "multiply", ops)) == "364,980 × 352,583 = Z"
    assert (equation(DerivedAtom("3.5%", "percent_change", ops))
            == "(364,980 − 352,583) / 352,583 × 100 = 3.5%")


def test_comparison_gt_verifies(store):
    """VER-1 slice 2 (D19): a numeric relation between cited operands is confirmed."""
    ops = [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS)]
    sent = Sentence("FY2024 total assets 364,980 exceed FY2023 352,583.",
                    derived=[DerivedAtom("true", "gt", ops)])
    assert verify(Answer([sent]), store).ok


def test_within_range_verifies_and_flags_wrong_boolean(store):
    val = bind(store, "364,980", TOTAL_ASSETS)
    lo = bind(store, "352,583", TOTAL_ASSETS)
    hi = bind(store, "364,980", TOTAL_ASSETS)            # inclusive upper bound
    text = "364,980 sits within [352,583, 364,980]."
    assert verify(Answer([Sentence(text, derived=[
        DerivedAtom("true", "within_range", [val, lo, hi])])]), store).ok
    # asserting the opposite of the recomputed relation is flagged
    assert not verify(Answer([Sentence(text, derived=[
        DerivedAtom("false", "within_range", [val, lo, hi])])]), store).ok


def test_comparison_equations(store):
    from cairn.verify import equation
    ab = [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS)]
    assert equation(DerivedAtom("true", "gt", ab)) == "364,980 > 352,583 → true"
    vlh = [bind(store, "364,980", TOTAL_ASSETS), bind(store, "352,583", TOTAL_ASSETS),
           bind(store, "364,980", TOTAL_ASSETS)]
    assert equation(DerivedAtom("true", "within_range", vlh)) == \
        "352,583 ≤ 364,980 ≤ 364,980 → true"


def test_a_figure_asserted_twice_needs_two_bindings():
    """D37 (I1): coverage was a SET difference, so one binding discharged every
    occurrence of a figure in a sentence. "Total assets were 364,980 and total
    liabilities were also 364,980" passed with a single binding and reported nothing
    unbound — the second assertion, about a different metric, was ungrounded prose that
    the first citation silently vouched for. Multiplicity is what makes N assertions
    require N bindings."""
    from cairn.ingest.document import make_document
    from cairn.spans import SpanStore
    from cairn.verify import Answer, AtomBinding, Sentence, verify

    text = "Total assets were 364,980 million as of year end."
    doc = make_document("D", text)
    store = SpanStore([doc])
    i = text.index("364,980")
    b = AtomBinding("364,980", "D", i, i + len("364,980"), doc.content_hash)

    twice = Sentence("Assets were 364,980 and liabilities were also 364,980.", atoms=[b])
    r = verify(Answer([twice]), store)
    assert not r.ok and r.unbound() == ["364,980"]

    r = verify(Answer([Sentence(twice.text, atoms=[b, b])]), store)
    assert r.ok and r.unbound() == []          # both assertions bound: passes

    once = Sentence("Assets were 364,980 million.", atoms=[b])
    assert verify(Answer([once]), store).ok    # the ordinary case is unaffected


def _mini():
    """A tiny corpus plus a binder, for the VER-1 operation tests (D59)."""
    from cairn.ingest.document import make_document
    from cairn.spans import SpanStore
    from cairn.verify import AtomBinding
    text = ("Revenue was 391,035 in FY2024 and 383,285 in FY2023. The filing is dated "
            "September 28, 2024 and the prior one September 30, 2023.")
    store = SpanStore([make_document("D", text)])

    def bind(lit):
        i = text.index(lit)
        return AtomBinding(lit, "D", i, i + len(lit), store._docs["D"].content_hash)
    return store, bind


def _derives(store, bind, op, result, operands, prose=None):
    from cairn.verify import Answer, DerivedAtom, Sentence, verify
    atoms = [bind(o) for o in operands]
    d = DerivedAtom(result, op, atoms)
    s = Sentence(prose or f"The value is {result}.", atoms=atoms, derived=[d])
    return verify(Answer([s]), store).ok


@pytest.mark.parametrize(("op", "result", "operands"), [
    ("percent", "102.02", ["391,035", "383,285"]),
    ("max", "391,035", ["391,035", "383,285"]),
    ("min", "383,285", ["391,035", "383,285"]),
    ("average", "387,160", ["391,035", "383,285"]),
    ("count", "2", ["391,035", "383,285"]),
])
def test_ver1_operations_recompute_from_cited_operands(op, result, operands):
    """D59: each new operation is a pure recomputation from operands that are themselves
    bound to spans. The result is declared and recomputed, never cited (D9)."""
    store, bind = _mini()
    assert _derives(store, bind, op, result, operands)


@pytest.mark.parametrize(("op", "wrong", "operands"), [
    ("percent", "150.00", ["391,035", "383,285"]),
    ("max", "383,285", ["391,035", "383,285"]),
    ("average", "400,000", ["391,035", "383,285"]),
    ("count", "5", ["391,035", "383,285"]),
])
def test_ver1_operations_reject_a_wrong_result(op, wrong, operands):
    """The half that matters: an operation that cannot fail is not verifying anything."""
    store, bind = _mini()
    assert not _derives(store, bind, op, wrong, operands)


def test_date_delta_verifies_and_rejects():
    """Dates dispatch BEFORE numeric parsing — `to_number` would reject a date literal,
    so a date operand must never reach it."""
    store, bind = _mini()
    dates = ["September 28, 2024", "September 30, 2023"]
    assert _derives(store, bind, "date_delta", "364", dates,
                    prose="There are 364 days between them.")
    assert not _derives(store, bind, "date_delta", "500", dates,
                        prose="There are 500 days between them.")


def test_a_duration_is_not_a_term():
    """D10, sharply. `date_delta` returns days and nothing more. Patent term involves
    adjustments, extensions, terminal disclaimers and maintenance status — none of them
    arithmetic — so the operation set offers no way to compute one. This test exists so
    that adding `patent_term` (or any adjudication-shaped operation) fails loudly rather
    than arriving quietly in a later commit."""
    from cairn.verify import _BOOL_OPS, _DATE_OPS, _OPS
    forbidden = {"patent_term", "expiry", "expiration", "term", "validity", "novelty",
                 "obviousness", "infringement", "scope", "prior_art"}
    offered = set(_OPS) | set(_BOOL_OPS) | set(_DATE_OPS)
    assert not (offered & forbidden), (
        f"an adjudication-shaped operation was added: {sorted(offered & forbidden)}. "
        f"Cairn locates and evidences; it does not conclude (D10).")


def test_to_date_accepts_only_what_verify_treats_as_a_date():
    """A looser parser would accept strings the rest of the system does not consider
    dates, so the two must agree on what a date literal is."""
    import datetime

    from cairn.verify import to_date
    assert to_date("September 28, 2024") == datetime.date(2024, 9, 28)
    assert to_date("Sep. 28, 2024") == datetime.date(2024, 9, 28)
    for bad in ("2024-09-28", "28 September 2024", "Septober 4, 2024", "391,035"):
        with pytest.raises(ValueError):
            to_date(bad)
