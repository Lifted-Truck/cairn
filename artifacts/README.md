# Artifacts

Self-contained HTML pages produced during development and kept for posterity. Each is a
**dated snapshot of what was true when it was written** — they are not maintained, and
where one disagrees with `ROADMAP.md`, the roadmap wins.

Open any of them directly in a browser; none needs a server or a network connection.

**On the old name.** Artifacts written before the D40 rename were updated to say *Cairn*,
because they describe our own mechanisms and carry no external factual claims. The two
research reports in [`../docs/`](../docs/) are the deliberate exception and still say
*ATTEST* throughout: their trademark findings are facts about the *ATTEST* mark, and a
mechanical rename fabricated "YOUCAIRN" and "cosign cairn" before it was caught. The test
is whether the old name is load-bearing evidence or just stale.

## Product & status

| File | What it is |
|---|---|
| [`2026-07-28-product-roadmap.html`](2026-07-28-product-roadmap.html) | The whole picture: 29 built / 9 partial / 10 not started, mapped onto the five workflow stages, and the single console that would hold them. Includes the structural finding that Cairn had no input channel for the reviewer. |
| [`2026-07-28-record-of-inquiry-sample.html`](2026-07-28-record-of-inquiry-sample.html) | A real **Record of Inquiry** (RT-5/D46) generated from the EDGAR reference build — the signable client deliverable. Limits first, corpus hashes, outcomes, what was set aside, signature block. |

## Mechanism explainers

| File | What it explains |
|---|---|
| [`2026-07-28-calibration-explainer.html`](2026-07-28-calibration-explainer.html) | **How the support floor works, and why the patent corpus cannot have one.** The measured score distributions for both corpora on one axis, the four calibration states, and what "non-separable" means for where trust sits in an engagement. |
| [`CalibrationExplainer.jsx`](CalibrationExplainer.jsx) | The same explainer as a self-contained React component — no imports beyond React, no chart library. Drop into a React app, or read as prose with diagrams attached. |
| [`2026-07-26-ocr-rotation-and-integrity.html`](2026-07-26-ocr-rotation-and-integrity.html) | D32–D34: why rotation is a per-glyph property, the 6↔9 phantom problem, and the wrong-citation bug a research swarm found in our own numeral extractor. |

Earlier explainers live in [`../docs/`](../docs/) rather than here, because they are
cross-referenced from `CLAUDE.md` and `ROADMAP.md` and moving them would break those
links: `system_overview.html`, `ocr_explainer.html`,
`ocr_confirmation_explainer.html`, `rt4_and_next_steps.html`,
`rt4_payoff_explainer.html`, `provability_findings.html`,
`rag_extension_discussion.html`.

## What is deliberately *not* here

Anything generated from an **engagement** store — `corpus/engagements/*/…` is gitignored,
and its evidence views, figure views and OCR manifests stay local. The sample above is
built from the public EDGAR reference corpus for exactly that reason.
