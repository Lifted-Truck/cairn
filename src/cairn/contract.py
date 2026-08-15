"""Truth-contract version anchor (D21; see `docs/truth_contract.md`).

The single source for the contract version stamped into every record (TC-2), so an
audit entry remains interpretable after the engine's rigor is upgraded and rigor is
comparable across versions. Bump per the monotonic rule: minor for a strengthening,
major for a structural change to what is guaranteed.
"""

# 1.2 (2026-07-06, D13/M2-T8): live constraint coverage — `verify` checks the cited
#     evidence covers the question frame's required constraints; presentation
#     requires ok AND coverage.complete. Strengthening → minor bump.
# 1.1 (2026-06-30, D22): outcome honesty refined — refuse-to-adjudicate becomes a
#     first-class fifth outcome, distinct from abstain. Strengthening → minor bump.
# 1.0 (2026-06-29, D21): initial declaration.
# 2.0 (D60): I6's literal "no runtime model calls" relaxed to "no model on the DECIDING
# path" — retrieval may embed a query with a pinned model, because retrieval proposes and
# never decides. Versioned as a major bump because the old form was checkable by grep and
# the new one takes judgment: a real reduction in auditability, even though no guarantee
# about output moved. See docs/truth_contract.md "I6 as amended".
CONTRACT_VERSION = "2.1"
