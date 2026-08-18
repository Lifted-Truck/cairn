# INDEX — knowledge map (read every session; keep small)

Tags: `gate-discipline` · `corpus-calibration` · `frame-coverage` · `patent-domain`
· `harness-lifecycle` · `eval-lessons`

- L0001 · gate-discipline · Echo-then-proceed is gate-masking: condition the commit on the gate's exit status, never on an echoed report of it.
- L0002 · eval-lessons, gate-discipline · Freeze a ratified oracle with a manifest hash over the frozen ids + a Layer-0 CI test (append-only, mechanical, not honor-system).
- L0003 · patent-domain, harness-lifecycle · Google Patents serves drawing sheets as thumbnail AND full-res under one name — fetch candidates, keep the largest; verify resolution after download.
- L0004 · eval-lessons, corpus-calibration · Census a proposed gate's firing condition on the real corpus first; all-benign hits → record the negative result, ship the advisory, don't build the gate.
- L0005 · patent-domain, corpus-calibration · Patent-sheet OCR traps: D1-D6 dimension labels → phantom numerals; spaced letter-ranges (FIGS. 3 A-C) → phantom figures. Inspect what extraction keeps AND discards.
- L0006 · corpus-calibration, eval-lessons · Validate any check/filter on REAL data first — it may delete signal OR flood false positives (≥10 floor, denial-cue gate, OCR leader-line floor, naive consecutive-numeral check: 4 instances). The reliable completeness check is a reconciliation, not a sequence-enumeration. Precision>>recall governs OUTPUT, not input pruning/eager flagging.
- L0007 · patent-domain, harness-lifecycle · Cross-modal confirmation: when sources disagree, let one guide a TARGETED second look at the other (tiled re-OCR searching only the text-predicted numeral); agree-from-two-angles is the bar; unresolved stays flagged. CG-tile-vs-Vision y-flip gotcha.
- L0008 · patent-domain, corpus-calibration · High-recall OCR needs: gated confusion variants (14a↔140), box-overlap fragment guards (incl. hit-vs-hit), and whole-image-only acceptance for lone glyphs; unreadable-but-predicted stays flagged.
- L0009 · harness-lifecycle, gate-discipline · All tools returning empty on visibly-valid input → test the instrument on a synthetic known-positive first; read subprocess stderr; sandbox blocks /tmp for spawned binaries (use the scratchpad).
- L0010 · harness-lifecycle, gate-discipline · A lesson in prose but not enforced by code/test gets re-learned (L0009's stderr corollary sat unimplemented for 4 milestones). Ask "what test would have caught this?" in the same change; a field whose only consumer is its own write site is decoration, not a guarantee.
- L0011 · harness-lifecycle, gate-discipline · A shared gate red on a FOREIGN artifact is an upstream report, never a local exclusion — desyncing a byte-identical detector also hides the defect. Report the observation, not a diagnosis; don't delete others' files.
