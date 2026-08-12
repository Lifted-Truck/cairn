# Traces

Evidence that a claim about this repo was checked, kept where a reader can find it without
reading the whole Decisions log.

Cairn's traces are unusual in one respect worth stating: most of what would normally be a
trace here is **already executable**. A claim about behaviour is a Layer-0 test (336 of
them, blocking on every push), and a claim about a measurement is a census script that
re-runs. So this directory holds the residue — the checks that produced a *number* or a
*negative result* rather than a standing assertion.

| Trace | What it records |
|---|---|
| [`../scripts/census_antecedent_basis.py`](../scripts/census_antecedent_basis.py) | Why the §112(b) antecedent-basis check was **not** shipped: 28%/24% of back-references flagged on two patents, dominated by coordinated introduction (D58). |
| [`../scripts/census_denial_cues.py`](../scripts/census_denial_cues.py) | Why the D25 abstain-gate was not built: the firing condition was all-benign on the real corpus (D24). |
| [`../scripts/corpus_fit_report.py`](../scripts/corpus_fit_report.py) | The 17 corpus-fitted constants, each with the evidence that set it and the observation that would falsify it (D42). |
| [`../docs/corpus_fit_record_US8046721B2.md`](../docs/corpus_fit_record_US8046721B2.md) | The second-corpus run: eight defects found on a system passing its whole gate, all in ingestion (D43/D45). |
| [`../docs/ocr_failure_modes.md`](../docs/ocr_failure_modes.md) | 72-agent OCR failure-mode survey; four claims about this repo reproduced before being acted on (D34). |
| [`../integrations/autonomous/`](../integrations/autonomous/) | The MCP security-hardening audit returned to the fleet, with every guard exercised against a running server rather than asserted (D35/D41/D49). |

**The convention.** A trace records a check that *could have gone the other way*. A census
that flooded and stopped a feature is a trace; a paragraph asserting a feature is good is
not. Negative results are the most valuable entries here, because they are the ones a
future session would otherwise re-derive.
