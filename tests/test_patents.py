"""Standing tests for the patent claim model (PE-1, first increment).

Deterministic structural parsing over the shared canonical text — no model. Uses a
synthetic sample patent so it is hermetic and free of confidentiality/copyright.
"""

from pathlib import Path

from cairn.ingest import DocumentStore
from cairn.ingest.files import ingest_paths
from cairn.patents import parse_claims
from cairn.spans import SpanStore

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "corpus" / "samples" / "sample_patent.txt"


def _text() -> str:
    return SAMPLE.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_parses_claims_with_dependency():
    claims = parse_claims(_text())
    assert [c.number for c in claims] == [1, 2, 3, 4, 5]
    assert [c.kind for c in claims] == [
        "independent", "dependent", "dependent", "independent", "dependent",
    ]
    assert [c.depends_on for c in claims] == [None, 1, 2, None, 4]


def test_claim_offsets_are_self_addressable():
    text = _text()
    claims = parse_claims(text)
    for c in claims:
        assert text[c.char_start:c.char_end] == c.text     # offsets are exact
        assert c.text.startswith(f"{c.number}.")           # starts at the claim number


def test_claim_spans_resolve_through_the_span_store(tmp_path):
    """Builds on the shared engine: each claim is a real, hash-verified span (I3)."""
    store_dir = tmp_path / "store"
    ingest_paths([str(SAMPLE)], store_dir, kind="patent")
    store = SpanStore.from_store(DocumentStore(store_dir))
    doc = SAMPLE.stem
    text = store.get_document(doc)
    for c in parse_claims(text):
        assert store.get_span(doc, c.char_start, c.char_end) == c.text


def test_no_claims_section_returns_empty():
    assert parse_claims("A document with no claims section at all.") == []


def test_decompose_independent_claim_into_limitations():
    from cairn.patents import decompose_claim
    claims = parse_claims(_text())
    lims = decompose_claim(claims[0])               # claim 1: comprising + 2 semicolons
    assert [lim.text for lim in lims] == [
        "a housing",
        "a sprocket coupled to the housing",
        "a controller configured to rotate the sprocket based on a measured temperature",
    ]
    text = _text()
    for lim in lims:                                # each limitation is self-addressable
        assert text[lim.char_start:lim.char_end] == lim.text


def test_dependent_wherein_is_one_limitation():
    from cairn.patents import decompose_claim
    claims = parse_claims(_text())
    lims = decompose_claim(claims[1])               # "...wherein the sprocket comprises titanium"
    assert len(lims) == 1
    assert lims[0].text == "the sprocket comprises titanium"


def test_limitations_resolve_through_the_span_store(tmp_path):
    from cairn.patents import decompose_claim
    store_dir = tmp_path / "store"
    ingest_paths([str(SAMPLE)], store_dir, kind="patent")
    store = SpanStore.from_store(DocumentStore(store_dir))
    doc = SAMPLE.stem
    c1 = parse_claims(store.get_document(doc))[0]
    for lim in decompose_claim(c1):
        assert store.get_span(doc, lim.char_start, lim.char_end) == lim.text


def test_parse_paragraphs_uses_native_numbering():
    from cairn.patents import parse_paragraphs
    paras = parse_paragraphs(_text())                       # synthetic has [0001]–[0006]
    assert [p.label for p in paras] == ["[0001]", "[0002]", "[0003]",
                                        "[0004]", "[0005]", "[0006]"]
    text = _text()
    for p in paras:                                         # each is self-addressable
        assert text[p.char_start:p.char_end] == p.text
    assert paras[0].text.startswith("[0001]")
    assert "claimed" not in " ".join(p.text for p in paras)  # claims excluded


def test_paragraphs_resolve_through_the_span_store(tmp_path):
    from cairn.patents import parse_paragraphs
    store_dir = tmp_path / "store"
    ingest_paths([str(SAMPLE)], store_dir, kind="patent")
    store = SpanStore.from_store(DocumentStore(store_dir))
    doc = SAMPLE.stem
    for p in parse_paragraphs(store.get_document(doc)):
        assert store.get_span(doc, p.char_start, p.char_end) == p.text


def test_support_mapping_links_limitation_to_spec_paragraph():
    """PE-3: claim 2's titanium limitation maps to the spec paragraph that describes it."""
    from cairn.patents import map_claim_support, parse_paragraphs
    text = _text()
    claims = parse_claims(text)
    paras = parse_paragraphs(text)
    mapping = dict((lim.text, edges)
                   for lim, edges in map_claim_support(claims[1], paras, SAMPLE.stem))
    edges = mapping["the sprocket comprises titanium"]
    assert edges, "expected support to be located"
    assert edges[0].paragraph_label == "[0005]"          # the titanium/aluminum paragraph
    assert edges[0].edge_type == "CLAIM_LIMITATION→SPEC_SUPPORT"


def test_support_edges_are_addressable(tmp_path):
    from cairn.patents import map_claim_support, parse_paragraphs
    store_dir = tmp_path / "store"
    ingest_paths([str(SAMPLE)], store_dir, kind="patent")
    store = SpanStore.from_store(DocumentStore(store_dir))
    doc = SAMPLE.stem
    text = store.get_document(doc)
    c1 = parse_claims(text)[0]
    for _lim, edges in map_claim_support(c1, parse_paragraphs(text), doc):
        for e in edges:                                  # each edge points at a real span
            assert store.get_span(doc, e.char_start, e.char_end)


def test_dependency_integrity_clean_patent_has_no_issues():
    from cairn.patents import check_dependencies
    assert check_dependencies(parse_claims(_text())) == []   # synthetic is well-formed


def test_dependency_integrity_flags_missing_and_forward_refs():
    from cairn.patents import Claim, check_dependencies
    claims = [
        Claim(1, "1. A device.", 0, 12, "independent", None),
        Claim(2, "2. The device of claim 9, …", 13, 40, "dependent", 9),    # missing
        Claim(3, "3. The device of claim 5, …", 41, 68, "dependent", 5),    # forward (5 exists)
        Claim(5, "5. The device of claim 1, …", 69, 96, "dependent", 1),    # ok
    ]
    issues = check_dependencies(claims)
    assert {i.claim_number for i in issues} == {2, 3}
    assert "does not exist" in next(i.message for i in issues if i.claim_number == 2)
    assert "not an earlier claim" in next(i.message for i in issues if i.claim_number == 3)


# --- PE-4: front matter + effective filing + regime flag ---


def test_front_matter_parses_the_synthetic_fixture():
    from cairn.patents import effective_filing, parse_front_matter, regime_flag
    fm = parse_front_matter(_text())
    assert fm.application_number == "17/000,000"
    assert fm.filed == "Mar. 15, 2021"
    assert any("Jane Smith" in i for i in fm.inventors)
    assert fm.priority_claims and "62/900,000" in fm.priority_claims[0]
    # effective filing = the PROVISIONAL's date (earlier than filing)
    src, d = effective_filing(fm)
    assert d == (2020, 3, 20) and "62/900,000" in src
    rf = regime_flag(fm)
    assert rf["flag"] == "AIA" and rf["effective_filing_date"] == "2020-03-20"
    assert "professional determination" in rf["note"]     # the D10 boundary, stated


def test_front_matter_parses_the_real_patent(tmp_path):
    import pathlib

    from cairn.patents import parse_front_matter, regime_flag
    real = pathlib.Path("corpus/engagements/US5447630A/US5447630A.txt")
    if not real.exists():
        import pytest as _pytest
        _pytest.skip("engagement corpus not present (local-only)")
    fm = parse_front_matter(real.read_text(encoding="utf-8"))
    assert fm.filed == "Apr. 28, 1993"
    assert fm.date_of_patent == "Sep. 5, 1995"
    assert fm.inventors == ["John M. Rummler"]
    assert fm.application_number == "08/053,402"
    rf = regime_flag(fm)
    assert rf["flag"] == "pre-AIA" and rf["effective_filing_date"] == "1993-04-28"


# --- RT-4 / PE-1 remainder: figures + references + reference numerals ---


def test_parse_figures_reads_the_drawings_captions():
    from cairn.patents import parse_figures
    text = _text()
    figs = parse_figures(text)
    assert [f.label for f in figs] == ["FIG. 1", "FIG. 2"]
    assert [f.number for f in figs] == ["1", "2"]
    assert figs[0].description.startswith("FIG. 1 is a perspective view")
    assert "cross-sectional view" in figs[1].description
    for f in figs:                                       # each caption self-addresses
        assert text[f.char_start:f.char_end] == f.description


def test_figure_references_carry_offsets():
    from cairn.patents import figure_references
    text = _text()
    refs = figure_references(text)
    assert {r.number for r in refs} == {"1", "2"}        # FIG.1 (×2) + FIG.2
    assert sum(r.number == "1" for r in refs) == 2       # caption + detailed-description
    for r in refs:                                       # the offset points at "FIG"
        assert text[r.char_start:].upper().startswith("FIG")


def test_reference_numerals_map_number_to_element():
    from cairn.patents import reference_numerals
    nums = {n.number: n.element for n in reference_numerals(_text())}
    assert set(nums) == {"100", "12", "14", "10"}                # the four ≥10 numerals
    assert "device" in nums["100"] and "housing" in nums["10"]
    assert "sprocket" in nums["12"] and "controller" in nums["14"]


def test_pointer_constructions_recite_a_numeral():
    """Defect D, made a standing test.

    "…as shown at 20" and "…indicated schematically at 43" are the idiomatic way a
    specification introduces a reference numeral, and both were invisible: the main
    pattern reads the words just before the numeral as the element, and there those
    words are "shown at" / "at", which _NOT_ELEMENT rejects — correctly, since that is
    the same guard that stops "at temperatures exceeding 500" binding a quantity.

    The cost was not a missing legend entry but a FALSE FINDING: with 20 absent from
    the text list, the drawing/spec reconciliation reported "numeral 20 appears on
    sheet 2 but is never recited in the specification — review", against a numeral
    plainly recited. On a locate-and-evidence tool a fabricated discrepancy is the
    expensive kind of wrong.
    """
    from cairn.patents import reference_numerals
    text = (
        "DESCRIPTION\n"
        'A ceramic particulate "scrubber" or filter is provided as shown at 20, such '
        "that airborne particulates are trapped.\n"
        "The dosing siphon, indicated schematically at 43, includes a float.\n"
        "The lower chamber has a maximum diameter of 20 inches.\n"
        "\nWhat is claimed is:\n\n1. A system.\n"
    )
    nums = {n.number: n.element for n in reference_numerals(text)}
    assert "20" in nums and "43" in nums
    assert "scrubber" in nums["20"], nums["20"]        # subject recovered across "as"
    assert nums["43"] == "dosing siphon"              # …and across the appositive comma
    for element in nums.values():                      # no lead-in leaks into an element
        assert not element.lower().startswith(("shown", "indicated", "as "))


def test_a_pointer_lead_in_never_binds_a_quantity():
    """The guard the pointer pass must not undo: a measurement is not a part. "20
    inches" and "500 W" stay out even when a pointer verb is nearby."""
    from cairn.patents import reference_numerals
    text = ("DESCRIPTION\nThe chamber, shown at 12, operates at temperatures "
            "exceeding 500 W and has a diameter of 20 inches.\n"
            "\nWhat is claimed is:\n\n1. A system.\n")
    nums = {n.number for n in reference_numerals(text)}
    assert "12" in nums
    assert "500" not in nums and "20" not in nums


def test_a_runaway_element_phrase_is_clipped_not_dropped():
    """A pointer whose subject is a whole clause yields a long phrase. It is truncated
    head-final, never discarded: a loose element is visible to a reviewer, a dropped
    numeral is not — the trade this module makes everywhere else."""
    from cairn.patents import reference_numerals
    text = ("DESCRIPTION\nLiquids exit the vessel and travel onward through the "
            "primary and secondary outlet manifolds designated at 56.\n"
            "\nWhat is claimed is:\n\n1. A system.\n")
    nums = {n.number: n.element for n in reference_numerals(text)}
    assert "56" in nums, "the numeral must survive a bad element phrase"
    assert len(nums["56"].split()) <= 8
    assert "manifolds" in nums["56"], "the head of the phrase is what is kept"


def test_reference_numerals_ignore_claim_noise_without_a_magnitude_floor():
    """Claim references ('of claim 1/2/4') are excluded STRUCTURALLY — by scanning the
    specification only — not by a minimum-numeral guess. The fixture's claims recite
    "of claim 1/2/4", none of which may appear as numerals."""
    from cairn.patents import parse_claims, reference_numerals
    text = _text()
    nums = {n.number: n.element for n in reference_numerals(text)}
    claim_starts = {c.char_start for c in parse_claims(text)}
    assert claim_starts, "fixture must have claims for this test to mean anything"
    for n in reference_numerals(text):                   # nothing sourced from the claims
        assert n.char_start < min(claim_starts)
    assert "claim" not in " ".join(nums.values())


def test_single_digit_reference_numerals_are_kept():
    """Regression (2026-07-08): a MIN_NUMERAL=10 floor silently deleted five REAL
    numerals from US5447630A ("bathtub or shower 1, toilet 2, … dishwasher 4 and
    clothes washer 5" — the FIG. 1 sources). "Numerals start at 10" is a folk rule,
    not a spec. Over-filtering deletes evidence invisibly; that is the worse failure."""
    import pathlib
    real = pathlib.Path("corpus/engagements/US5447630A/US5447630A.txt")
    if not real.exists():
        import pytest as _pytest
        _pytest.skip("engagement corpus not present (local-only)")
    from cairn.patents import reference_numerals
    nums = {n.number: n.element for n in reference_numerals(real.read_text(encoding="utf-8"))}
    assert "bathtub" in nums["1"] and "toilet" in nums["2"]
    assert "dishwasher" in nums["4"] and "clothes washer" in nums["5"]


def test_reference_numerals_reject_decimals_and_quantities():
    """A decimal ("measured as 0.24 mg/l") is not numeral 0; a quantity with a unit
    ("400 W", "60 degrees") is a measurement, not a pointer into a drawing."""
    from cairn.patents import reference_numerals
    sample = ("The chlorine residual has been measured as 0.24 mg/l in the tank 42. "
              "The magnetron 44 draws 400 W and the chamber holds 60 degrees.")
    nums = {n.number: n.element for n in reference_numerals(sample)}
    assert "0" not in nums                                # the decimal
    assert "400" not in nums and "60" not in nums           # quantities carrying units
    assert "tank" in nums["42"] and "magnetron" in nums["44"]


def test_figure_and_numeral_spans_resolve_through_the_span_store(tmp_path):
    from cairn.patents import parse_figures, reference_numerals
    store_dir = tmp_path / "store"
    ingest_paths([str(SAMPLE)], store_dir, kind="patent")
    store = SpanStore.from_store(DocumentStore(store_dir))
    doc = SAMPLE.stem
    text = store.get_document(doc)
    for f in parse_figures(text):
        assert store.get_span(doc, f.char_start, f.char_end) == f.description
    for n in reference_numerals(text):                   # the first-mention span is real
        assert store.get_span(doc, n.char_start, n.char_end)


def test_figures_validate_on_the_real_patent():
    """Sanity on US5447630A: the drawings block yields its figures, the ≥10 numerals
    include the known-good bindings (locate-only; not an exhaustive gate)."""
    import pathlib
    real = pathlib.Path("corpus/engagements/US5447630A/US5447630A.txt")
    if not real.exists():
        import pytest as _pytest
        _pytest.skip("engagement corpus not present (local-only)")
    from cairn.patents import parse_figures, reference_numerals
    t = real.read_text(encoding="utf-8")
    labels = [f.label for f in parse_figures(t)]
    # the caption block yields 1/2/4/5/6; sub-figures 3A-3C share one caption
    # ("FIGS. 3 A-C are respective right, left and rear views…") so they are emitted
    # from the references — every figure the text names must be listed & selectable,
    # and sorted so a sub-figure sits beside its parent.
    assert labels == ["FIG. 1", "FIG. 2", "FIG. 3A", "FIG. 3B", "FIG. 3C",
                      "FIG. 4", "FIG. 5", "FIG. 6"]
    nums = {n.number: n.element for n in reference_numerals(t)}
    assert "microwave reactor chamber" in nums["12"]
    assert "ceramic filter material" in nums["38"]
    assert "necked portion" in nums["89"]


def test_figure_reference_letter_range_expands():
    """Regression (D28 work): "FIGS. 3 A-C" (US5447630A's own caption style) must
    expand to 3A/3B/3C — an earlier regex read it as a phantom bare "3", which
    blocked the FIG→sheet elimination."""
    from cairn.patents import figure_references
    refs = figure_references("as shown in FIGS. 3 A-C are respective views; see FIG. 4.")
    assert [r.number for r in refs] == ["3A", "3B", "3C", "4"]
    assert "3" not in {r.number for r in refs}


def test_letter_suffixed_reference_numerals_are_distinct():
    """Julian's case: "12a" is a DIFFERENT part from "12". Collapsing the suffix
    reports 12 present and 12a missing — both wrong."""
    from cairn.patents import reference_numerals
    sample = ("the housing 12 supports a bracket 12a and a clamp 12b; "
              "the arm 14 carries a pin 14a.")
    nums = {n.number: n.element for n in reference_numerals(sample)}
    assert set(nums) == {"12", "12a", "12b", "14", "14a"}
    assert "bracket" in nums["12a"] and "housing" in nums["12"]


def test_numeral_key_orders_naturally():
    """9 < 10 < 12 < 12a < 12b, and a non-numeric label sorts after the numbered."""
    from cairn.patents import numeral_key
    labels = ["12b", "10", "STM", "9", "12", "12a"]
    assert sorted(labels, key=numeral_key) == ["9", "10", "12", "12a", "12b", "STM"]


def test_acronym_labels_are_candidates_from_the_spec():
    """Some drawings label a part with letters ("STM"), so the reference model can't
    be digits-only. Candidates come from the spec and need >=2 mentions; figure
    syntax and unit abbreviations are excluded. The DRAWINGS then adjudicate — a
    candidate that is really prose simply isn't found as a label."""
    from cairn.patents import acronym_labels
    spec = ("The solid treatment module STM feeds the liquid treatment module LTM. "
            "The STM houses a central processing unit CPU; the CPU drives it. "
            "The LTM is PVC. See FIG. 1 and FIGS. 2-3. Airflow is 300 CFM.")
    got = acronym_labels(spec)
    assert "STM" in got and "LTM" in got and "CPU" in got
    assert "FIG" not in got and "FIGS" not in got           # figure syntax
    assert "CFM" not in got                                 # unit abbreviation
    # "PVC" (a material) IS a candidate — deliberately permissive, because the
    # DRAWINGS adjudicate: it is never found as a label, at zero cost. The floor
    # that used to exclude it also deleted real single-mention labels (CZ/CL).
    assert "PVC" in got


def test_label_pattern_numeric_vs_acronym():
    import re

    from cairn.figures_map import label_pattern
    assert re.search(label_pattern("STM"), "the STM feeds")          # word-boundary
    assert not re.search(label_pattern("STM"), "the STMX feeds")     # not a prefix
    assert re.search(label_pattern("12"), "housing 12.")             # sentence-final ok
    assert not re.search(label_pattern("12"), "bracket 12a")         # not inside 12a
    assert not re.search(label_pattern("12"), "ratio 12.5")          # not a decimal


def test_list_sibling_numerals_inherit_the_head_element():
    """"pipes 56, 58" recites BOTH: 58 has no noun phrase of its own (it was
    invisible to the extractor — US5447630A's 58 appears only in lists)."""
    from cairn.patents import reference_numerals
    nums = {n.number: n.element for n in reference_numerals(
        "The liquid pipes 56, 58 then feed the drain manifolds 96, 98 below.")}
    assert "56" in nums and "58" in nums
    assert nums["58"] == nums["56"]                      # sibling inherits the element
    assert "96" in nums and "98" in nums


def test_acronym_labels_have_no_frequency_floor():
    """L0006 again (5th instance): a >=2-mention floor deleted REAL labels —
    US5447630A defines "CZ" (cooling zone) and "CL" (center line) exactly once each
    and both are plainly drawn. The DRAWINGS are the filter: a prose-only candidate
    is simply never found on a sheet and costs nothing."""
    from cairn.patents import acronym_labels
    spec = ("The shaded region CZ represents a cooling zone. "
            "CL designates the center line. See FIG. 1. Airflow is 300 CFM.")
    got = acronym_labels(spec)
    assert "CZ" in got and "CL" in got            # single-mention labels survive
    assert "FIG" not in got and "CFM" not in got  # syntax + units still excluded


def test_dimension_labels_are_their_own_class():
    """D1-D6 are letter-PREFIXED (so the numeral pattern rejects them — L0005) but
    they are real, spec-recited labels: "the respective dimensions D1-D6 can be as
    follows: D1 3.25\"…". They belong in the model as a distinct class."""
    from cairn.patents import dimension_labels, reference_numerals
    spec = ('CL designates the center line, and the respective dimensions D1-D6 can '
            'be as follows: D1 3.25" D2 1.50" D6 3.50". The valve 34 is shown.')
    dims = dimension_labels(spec)
    assert {"D1", "D2", "D6"} <= set(dims)
    nums = {n.number for n in reference_numerals(spec)}
    assert "1" not in nums and "2" not in nums   # D1/D2 must NOT pollute numerals
    assert "34" in nums


def test_element_phrase_may_end_in_punctuation():
    """"…garbage disposal) 3, dishwasher 4" recites 3 — a bracket between the noun
    and the numeral was hiding sub-10 labels entirely."""
    from cairn.patents import reference_numerals
    nums = {n.number for n in reference_numerals(
        "a sink (with a garbage disposal) 3, dishwasher 4 and clothes washer 5.")}
    assert {"3", "4", "5"} <= nums


def test_figures_sort_with_sub_figures_beside_their_parent():
    """3A/3B/3C must sit right after 2, not at the end (they are emitted from
    references, after the caption block, so the list needs a natural sort)."""
    from cairn.patents import numeral_key, parse_figures
    text = ("FIG. 1 is a schematic; FIG. 2 is a perspective view; FIGS. 3 A-C are "
            "respective views of FIG. 2; FIG. 4 is a separator; FIG. 10 is a chart.")
    assert [f.number for f in parse_figures(text)] == ["1", "2", "3A", "3B", "3C", "4", "10"]
    assert sorted(["12b", "3A", "2", "12"], key=numeral_key) == ["2", "3A", "12", "12b"]


def test_four_digit_and_uppercase_suffix_numerals_are_expressible():
    """D34: the extractor capped at three lowercase-suffixed digits, which broke two
    ways. The figure-keyed 1000-series (FIG. 10 -> 1000/1010) was unreadable, so on a
    post-2000 patent BOTH sides of the drawing/spec reconciliation come back empty and
    the coverage report reads clean over an empty map. Worse, "12A" fell through the
    lowercase-only suffix and matched as bare "12" — binding a DISTINCT part to its
    base numeral's span, on the path where grounding actually binds (I1)."""
    from cairn.patents import reference_numerals
    got = {n.number: n.element for n in
           reference_numerals("The controller 1002 drives the bus 1010.")}
    assert set(got) == {"1002", "1010"}

    got = {n.number for n in
           reference_numerals("The housing 12A supports the housing 12.")}
    assert got == {"12a", "12"}, "an uppercase suffix must not collapse into its base"


def test_quantities_are_not_bound_as_reference_numerals():
    """D34: "at temperatures exceeding 500" bound 500 as a part whose element phrase
    was "at temperatures exceeding". A part is never named "with" or "exceeding", so
    those join the function-word class that already blocks "at"/"of"/"between"."""
    from cairn.patents import reference_numerals
    text = ("The reactor operates at temperatures exceeding 500 and with 150 "
            "at temperatures below 220.")
    assert reference_numerals(text) == []


def test_every_extraction_site_shares_one_digit_cap():
    """D42: D34 widened the numeral cap to four digits at the HEAD pattern and left the
    list-sibling pattern at three, so "the pipes 1002, 1010" recited 1002 and silently
    dropped 1010. Four sites must agree (spec head, spec sibling, image, audit sweep);
    they now all interpolate `NUMERAL_DIGITS`, and this pins that they cannot diverge."""
    import re
    from pathlib import Path

    from cairn.patents import NUMERAL_DIGITS
    root = Path(__file__).resolve().parents[1]
    sites = ["src/cairn/patents.py", "scripts/ocr_patent_figures.py",
             "scripts/audit_sheet_labels.py"]
    for rel in sites:
        src = (root / rel).read_text()
        hard = re.findall(r"\\d\{1,(\d)\}\[a-z", src, re.IGNORECASE)
        assert not hard, f"{rel} hardcodes a digit cap {hard}; interpolate NUMERAL_DIGITS"
    assert NUMERAL_DIGITS == 4


def test_and_joined_list_siblings_are_recited():
    """D42: patents write "pipes 56, 58 and 60" — a comma-only sibling pattern drops the
    last element. The label must follow the conjunction IMMEDIATELY, so a following noun
    phrase is not mis-inherited."""
    from cairn.patents import reference_numerals
    assert [n.number for n in
            reference_numerals("The pipes 56, 58 and 60 carry flow.")] == ["56", "58", "60"]
    got = {n.number: n.element for n in
           reference_numerals("The pipe 56 and the valve 58 are shown.")}
    assert got["56"] == "pipe"
    assert got["58"] != "pipe", "a noun phrase after 'and' names its own element"


def test_range_captions_are_matched_so_the_caption_run_survives_them():
    """D43: `_FIG_CAPTION` required `FIG. N <verb>`, so a RANGE caption
    ("FIGS. 4A-4B illustrate…") could not match — "-4B" sits between the number and the
    verb. That cost twice: the caption was lost, AND the unmatched text inflated the gap
    to the next caption past `_CAPTION_GAP`, terminating the caption run early.

    On US8046721B2 this dropped FIG. 6, 9 and 10 — each recited three times — because the
    gap across the invisible 4A-4B and 5A-5D captions measured 450 against a 400 limit.
    Found by running the RT-6 corpus-fitting protocol on a second patent."""
    from cairn.patents import parse_figures
    text = (
        "FIG. 1 is a block diagram illustrating a portable electronic device. "
        "FIGS. 4A-4B illustrate the GUI display of a device in a lock state, according "
        "to some embodiments of the invention, at considerable length so that the prose "
        "between the previous caption and the next one comfortably exceeds the caption "
        "gap that terminates a caption run when a caption cannot be matched at all. "
        "FIG. 6 is a flow diagram illustrating a process for indicating progress."
    )
    got = [f.number for f in parse_figures(text)]
    assert "6" in got, "a plain caption after a range caption must survive"
    assert "4A" in got and "4B" in got
    assert got.index("1") < got.index("4A") < got.index("6")


def test_acronym_labels_over_generate_without_drawing_evidence():
    """RT-9: an executable statement of the contract, not a bug report.

    `acronym_labels` has no frequency floor ON PURPOSE (a real one-off like CZ or CL
    would be deleted by one), which makes the DRAWINGS the filter. Where no OCR'd sheets
    exist there is no filter at all. Measured on US8046721B2: 34 candidates including
    CDMA/GSM/CPU/IEEE and the section headings BRIEF and FIELD. This test pins that the
    output is candidates — so a future caller cannot mistake it for an assertion — and
    that intersecting with located sightings is what makes it safe."""
    from cairn.patents import acronym_labels
    spec = ("FIELD OF THE INVENTION. The device uses a CPU and a GSM radio with CDMA "
            "fallback, and the GUI is drawn by the CMOS controller. The cooling zone CZ "
            "is shown shaded.")
    candidates = acronym_labels(spec)
    assert "CZ" in candidates, "a genuine one-off label must survive (no frequency floor)"
    assert {"CPU", "GSM", "CDMA", "CMOS"} <= set(candidates), (
        "technology acronyms are NOT filtered out — that is the documented contract, "
        "and why the caller must adjudicate against the drawings")

    located = {"CZ"}                                  # what OCR actually found on a sheet
    assert [a for a in candidates if a in located] == ["CZ"]


def test_kind_code_is_stripped_for_any_form():
    """D45: `doc.rstrip("AB")` was fitted to US5447630A and silently does NOTHING to
    US8046721B2 — "B2" ends with a digit. The stem stayed "US8046721B2", every drawing
    URL missed, and the fetch reported "no drawing sheets found" as if the patent had
    none. A kind code is a letter optionally followed by a digit."""
    import re
    strip = lambda d: re.sub(r"[A-Z]\d?$", "", d)      # noqa: E731 — mirrors the fetcher
    assert strip("US5447630A") == "US5447630"
    assert strip("US8046721B2") == "US8046721"
    assert strip("US20050020A1") == "US20050020"
    assert strip("US1234567") == "US1234567"           # no kind code: unchanged


def test_figure_and_fig_are_the_same_caption():
    """D45: US5447630A abbreviates "FIG. 2"; US8046721B2 spells out "Figure 2", and the
    abbreviation-only pattern found NO caption on any of its 16 sheets."""
    import re
    pat = re.compile(r"\bFIG(?:URE)?S?\.?\s*(\d+[A-Z]?)", re.IGNORECASE)
    for s, want in (("FIG. 2", "2"), ("Figure 2", "2"), ("FIGS. 3A", "3A"),
                    ("Figures 4A", "4A"), ("FIG.6", "6")):
        m = pat.search(s)
        assert m and m.group(1).upper() == want, s
