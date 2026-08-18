# CLAUDE.md

Guidance for Claude Code working in this repository. Read this before starting any task.

## What this project is

CAIRN is a grounded-retrieval system: **ground or abstain — never invent.** Every claim is
bound to a verifiable source span or it is not made. v1 ships as **deterministic tools** (an
MCP server + CLI) that Claude Code invokes — CAIRN makes **no model calls of its own at
runtime**. See [`README.md`](README.md) for the value proposition and the precise guarantee,
and [`CAIRN_build_brief.md`](CAIRN_build_brief.md) for full architecture and rationale.

## Source-of-truth hierarchy

- [`CAIRN_build_brief.md`](CAIRN_build_brief.md) — architecture, invariants, rationale. **Wins on *design*.**
- [`DECISIONS.md`](DECISIONS.md) — the append-only decision log (D1–D83+). **Wins on *what was already settled and why*;** binding on later work.
- [`ROADMAP.md`](ROADMAP.md) — status and sequencing. **Wins on *what to do next*.** When the two disagree, that split holds.
- [`golden_seed.json`](golden_seed.json) — the ground-truth eval set (20 items, Apple FY2024 10-K).
- [`CAIRN_Patent_Tailoring_Consideration.md`](CAIRN_Patent_Tailoring_Consideration.md) — patent-domain specialization for the **first client engagement**. Provisional; **subordinate to `ROADMAP.md`**. Wins on patent-domain design where it doesn't conflict.
- [`CAIRN_Client_Intake_Questions.md`](CAIRN_Client_Intake_Questions.md) — the open client decisions. Treat its unresolved items as **DO NOT INVENT** (see ROADMAP D10/§10).
- [`docs/landscape_lessons.md`](docs/landscape_lessons.md) — external prior art (legal/finance AI failures + category winners) mapped onto our decisions. **Research input, subordinate to ROADMAP; authorizes no work.** Its **CONFIRMS** entries are guardrails — the market already validated those decisions, so don't "fix" them (especially: never soften `verified ≠ entailed`; never let answer-rates dominate the eval headline). Its **CANDIDATE** items go to human triage only.
- [`docs/rag_extension_discussion.html`](docs/rag_extension_discussion.html) — design discussion (2026-07-22): extending CAIRN toward RAG (embeddings, chunking, contextual retrieval) for larger corpora. **Design input, authorizes no work.** Standing conclusion: the guarantee lives at `verify`/grounding (downstream of retrieval), so RAG is a retrieval-backend swap that doesn't touch the contract — EXCEPT it needs a ruling on I6's literal 'no runtime model calls' (query embedding). Awaits Julian's Decisions 1-3.
- [`docs/provability_research.md`](docs/provability_research.md) — the provability/veridicality swarm synthesis (2026-07-16): can refuted-in-context citations be caught deterministically? **Research input, same status as the landscape doc: subordinate to ROADMAP; authorizes no work.** Its candidate rows **D24–D27** await human triage. Standing conclusions once triaged: the assertion/denial distinction is pragmatic (cue-less refutation is permanently invisible to deterministic checks); Gödel–Löb and general FOL entailment are inapplicable — don't re-litigate them.

## Two corpora: EDGAR (reference) + patents (client)

EDGAR 10-K is the **architecture-proving reference build** (M0–M5). The first paying
engagement is a **patent refresh-and-update** — a *specialization* of the same engine,
not a rewrite (ROADMAP **D10** + the patent track). The corpus-agnostic engine
(ingestion+hash, span store, retrieval, verify, audit log, eval harness) is shared; the
patent domain adds a richer document model, typed provenance, and structural checks.
**Patent-domain cardinal rule (sharpened from "ground or abstain"): *locate & evidence,
never adjudicate*** — never conclude on novelty, obviousness, validity, infringement, FTO,
or definitive claim construction (a patent professional is in the loop; UPL boundary).

## How to pick up work

1. Read **▶ Current focus** in [`ROADMAP.md`](ROADMAP.md). Take the topmost unchecked task in that milestone. **Read [`DECISIONS.md`](DECISIONS.md)** — every `D#` is binding; don't contradict one.
2. Implement to the task's **acceptance criteria (AC)**. State which invariants (I1–I6) it touches and how its tests cover them.
3. A milestone is `DONE` only when its **Gate** passes. Don't begin the next milestone — or **anything under Backlog (v2)** — until then.

### Working mode (single primary agent on `main`)

- **Commit directly to `main`** in small, single-purpose commits. There is **no PR gate** in this repo; CI runs on every push to `main`. If you do use a `feat/…` branch, **fast-forward merge it to `main` when done** — never leave finished work stranded on a branch.
- **Run the gate before every commit:** `ruff check . && pytest -m layer0`. **Never mask the exit code** (don't pipe `pytest` through `tail`/`head` in an `&&` chain — a failure will look like success). A red gate or violated invariant means *not done*.
- **Definition of done — do every item, every time** (a second agent skipped this and it had to be back-filled):
  1. `[x]` the task box in ROADMAP with a one-line **DONE** note (what + which tests).
  2. Append a **Changelog** line: `YYYY-MM-DD · M#-T# · short note`.
  3. Advance **▶ Current focus** to the next task.
  4. `git push` and confirm CI is green.
- **New design decisions get a new `D#` row** in [`DECISIONS.md`](DECISIONS.md) with rationale. The Decisions log and the golden oracle are append-only and binding — don't quietly change behavior that a `D#` established.

## Setup, the gate, and where things live

- **Dev install:** `pip install -e ".[dev]"` (ruff + pytest). Optional MCP server: `pip install -e ".[mcp]"`.
- **The gate:** `pytest -m layer0` — the blocking Layer-0 deterministic evals ([`docs/layer0_gate.md`](docs/layer0_gate.md)); fast, seeded, **no model calls**. CI = `ruff check .` + this.
- **Scripts** run with plain `python scripts/<x>.py` from the repo root (they bootstrap `src/`). The **CLI** needs the install: `cairn list` / `cairn call <tool> '<json>'`.
- **Committed artifacts:** corpus at `corpus/store/` (regen: `python scripts/ingest_corpus.py`); golden quotes bound by `scripts/resolve_golden_quotes.py`; the review GUI via `python scripts/build_evidence_view.py` → `evidence_view.html`.
- **Module map** (`src/cairn/`): `ingest/` = Document + content-hash (I3), `DocumentStore`, **`edgar.py` (the only corpus-specific file)**; `spans.py` = char-offset spans + resolution invariant (D7); `retrieval.py` = BM25 (I6); `support.py` = `check_support` / abstention (I2, D12); `verify.py` = atom resolver (D9/I1); `frame.py` = question frame + coverage (D13); `audit.py` = append-only log (I5); `session.py` = record/replay; `tools.py`/`cli.py`/`mcp_server.py` = the MCP+CLI surface; `evidence_view.py` = the review GUI. `cairn_rig.py` (M0 audition rig) lives at the repo root.

## Invariants — non-negotiable

These guarantees are declared in one place — [`docs/truth_contract.md`](docs/truth_contract.md) (**truth-contract v1**, D21) — each mapped to its enforcing mechanism, layer, and current strength, alongside the **monotonic rule** (rigor strengthens freely; weakening needs a new major contract version + rationale + the oracle) and the **upgrade ratchet** (new methods plug in behind a seam and ship only if Layer-0 holds + Layer-E improves-or-holds). Read it before changing anything on the evidence path.

Each maps to a standing test. A change that violates one does not merge.

- **I1** Span-level provenance — every claim points to a real span (`doc_id`, `char_start`, `char_end`).
- **I2** Abstention over fabrication — below threshold → structured refusal, not an answer.
- **I3** Verified immutability — content-hash at ingest; any span/hash drift is a hard failure.
- **I4** Read/write asymmetry — corpus is read-only; the only writable surface is the audit log.
- **I5** Append-only audit log — every interaction logged immutably and replayably.
- **I6** Deterministic evidence layer — same corpus + query → reproducible results (seeded). No runtime model calls.

## Engineering rules

- **Determinism is law on the evidence path.** Anything touching retrieval, span-mapping, or verification runs seeded / temperature 0. Non-determinism there is a bug, not a tuning knob.
- **The oracle is sacred.** Don't weaken a gate to make a PR pass. If a gate is genuinely wrong, change it in its own PR with rationale logged in `DECISIONS.md`.
- **Invariant tests are CI, not afterthoughts.** I3/I4/I5/I6 each get a standing per-PR test from M1 onward.
- **CAIRN composes nothing in v1.** The agent drafts prose; CAIRN tools are pure deterministic functions. No `answer_with_citations` tool.
- **The corpus adapter is isolated.** All corpus-specific code lives in the ingestion module so a corpus swap touches one file.
- **"Verified" ≠ "entailed."** `verify` confirms a cited span *exists and is real*; it does not confirm the span *supports* the claim. Never let docs or output overclaim — entailment is measured offline (Layer E), not enforced at runtime in v1.

## The trap (watch for it)

The temptation will be to make CAIRN *cleverer* — esoteric retrieval, a richer ontology, a
more elegant abstraction — until it's a research project only its author can read. **Don't.**
All architectural ambition goes into the **eval harness**, where depth is the selling point.
Everywhere else, choose the boring, legible option. Legibility to a non-specialist is the
product.

## Runtime agent loop (M2+)

### Tool contracts (as built; MCP names land at M4)

| Loop role | Python (today) | Returns | Notes |
|---|---|---|---|
| locate | `retrieval.Retriever.search(q, k)` → `search_corpus` | `list[Hit{span, score}]` | deterministic, ranked (I6) |
| abstain-trigger | `support.check_support(q, retriever)` | `SupportResult{status, supporting[], closest[]}` | `insufficient` = content-absent abstain (D12) |
| read | `spans.SpanStore.get_span(doc_id, s, e)` / `get_document(doc_id)` | `str` (hash-verified, I3) | **read freely** (D11) |
| verify | `verify.verify(answer, store)` | `VerifyResult{ok, sentences[], unbound()}` | atom resolver (D9/I1) |
| *(forthcoming)* | `check_claim` (M4), `get_audit_log` (M3/M4) | — | per brief §5 |

`Answer` = `[Sentence{text, atoms:[AtomBinding{text, doc_id, char_start, char_end}], derived:[DerivedAtom]}]`.

### The loop (every session)

1. **Locate.** `check_support(question)` / `search_corpus`; **read freely** with `get_document` / `get_span` for the context a citation needs (D11) — retrieval is a navigational aid, not a cage.
2. **Abstain when unsupported (two mechanisms, D12):**
   - `check_support` → `insufficient` → **abstain**: structured refusal + the `closest` spans (show you looked, and where). *(deterministic, content-absence)*
   - Even when spans clear the floor, abstain/partial/reject by **reasoning** when the content doesn't answer *this* question — wrong period, wrong entity, false premise. *(your judgment; measured at Layer-E)* For the patent corpus this includes the **refusal-to-adjudicate** class (D10): locate & evidence, never conclude on novelty/validity/infringement/claim construction.
   - **Five outcomes, not present-vs-silent (D16, D22):** *answer* · *abstain* (content absent — stay silent) · **correction** — a **false premise** → present a **grounded refutation** citing the contradicting span (e.g. "assets did not decline — they rose, see ⟨span⟩") · **partial** — answer the in-corpus part and **explicitly flag** what's out of corpus · **refuse-to-adjudicate (D22)** — the evidence may be *present*, but the question asks for a **legal conclusion** (novelty/validity/infringement/claim construction, D10): decline the conclusion and **offer the located evidence** for professional review. **Locate first, then decline:** run the locate step (search/read) and cite the found spans (doc id + offsets) in the refusal — an *empty* refusal wastes the boundary; the professional needs the evidence to do their half. Distinct from `abstain` — refusal is a boundary, not an absence. `correction`/`partial` still present and go through `verify`; a `refuse` presents no conclusion (nothing to verify).
3. **Compose from the corpus, ground the output.** Bind each load-bearing atom (figure, date, entity) to its exact span; derived values declare operands, not a cited result (D9). The constraint is on *output*; reading is unrestricted.
4. **Plural & ranked.** When multiple defensible answers exist, return them all, ranked, each with its own evidence — never collapse to one (brief §4).
5. **`verify(answer, frame, outcome)` before presenting.** It confirms every atom resolves at its offset + hash-matches (I1/I3), flags unbound figures, and recomputes derived values. **Also pass the `frame` (M2-T8/D13):** decompose the question into typed constraints (`role` ∈ entity/metric/attribute/subject/period/unit/scope/comparison; mark implicit ones `required: false`) — verify then checks the cited evidence *covers every required constraint* (the connecting clause) and returns `coverage`. Constraint `text` must be a literal you expect **verbatim in the cited span** — short tokens, not paraphrases; and a **locator-style constraint can't be its own coverage** (a claim never names itself: claim 9's text says "of claim 1", never "claim 9") — when the constraint names the *place you're citing from*, mark it `required: false`; the binding's location satisfies it. **Present only if `ok` AND `coverage.complete`** — coverage-incomplete means the citation doesn't demonstrably answer *this* question: re-bind to a span that carries the constraint, or downgrade to partial/abstain. (`verify` confirms a citation is *real* and coverage that it *carries the question's terms* — full entailment is still Layer-E.) Pass `outcome` (D16: `answer` / `correction` / `partial`) so the audit log and evidence view record *which kind* of presentation it was (a grounded correction renders distinctly).
6. The verify/support result is appended to the audit log (I5, from M3). Present, or abstain.
7. **(Layer-E convention)** When run under the Layer-E harness (`scripts/run_layer_e.py`), end the answer with a line `Confidence: 0.NN` — your calibrated confidence that the answer is correct and grounded. The harness parses it for the calibration curve; it has no effect on the runtime guarantee.

## Stack (start boring on purpose)

- **Python** for CAIRN tools (MCP server + CLI), the rig, and the current GUI (a deterministic, server-less static HTML **evidence view**, `evidence_view.py`).
- **TypeScript/React** is the **M5** upgrade of that GUI (audit-log replay); not built yet — don't assume a React app exists.
- **Retrieval v1:** BM25 + a single embedding model, hybrid. Storage: sqlite (+ vector ext) or in-memory. No managed vector DB until the eval says you need it.

<!-- KNOWLEDGE-LOOP:START -->
## Self-Improving Knowledge Loop

Each session: read accumulated knowledge before acting, write distilled knowledge
after. This meta-layer sits on top of my primary role and never overrides it.

### Every session
1. **ORIENT** — Read INDEX.md in full (kept small on purpose). Pull ONLY the matching
   entries from LIBRARY.md into context. Never load all of LIBRARY by default.
2. **ACT** — Do the work, applying retrieved lessons. If a lesson proves wrong,
   correcting it outranks adding a new one.
3. **REFLECT** — Ask: "What did I learn that a future session needs and could not
   cheaply re-derive?" A lesson qualifies only if durable, evidenced (tied to a
   concrete trigger), and non-obvious. If nothing qualifies, write nothing.
4. **WRITE (atomic)** — Append the lesson to LIBRARY.md and a one-line pointer to
   INDEX.md in the same change. New lessons enter as `tier: candidate`; promote to
   `canonical` only on a second independent occurrence or human review.

### Write gate (anti-poisoning)
This loop feeds its own output back as input, so a wrong lesson, written once, is
retrieved and reinforced forever. Therefore: prefer not writing over writing
unverified; every lesson states what would falsify it; if a retrieved lesson
contradicts present evidence, trust the evidence and demote the lesson.

### Consolidation (periodic)
When LIBRARY exceeds ~30 entries, merge duplicates, delete superseded entries,
promote recurring candidates, tighten tags. Refactor it like code; don't grow it
like a log.

### LIBRARY entry template
`[Lxxxx] <title> | tier | added: YYYY-MM-DD | tags: … | lesson: … | evidence: … | falsifier: … | supersedes: …`
<!-- KNOWLEDGE-LOOP:END -->

<!-- kit:mailbox v2.1.0 — appended by /retrofit; edit freely, keep the three answers -->
## Mailbox

Cross-repo exchanges are files, not chat (doctrine `INTEGRATIONS.md` §2). Three
questions, answered once so no session has to guess:

- **Who owes me anything?** Briefs addressed to Cairn land in **`integrations/` in
  this repo** — that directory is our mailbox and the only place to look for work
  filed at us.
- **Did anyone answer my brief?** Responses to briefs *we* filed live in the
  **provider's** tree (e.g. `autonomous/integrations/attest/`), not here. They do
  not arrive; they must be pulled and read.
- **Should I act on an exchange between two other repos?** Read it freely if it is
  useful context — but it is not ours to act on, and not ours to raise to Julian as
  though it were. If it genuinely concerns Cairn, the response is to file our own
  brief, which puts it in a mailbox someone owes an answer to.

Decisions never live in `integrations/`. An exchange records what was said; what was
*decided* goes in `DECISIONS.md` in the same change.
<!-- /kit:mailbox -->
