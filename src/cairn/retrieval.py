"""Retrieval over the span store (ROADMAP M1-T3, brief §8).

Deliberately simple and deterministic. v1 ships a BM25 backend behind a small
`RetrievalBackend` interface; an embedding backend can be added later behind the
same interface and fused (e.g. reciprocal-rank fusion) without touching callers
— that's the "hybrid" seam from brief §8, kept open without taking the dependency.

Determinism (I6): BM25 is a pure function of the corpus + query; equal-scoring
spans are tie-broken by `span_id`, so the same corpus + query yields byte-identical
rankings across runs. No randomness, hence nothing to seed; an embedding backend
*would* need a pinned model + cached vectors to preserve this — the obligations are
written out on `RetrievalBackend` (D60).

Corpus-agnostic and multi-document by construction (the patent track reuses it).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from .spans import Span, SpanStore

_TOKEN = re.compile(r"[a-z]+(?:-[a-z]+)*|\d{1,3}(?:,\d{3})+|\d+")

BM25_K1 = 1.5
BM25_B = 0.75

# Standard function words removed from *queries* only (the index keeps everything).
# Bare digit tokens are dropped from queries too — in a question they're dates/ordinals,
# while real figures are comma-grouped ("364,980") and survive. This is ordinary query
# normalization, not corpus-specific tuning.
STOPWORDS = frozenset(
    "a an the of to for in on at as is are was were be do does did what which who whom "
    "how much many and or by from this that these those with about into over under "
    "apple apples".split()
)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def featurize(text: str, *, is_query: bool = False) -> list[str]:
    """Unigrams + adjacent bigrams — phrase signal so 'total assets' keys on the
    right line, not every line containing 'total'. Queries are first reduced to
    content terms (stopwords + bare numbers dropped)."""
    toks = tokenize(text)
    if is_query:
        toks = [t for t in toks if t not in STOPWORDS and not t.isdigit()]
    return toks + [f"{toks[i]}_{toks[i + 1]}" for i in range(len(toks) - 1)]


@dataclass(frozen=True)
class Hit:
    span: Span
    score: float


class RetrievalBackend(Protocol):
    """What any retrieval backend must satisfy (D60, contract 2.0).

    The seam is deliberately tiny — propose candidates, return ranked hits — because
    retrieval **proposes and never decides**. Everything that decides sits downstream and
    is a pure function: the support floor, `verify`'s span resolution and hash check,
    coverage, the outcome classes. A wrong retrieval yields a worse answer or an
    abstention; it cannot yield a wrong citation, because `verify` re-checks the span
    however it was found. That asymmetry is what makes it safe to relax I6 here and
    nowhere else.

    Four obligations, none of them optional:

    1. **Deterministic ranking.** Same corpus + query → byte-identical order. BM25 gets
       this free and tie-breaks equal scores by `span_id`; an embedding backend needs a
       pinned model *and* cached vectors, because float non-determinism across runtimes
       would otherwise reorder ties invisibly.
    2. **Document-side artifacts are ingestion-time and frozen.** Embeddings for the
       corpus are computed once, hashed into a manifest, and never recomputed at answer
       time — exactly the discipline OCR is held to (D28). Only the *query* side may run
       at retrieval time.
    3. **`name` is a provenance tag** (TC-2) and must change when anything that could
       change results changes — the model, its version, the fusion weights. A record that
       says `bm25` when an embedding backend answered it is a lie in the audit log, and
       D45 showed how expensive an unrecorded version change is.
    4. **No decision.** A backend returns candidates and scores. It does not decide
       support, does not abstain, and must apply **no relevance threshold of its own** —
       ranking is its job, sufficiency is `check_support`'s. The distinction is narrow but
       real: returning nothing because no query term appears anywhere is *zero signal*,
       which is honest; returning nothing because the best score looked too low is a
       decision, and it would silently pre-empt the floor that the calibration record
       exists to make auditable.

    Nothing beyond BM25 is built. This documents the levers so a future backend meets a
    written contract rather than an inferred one (RAG Decision 2, move A).
    """

    #: Provenance tag recorded on every interaction — see obligation 3.
    name: str

    def search(self, query: str, k: int) -> list[Hit]: ...


class BM25Backend:
    """Okapi BM25 over featurized spans. Deterministic; tie-break by span_id."""

    name = "bm25"   # method tag for provenance (TC-2)

    def __init__(self, spans: list[Span], k1: float = BM25_K1, b: float = BM25_B):
        self.spans = spans
        self.k1 = k1
        self.b = b
        self._feats = [featurize(s.text) for s in spans]
        self.n = len(spans)
        self.avgdl = (sum(len(f) for f in self._feats) / self.n) if self.n else 0.0
        df: Counter[str] = Counter()
        for f in self._feats:
            df.update(set(f))
        self.idf = {t: math.log(1 + (self.n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self._tf = [Counter(f) for f in self._feats]

    def _score(self, q_terms: list[str], i: int) -> float:
        tf = self._tf[i]
        dl = len(self._feats[i])
        total = 0.0
        for t in q_terms:
            f = tf.get(t)
            if not f:
                continue
            denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl) if self.avgdl else 1.0
            total += self.idf.get(t, 0.0) * (f * (self.k1 + 1)) / denom
        return total

    def search(self, query: str, k: int = 10) -> list[Hit]:
        q = featurize(query, is_query=True)
        scored = [(self._score(q, i), self.spans[i]) for i in range(self.n)]
        # Deterministic order: score desc, then span_id asc (stable across runs → I6).
        scored.sort(key=lambda x: (-x[0], x[1].span_id))
        return [Hit(sp, sc) for sc, sp in scored[:k] if sc > 0]


class Retriever:
    """Facade over the span store. BM25-only today; add an embedding backend
    behind RetrievalBackend and fuse here when the eval says it's needed."""

    def __init__(self, span_store: SpanStore, doc_ids: list[str] | None = None):
        ids = doc_ids if doc_ids is not None else list(span_store._docs)
        spans: list[Span] = []
        for doc_id in ids:
            spans.extend(span_store.spans(doc_id))
        self.backend: RetrievalBackend = BM25Backend(spans)

    @property
    def method(self) -> str:
        """Backend tag for provenance (TC-2) — becomes e.g. 'bm25+embed' under fusion."""
        return getattr(self.backend, "name", "unknown")

    def search(self, query: str, k: int = 10) -> list[Hit]:
        return self.backend.search(query, k)
