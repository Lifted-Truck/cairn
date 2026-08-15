"""Standing tests for the FIG→sheet / numeral→sheet mapping (RT-4/PE-2, D28).

The OCR itself runs once at ingestion (macOS Vision, local-only) and is NOT under
test here — these tests pin the DETERMINISTIC layer over a frozen manifest, with a
synthetic fixture, so they are hermetic and CI-runnable. The split is the point:
same manifest, same answers (I6); OCR variance is quarantined at ingestion.
"""

from cairn.figures_map import (
    ELIMINATION,
    OCR,
    cross_check_numerals,
    element_numeral_issues,
    fig_to_sheets,
    numeral_sightings,
)
from cairn.patents import Numeral

# A synthetic manifest shaped exactly like scripts/ocr_patent_figures.py output:
# three sheets — one clean label, one garbled label ("FIG.A", as Vision actually
# produced for FIG. 4 on US5447630A), one clean — plus numerals incl. a low-conf one.
MANIFEST = {
    "engine": "test-fixture",
    "pages": [
        {"page": 2, "file": "drawings-page-2.png",
         "fig_labels": [{"fig": "1", "confidence": 0.5, "x": 0.5, "y": 0.7}],
         "sheet_id": {"sheet": 1, "of": 3},
         "numerals": [
             {"numeral": "10", "source_text": "10", "confidence": 1.0,
              "x": 0.4, "y": 0.3, "w": 0.02, "h": 0.02},
             {"numeral": "12", "source_text": "-12", "confidence": 0.3,
              "x": 0.5, "y": 0.3, "w": 0.03, "h": 0.02},
         ]},
        {"page": 3, "file": "drawings-page-3.png",
         "fig_labels": [{"fig": "A", "confidence": 0.5, "x": 0.5, "y": 0.03}],  # garbled "4"
         "sheet_id": {"sheet": 2, "of": 3},
         "numerals": [
             {"numeral": "89", "source_text": "89", "confidence": 1.0,
              "x": 0.6, "y": 0.4, "w": 0.02, "h": 0.02},
         ]},
        {"page": 4, "file": "drawings-page-4.png",
         "fig_labels": [{"fig": "5", "confidence": 1.0, "x": 0.5, "y": 0.03}],
         "sheet_id": {"sheet": 3, "of": 3},
         "numerals": [
             {"numeral": "77", "source_text": "77", "confidence": 1.0,
              "x": 0.2, "y": 0.5, "w": 0.02, "h": 0.02},
         ]},
    ],
}
KNOWN = ["1", "4", "5"]


def test_fig_to_sheets_ocr_plus_single_gap_elimination():
    """Clean labels map by OCR; the garbled 'FIG.A' cannot invent figure A; with
    exactly one figure and one sheet left, they pair BY ELIMINATION — flagged."""
    got = {a.fig: a for a in fig_to_sheets(MANIFEST, KNOWN)}
    assert set(got) == {"1", "4", "5"}
    assert got["1"].page == 2 and got["1"].method == OCR and got["1"].confidence == 0.5
    assert got["5"].page == 4 and got["5"].method == OCR
    assert got["4"].page == 3 and got["4"].method == ELIMINATION
    assert got["4"].confidence is None                   # no fake confidence


def test_elimination_needs_a_unique_gap():
    """Two unassigned figures → no guessing: both stay unassigned (a surfaced gap)."""
    got = fig_to_sheets(MANIFEST, ["1", "4", "5", "6"])  # 6 has no sheet anywhere
    methods = {a.fig: a.method for a in got}
    assert "4" not in methods and "6" not in methods     # neither invented
    assert methods == {"1": OCR, "5": OCR}


def test_numeral_sightings_confidence_floor():
    all_s = numeral_sightings(MANIFEST)
    assert [(s.numeral, s.page) for s in all_s] == [("10", 2), ("12", 2), ("89", 3), ("77", 4)]
    high = numeral_sightings(MANIFEST, min_confidence=0.5)
    assert [(s.numeral, s.page) for s in high] == [("10", 2), ("89", 3), ("77", 4)]  # -12 dropped


def test_cross_check_three_classes():
    cc = cross_check_numerals(["10", "89", "42"], MANIFEST)
    assert sorted(cc.matched) == ["10", "89"]
    assert cc.text_only == ["42"]                          # recited, never located
    assert [(s.numeral, s.page) for s in cc.sheet_only] == [("12", 2), ("77", 4)]


def test_element_numeral_issues_word_the_ocr_caveat():
    """PE-2's check surfaces facts with the indistinguishability caveat — never a
    §112 conclusion (D10)."""
    nums = [Numeral("10", "separator", 0, 2), Numeral("42", "ash outlet", 10, 12)]
    issues = element_numeral_issues(nums, MANIFEST, min_confidence=0.5)
    kinds = {(i["kind"], i["numeral"]) for i in issues}
    assert ("recited-not-located", "42") in kinds
    assert ("located-not-recited", "77") in kinds
    assert ("located-not-recited", "89") in kinds          # 89 not in the recited list here
    for i in issues:                                     # the honesty wording is load-bearing
        assert "indistinguishable" in i["message"] and "review" in i["message"]
        assert "112" not in i["message"] and "invalid" not in i["message"]


def _rel(span: str, known=("10", "12", "89", "77")):
    from cairn.figures_map import numeral_sightings, relevant_figures
    return relevant_figures([span], fig_to_sheets(MANIFEST, KNOWN),
                            numeral_sightings(MANIFEST), list(known))


def test_relevant_figures_by_numeral_and_ref():
    """RT-4 payoff: a cited span → the figures to show. Numeral 10 → its sheet's
    figure (1); an explicit FIG. 5 → figure 5; numeral 89 → the elimination-mapped
    figure 4; the two signals union and sort."""
    assert _rel("the separator 10, which splits flow") == ["1"]
    assert _rel("a necked portion 89 is provided") == ["4"]          # elimination-mapped
    assert _rel("as shown in FIG. 5 in cross-section") == ["5"]
    assert _rel("separator 10 and FIG. 5") == ["1", "5"]             # union


def test_relevant_figures_numeral_boundary():
    """A numeral must be a STANDALONE integer — not part of a larger/grouped/decimal
    number. Grouping comma ('10,500') excludes it; punctuation comma ('10, which')
    does not."""
    assert _rel("revenue of $10,500 thousand") == []                 # grouped
    assert _rel("a ratio of 10.5 to one") == []                      # decimal
    assert _rel("chamber 100 holds") == []                           # 100 ≠ 10
    assert _rel("the separator 10, however,") == ["1"]               # punctuation comma


def test_relevant_figures_unknown_signals_yield_nothing():
    assert _rel("plain prose with no figure or numeral", known=["10"]) == []
    assert _rel("FIG. 9 does not exist here", known=["10"]) == []      # 9 not assigned


def test_numeral_figures_all_appearances():
    """The 'all references' resolver: a numeral OCR-located on several sheets lists
    every figure it appears in (the user's shared-component case), sorted; an
    unassigned-sheet sighting contributes no figure."""
    from cairn.figures_map import numeral_figures, numeral_sightings
    assigns = fig_to_sheets(MANIFEST, KNOWN)         # 1→p2, 4→p3(elim), 5→p4
    allf = numeral_figures(assigns, numeral_sightings(MANIFEST))
    assert allf["10"] == ["1"]                         # p2 → FIG 1
    assert allf["89"] == ["4"]                         # p3 → FIG 4 (elimination)
    assert allf["77"] == ["5"]                         # p4 → FIG 5


def test_numeral_sighting_carries_bbox():
    """Bounding boxes survive into the sighting for the confirmation overlay."""
    from cairn.figures_map import numeral_sightings
    s = {(x.numeral, x.page): x for x in numeral_sightings(MANIFEST)}
    assert s[("10", 2)].bbox == (0.4, 0.3, 0.02, 0.02)
    assert s[("89", 3)].bbox == (0.6, 0.4, 0.02, 0.02)


def test_numeral_sighting_bbox_absent_is_none():
    """A legacy manifest without w/h yields bbox=None, not a crash."""
    from cairn.figures_map import numeral_sightings
    legacy = {"pages": [{"page": 2, "file": "p.png", "fig_labels": [], "sheet_id": None,
                         "numerals": [{"numeral": "5", "source_text": "5",
                                       "confidence": 1.0, "x": 0.1, "y": 0.1}]}]}
    assert numeral_sightings(legacy)[0].bbox is None


def test_numeral_coverage_reconciliation():
    """The consistency check (Julian's ask): reconcile spec text vs OCR'd drawings.
    Reliable flags — recited-not-drawn, drawn-not-recited, per-figure mismatch —
    NOT the consecutive-integer check (unreliable for patents; returned as WEAK)."""
    from cairn.figures_map import numeral_coverage
    from cairn.patents import Numeral, figure_references
    # FIG1→p2 (OCR: 10,12), FIG4→p3 (OCR: 89), FIG5→p4 (OCR: 77) — from MANIFEST.
    text = ("As shown in FIG. 1, the separator 10 operates. "
            "In FIG. 5, the frame 12 and a gauge 34 are shown. "
            "In FIG. 4, the widget 89 is disassembled.")
    numerals = [Numeral(n, "x", 0, 1) for n in ("10", "12", "34", "89")]  # 77: nobody
    refs = figure_references(text)
    assigns = fig_to_sheets(MANIFEST, KNOWN)
    cov = numeral_coverage(numerals, text, refs, assigns, numeral_sightings(MANIFEST))

    assert cov.figure_tied == ["10", "12", "34", "89"]
    assert cov.recited_not_drawn == ["34"]        # tied to FIG 5 in text, OCR found it nowhere
    assert cov.drawn_not_recited == ["77"]        # OCR has 77 (p4), text never recites it
    mism = {m["numeral"]: m["not_located_on"] for m in cov.figure_mismatches}
    assert mism.get("12") == ["5"]                # text ties 12 to FIG 5, OCR has it on FIG 1
    assert "10" not in mism                        # 10 tied to FIG 1 AND OCR'd on FIG 1 → clean
    assert cov.seq_gaps                          # computed, but weak (not a shipped flag)


def test_numeral_text_figures_sees_all_mentions():
    """Unlike reference_numerals (first mention only), this finds every figure a
    numeral is discussed near — the basis of the separator-10 finding."""
    from cairn.figures_map import numeral_text_figures
    from cairn.patents import figure_references
    text = ("In FIG. 1 the separator 10 enters. Later, referring to FIG. 4, "
            "the disassembled separator 10 is shown.")
    refs = figure_references(text)
    assert numeral_text_figures(text, "10", refs) == ["1", "4"]     # both, not just the first


def test_numeral_sighting_method_round_trips():
    """D28 confirmation pass: a numeral record's `method` (first-pass | text-guided)
    survives into the sighting so the view can mark recovered numerals; a legacy
    record without the field defaults to first-pass."""
    from cairn.figures_map import numeral_sightings
    man = {"pages": [{"page": 7, "file": "p.png", "fig_labels": [], "sheet_id": None,
                      "numerals": [
                          {"numeral": "10", "source_text": "10", "confidence": 0.3,
                           "x": 0.2, "y": 0.56, "w": 0.08, "h": 0.02, "method": "text-guided"},
                          {"numeral": "80", "source_text": "80", "confidence": 1.0,
                           "x": 0.7, "y": 0.6, "w": 0.02, "h": 0.02},  # no method → first-pass
                      ]}]}
    by = {s.numeral: s for s in numeral_sightings(man)}
    assert by["10"].method == "text-guided"
    assert by["80"].method == "first-pass"


def test_plain_label_does_not_match_inside_a_suffixed_one():
    """Boundary: searching for "12" must NOT fire on "12a" (a different part)."""
    assert _rel("the bracket 12a is welded", known=["12"]) == []
    assert _rel("the housing 12 is welded", known=["12"]) == ["1"]


MULTI = {
    "pages": [{"page": 2, "file": "p.png",
               "fig_labels": [{"fig": "1", "confidence": 1.0, "x": 0.5, "y": 0.7}],
               "sheet_id": None,
               "numerals": [        # the SAME label twice on one sheet (FIG 3A does this)
                   {"numeral": "12a", "source_text": "12a", "confidence": 1.0,
                    "x": 0.20, "y": 0.70, "w": 0.03, "h": 0.02, "method": "text-guided"},
                   {"numeral": "12a", "source_text": "12a", "confidence": 0.9,
                    "x": 0.60, "y": 0.30, "w": 0.03, "h": 0.02, "method": "text-guided"},
               ]}],
}


def test_same_label_twice_on_a_sheet_keeps_both_instances():
    """A label legitimately repeats on one drawing — both instances survive so the
    reviewer gets a confirmation box on each (Julian: 12a appears twice on FIG 3A)."""
    from cairn.figures_map import numeral_figures, numeral_sightings
    sights = [s for s in numeral_sightings(MULTI) if s.numeral == "12a"]
    assert len(sights) == 2
    assert {s.bbox[0] for s in sights} == {0.20, 0.60}      # two distinct positions
    # but it is still ONE figure association, not a duplicate
    assigns = fig_to_sheets(MULTI, ["1"])
    assert numeral_figures(assigns, sights)["12a"] == ["1"]


def test_view_marker_letters_derived_from_sub_figures():
    from cairn.figures_map import view_marker_letters
    assert view_marker_letters(["1", "2", "3A", "3B", "3C", "4"]) == ["A", "B", "C"]
    assert view_marker_letters(["1", "2"]) == []          # no sub-figures → no markers


def test_is_fragment_box_overlap():
    """A token sitting ON a longer token containing it is a fragment: tiles cut
    '12b' → '1'; prose 'FINAL PURIFIED EFFLUENT. 1' ends in a fragment '1' far from
    the observation's CENTER — hence box overlap, not center distance."""
    from cairn.figures_map import is_fragment
    page = {"numerals": [{"numeral": "12b", "x": 0.399, "y": 0.084, "w": 0.02, "h": 0.02}],
            "observations": [{"text": "FINAL PURIFIED EFFLUENT. 1",
                              "x": 0.60, "y": 0.526, "w": 0.13, "h": 0.02}]}
    assert is_fragment({"numeral": "1", "x": 0.400, "y": 0.087}, page)      # atop 12b
    assert is_fragment({"numeral": "1", "x": 0.726, "y": 0.526}, page)      # prose tail
    assert not is_fragment({"numeral": "1", "x": 0.200, "y": 0.300}, page)  # standalone


def test_letters_from_first_pass_reclassifies_only_clean_reads():
    """Single-letter view markers come ONLY from whole-image observations (tiles
    hallucinate letters on line art). Exact-core match; header band excluded."""
    from cairn.figures_map import letters_from_first_pass
    page = {"numerals": [],
            "observations": [
                {"text": "B", "x": 0.134, "y": 0.218, "w": 0.01, "h": 0.015,
                 "confidence": 0.3},
                {"text": "FIG.A", "x": 0.47, "y": 0.03, "w": 0.05, "h": 0.02,
                 "confidence": 0.5},                      # garble — core is FIGA, not A
                {"text": "C", "x": 0.5, "y": 0.95, "w": 0.01, "h": 0.01,
                 "confidence": 1.0},                      # header band — excluded
            ]}
    got = letters_from_first_pass(page, ["A", "B", "C"])
    assert [(h["numeral"], h["method"]) for h in got] == [("B", "text-guided")]


def test_likely_misreads_resolves_a_zero_confusion():
    """A sheet-only '140' positionally coinciding with the recited '14a' is surfaced
    as a likely a↔0 misread and leaves the drawn-not-recited anomaly list."""
    from cairn.figures_map import numeral_coverage
    from cairn.patents import Numeral, figure_references
    man = {"pages": [{"page": 3, "file": "p.png",
                      "fig_labels": [{"fig": "2", "confidence": 1.0, "x": 0.5, "y": 0.03}],
                      "sheet_id": None,
                      "numerals": [
                          {"numeral": "140", "source_text": "14 140", "confidence": 0.5,
                           "x": 0.565, "y": 0.183, "w": 0.04, "h": 0.02},
                          {"numeral": "14a", "source_text": "140", "confidence": 0.5,
                           "x": 0.599, "y": 0.186, "w": 0.03, "h": 0.02,
                           "method": "text-guided"},
                      ]}]}
    text = "Referring to FIG. 2, the impeller 14a rotates."
    nums = [Numeral("14a", "impeller", 0, 1)]
    refs = figure_references(text)
    assigns = fig_to_sheets(man, ["2"])
    cov = numeral_coverage(nums, text, refs, assigns, numeral_sightings(man))
    assert cov.drawn_not_recited == []                    # 140 resolved, not an anomaly
    assert cov.likely_misreads and cov.likely_misreads[0]["read_as"] == "140"
    assert cov.likely_misreads[0]["actually"] == "14a"


def test_drop_fragment_hits_cross_filters_recovered_hits():
    """Fresh hits check against EACH OTHER: tiles re-reading "84" also emit a bare
    "4" at the same spot; the longer label wins. A distant "4" survives."""
    from cairn.figures_map import drop_fragment_hits
    hits = [
        {"numeral": "4", "x": 0.428, "y": 0.501, "confidence": 1.0},   # inside 84's box
        {"numeral": "84", "x": 0.416, "y": 0.499, "confidence": 1.0},
        {"numeral": "4", "x": 0.100, "y": 0.100, "confidence": 1.0},   # elsewhere — real
    ]
    kept = {(h["numeral"], h["x"]) for h in drop_fragment_hits(hits)}
    assert kept == {("84", 0.416), ("4", 0.100)}


def test_sub_figure_parent_from_the_caption():
    """View markers sit ON the parent figure — "FIGS. 3 A-C are …views of the module
    of FIG. 2" names it inside the caption sentence (Julian: 'A was on FIG 2')."""
    from cairn.figures_map import sub_figure_parent
    from cairn.patents import figure_references
    text = ("FIGS. 3 A-C are respective right, left and rear views of the module "
            "of FIG. 2; FIG. 4 is a perspective view of a separator.")
    refs = figure_references(text)
    assert sub_figure_parent(text, "3", refs) == "2"      # the caption's parent
    # a caption naming NO parent → None (searched nowhere, not everywhere)
    text2 = "FIGS. 7 A-B are schematic views of the assembly. FIG. 8 is a chart."
    refs2 = figure_references(text2)
    assert sub_figure_parent(text2, "7", refs2) is None


def test_manual_annotation_sidecar_merges_with_human_provenance(tmp_path):
    """The human/visual confirmation channel: a reviewer-confirmed mark the OCR
    engine is blind to (the FIG-2 view-marker "A" — Vision detects nothing at any
    scale/API) enters via figures/manual_annotations.json with method:"human",
    distinct provenance, and full downstream behavior (sighting, box, coverage)."""
    import json as _json

    from cairn.figures_map import load_manifest, numeral_sightings
    fig_dir = tmp_path / "figures"
    fig_dir.mkdir()
    (fig_dir / "ocr_manifest.json").write_text(_json.dumps(
        {"pages": [{"page": 3, "file": "p.png", "fig_labels": [], "sheet_id": None,
                    "numerals": []}]}))
    (fig_dir / "manual_annotations.json").write_text(_json.dumps(
        [{"numeral": "A", "page": 3, "x": 0.84, "y": 0.19, "w": 0.03, "h": 0.02,
          "note": "view marker", "by": "reviewer", "date": "2026-07-22"}]))
    store_dir = tmp_path / "store"
    m = load_manifest(store_dir)
    s = numeral_sightings(m)
    assert [(x.numeral, x.page, x.method) for x in s] == [("A", 3, "human")]
    assert s[0].bbox == (0.84, 0.19, 0.03, 0.02)
    assert s[0].confidence == 1.0


def test_tesseract_tsv_converts_to_common_observations():
    """Engine converters normalize everything to ONE observation format: pixel
    top-left boxes → normalized bottom-left; conf 0-100 → 0-1; -1 rows skipped."""
    from cairn.figures_map import tesseract_tsv_to_observations
    tsv = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
           "left\ttop\twidth\theight\tconf\ttext\n"
           "5\t1\t1\t1\t1\t1\t100\t50\t40\t20\t96.5\t64\n"
           "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t-1\t\n")
    obs = tesseract_tsv_to_observations(tsv, 1000, 1000)
    assert len(obs) == 1
    o = obs[0]
    assert o["text"] == "64" and o["confidence"] == 0.965
    assert o["x"] == 0.1 and o["w"] == 0.04 and o["h"] == 0.02
    assert o["y"] == 0.93                                 # bottom-left flip (rounded)


def test_rapidocr_result_converts_to_common_observations():
    from cairn.figures_map import rapidocr_result_to_observations
    result = [([[100, 50], [140, 50], [140, 70], [100, 70]], "12a", 0.88)]
    o = rapidocr_result_to_observations(result, 1000, 1000)[0]
    assert o["text"] == "12a" and o["confidence"] == 0.88
    assert o["x"] == 0.1 and o["w"] == 0.04 and o["y"] == 0.93


def test_merge_same_spot_numerals_corroborates_across_engines():
    """The same label at the same spot from two engines is ONE mark with union'd
    engine provenance (corroboration); different spots stay separate instances."""
    from cairn.figures_map import merge_same_spot_numerals
    merged = merge_same_spot_numerals([
        {"numeral": "12", "x": 0.50, "y": 0.30, "confidence": 0.9, "engine": "vision"},
        {"numeral": "12", "x": 0.505, "y": 0.302, "confidence": 0.7, "engine": "tesseract"},
        {"numeral": "12", "x": 0.80, "y": 0.30, "confidence": 1.0, "engine": "rapidocr"},
    ])
    by_x = {m["x"]: m for m in merged}
    assert len(merged) == 2                               # two real instances
    assert by_x[0.50]["engines"] == ["tesseract", "vision"]   # corroborated
    assert by_x[0.50]["confidence"] == 0.9                    # best read kept
    assert by_x[0.80]["engines"] == ["rapidocr"]


def test_sub_figure_caption_is_not_a_numeral():
    """Patents write reference numerals with a LOWERCASE suffix ("12a") and
    sub-figures with an UPPERCASE one ("FIG. 3A"), so a digit run followed by an
    uppercase letter is a caption fragment. This pins the discriminator the OCR
    token pattern relies on (audit found bare '3' leaking from '3A'/'3C' reads)."""
    import re
    digit_run = re.compile(r"(?<![A-Za-z0-9])(\d{1,3}[a-z]?)(?![\dA-Za-z])")
    assert digit_run.findall("12a") == ["12a"]     # real numeral, lowercase suffix
    assert digit_run.findall("3A") == []           # sub-figure caption fragment
    assert digit_run.findall("3C") == []
    assert digit_run.findall("the valve 34.") == ["34"]


def test_same_spot_conflict_resolves_toward_the_text_tied_reading():
    """Julian's case: engines read ONE mark two ways ("58" vs "38" at the same
    position on FIG 2). The text ties 58 to that figure, so 38 is reported as its
    misread — and 38 leaves the drawn-not-recited anomaly list."""
    from cairn.figures_map import numeral_coverage
    from cairn.patents import Numeral, figure_references
    man = {"pages": [{"page": 3, "file": "p.png",
                      "fig_labels": [{"fig": "2", "confidence": 1.0, "x": 0.5, "y": 0.9}],
                      "sheet_id": None,
                      "numerals": [
                          {"numeral": "58", "source_text": "58", "confidence": 0.67,
                           "x": 0.591, "y": 0.382, "w": 0.027, "h": 0.02},
                          {"numeral": "38", "source_text": "38", "confidence": 0.81,
                           "x": 0.594, "y": 0.384, "w": 0.020, "h": 0.02},
                      ]}]}
    text = "Referring to FIG. 2, the outlet pipes 56, 58 feed the manifold."
    cov = numeral_coverage([Numeral("58", "outlet pipe", 0, 1)], text,
                           figure_references(text), fig_to_sheets(man, ["2"]),
                           numeral_sightings(man))
    mm = {m["read_as"]: m for m in cov.likely_misreads}
    assert "38" in mm and mm["38"]["actually"] == "58"
    assert not mm["38"].get("unresolved")          # text evidence decided it
    assert "38" not in cov.drawn_not_recited       # no longer a bare anomaly


def test_same_spot_conflict_stays_unresolved_without_text_evidence():
    """On a sub-figure the spec ties no numerals to (FIG 3C shares a caption), a
    disagreement cannot be RESOLVED — it must still be REPORTED for a reviewer."""
    from cairn.figures_map import numeral_coverage
    from cairn.patents import figure_references
    man = {"pages": [{"page": 6, "file": "p.png",
                      "fig_labels": [{"fig": "3C", "confidence": 1.0, "x": 0.5, "y": 0.9}],
                      "sheet_id": None,
                      "numerals": [
                          {"numeral": "54", "source_text": "54", "confidence": 0.63,
                           "x": 0.582, "y": 0.330, "w": 0.025, "h": 0.02},
                          {"numeral": "34", "source_text": "34", "confidence": 0.72,
                           "x": 0.585, "y": 0.331, "w": 0.021, "h": 0.02},
                      ]}]}
    text = "FIGS. 3 A-C are respective views of the module of FIG. 2."
    cov = numeral_coverage([], text, figure_references(text),
                           fig_to_sheets(man, ["3C"]), numeral_sightings(man))
    unres = [m for m in cov.likely_misreads if m.get("unresolved")]
    assert unres and {unres[0]["read_as"], unres[0]["actually"]} == {"34", "54"}
    assert "NOT resolved" in unres[0]["message"]


def test_sub_ten_numerals_are_not_locatable_by_policy():
    """D30: sub-10 numerals are recited (element + figure) but never LOCATED — a
    one-stroke glyph beside a leader line is indistinguishable from line art, and
    the sightings were garbage (the box for "2" landed on the word GRAYWATER).
    Non-numeric labels stay locatable: they are multi-stroke and read reliably."""
    from cairn.figures_map import is_locatable
    assert not any(is_locatable(str(n)) for n in range(1, 10))
    assert is_locatable("10") and is_locatable("12a") and is_locatable("89")
    assert is_locatable("STM") and is_locatable("CL") and is_locatable("D1")
    assert is_locatable("A")                      # view markers are located fine


def test_sub_ten_absence_is_not_reported_as_an_ocr_miss():
    """A label we never look for must not appear as recited-not-drawn — that would
    be a false anomaly (we abstained on position by policy, not by failure)."""
    from cairn.figures_map import numeral_coverage
    from cairn.patents import Numeral, figure_references
    man = {"pages": [{"page": 2, "file": "p.png",
                      "fig_labels": [{"fig": "1", "confidence": 1.0, "x": 0.5, "y": 0.9}],
                      "sheet_id": None, "numerals": []}]}
    text = "As shown in FIG. 1, the toilet 2 and the separator 10 are connected."
    cov = numeral_coverage([Numeral("2", "toilet", 0, 1), Numeral("10", "separator", 2, 3)],
                           text, figure_references(text), fig_to_sheets(man, ["1"]),
                           numeral_sightings(man))
    assert "2" not in cov.recited_not_drawn        # policy, not a miss
    assert "10" in cov.recited_not_drawn           # genuinely not located


def test_unrotate_observation_round_trips():
    """D31: sheets printed sideways must be OCR'd rotated and mapped back. Validated
    against known controls on US5447630A FIG 1 (mean error 0.002 in both axes); this
    pins the algebra. 270° CCW: x→1-y-h, y→x, and w/h swap."""
    from cairn.figures_map import unrotate_observation
    o = {"text": "33", "confidence": 1.0, "x": 0.20, "y": 0.60, "w": 0.03, "h": 0.02}
    r = unrotate_observation(o, 270)
    assert (r["x"], r["y"], r["w"], r["h"]) == (1 - 0.60 - 0.02, 0.20, 0.02, 0.03)
    assert r["text"] == "33" and r["confidence"] == 1.0        # payload preserved
    b = unrotate_observation(o, 90)
    assert (b["x"], b["y"], b["w"], b["h"]) == (0.60, 1 - 0.20 - 0.03, 0.02, 0.03)
    assert unrotate_observation(o, 0) == o                      # upright is identity


def test_unrotate_270_and_90_are_inverse_on_the_axes():
    """A 270° map followed by a 90° map returns the original box (the two rotations
    compose to identity), which is the invariant that keeps boxes landing right."""
    from cairn.figures_map import unrotate_observation
    o = {"text": "x", "confidence": 1.0, "x": 0.31, "y": 0.42, "w": 0.05, "h": 0.02}
    there = unrotate_observation(o, 270)
    back = unrotate_observation(there, 90)
    assert (round(back["x"], 4), round(back["y"], 4)) == (o["x"], o["y"])
    assert (back["w"], back["h"]) == (o["w"], o["h"])


def test_upright_reads_are_never_gated():
    """D32: the union across rotations may only ADD. Over-filtering has bitten this
    pipeline repeatedly (the >=10 floor, the >=2-mention floor), so a label read
    upright is admitted whatever the spec says and however few engines saw it."""
    from cairn.figures_map import gate_rotated_numerals
    up = {"numeral": "77", "angles": [0], "engines": ["vision"]}
    assert gate_rotated_numerals([up], recited=set()) == [up]   # unknown to spec, kept


def test_rotated_only_reads_need_corroboration():
    """D32: a label seen ONLY on a rotated pass is admitted on spec recital or on
    cross-engine agreement, and rejected when it has neither."""
    from cairn.figures_map import gate_rotated_numerals
    def n(label, angles, engines):
        return {"numeral": label, "angles": angles, "engines": engines}
    kept = gate_rotated_numerals([
        n("38", [90, 270], ["tesseract"]),           # spec recites it
        n("33", [90], ["vision", "rapidocr"]),       # off-spec but two engines agree
        n("607", [90], ["vision"]),                  # neither → artifact
    ], recited={"38"})
    assert [k["numeral"] for k in kept] == ["38", "33"]
    assert [k["corroboration"] for k in kept] == ["spec", "cross-engine"]


def test_upside_down_is_held_to_cross_engine_only():
    """D32: 180° is the 6<->9 artifact generator (FIG 4's real 86 produced a phantom
    98; FIG 5's real 98 produced a phantom 86) and no printed sheet is inverted. Spec
    recital cannot filter those — BOTH members of a 6/9 pair are usually recited — so
    at 180° alone, spec recital is not enough."""
    from cairn.figures_map import gate_rotated_numerals
    recited = {"86", "98"}
    phantom = {"numeral": "98", "angles": [180], "engines": ["tesseract"]}
    assert gate_rotated_numerals([phantom], recited) == []       # spec alone: rejected
    two = {"numeral": "98", "angles": [180], "engines": ["tesseract", "vision"]}
    assert len(gate_rotated_numerals([two], recited)) == 1       # cross-engine: admitted
    # ...and 180° alongside a physically plausible angle is fine on spec alone.
    sideways = {"numeral": "98", "angles": [180, 270], "engines": ["tesseract"]}
    assert len(gate_rotated_numerals([sideways], recited)) == 1


def test_raster_drift_is_refused(tmp_path):
    """D34: `image_sha256` had exactly one consumer — the line that wrote it. Every box
    is a NORMALIZED fraction, so a re-fetched or re-cropped sheet still resolves every
    box, silently, onto a different raster. That is the wrong-place class."""
    import hashlib
    import json as _json

    import pytest

    from cairn.figures_map import RasterDrift, verify_raster_binding
    figs = tmp_path / "figures"
    figs.mkdir()
    sheet = figs / "drawings-page-2.png"
    sheet.write_bytes(b"original raster")
    m = {"pages": [{"file": sheet.name, "page": 2,
                    "image_sha256": hashlib.sha256(b"original raster").hexdigest()}]}
    verify_raster_binding(m, figs)                      # matching bytes: silent
    sheet.write_bytes(b"a re-fetched, re-cropped raster")
    with pytest.raises(RasterDrift, match="changed since OCR"):
        verify_raster_binding(m, figs)
    # The manifest is portable; the sheets are gitignored client material, so an
    # ABSENT sheet is not drift — only a mismatch is.
    sheet.unlink()
    verify_raster_binding(m, figs)
    _json.dumps(m)                                       # manifest stays serialisable


def test_a_dead_engine_is_refused_not_recorded_as_zero():
    """D34 / L0009 installed in code. A sandbox once made /tmp unreadable to spawned
    binaries: Tesseract failed, its error went to stderr, the harness read stdout and
    checked neither — so a dead engine was indistinguishable from a diligent engine
    finding nothing, and we concluded Tesseract was blind to this corpus. Silence is
    the danger: a broken instrument reads exactly like a clean sheet."""
    import subprocess
    import sys
    from pathlib import Path

    import pytest
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from ocr_patent_figures import EngineFailure, _assert_engine_ran

    def proc(rc, out, err):
        return subprocess.CompletedProcess(["tesseract"], rc, out, err)

    p = Path("drawings-page-2.png")
    with pytest.raises(EngineFailure, match="exited 1"):
        _assert_engine_ran("tesseract", proc(1, b"", b"cannot read input"), p)
    with pytest.raises(EngineFailure, match="no output"):
        _assert_engine_ran("tesseract", proc(0, b"  \n", b"Error in pixReadStream"), p)
    _assert_engine_ran("tesseract", proc(0, b"level\tconf\n5\t88\n", b""), p)   # alive
    # A tile of blank drawing legitimately has no text, so there the exit code is the
    # only signal available — an empty read must NOT fail.
    _assert_engine_ran("tesseract", proc(0, b"", b""), p, require_output=False)


def test_strobogrammatic_transform():
    """D36: rotation reverses left-to-right order as well as mapping each digit, so
    "86" reads "98" and "106" reads "901" — the two phantoms observed on US5447630A."""
    from cairn.figures_map import strobogrammatic
    assert strobogrammatic("86") == "98"
    assert strobogrammatic("98") == "86"
    assert strobogrammatic("106") == "901"
    assert strobogrammatic("88") == "88"            # self-inverse
    assert strobogrammatic("12a") is None           # suffixed: not digits
    assert strobogrammatic("34") is None            # 3/4 do not invert legibly


def test_a_180_read_over_an_upright_mark_is_the_same_ink():
    """D36 (Julian's inversion test): a phantom is not a second mark, it is one mark
    read twice. Un-rotation puts it at the SAME page position as its upright source,
    and its label is that source's strobogrammatic inverse — position coincidence plus
    inverse label is proof of double-reading, not evidence of it."""
    from cairn.figures_map import drop_strobogrammatic_twins
    real = {"numeral": "86", "angles": [0], "engines": ["vision"], "x": 0.598, "y": 0.314}
    phantom = {"numeral": "98", "angles": [180], "engines": ["vision", "tesseract"],
               "x": 0.599, "y": 0.315}
    kept = drop_strobogrammatic_twins([real, phantom], [real])
    assert [k["numeral"] for k in kept] == ["86"]

    # It catches what corroboration cannot: the phantom above was read by TWO engines.
    # Engines fed the same inverted ink agree with each other, so cross-engine
    # agreement is no defence against a defect that lives in the pixels.
    far = {**phantom, "x": 0.20, "y": 0.80}          # same label, elsewhere: a real mark
    assert len(drop_strobogrammatic_twins([real, far], [real])) == 2
    upright_too = {**phantom, "angles": [0, 180]}     # legible upright: never dropped
    assert len(drop_strobogrammatic_twins([real, upright_too], [real])) == 2


def test_a_correction_replaces_the_mark_it_corrects(tmp_path):
    """D69: a correction is a refutation plus an assertion, and both halves must land.

    `apply_adjudications` only ever APPENDED the corrected mark, so correcting a
    misread "14a" to "12A" left both on the sheet — the phantom the reviewer had just
    rejected, sitting beside the fix. The reconciliation went on reporting the phantom,
    which means the reviewer's correction made the record worse than leaving it alone.
    """
    from cairn.adjudication import Adjudication, AdjudicationLog
    from cairn.figures_map import apply_adjudications

    log = AdjudicationLog(tmp_path / "adjudications.jsonl")
    log.append(Adjudication(
        adj_id="a::correct::2026-08-15", kind="correct", target_kind="figure-numeral",
        target={"page": 2, "numeral": "14a", "x": 0.5, "y": 0.3},
        value={"numeral": "12A", "x": 0.5, "y": 0.3, "w": 0.02, "h": 0.015},
        by="J. Smith", on="2026-08-15", note="misread"))
    man = {"pages": [{"page": 2, "numerals": [
        {"numeral": "14a", "x": 0.5, "y": 0.3, "w": 0.02, "h": 0.015,
         "confidence": 0.7, "engines": ["tesseract"]}]}]}

    labels = [n["numeral"] for n in apply_adjudications(man, tmp_path)["pages"][0]["numerals"]]
    assert labels == ["12A"], "the corrected mark must not survive alongside its fix"


def test_a_refutation_spares_the_same_numeral_elsewhere_on_the_sheet(tmp_path):
    """One numeral legitimately appears several times on a sheet, so position is part
    of a mark's identity. Refuting the phantom must not delete the real one."""
    from cairn.adjudication import Adjudication, AdjudicationLog
    from cairn.figures_map import apply_adjudications

    log = AdjudicationLog(tmp_path / "adjudications.jsonl")
    log.append(Adjudication(
        adj_id="b::refute::2026-08-15", kind="refute", target_kind="figure-numeral",
        target={"page": 2, "numeral": "12", "x": 0.10, "y": 0.10},
        by="J. Smith", on="2026-08-15", note="not on the sheet"))
    man = {"pages": [{"page": 2, "numerals": [
        {"numeral": "12", "x": 0.10, "y": 0.10, "w": 0.02, "h": 0.015, "confidence": 0.4},
        {"numeral": "12", "x": 0.80, "y": 0.70, "w": 0.02, "h": 0.015, "confidence": 1.0}]}]}

    left = apply_adjudications(man, tmp_path)["pages"][0]["numerals"]
    assert len(left) == 1 and left[0]["x"] == 0.80
