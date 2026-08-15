# CAIRN — the truth contract

**Version: 2.1** · governed by [`ROADMAP.md`](../ROADMAP.md) decision **D21**.

| Version | Date | Change | Kind |
|---|---|---|---|
| **2.1** | 2026-08-14 | **I3 enforced rather than offered (D65):** `verify` compared the corpus hash only when a binding supplied one, so an omitted hash SKIPPED the drift check instead of failing it — and no read tool returned a hash, so the field was unreachable. It was supplied 0 times in 61 bindings on the first engagement; when the corpus moved, every offset went stale in silence. `get_span`/`get_document` now return the hash they read against, and an unhashed binding resolves `unhashed` (not ok). Retroactively invalidates all 23 answers recorded for US5447630A, which is correct — they do not resolve. | strengthening → minor |
| **2.0** | 2026-08-09 | **I6 relaxed to "no model on the deciding path" (D60):** retrieval may embed a query with a pinned, recorded model, because retrieval proposes and never decides; everything downstream stays model-free. Document embeddings are ingestion-time and frozen. Versioned as a major bump because the old form was grep-checkable and the new one takes judgment. | weakening → major |
| **1.2** | 2026-07-06 | **Live constraint coverage (D13/M2-T8):** the agent emits a typed question frame; `verify` deterministically checks the cited evidence **covers every required constraint** (the connecting clause), logs frame + coverage (replayable), and the loop presents **only if `ok` AND `coverage.complete`**. Converts a chunk of "does the evidence answer *this* question" from offline-judged into runtime-checkable — the guarantee the incumbents were falsified on ([landscape §1](landscape_lessons.md)). | strengthening → minor |
| 1.1 | 2026-06-30 | Outcome honesty refined (D22): **refuse-to-adjudicate** becomes a first-class fifth outcome, distinct from `abstain` — the evidence may be *present*; the legal conclusion is declined (UPL boundary). Scored separately at Layer-E (`refusal_accuracy`); rendered distinctly. | strengthening → minor |
| 1.0 | 2026-06-29 | Initial declaration (D21). | — |

This is the single, declared statement of what CAIRN guarantees about anything it
asserts — and how each guarantee is enforced or measured. It exists so that
**epistemic rigor can be raised over time without a rewrite and without silently
breaking what past outputs promised.** When the guarantees change, *this document's
version changes*, and outputs are stamped with the version they were produced under
(see Provenance).

## The cardinal guarantee

> **Ground or abstain — never invent.** Every load-bearing claim CAIRN presents is
> bound to a verifiable source span, or it is not presented. When the evidence is
> absent or doesn't answer the question, CAIRN **abstains, corrects, or partials**
> (D16) — it does not fabricate.

Everything below is the machinery that makes that guarantee real and checkable.

## The guarantees (v1)

| Guarantee | What it promises | Enforced by | Layer | Strength (v1) |
|---|---|---|---|---|
| **I1 — span provenance** | every cited atom points to a real `(doc_id, char_start, char_end)` | `verify` atom resolver (D9) | runtime + Layer-0 | **hard** — enforced live, gated |
| **I2 — abstain over fabricate** | below the support floor → structured refusal, not an answer | `check_support` (content-absence, D12); agent reasoning for traps | runtime; Layer-0 (deterministic half); Layer-E (semantic) | **hard** for content-absence; **measured** for semantic traps |
| **I3 — verified immutability** | content-hash at ingest; any span/hash drift is a hard failure — **and a binding that carries no hash fails too** (D65) | content-hash + `verify` hash check, mandatory per binding; read tools return the hash to bind with | runtime + Layer-0 | **hard** |
| **I4 — read/write asymmetry** | the corpus is read-only; the only writable surface is the audit log | structural (only write tools hold the log) | runtime + Layer-0 | **hard** |
| **I5 — append-only audit** | every interaction logged immutably and replayably | `AuditLog` (hash-chained) | runtime + Layer-0 | **hard** |
| **I6 — deterministic evidence** | same corpus + query → reproducible results; **no model on the deciding path** (see I6 note, contract 2.0) | seeded/temperature-0 evidence path | runtime + Layer-0 | **hard** |
| **Outcome honesty (D16, D22)** | answer / abstain / **correction** / **partial** / **refuse** — a false premise is refuted with evidence; a legal conclusion is declined *as its own outcome*, never blurred into abstention | agent + `verify(outcome=…)`; `refuse` rendered + scored first-class | runtime; Layer-E | **hard** (present/abstain decision); **measured** (correctness, `refusal_accuracy`) |
| **Constraint coverage (D13, v1.2)** | when a frame is supplied, a presented answer's cited evidence **covers every required question constraint** (subject + attribute + qualifiers — the connecting clause), not merely the answer token | `verify(frame=…)` → deterministic `check_coverage` over the cited spans; loop presents only if `ok AND coverage.complete`; frame + coverage logged (I5, replayable) | runtime (deterministic flag + loop rule); Layer-E (adherence + the residuals) | **hard** (flag); **measured** (adherence; negation/attachment/coreference remain Layer-E) |
| **Locate-never-adjudicate (D10)** | patent domain: surface & evidence; never conclude novelty/validity/infringement/claim-construction — expressed as the first-class **refuse** outcome (D22) | agent refusal class + design | runtime; Layer-E negative test | **hard** (boundary); **measured** (adherence) |

### The one deliberate non-guarantee — `verified ≠ entailed`

`verify` confirms a citation is **real and located** — *not* that the span **supports**
the claim. Entailment (does the evidence actually answer *this* question?) is
**measured offline at Layer-E**, not gated at runtime in v1. This is stated plainly
so it is never overclaimed — and it is **the frontier**: the guarantee most likely to
strengthen as research arrives (toward runtime entailment-gating; see Backlog v2).

## Layers (where a guarantee lives)

- **Runtime** — enforced on every interaction (the deterministic tools; no model calls).
- **Layer-0** — the blocking, per-commit deterministic gate (the oracle). A guarantee
  marked *hard* has a standing Layer-0 test; a red gate means *not done*.
- **Layer-E** — periodic, model-in-the-loop, **measured not gated** (entailment,
  abstention calibration, adjudication-refusal). This is where rigor is *quantified*.

### I6 as amended — contract 2.0 (D60)

I6 read *"no runtime model calls"*. That literal form was never the guarantee anyone
needed; it was a proxy for the guarantee, and it forbade a class of work — embedding-based
retrieval — for a reason that does not apply to it. The amended form:

> Same corpus + query → reproducible results. **No model may sit on the deciding path.**
> Retrieval *may* embed a query with a pinned model, because retrieval proposes and never
> decides.

**What "deciding path" means, exactly.** Everything downstream of retrieval:
`check_support`'s floor comparison, `verify`'s span resolution and hash check, coverage,
and every outcome class. None of those may call a model, then or now. Retrieval's job is
to *propose candidates*; the decisions are made over the candidates it returns, by pure
functions, from spans that are hash-verified either way. A wrong retrieval yields a worse
answer or an abstention — never a wrong citation, because `verify` re-checks the span
regardless of how it was found.

**Why this is a WEAKENING and versioned as one.** The old form was checkable by grep: no
model calls, anywhere, full stop. The new one requires judgment about what counts as
deciding, and judgment is weaker than a syntactic rule. That is a real reduction in how
cheaply the claim can be audited, so it takes a major version rather than a quiet edit —
even though no guarantee about *output* changes.

**Two conditions, both learned the hard way.**

1. **Document embeddings are ingestion-time and frozen**, exactly as OCR is (D28). They
   are computed once, hashed into a manifest, and never recomputed at answer time. Only
   the *query* embedding happens at runtime.
2. **The model is pinned and recorded in provenance.** An embedding model has the same
   version-drift problem OCR does — the same input can embed differently across model
   versions, runtimes and hardware. D45 found the OCR version of this the expensive way.
   So a record says which embedding model produced it, and a changed model makes prior
   records stale rather than silently incomparable.

**What did not change.** `verified ≠ entailed`. The five outcome classes. Span-level
provenance. The hash chain. Abstention over fabrication. A model still never decides
whether evidence supports a claim.

## Versioning + the monotonic rule (D21)

The contract is **monotonic**: rigor may **strengthen** freely (a strengthening is a
minor version bump + a Decisions-log note). A change that would **weaken** a guarantee
is not allowed silently — it requires a **new major version**, a logged rationale, and
the oracle re-run. The Decisions log + the sacred oracle are what enforce "no quiet
weakening."

- `1.x` — additive strengthenings (new verify ops, a better calibrator, a sharper
  abstention) that don't reduce any guarantee.
- `2.0` — a structural change to what is guaranteed (e.g., entailment becomes
  runtime-gated, or a guarantee is relaxed) — logged and ratified.
  **Reached 2026-08-09 (D60):** I6's literal "no runtime model calls" relaxed to "no model
  on the deciding path", ratified by Julian, with the two conditions above.

## The upgrade ratchet (how new rigor is adopted)

New understanding/technology/research is adopted **behind an existing seam**, and
ships only if it passes the oracle:

> swap a component behind its interface → **the Layer-0 gate must hold** and
> **Layer-E must improve-or-hold** → otherwise it does not ship.

That is the whole forward-compatibility mechanism: ambition goes into the eval
harness; the harness decides what is real.

### The seams (today's extension points)

| Component | Seam | Upgrades it absorbs |
|---|---|---|
| retrieval | `RetrievalBackend` Protocol | embeddings, rerankers, hybrid fusion |
| support floor | `calibrate_threshold` (D20), `CAIRN_SUPPORT_THRESHOLD` | better calibration; per-corpus / per-engagement floors |
| verify math | the derived-op set (D18/D19) | new operations (kept pure, recompute-from-cited) |
| entailment | the injected judge (`ask`) | better judges; later, a formal entailment provider |
| corpus | the ingestion adapter (`edgar.py`, `patents.py`) | new corpora / domain packs |

## Provenance (TC-2 — implemented)

Every audit record carries a `provenance` block stamping the **rigor it was produced
under**, so it stays interpretable after an upgrade and rigor is **comparable across
versions**:

- `check_support` / `check_claim` → `{contract, retrieval, threshold}`
- `verify` → `{contract, verify_ops}`

`contract` is the version of *this* document ([`cairn.contract.CONTRACT_VERSION`](../src/cairn/contract.py)).
Replay reads the recorded floor (not the default), so a record made under a
per-engagement threshold reproduces byte-identically (I6). The evidence view renders
the line — e.g. *"truth-contract v1.0 · retrieval bm25 · floor 15 · verify-ops 1"*.
Additive and backward-compatible: records without a stamp read as pre-provenance.

The remaining seam is **entailment provenance** — stamped when a runtime entailment
method exists (today entailment is Layer-E only, recorded in the eval trend, not the
runtime record).

## The anti-trap

Forward-compatibility here is **declaration + provenance + the upgrade rule** — not a
speculative plugin framework. The seams above already exist; you formalize a new
interface (e.g. `EntailmentProvider`) **only when a second real implementation
arrives**, never preemptively. Legibility to a non-specialist remains the product.
