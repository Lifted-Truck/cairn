"""render_evidence_view — interactive parallel evidence GUI (ROADMAP M2-T7 / D8, D15).

A self-contained HTML page: the full canonical document on the left, the
interactions on the right. The document is **clean by default** — nothing
highlighted. **Click an interaction's card** and only *that* interaction's
evidence lights up: its figures + question-label terms highlight in both panes, a
tight bounding box is drawn around each contiguous evidence cluster, and the
document scrolls to it. Clicking a figure also scrolls to it; clicking the active
card again clears. This keeps "which highlight belongs to which query"
unambiguous (D15).

Read-only (I4), deterministic, no server. Renders the normalized canonical text
CAIRN hashes and cites (D8). Your review is the un-gated step: does the
highlighted span actually support the claim (entailment)?
"""

from __future__ import annotations

import html
import json
import re
from bisect import bisect_right
from dataclasses import dataclass, field

from .cues import denial_cue_hits
from .frame import QuestionFrame, check_coverage, frame_from_json
from .retrieval import Hit
from .spans import SpanStore
from .verify import Answer, VerifyResult, answer_from_json, equation
from .verify import verify as run_verify


@dataclass(frozen=True)
class FigurePanel:
    """A companion drawing shown beside the document (RT-4). Corpus-agnostic — the
    view renders what it is given; the caller (a patent script) supplies the label,
    caption, and an embedded image (a data: URI). D21: displayed evidence, never a
    text citation — so a FigurePanel carries no span and is never `verify`-checked."""
    label: str                # "FIG. 4" — the key an Interaction.figures entry names
    caption: str
    image: str                # a self-contained data: URI (server-less, like the view)


@dataclass
class Interaction:
    question: str
    kind: str  # "answer" | "abstain" | "correction" | "partial" | "refuse" (D16/D22)
    answer: Answer | None = None
    verify: VerifyResult | None = None
    reason: str = ""
    closest: list[Hit] = field(default_factory=list)
    note: str = ""
    trace: str = ""
    frame: QuestionFrame | None = None
    figures: list[str] = field(default_factory=list)  # FigurePanel labels to surface (RT-4)


# Outcome classes that PRESENT something (D16) — they get cited-span highlights and
# the answer-style card; only `abstain` stays silent.
_PRESENTS = {"answer", "correction", "partial"}


def interactions_from_audit(entries: list[dict], store: SpanStore) -> list[Interaction]:
    """Reconstruct presented interactions from audit-log payloads (I5) → evidence view.

    The bridge from a live Claude Code / Desktop session to the review GUI: each
    `verify(ok)` record becomes a card. `verify` is re-run (deterministic) so the view
    reflects the current corpus. Abstentions (no `verify ok`) are not rendered.

    The question comes from the record's **own** `frame.question` (D13), never from a
    neighbouring record. Carrying the last `check_support` query forward was wrong on
    all 23 records of the first engagement: 18 showed the retrieval *query* in place of
    the question, and 3 attached an answer to an unrelated earlier question, because a
    `question` variable that survives the loop iteration outlives the record it came
    from. A search query is not a question, and proximity in a log is not attribution.
    """
    out: list[Interaction] = []
    sup_prov: dict = {}
    last_query = None
    for e in entries:
        kind = e.get("kind")
        if kind in ("check_support", "check_claim"):
            last_query = e.get("query") or e.get("claim") or last_query
            sup_prov = e.get("provenance", {}) or sup_prov
        elif kind == "verify" and e.get("ok") and e.get("answer"):
            answer = answer_from_json(e["answer"])
            outcome = e.get("outcome") if e.get("outcome") in _PRESENTS else "answer"
            frame = frame_from_json(e["frame"]) if e.get("frame") else None
            out.append(Interaction(
                question=_question_for(e, last_query),
                kind=outcome, answer=answer, verify=run_verify(answer, store),
                note="Reconstructed from the audit log (I5) — a real logged session.",
                trace=_provenance_line(e.get("provenance", {}), sup_prov),
                frame=frame,
            ))
    return out


def _question_for(record: dict, last_query: str | None) -> str:
    """The question a verify record answered, from the record itself where possible.

    A pre-D13 record carries no frame, so the nearest retrieval query is the only
    thing left — it is shown, but LABELLED as a query, because presenting a BM25
    query string as if it were the reviewer's question misrepresents the record on a
    surface a client signs.
    """
    own = (record.get("frame") or {}).get("question")
    if own:
        return own
    if last_query:
        return f"(question not logged; nearest retrieval query: {last_query!r})"
    return "(question not in log)"


def sessions_from_audit(entries: list[dict], store: SpanStore) -> list[dict]:
    """Group audit entries into sessions (RT-1) delimited by `session_start` markers.

    Returns `[{label, ts, interactions}]` in log order. Entries before the first
    marker (pre-RT-1 logs) form an "(unmarked)" session so old logs stay browsable.
    Sessions whose interactions are empty (e.g. all-abstain) are kept — an empty
    session is still history.
    """
    groups: list[tuple[str, str, list[dict]]] = []
    current: list[dict] = []
    label, ts = "(unmarked)", ""
    started = False                                  # a marker has opened a session
    for e in entries:
        if e.get("kind") == "session_start":
            if started or current:                   # close the prior session / non-empty preamble
                groups.append((label, ts, current))
            label, ts = e.get("label") or "(unlabeled)", e.get("ts", "")
            current, started = [], True
        else:
            current.append(e)
    if started or current:
        groups.append((label, ts, current))
    return [
        {"label": lb, "ts": t, "interactions": interactions_from_audit(es, store)}
        for lb, t, es in groups
    ]


def _provenance_line(verify_prov: dict, support_prov: dict) -> str:
    """The rigor a logged answer was produced under (TC-2/D21), for the trace."""
    bits = []
    if verify_prov.get("contract"):
        bits.append(f"truth-contract v{verify_prov['contract']}")
    if support_prov.get("retrieval"):
        bits.append(f"retrieval {support_prov['retrieval']}")
    if support_prov.get("threshold") is not None:
        bits.append(f"floor {support_prov['threshold']:g}")
    if verify_prov.get("verify_ops"):
        bits.append(f"verify-ops {verify_prov['verify_ops']}")
    return " · ".join(bits)


_CSS = """
:root { --bg:#0f1115; --panel:#171a21; --ink:#e6e9ef; --muted:#8b93a3;
  --line:#262b36; --markb:#e0a32e; --ok:#3fb950; --bad:#f85149;
  --chip:#1f6feb22; --chipb:#388bfd; --teal:#5fe0c4; --corr:#a371f7; --refuse:#f0883e; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); height:100vh; overflow:hidden;
  display:flex; flex-direction:column;
  font:15px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
header { padding:16px 24px; border-bottom:1px solid var(--line); flex:0 0 auto; }
header h1 { margin:0 0 4px; font-size:18px; }
header p { margin:0; color:var(--muted); font-size:13px; }
header a { color:var(--chipb); }
/* two panes, each scrolling INDEPENDENTLY inside the viewport below the header —
   the document's scroll extent must not depend on the answers column's length */
.layout { display:grid; grid-template-columns:1fr 1fr; flex:1 1 auto; min-height:0;
  overflow:hidden; }
@media (max-width:860px){
  body{ height:auto; overflow:visible; display:block; }
  .layout{ grid-template-columns:1fr; overflow:visible; }
  .doc{ height:60vh!important; }
  .cards{ height:auto!important; overflow:visible!important; } }
.doc { height:100%; min-height:0; overflow:auto; border-right:1px solid var(--line);
  padding:14px 18px; background:#0c0e12; }
.doc h3 { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted);
  margin:0 0 8px; }
.docbody { font-size:12px; line-height:1.5; font-family:ui-monospace,Menlo,monospace; margin:0; }
.figstrip { position:sticky; top:0; z-index:5; display:flex; gap:10px; flex-wrap:wrap; }
.figstrip:has(.figpanel.on) { padding:8px 0 12px; margin-bottom:6px;
  border-bottom:1px solid var(--line); background:var(--bg); }
.figpanel { display:none; margin:0; max-width:230px; }
.figpanel.on { display:block; }
.figpanel img { width:100%; border:1px solid var(--line); border-radius:6px; background:#fff; }
.figpanel figcaption { font-size:10.5px; color:var(--muted); margin-top:3px; line-height:1.35; }
.docln { white-space:pre-wrap; word-break:break-word; color:#aab2c0; padding:0 6px;
  border-left:2px solid transparent; border-right:2px solid transparent; }
.docln.h { color:var(--ink); font-weight:700; font-size:13px; margin-top:12px; }
.docln.sub { color:#c6ccd8; font-weight:600; margin-top:4px; }
.docln.blank { height:8px; }
/* financial rows: label left, numeric columns right-aligned + aligned across rows */
.docln.trow { display:flex; gap:10px; align-items:baseline; }
.trow .tlabel { flex:1 1 auto; min-width:0; }
.trow .tnums { display:flex; gap:18px; flex:0 0 auto; }
.trow .tnum { min-width:90px; text-align:right; white-space:pre; }
/* bounding box around an active interaction's evidence cluster */
.docln.bx { border-left-color:var(--chipb); border-right-color:var(--chipb); background:#12243f55; }
.docln.bx-top { border-top:2px solid var(--chipb); border-top-left-radius:5px;
  border-top-right-radius:5px; }
.docln.bx-bot { border-bottom:2px solid var(--chipb); border-bottom-left-radius:5px;
  border-bottom-right-radius:5px; }
/* document marks: plain by default; lit only for the active interaction */
mark.m { background:none; color:inherit; border-radius:3px; padding:0 1px; scroll-margin-top:16px; }
mark.m.on.k-fig { background:#3b2f12; color:var(--markb); font-weight:600; }
mark.m.on.k-lbl { background:#0e3a36; color:var(--teal); }
mark.m.on.k-cls { background:#23262e; color:#c6ccd8; }
mark.flash { outline:2px solid var(--chipb); }
.cards { height:100%; min-height:0; overflow:auto; }
.card { border-bottom:1px solid var(--line); padding:18px 24px; cursor:pointer;
  border-left:3px solid transparent; }
.card.active { border-left-color:var(--chipb); background:#10131a; }
.card.correction.active { border-left-color:var(--corr); }
.card.partial.active { border-left-color:var(--markb); }
.card.refuse.active { border-left-color:var(--refuse); }
.card .hint { color:var(--muted); font-size:11px; } .card.active .hint { color:var(--chipb); }
.q { font-weight:600; margin:0 0 2px; }
.badge { display:inline-block; font-size:11px; font-weight:700; letter-spacing:.04em;
  padding:2px 8px; border-radius:999px; text-transform:uppercase; margin-bottom:10px; }
.badge.answer { background:#11331c; color:var(--ok); }
.badge.abstain, .badge.reject { background:#3a1d1d; color:var(--bad); }
.badge.correction { background:#241a3a; color:var(--corr); }
.badge.partial { background:#3a2f12; color:var(--markb); }
.badge.refuse { background:#3a2413; color:var(--refuse); }
.answer-text { background:var(--panel); border:1px solid var(--line); border-radius:8px;
  padding:12px 14px; }
.reason { color:var(--muted); margin:0 0 8px; }
/* response-column label terms: plain until the card is active (then teal, matching the doc) */
mark.qlbl { background:none; color:inherit; border-radius:3px; padding:0 1px; }
.card.active mark.qlbl { background:#0e3a36; color:var(--teal); }
.chip { background:var(--chip); border:1px solid var(--chipb); color:var(--ink); border-radius:4px;
  padding:0 4px; cursor:pointer; font-weight:600; }
.chip.derived { background:#2a1f3a; border-color:#a371f7; cursor:help; }
.closest { font-family:ui-monospace,Menlo,monospace; font-size:12px; margin:6px 0 0; }
.closest a { color:var(--chipb); cursor:pointer; text-decoration:none; }
.vstatus { font-size:12px; margin-top:8px; }
.vstatus.ok{ color:var(--ok); } .vstatus.bad{ color:var(--bad); }
.vstatus.cue{ color:#d29922; }
.cover { font-size:12px; margin:6px 0 0; display:flex; flex-wrap:wrap; gap:6px; }
.cover span { border-radius:4px; padding:0 6px; border:1px solid var(--line); }
.cov-ok { color:var(--ok); } .cov-bad { color:var(--bad); border-color:var(--bad)!important; }
.deriv { font-family:ui-monospace,Menlo,monospace; font-size:12px; margin:6px 0 0; color:#c6ccd8; }
.deriv .ok { color:var(--ok); } .deriv .bad { color:var(--bad); }
.trace { color:var(--muted); font-size:12px; margin:10px 0 0;
  font-family:ui-monospace,Menlo,monospace; }
.trace b { color:var(--ink); font-weight:600; }
"""

_JS = """
const CLUSTERS = %s;
const FIGMAP = %s;
function clearAll(){
  document.querySelectorAll('.card.active').forEach(c=>c.classList.remove('active'));
  document.querySelectorAll('mark.m.on').forEach(m=>m.classList.remove('on'));
  document.querySelectorAll('mark.flash').forEach(m=>m.classList.remove('flash'));
  document.querySelectorAll('.figpanel.on').forEach(f=>f.classList.remove('on'));
  document.querySelectorAll('.docln.bx,.docln.bx-top,.docln.bx-bot')
    .forEach(e=>e.classList.remove('bx','bx-top','bx-bot'));
}
function light(id){
  const card=document.getElementById(id); if(card) card.classList.add('active');
  document.querySelectorAll('mark.m').forEach(m=>{
    if((m.dataset.int||'').split(' ').includes(id)) m.classList.add('on');
  });
  (FIGMAP[id]||[]).forEach(lab=>{
    document.querySelectorAll('.figpanel').forEach(f=>{
      if(f.dataset.fig===lab) f.classList.add('on');
    });
  });
  (CLUSTERS[id]||[]).forEach(lines=>lines.forEach((lid,i)=>{
    const e=document.getElementById(lid); if(!e) return;
    e.classList.add('bx');
    if(i===0) e.classList.add('bx-top');
    if(i===lines.length-1) e.classList.add('bx-bot');
  }));
}
function flashTo(markId){
  const el=document.getElementById(markId); if(!el) return;
  document.querySelectorAll('mark.flash').forEach(m=>m.classList.remove('flash'));
  el.classList.add('flash'); el.scrollIntoView({behavior:'smooth', block:'center'});
}
document.querySelectorAll('.card').forEach(card=>card.addEventListener('click', e=>{
  const chip=e.target.closest('[data-target]');
  const active=card.classList.contains('active');
  if(chip){ if(!active){ clearAll(); light(card.id); } flashTo(chip.dataset.target); return; }
  if(active){ clearAll(); return; }
  clearAll(); light(card.id);
  const c=CLUSTERS[card.id]; if(c&&c.length&&c[0].length) flashTo(c[0][0]);
}));
"""

_PRIORITY = {"figure": 3, "label": 2, "closest": 1}
_KIND_CLASS = {"figure": "k-fig", "label": "k-lbl", "closest": "k-cls"}
_FIG = re.compile(r"\d{1,3}(?:,\d{3})+")
# A numeric table cell (optional $, optional parenthesised-negative, comma-grouped).
_CELLPAT = r"\$?\s?\(?\d{1,3}(?:,\d{3})+\)?"
_CELL = re.compile(_CELLPAT)
# A financial row: a label followed by a trailing run of numeric cells to end-of-line.
_ROW = re.compile(rf"((?:\s*{_CELLPAT})+)\s*$")
# A period-header cell, e.g. "September 28, 2024" (years are bare, not comma-grouped).
_DATE_CELL = re.compile(r"[A-Z][a-z]+ \d{1,2},? \d{4}")


def _column_header(store: SpanStore, doc_id: str, fig_start: int) -> tuple[int, int] | None:
    """For a figure in a financial row, the matching period-header cell's (start, end).

    Maps the figure's numeric-column index to the same-index date cell on the nearest
    period-header line above it — so an answer can highlight the *column* its figure
    sits under (the period qualifier, D13). Returns None when the figure isn't in a
    date-keyed table or the columns don't line up (graceful: just no header mark).
    """
    text = store.get_document(doc_id)
    starts = _line_starts(text)
    li = bisect_right(starts, fig_start) - 1
    if li < 0:
        return None
    lend = starts[li + 1] - 1 if li + 1 < len(starts) else len(text)
    cells = list(_CELL.finditer(text, starts[li], lend))
    col = next((i for i, m in enumerate(cells) if m.start() <= fig_start < m.end()), None)
    if col is None:
        return None
    for hj in range(li - 1, max(-1, li - 80), -1):              # nearest period header above
        hend = starts[hj + 1] - 1
        dates = list(_DATE_CELL.finditer(text, starts[hj], hend))
        if dates:
            return (dates[col].start(), dates[col].end()) if col < len(dates) else None
    return None


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _classify(line: str) -> str:
    s = line.strip()
    if not s:
        return "blank"
    if [c for c in s if c.isalpha()] and s == s.upper() and len(s) <= 90:
        return "h"
    if re.match(r"(PART |Item |ITEM )", s):
        return "h"
    if s.endswith(":") and len(s) <= 60 and not _FIG.search(s):
        return "sub"
    return "ln"


def _render_text(text: str, chips: tuple = (), label_terms: tuple = ()) -> str:
    """Escape `text`, wrapping figure chips (by literal) + the question's label terms
    (case-insensitive, as `qlbl` marks — lit when the card is active) as non-overlapping spans."""
    spans: list[tuple[int, int, str]] = []

    def claim(literal: str, make_html, ci: bool) -> None:
        hay = text.lower() if ci else text
        needle = literal.lower() if ci else literal
        i = hay.find(needle)
        while i != -1:
            s, e = i, i + len(literal)
            if all(e <= os or s >= oe for os, oe, _ in spans):
                spans.append((s, e, make_html(text[s:e])))
                return
            i = hay.find(needle, i + 1)

    for literal, cls, target, title in chips:
        attr = f' data-target="{target}"' if target else ""
        tip = f' title="{_esc(title)}"' if title else ""
        claim(literal, lambda t, c=cls, a=attr, p=tip: f'<span class="{c}"{a}{p}>{_esc(t)}</span>',
              ci=False)
    for term in label_terms:
        claim(term, lambda t: f'<mark class="qlbl">{_esc(t)}</mark>', ci=True)

    out, cursor = [], 0
    for s, e, h in sorted(spans):
        out.append(_esc(text[cursor:s]))
        out.append(h)
        cursor = e
    out.append(_esc(text[cursor:]))
    return "".join(out)


# --- document marking: kinded, interaction-owned ranges → painted segments ---


def _gather(interactions, store) -> dict[str, list[tuple[int, int, str, str]]]:
    """Per doc: (start, end, kind, interaction_id) ranges — figures, label terms, closest."""
    raw: dict[str, list[tuple[int, int, str, str]]] = {}

    def add(doc_id, s, e, kind, iid):
        raw.setdefault(doc_id, []).append((s, e, kind, iid))

    for idx, inter in enumerate(interactions):
        iid = f"i{idx}"
        if inter.kind in _PRESENTS and inter.answer is not None:
            cons = inter.frame.constraints if inter.frame else []
            for sent in inter.answer.sentences:
                atoms = list(sent.atoms) + [o for d in sent.derived for o in d.operands]
                for a in atoms:
                    add(a.doc_id, a.char_start, a.char_end, "figure", iid)
                    hdr = _column_header(store, a.doc_id, a.char_start)
                    if hdr:                      # light the column header (the period qualifier)
                        add(a.doc_id, hdr[0], hdr[1], "label", iid)
                    sp = store.span_containing(a.doc_id, a.char_start)
                    if sp is None:
                        continue
                    low = sp.text.lower()
                    for c in cons:
                        i = low.find(c.text.lower())
                        if i != -1:
                            add(sp.doc_id, sp.char_start + i, sp.char_start + i + len(c.text),
                                "label", iid)
        for h in inter.closest:
            add(h.span.doc_id, h.span.char_start, h.span.char_end, "closest", iid)
    return raw


def _paint(ranges: list[tuple[int, int, str, str]]) -> list[tuple[int, int, str, list[str], str]]:
    """Overlapping (start,end,kind,iid) → non-overlapping (start,end,kind,iids,mark_id)."""
    points = sorted({p for s, e, _k, _i in ranges for p in (s, e)})
    segs: list[tuple[int, int, str, list[str]]] = []
    for a, b in zip(points, points[1:], strict=False):
        cover = [(k, i) for s, e, k, i in ranges if s <= a and e >= b]
        if not cover:
            continue
        kind = max((k for k, _ in cover), key=lambda k: _PRIORITY[k])
        iids = sorted({i for _, i in cover})
        if segs and segs[-1][1] == a and segs[-1][2] == kind and segs[-1][3] == iids:
            segs[-1] = (segs[-1][0], b, kind, iids)
        else:
            segs.append((a, b, kind, iids))
    return [(s, e, k, i, f"m{n}") for n, (s, e, k, i) in enumerate(segs)]


def _seg_id(painted, pos: int) -> str:
    for s, e, _k, _i, mid in painted:
        if s <= pos < e:
            return mid
    return ""


def _line_starts(text: str) -> list[int]:
    starts, off = [], 0
    for raw in text.split("\n"):
        starts.append(off)
        off += len(raw) + 1
    return starts


def _splice(text: str, a: int, b: int, marks) -> str:
    """HTML for text[a:b], wrapping any marks (absolute, sorted) that fall inside it."""
    out, cur = [], a
    for s, e, kind, iids, mid in marks:
        if e <= a or s >= b:
            continue
        s, e = max(s, a), min(e, b)
        out.append(_esc(text[cur:s]))
        out.append(f'<mark class="m {_KIND_CLASS[kind]}" id="{mid}" '
                   f'data-int="{" ".join(iids)}">{_esc(text[s:e])}</mark>')
        cur = e
    out.append(_esc(text[cur:b]))
    return "".join(out)


def _doc_pane(store: SpanStore, doc_id: str, painted, label: str, prepend: str = "") -> str:
    text = store.get_document(doc_id)
    marks = sorted(painted)
    lines, offset, mi = [], 0, 0
    for n, raw in enumerate(text.split("\n")):
        line_end = offset + len(raw)
        lmarks = []
        while mi < len(marks) and marks[mi][0] < line_end:
            lmarks.append(marks[mi])
            mi += 1
        cls = _classify(raw)
        row = _ROW.search(raw) if cls == "ln" else None
        if row and row.start(1) > 0 and any(c.isalpha() for c in raw[: row.start(1)]):
            # Financial row → label + right-aligned numeric cells (display-only alignment).
            block = offset + row.start(1)
            label_html = _splice(text, offset, block, lmarks)
            cell_htmls = []
            for cm in _CELL.finditer(raw, row.start(1)):
                inner = _splice(text, offset + cm.start(), offset + cm.end(), lmarks)
                cell_htmls.append(f'<span class="tnum">{inner}</span>')
            body = (f'<span class="tlabel">{label_html}</span>'
                    f'<span class="tnums">{"".join(cell_htmls)}</span>')
            lines.append(f'<div class="docln ln trow" id="L{n}">{body}</div>')
        elif cls == "blank":
            lines.append(f'<div class="docln blank" id="L{n}"></div>')
        else:
            lines.append(f'<div class="docln {cls}" id="L{n}">'
                         f'{_splice(text, offset, line_end, lmarks)}</div>')
        offset = line_end + 1
    return (
        f'<aside class="doc"><h3>{_esc(label)}</h3>{prepend}'
        f'<div class="docbody">{"".join(lines)}</div></aside>'
    )


def _clusters(raw_for_doc, starts: list[int]) -> dict[str, list[list[str]]]:
    """Per interaction: contiguous runs of document line-ids covering its ranges."""
    by_int: dict[str, set[int]] = {}
    for s, _e, _k, iid in raw_for_doc:
        by_int.setdefault(iid, set()).add(bisect_right(starts, s) - 1)
    out: dict[str, list[list[str]]] = {}
    for iid, line_set in by_int.items():
        runs, run = [], []
        for ln in sorted(line_set):
            if run and ln - run[-1] > 2:  # > one blank line between → new cluster
                runs.append(run)
                run = []
            run.append(ln)
        if run:
            runs.append(run)
        out[iid] = [[f"L{n}" for n in range(r[0], r[-1] + 1)] for r in runs]
    return out


def _answer_card(inter: Interaction, store: SpanStore, seg_id) -> str:
    right, cited_texts, derivations = [], [], []
    label_terms = tuple(c.text for c in inter.frame.constraints) if inter.frame else ()
    for si, s in enumerate(inter.answer.sentences):
        oks = inter.verify.sentences[si].derived_ok if inter.verify else []
        chips: list[tuple[str, str, str, str]] = []
        for a in s.atoms:
            chips.append((a.text, "chip", seg_id(a.doc_id, a.char_start), ""))
            sp = store.span_containing(a.doc_id, a.char_start)
            if sp:
                cited_texts.append(sp.text)
        for di, d in enumerate(s.derived):
            eq = equation(d)
            chips.append((d.text, "chip derived", "", eq))
            derivations.append((eq, oks[di] if di < len(oks) else False))
            for o in d.operands:
                chips.append((o.text, "chip", seg_id(o.doc_id, o.char_start), ""))
                sp = store.span_containing(o.doc_id, o.char_start)
                if sp:
                    cited_texts.append(sp.text)
        right.append(f"<p>{_render_text(s.text, tuple(chips), label_terms)}</p>")

    ok = inter.verify.ok if inter.verify else False
    vtext = "✓ verify: every figure resolves to a cited span" if ok else \
        f"✗ verify: unbound — {', '.join(inter.verify.unbound()) if inter.verify else '?'}"
    parts = [f'<div class="answer-text">{" ".join(right)}</div>',
             f'<div class="vstatus {"ok" if ok else "bad"}">{vtext}</div>']
    for eq, deq_ok in derivations:
        parts.append(f'<p class="deriv">ƒ {_esc(eq)} <span class="{"ok" if deq_ok else "bad"}">'
                     f'{"✓ recomputed" if deq_ok else "✗ mismatch"}</span></p>')
    if inter.frame is not None:
        cov = check_coverage(inter.frame, cited_texts)
        bits = [f'<span class="cov-ok">{_esc(c.role)} ✓ {_esc(c.text)}</span>' for c in cov.covered]
        bits += [
            f'<span class="cov-bad">{_esc(c.role)} ✗ {_esc(c.text)}</span>' for c in cov.missing
        ]
        head = "✓ question coverage" if cov.complete else "✗ question coverage — incomplete"
        parts.append(f'<div class="vstatus {"ok" if cov.complete else "bad"}">{head}</div>')
        parts.append(f'<p class="cover">{" · ".join(bits)}</p>')

    # D24 advisory (non-blocking): an evaluative denial/correction cue span-local to
    # a cited figure. Worded as "cue near citation — review", never "refuted" (a
    # discourse claim the scan cannot substantiate). Gates nothing.
    cue_notes = []
    for s in inter.answer.sentences:
        for a in list(s.atoms) + [o for d in s.derived for o in d.operands]:
            sp = store.span_containing(a.doc_id, a.char_start)
            if sp is None:
                continue
            for h in denial_cue_hits(sp.text, [a.char_start - sp.char_start]):
                cue_notes.append(f'“{_esc(h.cue)}” {h.distance} chars from {_esc(a.text)}')
    if cue_notes:
        parts.append('<div class="vstatus cue">⚠ denial/correction cue in cited span — '
                     f'review (advisory, D24): {" · ".join(sorted(set(cue_notes)))}</div>')
    return "".join(parts)


def _abstain_card(inter: Interaction, seg_id) -> str:
    label_terms = tuple(c.text for c in inter.frame.constraints) if inter.frame else ()
    parts = [f'<p class="reason">{_render_text(inter.reason, label_terms=label_terms)}</p>']
    if inter.note:
        parts.append(f"<p>{_esc(inter.note)}</p>")
    for h in inter.closest:
        mid = seg_id(h.span.doc_id, h.span.char_start)
        link = f'<a data-target="{mid}">{_esc(h.span.text)}</a>' if mid else _esc(h.span.text)
        parts.append(f'<p class="closest">▸ {link} '
                     f'<span style="color:#8b93a3">(score {h.score:.0f})</span></p>')
    return "".join(parts)


def render_evidence_view(
    interactions: list[Interaction], store: SpanStore, *,
    title: str = "CAIRN — evidence view", figures: list[FigurePanel] | None = None,
) -> str:
    raw = _gather(interactions, store)
    painted = {doc_id: _paint(rs) for doc_id, rs in raw.items()}

    def seg_id(doc_id: str, pos: int) -> str:
        return _seg_id(painted.get(doc_id, []), pos)

    # RT-4: companion drawings, surfaced per-interaction. The strip is sticky at the
    # top of the (first) document pane and stays empty until a card that names figures
    # is active — so a cited numeral/FIG can show its drawing IN the document view.
    figstrip, figmap = "", {}
    if figures:
        panels = "".join(
            f'<figure class="figpanel" data-fig="{_esc(f.label)}">'
            f'<img src="{f.image}" alt="{_esc(f.label)}">'
            f'<figcaption>{_esc(f.label)} · {_esc(f.caption)}</figcaption></figure>'
            for f in figures
        )
        figstrip = f'<div class="figstrip">{panels}</div>'
        known = {f.label for f in figures}
        figmap = {f"i{idx}": [lab for lab in inter.figures if lab in known]
                  for idx, inter in enumerate(interactions) if inter.figures}

    doc_ids = list(painted) or list(store._docs)[:1]
    clusters: dict[str, list[list[str]]] = {}
    panes = []
    for pi, doc_id in enumerate(doc_ids):
        m = store._docs[doc_id].metadata
        label = f"{m.get('company', doc_id)} {m.get('form', '')}".strip() + " — canonical text"
        panes.append(_doc_pane(store, doc_id, painted.get(doc_id, []), label,
                               prepend=figstrip if pi == 0 else ""))
        clusters.update(_clusters(raw.get(doc_id, []), _line_starts(store.get_document(doc_id))))

    cards = []
    for idx, inter in enumerate(interactions):
        body = _answer_card(inter, store, seg_id) if (
            inter.kind in _PRESENTS and inter.answer is not None
        ) else _abstain_card(inter, seg_id)
        trace = f'<p class="trace"><b>decision</b> · {_esc(inter.trace)}</p>' if inter.trace else ""
        terms = tuple(c.text for c in inter.frame.constraints) if inter.frame else ()
        q_html = _render_text(inter.question, label_terms=terms)
        cards.append(
            f'<section class="card {inter.kind}" id="i{idx}"><p class="q">{q_html}</p>'
            f'<span class="badge {inter.kind}">{inter.kind}</span> '
            f'<span class="hint">click to show evidence</span>{body}{trace}</section>'
        )

    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{_esc(title)}</title><style>{_CSS}</style></head><body>"
        f"<header><h1>{_esc(title)}</h1><p>{_source_links(store)}</p>"
        "<p>Document is clean until you <b>click a card</b> — then only that query's evidence "
        "lights up and is boxed. Your review: does the highlighted span support the claim? "
        "(entailment — not gated in v1)</p></header>"
        f'<div class="layout">{"".join(panes)}'
        f'<main class="cards">{"".join(cards)}</main></div>'
        f"<script>{_JS % (json.dumps(clusters), json.dumps(figmap))}</script></body></html>"
    )


def _source_links(store: SpanStore) -> str:
    parts = []
    for doc_id, doc in store._docs.items():
        m = doc.metadata
        label = f"{m.get('company', doc_id)} {m.get('form', '')}".strip()
        bits = [f"<b>{_esc(label)}</b>"]
        if m.get("primary_url"):
            url = _esc(m["primary_url"])
            bits.append(f'<a href="{url}" target="_blank" rel="noopener">SEC filing ↗</a>')
        parts.append(" · ".join(bits))
    return "Source: " + " &nbsp;|&nbsp; ".join(parts)
