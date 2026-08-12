"""Standing tests for retrieval (ROADMAP M1-T3, brief §8).

Core AC: results are candidate spans with offsets, and retrieval is reproducible
across runs (I6). Also a recall sanity check against the golden set — the gold
span for (almost) every answerable item appears in the candidate set; the one
known lexical gap (G009, the auditor signature) is documented and deferred to M2
(embedding backend / section-aware chunking).
"""

import json
from pathlib import Path

import pytest

from cairn.ingest import DocumentStore
from cairn.retrieval import Retriever
from cairn.spans import SpanStore

ROOT = Path(__file__).resolve().parent.parent
DOC_ID = "AAPL-10K-FY2024"

QUERIES = [
    "What were Apple's total assets as of September 28, 2024?",
    "How much commercial paper did Apple have outstanding?",
    "Who is Apple's independent registered public accounting firm?",
]


@pytest.fixture(scope="module")
def store() -> SpanStore:
    ds = DocumentStore(ROOT / "corpus" / "store")
    if DOC_ID not in ds.list_docs():
        pytest.skip("corpus not ingested — run scripts/ingest_corpus.py")
    return SpanStore.from_store(ds)


@pytest.fixture(scope="module")
def golden() -> list[dict]:
    return json.loads((ROOT / "golden_seed.json").read_text(encoding="utf-8"))["items"]


def test_hits_carry_resolvable_offsets(store):
    r = Retriever(store)
    hits = r.search(QUERIES[0], k=10)
    assert hits, "expected candidate spans"
    for h in hits:
        # offsets round-trip through the (hash-verified) span store
        assert store.get_span(h.span.doc_id, h.span.char_start, h.span.char_end) == h.span.text


def test_retrieval_is_reproducible(store):
    """I6: same corpus + query → byte-identical rankings across independent runs."""
    a = Retriever(store)
    b = Retriever(store)
    for q in QUERIES:
        ra = [(h.span.span_id, h.score) for h in a.search(q, k=20)]
        rb = [(h.span.span_id, h.score) for h in b.search(q, k=20)]
        assert ra == rb, f"non-deterministic retrieval for {q!r}"


def _gold_span_ids(store, item) -> set[str]:
    ids = set()
    for s in item.get("supporting", []):
        quote = s.get("verbatim_quote")
        if not quote:
            continue
        start, _ = store.resolve_quote(DOC_ID, quote)
        sp = store.span_containing(DOC_ID, start)
        if sp:
            ids.add(sp.span_id)
    return ids


def test_recall_on_answerable_golden(store, golden):
    r = Retriever(store)
    answerable = [it for it in golden if it["answerable"] and _gold_span_ids(store, it)]
    recall20 = sum(
        bool(_gold_span_ids(store, it) & {h.span.span_id for h in r.search(it["question"], 20)})
        for it in answerable
    )
    # All but the known auditor lexical gap (G009) should surface in the candidate set.
    assert recall20 >= len(answerable) - 1, f"recall@20 {recall20}/{len(answerable)} too low"


def test_the_backend_contract_holds_for_the_shipped_backend():
    """D60: the four obligations on `RetrievalBackend` are a written contract, so the one
    backend that exists must demonstrably meet them — otherwise the contract is
    aspiration, and a future backend inherits an unmet example."""
    from cairn.ingest.document import make_document
    from cairn.retrieval import Retriever
    from cairn.spans import SpanStore

    store = SpanStore([make_document(
        "D", "Total assets were 364,980. Total liabilities were 308,030. "
             "Revenue was 391,035 for the fiscal year.")])
    r = Retriever(store)

    # 1. Deterministic ranking — same corpus + query, byte-identical order.
    a = [(h.span.span_id, h.score) for h in r.search("total assets", 10)]
    b = [(h.span.span_id, h.score) for h in Retriever(store).search("total assets", 10)]
    assert a == b

    # 3. `name` is a provenance tag and is actually populated.
    assert r.method == "bm25"
    assert getattr(r.backend, "name", None) == "bm25"

    # 4. No decision: a WEAK match is still returned, and the floor decides. The
    #    distinction this pins is narrow and was got wrong once: returning nothing
    #    because no term appears is zero signal (honest); returning nothing because the
    #    score looked low would be the backend pre-empting check_support.
    weak = r.search("total churn rate", 10)          # one term overlaps: weak, not absent
    assert weak, "a weak match must survive — sufficiency is check_support's call"
    assert weak[0].score < 1.0, "and it really is weak"
    assert all(hasattr(h, "score") for h in weak)
    assert r.search("zzzz qqqq", 10) == [], "no overlap at all is zero signal, not a filter"


def test_retrieval_cannot_produce_a_wrong_citation():
    """The asymmetry that makes relaxing I6 safe at retrieval and nowhere else: whatever
    retrieval returns, `verify` re-checks the span against the document and its hash. A
    bad backend degrades the ANSWER; it cannot fabricate a citation."""
    from cairn.ingest.document import make_document
    from cairn.spans import SpanStore
    from cairn.verify import Answer, AtomBinding, Sentence, verify

    text = "Total assets were 364,980 million."
    store = SpanStore([make_document("D", text)])
    i = text.index("364,980")

    good = Sentence("Assets were 364,980 million.",
                    atoms=[AtomBinding("364,980", "D", i, i + 7)])
    assert verify(Answer([good]), store).ok

    # However a span was found, a binding that does not hold at its offsets fails.
    bad = Sentence("Assets were 364,980 million.",
                   atoms=[AtomBinding("364,980", "D", 0, 7)])
    assert not verify(Answer([bad]), store).ok
