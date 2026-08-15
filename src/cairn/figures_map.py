"""FIG→sheet and numeral→sheet mapping over the OCR manifest (RT-4/PE-2, D28).

The deterministic half of the OCR split: `scripts/ocr_patent_figures.py` runs
Apple-Vision OCR **once at ingestion** and freezes a hashed manifest; everything
here is a pure function over that manifest — same manifest, same answers (I6).
Nothing in this module (or anywhere at runtime) calls OCR.

Honesty rules (D21/D28), enforced in the data model:
- every mapping carries its **method** — `"ocr"` (a label read on the sheet) or
  `"elimination"` (exactly one known figure unassigned + exactly one sheet with a
  garbled/missing label) — and its OCR confidence where one exists;
- a numeral's sheet location is *"located by OCR"*, never a verified citation —
  the spec TEXT remains the only citable surface;
- cross-checks surface facts for review ("recited in the spec, not located on any
  sheet — OCR miss or drawing omission"), never conclusions (D10).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .patents import numeral_key

OCR = "ocr"
ELIMINATION = "elimination"

# How far a figure's "current context" carries in the spec text. Patent prose says
# "Referring now to FIG. 2, …" and then discusses that figure's parts for several
# paragraphs, so a numeral's governing figure is the nearest PRECEDING FIG reference,
# not one within a tight radius. Measured on US5447630A: at 500 chars the check failed
# to tie 14a/54/62/64/66 to FIG. 2 (numerals the spec plainly discusses under it, and
# which a reviewer spotted on the sheet); at 2000 all five tie correctly. Wider than
# that ties more numerals without recovering any more of them — so 2000 is where the
# evidence stops improving.
FIGURE_CONTEXT_WINDOW = 2000


HEADER_BAND = 0.88   # normalized y above this = the sheets' running header

# Sub-10 reference numerals are NOT located on the sheets (D30). This is a SIGHTING
# policy, not an extraction policy — the text side still recites them with their
# element and figure ("2 · toilet · FIG. 1"), because that part is reliable. What is
# unreliable is the IMAGE side: a one- or two-stroke glyph beside a leader line is
# indistinguishable from line art to every engine, and the "sightings" they produced
# were garbage (the box for "2" landed on the word GRAYWATER). Locating nothing is
# honest; boxing the wrong ink is not — so we assert the label and abstain on its
# position, which is the same discipline as the rest of the system.
MIN_LOCATABLE_NUMERAL = 10


def is_locatable(label: str) -> bool:
    """Whether we attempt to LOCATE this label on a drawing sheet (D30). Non-numeric
    labels (STM, CL, D1, A) are locatable — they are multi-stroke and read reliably."""
    return not (label.isdigit() and int(label) < MIN_LOCATABLE_NUMERAL)


# --- multi-engine OCR support (D29) ------------------------------------------------
# CAIRN runs on non-Mac systems too, and engines have COMPLEMENTARY blind spots
# (measured on US5447630A/FIG 2: Vision reads the view-marker B but is totally blind
# to A; Tesseract reads A in sparse/single-glyph mode but misses B; RapidOCR has the
# best whole-image recall — 24/30 labels vs Vision's ~18 — but reads neither letter).
# These pure converters normalize each engine's output into the ONE observation
# format (text, confidence 0..1, x/y/w/h normalized, origin bottom-left) so the
# frozen manifest and everything downstream stay engine-agnostic.

def unrotate_observation(o: dict, angle: int) -> dict:
    """Map an observation read on a ROTATED sheet back to the original frame (D31).

    Patent sheets are sometimes printed sideways (US5447630A's FIG. 1 fills a
    landscape page), and the engines read ISOLATED glyphs upright only — so those
    sheets must be OCR'd rotated and the coordinates mapped back, or the boxes land
    nowhere. (Dense text lines are orientation-robust: the running header "Sheet 1 of
    8" parses at all four angles, because a long line has language-model support a
    lone "33" on a leader line does not. That asymmetry is why rotation is a per-GLYPH
    property, not a per-page one — see D32.)

    `angle` is the CCW rotation applied before OCR (PIL's convention). Coordinates are
    normalized with a BOTTOM-left origin. For 270° CCW (= 90° CW) the derivation is
    x_orig = 1 - y - h, y_orig = x (NOT x - w — the box's leading edge in the rotated
    frame is already the bottom edge in the original, and subtracting the width
    shifted every box down by one glyph, ~0.02).
    """
    x, y, w, h = o["x"], o["y"], o["w"], o["h"]
    if angle % 360 == 270:
        nx, ny, nw, nh = 1 - y - h, x, h, w
    elif angle % 360 == 90:
        nx, ny, nw, nh = y, 1 - x - w, h, w
    elif angle % 360 == 180:
        nx, ny, nw, nh = 1 - x - w, 1 - y - h, w, h
    else:
        return dict(o)
    return {**o, "x": round(nx, 4), "y": round(ny, 4),
            "w": round(nw, 4), "h": round(nh, 4)}


def tesseract_tsv_to_observations(tsv: str, width: int, height: int) -> list[dict]:
    """Tesseract `tsv` output → common observations. Pixel boxes are TOP-left origin
    (flip y); conf is 0-100 with -1 on non-word rows (skipped)."""
    out = []
    lines = tsv.strip().split("\n")
    if not lines:
        return out
    head = lines[0].split("\t")
    idx = {k: i for i, k in enumerate(head)}
    for line in lines[1:]:
        f = line.split("\t")
        if len(f) != len(head):
            continue
        text = f[idx["text"]].strip()
        conf = float(f[idx["conf"]])
        if not text or conf < 0:
            continue
        left, top = int(f[idx["left"]]), int(f[idx["top"]])
        w_px, h_px = int(f[idx["width"]]), int(f[idx["height"]])
        out.append({
            "text": text, "confidence": round(conf / 100.0, 3),
            "x": round(left / width, 4), "y": round(1 - (top + h_px) / height, 4),
            "w": round(w_px / width, 4), "h": round(h_px / height, 4),
        })
    return out


def rapidocr_result_to_observations(result, width: int, height: int) -> list[dict]:
    """RapidOCR `(box_4pts_px_topleft, text, score)` entries → common observations."""
    out = []
    for box, text, conf in (result or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        out.append({
            "text": str(text), "confidence": round(float(conf), 3),
            "x": round(x0 / width, 4), "y": round(1 - y1 / height, 4),
            "w": round((x1 - x0) / width, 4), "h": round((y1 - y0) / height, 4),
        })
    return out


def merge_same_spot_numerals(numerals: list[dict], *, radius: float = 0.02) -> list[dict]:
    """Cross-engine dedupe for the manifest: the same label read at the same spot by
    several engines is ONE mark. Keeps the highest-confidence record and unions the
    contributing engines into `engines` — corroboration is provenance, not noise
    (two independent engines agreeing on a mark is stronger evidence than one)."""
    kept: list[dict] = []
    for n in sorted(numerals, key=lambda d: -d["confidence"]):
        dup = next((k for k in kept if k["numeral"] == n["numeral"]
                    and abs(k["x"] - n["x"]) < radius and abs(k["y"] - n["y"]) < radius), None)
        if dup is None:
            n = dict(n)
            n["engines"] = sorted(set(n.get("engines") or [n.get("engine", "unknown")]))
            # which rotations this mark was legible at — provenance for the D32 gate,
            # and the signal the review GUI shows as "read at 270°".
            n["angles"] = sorted(set(n.get("angles") or [n.get("angle", 0)]))
            n.pop("engine", None), n.pop("angle", None)
            kept.append(n)
        else:
            dup["engines"] = sorted(set(dup["engines"])
                                    | set(n.get("engines") or [n.get("engine", "unknown")]))
            dup["angles"] = sorted(set(dup["angles"])
                                   | set(n.get("angles") or [n.get("angle", 0)]))
    return kept



# Digits that stay legible when the page is turned upside down. Deliberately
# conservative — 2/5/7 invert plausibly in some typefaces and not others, and a wrong
# entry here DELETES a real label, which is the failure mode this repo keeps repeating.
_STROBOGRAMMATIC = {"0": "0", "1": "1", "6": "9", "8": "8", "9": "6"}


def strobogrammatic(label: str) -> str | None:
    """What `label` would read as if the same ink were rotated 180°, or None if it
    would not read as digits at all. The string REVERSES as well as mapping, because
    rotation reverses left-to-right order: "86" → "98", "106" → "901"."""
    if not label.isdigit():
        return None
    out = []
    for ch in reversed(label):
        if ch not in _STROBOGRAMMATIC:
            return None
        out.append(_STROBOGRAMMATIC[ch])
    return "".join(out)


def drop_strobogrammatic_twins(numerals: list[dict], upright: list[dict],
                               *, radius: float = 0.02) -> list[dict]:
    """Reject a rotated read that is the SAME INK as an upright read (D36, Julian).

    The mechanism, not a heuristic: a 180° phantom is not a second mark, it is one mark
    read twice. Because observations are un-rotated back into page coordinates, the
    phantom lands at the *same page position* as the upright read it came from — and
    its label is the upright label's strobogrammatic inverse. Position coincidence plus
    inverse label is therefore proof of double-reading, not evidence of it.

    Measured on US5447630A: 19 coincidences, including every phantom identified by hand
    (FIG 4's "98" over the real "86", FIG 5's "86" over the real "98", "901" over "106").

    This catches strictly more than the cross-engine bar it supplements: several
    phantoms were read by two or three engines, which is exactly what one would expect
    — engines fed the same inverted ink agree with each other. Corroboration cannot see
    a defect that lives in the pixels rather than in the models (the D31 lesson again),
    so both rules are kept: corroboration decides whether a mark is real, and this
    decides whether it is a *separate* mark.
    """
    kept = []
    for n in numerals:
        angles = n.get("angles") or [n.get("angle", 0)]
        inv = strobogrammatic(str(n["numeral"]))
        if 0 in angles or 180 not in angles or inv is None:
            kept.append(n)
            continue
        twin = any(str(u["numeral"]) == inv
                   and abs(u["x"] - n["x"]) < radius and abs(u["y"] - n["y"]) < radius
                   for u in upright)
        if not twin:
            kept.append(n)
    return kept


def gate_rotated_numerals(numerals: list[dict], recited: set[str]) -> list[dict]:
    """Admission rule for labels seen ONLY on a rotated pass (D32).

    Reading every sheet at 0/90/180/270 and unioning the results raises recall a lot
    (pick-one-angle loses labels on 7 of US5447630A's 8 sheets), but it also invites
    the rotational-symmetry artifact: upside down, 6 reads as 9 and "106" reads as
    "901". Those artifacts are indistinguishable from real labels by shape alone, so
    an angle-only find must be CORROBORATED before it is admitted:

      · the specification recites that numeral (text-guided — the same principle as
        the confirmation pass: the spec predicts, the sheet confirms), OR
      · two or more engines independently read it at the same spot (D29 — engines
        have complementary blind spots, so agreement is real evidence).

    UPSIDE DOWN (180°) IS HELD TO THE STRICTER BAR — cross-engine only. Two reasons,
    both measured on US5447630A:
      · No printed patent sheet is inverted. A sheet is portrait or landscape, so 90°
        and 270° are physically motivated in a way 180° is not.
      · 180° is precisely the rotational-symmetry generator: it turns 6 into 9. FIG 4's
        real "86" produced a phantom "98"; FIG 5's real "98" produced a phantom "86".
    Spec recital cannot filter those, because BOTH members of a 6/9 pair are usually
    recited — a 68-numeral spec "corroborates" almost any plausible two-digit artifact.
    So spec recital is necessary-but-weak evidence, and at the one angle that mass
    produces spec-shaped artifacts it is not enough on its own.

    Anything read upright (angle 0) is admitted as before: that is the primary pass,
    and gating it would re-introduce the over-filtering that has bitten this pipeline
    repeatedly (the >=10 floor, the >=2-mention floor). This gate only ever ADMITS
    labels the old pick-one-angle design could not see; it never removes an upright one.
    """
    out = []
    for n in numerals:
        angles = n.get("angles") or [n.get("angle", 0)]
        if 0 in angles:
            out.append(n)
            continue
        cross = len(n.get("engines") or []) >= 2
        if cross:
            out.append({**n, "corroboration": "cross-engine"})
        elif str(n["numeral"]) in recited and set(angles) != {180}:
            out.append({**n, "corroboration": "spec"})
    return out


def is_fragment(hit: dict, page: dict, *, radius: float = 0.025) -> bool:
    """A recovered token that sits ON TOP of a longer token containing it is a
    FRAGMENT, not a label: tiles cut "12b" and read "1"; "13" re-reads as "1J";
    "CL" (a centerline mark) yields "C". Checked against both the page's numeral
    records and its raw first-pass observations."""
    tok = str(hit["numeral"]).lower()

    def overlaps(rec: dict) -> bool:
        # box overlap on x (a long observation's CENTER can be far from a fragment
        # at its end — "FINAL PURIFIED EFFLUENT. 1"), radius band on y.
        x0, x1 = rec["x"] - radius, rec["x"] + rec.get("w", 0.0) + radius
        return x0 <= hit["x"] <= x1 and abs(rec["y"] - hit["y"]) < radius

    for n in page.get("numerals", []):
        lbl = str(n["numeral"]).lower()
        if lbl != tok and tok in lbl and overlaps(n):
            return True
    for o in page.get("observations", []):
        core = re.sub(r"[^A-Za-z0-9]", "", o["text"]).lower()
        if core != tok and tok in core and overlaps(o):
            return True
    return False


def letters_from_first_pass(page: dict, markers: list[str]) -> list[dict]:
    """A view-marker letter the WHOLE-IMAGE pass already read (tiles often can't —
    "B" reads at full view but vanishes in every tile) is reclassified from a raw
    observation into a sighting; nothing is re-OCR'd."""
    out = []
    have = {str(n["numeral"]) for n in page.get("numerals", [])}
    for o in page.get("observations", []):
        core = re.sub(r"[^A-Za-z0-9]", "", o["text"])
        if core in markers and core not in have and o["y"] < HEADER_BAND:
            out.append({"numeral": core, "source_text": o["text"],
                        "confidence": o["confidence"], "method": "text-guided",
                        "engine": o.get("engine", "unknown"),
                        "x": o["x"], "y": o["y"], "w": o["w"], "h": o["h"]})
    return out


def drop_fragment_hits(hits: list[dict]) -> list[dict]:
    """Cross-filter freshly recovered hits against EACH OTHER: a hit whose token is
    contained in a LONGER co-located hit is a fragment of it (tiles re-read "84" and
    a weaker candidate yields a bare "4" at the same spot). Longer labels win."""
    kept: list[dict] = []
    for h in sorted(hits, key=lambda d: -len(str(d["numeral"]))):
        tok = str(h["numeral"]).lower()
        clash = any(tok != str(k["numeral"]).lower() and tok in str(k["numeral"]).lower()
                    and abs(k["x"] - h["x"]) < 0.03 and abs(k["y"] - h["y"]) < 0.03
                    for k in kept)
        if not clash:
            kept.append(h)
    return kept


def sub_figure_parent(text: str, base: str, fig_refs) -> str | None:
    """The figure a sub-figure family's views are TAKEN OF — where its view markers
    physically sit. Derived from the family's own caption: "FIGS. 3 A-C are …views
    of the solid treatment module of FIG. 2" names the parent within the caption
    sentence. Returns None when the caption names no parent (then markers can't be
    localized and are searched nowhere — predicted-but-unplaceable, not guessed)."""
    fam = [r for r in fig_refs
           if r.number.startswith(base) and r.number[len(base):].isalpha()]
    if not fam:
        return None
    first = min(fam, key=lambda r: r.char_start)
    # sentence terminator, scanned AFTER the family reference; "FIG. "/"FIGS. " carry
    # a ". " of their own, so the abbreviation's period must not end the sentence.
    m = re.search(r";|(?<!FIG)(?<!FIGS)\.\s", text[first.char_end:first.char_end + 400])
    end = first.char_end + (m.start() if m else 400)
    for r in sorted(fig_refs, key=lambda r: r.char_start):
        if first.char_start < r.char_start <= end and not r.number.startswith(base):
            return r.number
    return None


def view_marker_letters(known_figs: list[str]) -> list[str]:
    """Single-letter view/section markers derived from sub-figure suffixes: if the
    patent has FIGS. 3A/3B/3C ("respective right, left and rear views of FIG. 2"),
    the letters A/B/C appear ON the parent drawing marking where each view is taken
    from. Derived from the figure list (text side), searched on the sheets with an
    exact-token rule — a lone letter is far too noisy to match as a substring."""
    return sorted({f[-1].upper() for f in known_figs if len(f) > 1 and f[-1].isalpha()})


def label_pattern(label: str) -> str:
    """Regex for a reference LABEL as a standalone token. A numeric label needs
    number-aware guards (no trailing digit/letter so "12" never fires inside "12a";
    no decimal "10.5"; a trailing comma is punctuation unless it is grouping
    "10,500"). An acronym label ("STM") just needs word boundaries."""
    if label[0].isdigit():
        return rf"(?<![\d.,]){re.escape(label)}(?![\da-z])(?!\.\d)(?!,\d)"
    return rf"\b{re.escape(label)}\b" 


@dataclass(frozen=True)
class SheetAssignment:
    fig: str                  # "1", "3A"
    page: int                 # drawings-page-N
    method: str               # OCR | ELIMINATION
    confidence: float | None  # Vision confidence of the label (None for elimination)


@dataclass(frozen=True)
class NumeralSighting:
    numeral: str      # a reference LABEL: "12", "12a", or an acronym
    page: int
    confidence: float
    source_text: str          # the raw OCR text the digits came from ("-82" → 82)
    # (x, y, w, h) normalized, origin bottom-left — for the confirmation box overlay:
    bbox: tuple[float, float, float, float] | None = None
    method: str = "first-pass"  # "first-pass" | "text-guided" (D28 confirmation pass)


class RasterDrift(RuntimeError):
    """A sheet's bytes no longer match the raster its boxes were measured against."""


def verify_raster_binding(manifest: dict, fig_dir: str | Path) -> None:
    """Re-hash each sheet and check it against the `image_sha256` frozen with it (D34).

    Until now that field had exactly ONE consumer in the whole tree: the line that
    wrote it. A hash nobody checks is decoration — and this one guards the assumption
    the whole figures view rests on, because every box is stored as a NORMALIZED
    fraction. Re-fetch or re-crop a sheet without re-OCRing and every fraction still
    resolves, silently, to a different place on a different raster. That is the
    wrong-place class: a confident box drawn over the wrong mark, which is exactly
    what CAIRN claims never to do. Absent bytes are not an error (the manifest is
    portable; the sheets are gitignored client material) — only a MISMATCH is.
    """
    fig_dir = Path(fig_dir)
    for page in manifest.get("pages", []):
        want = page.get("image_sha256")
        sheet = fig_dir / page["file"]
        if not want or not sheet.exists():
            continue
        got = hashlib.sha256(sheet.read_bytes()).hexdigest()
        if got != want:
            raise RasterDrift(
                f"{page['file']} changed since OCR (manifest {want[:12]}…, "
                f"file {got[:12]}…). Every box on this sheet is a normalized "
                f"fraction of the raster it was measured on, so they now point "
                f"somewhere else. Re-run scripts/ocr_patent_figures.py.")


def load_manifest(store_dir: str | Path) -> dict:
    """The frozen OCR manifest, merged with the reviewer's ADJUDICATIONS (D47).

    A human confirmation is an EVIDENCE SOURCE with its own provenance, never conflated
    with an OCR read: merged marks carry `method: "human"` plus who recorded them and
    when. They are the marks OCR cannot see at all — a lone view-marker glyph reads as
    line art to every engine, at every scale.

    Judgments come from the append-only, hash-chained `figures/adjudications.jsonl`
    (RT-7a). The previous home was a mutable JSON array, and it failed as that design
    must: a reviewer's confirmation of FIG. 2's "A" was replaced by a machine read and is
    unrecoverable. The legacy file is still read when the log is absent, so an
    un-migrated engagement keeps working — but it is read, never written.

    `refute` withdraws an OCR-located mark the reviewer says is not there. That is the
    only way anything is removed from the manifest view, and it takes a named human
    saying so on a dated record."""
    fig_dir = Path(store_dir).parent / "figures"
    manifest = json.loads((fig_dir / "ocr_manifest.json").read_text(encoding="utf-8"))
    verify_raster_binding(manifest, fig_dir)
    apply_adjudications(manifest, fig_dir)
    return manifest


# How near a judgment's coordinates must be to the mark it names. Deliberately the
# same 0.02 as `merge_same_spot_numerals`: both answer "are these the same mark?", and
# two different answers to one question is how a refutation misses its target.
_MARK_RADIUS = 0.02


def _without_mark(numerals: list[dict], target: dict) -> list[dict]:
    """Drop the mark a judgment names — same label, within `_MARK_RADIUS` of the spot.

    Position is part of the identity because one numeral legitimately appears several
    times on a sheet; refuting the phantom "12" must not delete the real one.
    """
    return [n for n in numerals
            if not (str(n["numeral"]) == str(target.get("numeral"))
                    and abs(n["x"] - target.get("x", -9)) < _MARK_RADIUS
                    and abs(n["y"] - target.get("y", -9)) < _MARK_RADIUS)]


def apply_adjudications(manifest: dict, fig_dir: str | Path) -> dict:
    """Fold the reviewer's effective judgments into the manifest view (D47)."""
    from .adjudication import CONFIRM, CORRECT, REFUTE, AdjudicationLog
    from .adjudication import import_legacy_sidecar as _legacy

    fig_dir = Path(fig_dir)
    log = AdjudicationLog(fig_dir / "adjudications.jsonl")
    if log.path.exists():
        log.verify_chain()          # a doctored record fails loudly, never reads clean
        judgments = log.effective()
    else:                            # un-migrated engagement: read the legacy file
        judgments = _legacy(fig_dir / "manual_annotations.json",
                            by="(unknown — pre-D47 record)", on="(undated)")

    by_page = {p["page"]: p for p in manifest["pages"]}
    for a in judgments:
        # Only marks-on-sheets judgments touch the manifest. The log now also carries
        # INTERPRETIVE rulings (D77) whose targets name a page but assert nothing about
        # a mark — confirming "FIG. 6 is on sheet p.7" would otherwise inject a numeral
        # called "6" onto that sheet. One log, several target kinds, and each consumer
        # must read only its own.
        if a.target_kind != "figure-numeral":
            continue
        page = by_page.get(a.target.get("page"))
        if page is None:
            continue
        if a.kind == REFUTE:
            # The reviewer says the tool located something that is not on the sheet.
            page["numerals"] = _without_mark(page["numerals"], a.target)
            continue
        if a.kind not in (CONFIRM, CORRECT):
            continue                 # a note asserts nothing about the marks
        if a.kind == CORRECT:
            # A correction REPLACES; it used to only append. Correcting a misread
            # "14a" to "12A" left both on the sheet — the wrong mark the reviewer had
            # just rejected, beside the right one — so the reconciliation still
            # reported the phantom and the reviewer's fix made the record worse, not
            # better. A correction is a refutation plus an assertion, and both halves
            # have to land.
            page["numerals"] = _without_mark(page["numerals"], a.target)
        src = a.value if a.kind == CORRECT else a.target
        page["numerals"].append({
            "numeral": src.get("numeral", a.target.get("numeral")),
            "source_text": a.note or "reviewer-confirmed",
            "confidence": 1.0, "method": "human",
            "adjudication": a.adj_id, "by": a.by, "on": a.on,
            "x": src.get("x", a.target.get("x")), "y": src.get("y", a.target.get("y")),
            "w": src.get("w", 0.02), "h": src.get("h", 0.02),
        })
    return manifest


def fig_to_sheets(manifest: dict, known_figs: list[str]) -> list[SheetAssignment]:
    """Assign each known figure (from the TEXT side — `patents.parse_figures` /
    `figure_references`) to its drawing sheet.

    Primary evidence: an OCR-read FIG label on the sheet, accepted only if it names
    a KNOWN figure (so a garbled "FIG.A" cannot invent figure A). Fallback: if
    exactly one known figure is unassigned and exactly one sheet has no accepted
    label, they pair by ELIMINATION — flagged as such, never silently. Anything
    less determinate stays unassigned (a surfaced gap, not a guess).
    """
    known = {f.upper() for f in known_figs}
    out: list[SheetAssignment] = []
    labeled_pages: set[int] = set()
    for page in manifest["pages"]:
        for lab in page["fig_labels"]:
            if lab["fig"] in known:
                out.append(SheetAssignment(lab["fig"], page["page"], OCR, lab["confidence"]))
                labeled_pages.add(page["page"])
    assigned = {a.fig for a in out}
    missing = sorted(known - assigned)
    unlabeled = [p["page"] for p in manifest["pages"] if p["page"] not in labeled_pages]
    if len(missing) == 1 and len(unlabeled) == 1:
        out.append(SheetAssignment(missing[0], unlabeled[0], ELIMINATION, None))
    return sorted(out, key=lambda a: (a.page, a.fig))


def numeral_sightings(manifest: dict, *, min_confidence: float = 0.0) -> list[NumeralSighting]:
    """Every numeral candidate OCR located on any sheet (optionally floored by
    confidence). Located-by-OCR facts — display/review evidence only."""
    out = []
    for page in manifest["pages"]:
        for n in page["numerals"]:
            if n["confidence"] < min_confidence:
                continue
            bbox = ((n["x"], n["y"], n["w"], n["h"])
                    if all(k in n for k in ("x", "y", "w", "h")) else None)
            out.append(NumeralSighting(n["numeral"], page["page"], n["confidence"],
                                       n["source_text"], bbox, n.get("method", "first-pass")))
    return sorted(out, key=lambda s: (s.page, numeral_key(s.numeral)))


def numeral_figures(
    assignments: list[SheetAssignment], sightings: list[NumeralSighting],
) -> dict[str, list[str]]:
    """For every numeral, ALL figures it is OCR-located in (a numeral shared across
    figures — "the separator 10" appears in FIGS. 1, 2, 5 — surfaces all of them,
    not just the first text mention). Figures are ordered as assigned; a sighting on
    an unassigned sheet contributes nothing (no figure to name). Locate-only."""
    page_to_fig = {a.page: a.fig for a in assignments}
    out: dict[str, list[str]] = {}
    for s in sightings:
        fig = page_to_fig.get(s.page)
        if fig and fig not in out.setdefault(s.numeral, []):
            out[s.numeral].append(fig)
    return {n: sorted(figs, key=lambda f: (len(f), f)) for n, figs in out.items()}


@dataclass(frozen=True)
class NumeralCrossCheck:
    matched: dict[str, list[NumeralSighting]]   # recited in spec AND located on sheets
    text_only: list[str]                        # recited, never located (OCR miss OR omission)
    sheet_only: list[NumeralSighting]           # located, never recited (OCR artifact OR gap)


def cross_check_numerals(
    text_numerals: list[str], manifest: dict, *, min_confidence: float = 0.0,
) -> NumeralCrossCheck:
    """The PE-2 element-numeral bridge: reconcile the spec's numeral list (from
    `patents.reference_numerals`, deterministic over text) with the sheets' (OCR).

    Surfaces three fact classes for professional review. `text_only` is worded as
    "not LOCATED on any sheet" — an OCR miss and a drawing omission are
    indistinguishable from here, and the check never claims otherwise (D10).
    """
    sightings = numeral_sightings(manifest, min_confidence=min_confidence)
    by_num: dict[str, list[NumeralSighting]] = {}
    for s in sightings:
        by_num.setdefault(s.numeral, []).append(s)
    text_set = set(text_numerals)
    return NumeralCrossCheck(
        matched={n: by_num[n] for n in sorted(text_set & set(by_num), key=numeral_key)},
        text_only=sorted(text_set - set(by_num), key=numeral_key),
        sheet_only=[s for s in sightings if s.numeral not in text_set],
    )


def relevant_figures(
    cited_span_texts: list[str],
    assignments: list[SheetAssignment],
    sightings: list[NumeralSighting],
    known_numerals: list[str],
) -> list[str]:
    """Which figures should ride beside these cited spans (RT-4's payoff rule).

    Two deterministic signals, union'd:
    - an explicit ``FIG. N`` reference in a cited span → that figure;
    - a known reference numeral recited in a cited span → every sheet OCR sighted
      it on → those sheets' assigned figures.

    Display-only (D21): this selects which drawing panels to SHOW next to the
    highlighted text — it asserts nothing and nothing here passes through
    `verify`. The numeral match is a token-boundary heuristic over short
    line-level spans; a spurious panel costs a glance, a missing one costs
    nothing (the standalone figures view still has everything).
    """
    import re as _re

    assigned = {a.fig for a in assignments}
    page_to_fig = {a.page: a.fig for a in assignments}
    num_to_pages: dict[str, set[int]] = {}
    for s in sightings:
        num_to_pages.setdefault(s.numeral, set()).add(s.page)

    out: set[str] = set()
    fig_ref = _re.compile(r"FIGS?\.?\s*(\d+[A-Z]?)", _re.IGNORECASE)
    for text in cited_span_texts:
        for m in fig_ref.finditer(text):
            if m.group(1).upper() in assigned:
                out.add(m.group(1).upper())
        for n in known_numerals:
            # standalone label n: not inside a larger/grouped/decimal number, and not
            # a prefix of a suffixed label ("12" must NOT match inside "12a") — hence
            # the trailing [\da-z] guard. A trailing `,` is punctuation ("10, which")
            # but `,\d` is grouping ("10,500").
            if _re.search(label_pattern(n), text):
                for page in num_to_pages.get(n, ()):
                    if page in page_to_fig:
                        out.add(page_to_fig[page])
    return sorted(out, key=lambda f: (len(f), f))


def numeral_text_figures(text: str, numeral: str, fig_refs, *,
                         window: int = FIGURE_CONTEXT_WINDOW) -> list[str]:
    """Every figure a numeral is discussed near across ALL its spec mentions — the
    nearest `FIG. N` reference at/before each standalone occurrence, within `window`
    chars. (`reference_numerals` gives only the FIRST mention; this sees them all, so
    "separator 10" discussed under both FIG. 1 and FIG. 4 surfaces both.)"""
    figs: set[str] = set()
    pat = re.compile(label_pattern(numeral))
    for m in pat.finditer(text):
        best = None
        for r in fig_refs:
            if r.char_start <= m.start() and m.start() - r.char_start <= window:
                if best is None or r.char_start > best.char_start:
                    best = r
        if best is not None:
            figs.add(best.number)
    return sorted(figs, key=lambda f: (len(f), f))


@dataclass(frozen=True)
class NumeralCoverage:
    figure_tied: list[str]         # the clean set: numerals the spec recites near a figure
    recited_not_drawn: list[str]    # figure-tied, but OCR found on NO sheet → OCR-miss flag
    drawn_not_recited: list[str]    # OCR-located, never recited in the spec → artefact/unlabeled
    figure_mismatches: list[dict]   # tied to FIG. N in text, not OCR-located on FIG. N's sheet
    seq_gaps: list[int]             # missing ints in figure_tied's range — WEAK (patents skip)
    likely_misreads: list[dict]     # sheet-only "140" that is positionally the recited "14a"


def _same_spot_conflicts(sightings: list[NumeralSighting], *, radius: float = 0.01):
    """Pairs of DIFFERENT labels sighted at the same position on the same page — one
    mark two engines read differently (the "58"/"38" class). Distinct from
    `merge_same_spot_numerals`, which merges IDENTICAL labels as corroboration."""
    out = []
    for i, a in enumerate(sightings):
        if a.bbox is None:
            continue
        for b in sightings[i + 1:]:
            if (b.bbox is None or b.page != a.page or b.numeral == a.numeral
                    or not (a.numeral.isdigit() and b.numeral.isdigit())):
                continue
            if (abs(a.bbox[0] - b.bbox[0]) < radius and abs(a.bbox[1] - b.bbox[1]) < radius):
                out.append((a, b))
    return out


def numeral_coverage(
    numerals, text, fig_refs, assignments: list[SheetAssignment],
    sightings: list[NumeralSighting], *, min_confidence: float = 0.0,
) -> NumeralCoverage:
    """Reconcile the spec text vs. the drawings (OCR) and flag every numeral the two
    disagree on. Locate-only (D10): each flag is an OCR miss OR skipped numbering
    (patents routinely skip) OR a document limit — the check states the fact, never
    which.

    Design honesty (see the module's L0006-class lesson): the naive "are all
    CONSECUTIVE numbers present?" check is **not reliable** for patents — they skip
    reference numerals by design, and both quantities and OCR misreads corrupt the
    range — so `seq_gaps` is returned but flagged WEAK. The reliable checks are the
    reconciliation ones, which don't depend on enumerating a contiguous sequence:

    - `recited_not_drawn`: a **figure-tied** numeral (the spec recites it near a
      `FIG. N`, so it is a real reference numeral, not a quantity) that OCR located on
      no sheet at all — the strongest OCR-miss / missing-from-drawings signal.
    - `drawn_not_recited`: OCR read a number the spec never recites — an OCR artefact
      or a genuinely unlabelled element.
    - `figure_mismatches`: tied to FIG. N in text but not OCR-located on FIG. N's sheet
      (the separator-10 / FIG-4 case) — a per-figure OCR-miss.
    """
    text_nums = {n.number for n in numerals}
    sightings = [s for s in sightings if s.confidence >= min_confidence]
    ocr_nums = {s.numeral for s in sightings if s.numeral != "0"}   # "0" = OCR noise
    ocr_figs = numeral_figures(assignments, sightings)
    assigned_figs = {a.fig for a in assignments}

    text_figs_of = {n: [f for f in numeral_text_figures(text, n, fig_refs) if f in assigned_figs]
                    for n in text_nums}
    # TEXT-AUTHORITATIVE, figure-tied: numerals the spec recites in the context of a
    # figure. Excludes quantity noise ("220° F" — recited, not figure-tied) and OCR
    # misreads ("280" — on a sheet, never recited). The spec defines the numerals.
    figure_tied = sorted({n for n, fs in text_figs_of.items() if fs and n != "0"},
                         key=numeral_key)
    ints = sorted(int(n) for n in figure_tied if n.isdigit())   # suffixed labels excluded
    seq_gaps = ([i for i in range(ints[0], ints[-1] + 1) if i not in set(ints)] if ints else [])

    mismatches = []
    for n in figure_tied:
        missing = [f for f in text_figs_of[n] if f not in ocr_figs.get(n, [])]
        if missing:
            mismatches.append({
                "numeral": n, "text_figures": text_figs_of[n],
                "ocr_figures": ocr_figs.get(n, []), "not_located_on": missing,
                "message": (f"numeral {n} is discussed in the text in the context of "
                            f"FIG(S). {', '.join(missing)}, but OCR did not locate it there "
                            f"— an OCR miss or the number is not labeled on that sheet; review"),
            })
    # OCR confusions, surfaced for review (never deleted — D28 keeps the raw read):
    #  (a) a↔0 — a sheet-only "140" sitting on top of the recited "14a";
    #  (b) same-spot DISAGREEMENT — two different labels read at the SAME position by
    #      different engines are ONE mark read two ways ("58" vs "38" within 0.003 on
    #      FIG 2's sheet), not two marks. Resolved toward the reading the text ties to
    #      that figure; the loser is reported, never silently dropped.
    drawn_only = ocr_nums - text_nums
    misreads = []
    for lbl in sorted(drawn_only, key=numeral_key):
        if not (lbl.isdigit() and lbl.endswith("0")):
            continue
        twin = lbl[:-1] + "a"
        if twin not in text_nums:
            continue
        spots = [(s0, s1) for s0 in sightings if s0.numeral == lbl and s0.bbox
                 for s1 in sightings if s1.numeral == twin and s1.page == s0.page and s1.bbox
                 if s0.bbox[0] - 0.02 <= s1.bbox[0] <= s0.bbox[0] + s0.bbox[2] + 0.02
                 and abs(s0.bbox[1] - s1.bbox[1]) < 0.02]
        if spots:
            misreads.append({"read_as": lbl, "actually": twin, "page": spots[0][0].page,
                             "message": (f'sheet label read as "{lbl}" is positionally the '
                                         f'recited "{twin}" — the a↔0 OCR confusion; treated '
                                         f"as {twin}, raw read preserved")})
            drawn_only = drawn_only - {lbl}

    fig_of_page = {a.page: a.fig for a in assignments}
    for a, b in _same_spot_conflicts(sightings):
        fig = fig_of_page.get(a.page)
        a_tied = fig in text_figs_of.get(a.numeral, [])
        b_tied = fig in text_figs_of.get(b.numeral, [])
        if a_tied == b_tied:
            # No text evidence either way (the spec ties no numeral to FIG 3C, whose
            # caption is shared). We cannot RESOLVE it — but a disagreement about one
            # mark is exactly what a reviewer should see, so report it unresolved.
            hi, lo = sorted((a, b), key=lambda s0: -s0.confidence)
            misreads.append({
                "read_as": lo.numeral, "actually": hi.numeral, "page": a.page,
                "unresolved": True,
                # The disputed mark's own box, so a surface that says "a reviewer must
                # read the sheet" can actually show them the sheet (D78).
                "bbox": list(hi.bbox) if hi.bbox else None,
                "message": (f'engines disagree on one mark on FIG. {fig}\'s sheet — '
                            f'"{a.numeral}" vs "{b.numeral}" at the same position, and the '
                            f"text ties neither to that figure, so this is NOT resolved; "
                            f"a reviewer must read the sheet"),
            })
            continue
        win, lose = (a, b) if a_tied else (b, a)
        misreads.append({
            "read_as": lose.numeral, "actually": win.numeral, "page": a.page,
            "message": (f'engines disagree on one mark on FIG. {fig}\'s sheet — '
                        f'"{lose.numeral}" vs "{win.numeral}" at the same position. The '
                        f'text ties "{win.numeral}" to that figure, so the other is very '
                        f"likely a misread of it; review"),
        })
        drawn_only = drawn_only - {lose.numeral}

    # single-letter view markers are a different class (derived from sub-figure
    # suffixes, not recited as numerals) — not anomalies.
    drawn_only = {n for n in drawn_only if not (len(n) == 1 and n.isalpha())}
    return NumeralCoverage(
        figure_tied=figure_tied,
        # sub-10 labels are excluded by policy (D30) — not attempted, so not a miss
        recited_not_drawn=[n for n in figure_tied
                           if n not in ocr_nums and is_locatable(n)],
        drawn_not_recited=sorted(drawn_only, key=numeral_key),
        figure_mismatches=mismatches,
        seq_gaps=seq_gaps,
        likely_misreads=misreads,
    )


def element_numeral_issues(
    numerals, manifest: dict, *, min_confidence: float = 0.0,
) -> list[dict]:
    """PE-2's element-numeral consistency check, at last buildable at high precision
    — the OCR manifest supplies the drawing-side ground truth the naive text-only
    heuristic lacked (it flagged 34/67 numerals, mostly false positives).

    `numerals` is `patents.reference_numerals(text)` output (number + element).
    Returns surfaced facts, one dict per issue, worded to D10 discipline: a
    structural observation with its OCR caveat, never a §112 conclusion.
    """
    cc = cross_check_numerals([n.number for n in numerals], manifest,
                              min_confidence=min_confidence)
    by_num = {n.number: n.element for n in numerals}
    issues = [
        {"kind": "recited-not-located", "numeral": n,
         "message": (f'numeral {n} ("{by_num[n]}") is recited in the specification but '
                     f"was not located on any drawing sheet — an OCR miss and a drawing "
                     f"omission are indistinguishable here; review the sheets")}
        for n in cc.text_only
    ]
    issues += [
        {"kind": "located-not-recited", "numeral": s.numeral,
         "message": (f"numeral {s.numeral} appears on sheet page {s.page} "
                     f'(OCR of "{s.source_text}", conf {s.confidence}) but is never '
                     f"recited in the specification — an OCR artefact and a spec gap "
                     f"are indistinguishable here; review")}
        for s in cc.sheet_only
    ]
    return issues
