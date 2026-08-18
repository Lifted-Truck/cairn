"""console — one frame around the surfaces that never linked to each other (RT-10, D48).

Cairn's engine was never the weak part; **cohesion** was. Four generators each produced a
complete, self-contained HTML page, and a reviewer opened one, read it, closed it, and
re-oriented from scratch on the next. Nothing carried them between surfaces, and nothing
carried the corpus's own state alongside the evidence.

**This wraps rather than replaces.** Each generator still emits a standalone page — that
property is worth keeping, because a single page is what gets emailed, archived beside an
engagement, and opened years later without this tool. The console adds the two things a
set of pages cannot have on its own:

  1. a **persistent header** carrying the facts that must never leave the screen — which
     corpus, whether its support floor is calibrated for it, how many reviewer judgments
     are on record, how many discrepancies are outstanding;
  2. **navigation**, so the five stages of the work are one surface rather than five.

The header is where D33's rule lands architecturally: a caveat that scrolls away is a
caveat that did not work. An uncalibrated corpus skews toward *false abstention* — refusing
questions it can answer — and that is precisely the failure a reviewer would otherwise read
as diligence. So it is stated at the top of every pane, not filed under a settings tab.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field

from .refresh import button


@dataclass
class Pane:
    """One stage of the work, and the page that serves it (or does not, yet)."""

    key: str
    label: str
    stage: str                  # the question this stage answers, in the reviewer's words
    page: str | None = None     # generated filename, relative to the console directory
    absent_note: str = ""       # shown INSTEAD of a page — what is missing and why


@dataclass
class ConsoleState:
    """The facts that ride above every pane."""

    engagement: str
    doc_ids: list[str]
    calibration: str
    calibrated: bool
    contract: str
    adjudications: int = 0
    # Open questions of MEANING (D77). Carried in the header because an
    # unresolved reading changes how every other pane should be read, and a
    # count that lives only on one tab is a count nobody sees.
    ambiguities: int = 0
    flags: int | None = None            # outstanding discrepancies, None = not applicable
    generated_on: str = ""
    panes: list[Pane] = field(default_factory=list)


def _e(s: object) -> str:
    return html.escape(str(s), quote=True)


def render(state: ConsoleState) -> str:
    tabs, bodies = [], []
    first = next((p for p in state.panes if p.page), state.panes[0] if state.panes else None)
    for p in state.panes:
        sel = " aria-selected='true'" if first and p.key == first.key else ""
        dim = " class='dim'" if not p.page else ""
        tabs.append(
            f"<button role='tab' data-pane='{_e(p.key)}'{sel}{dim}>"
            f"<span class='lbl'>{_e(p.label)}</span>"
            f"<span class='stg'>{_e(p.stage)}</span></button>")
        hidden = "" if (first and p.key == first.key) else " hidden"
        if p.page:
            inner = (f"<iframe src='{_e(p.page)}' title='{_e(p.label)}' loading='lazy'>"
                     f"</iframe>")
        else:
            inner = (f"<div class='absent'><h2>Not built yet</h2>"
                     f"<p>{_e(p.absent_note)}</p></div>")
        bodies.append(f"<section id='pane-{_e(p.key)}'{hidden}>{inner}</section>")

    cal_cls = "ok" if state.calibrated else "warn"
    flags = ("" if state.flags is None else
             f"<span class='stat {'warn' if state.flags else 'ok'}'>"
             f"<b>{state.flags}</b> discrepanc{'y' if state.flags == 1 else 'ies'}</span>")

    return _PAGE.format(
        engagement=_e(state.engagement),
        docs=_e(", ".join(state.doc_ids) or "no documents"),
        n_docs=len(state.doc_ids),
        contract=_e(state.contract),
        generated=_e(state.generated_on or "—"),
        cal_cls=cal_cls,
        cal_short=_e("calibrated" if state.calibrated else "NOT calibrated"),
        calibration=_e(state.calibration),
        adj=state.adjudications,
        ambs=("<span class='stat warn'><b>%d</b> open reading(s)</span>"
              % state.ambiguities) if state.ambiguities else "",
        flags=flags,
        tabs="".join(tabs),
        bodies="".join(bodies),
        pane_json=json.dumps([p.key for p in state.panes]),
    ) + button()


_PAGE = """<meta charset="utf-8"><title>Cairn — {engagement}</title>
<style>
:root{{--bg:#f7f5f0;--panel:#fff;--ink:#161c26;--mut:#5d6779;--rule:#dcd6ca;
 --ok:#3f6b52;--okbg:#e9f1ec;--warn:#a2402f;--warnbg:#fbeeeb;--accent:#2f4f8f;
 --sans:ui-sans-serif,system-ui,"Segoe UI",Helvetica,sans-serif;
 --mono:ui-monospace,"SF Mono",Menlo,monospace}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f131a;--panel:#151b24;--ink:#e7e3d9;
 --mut:#98a2b3;--rule:#2a323f;--ok:#7fc39c;--okbg:#16241d;--warn:#e8837a;
 --warnbg:#271619;--accent:#8fb3dd}}}}
:root[data-theme="dark"]{{--bg:#0f131a;--panel:#151b24;--ink:#e7e3d9;--mut:#98a2b3;
 --rule:#2a323f;--ok:#7fc39c;--okbg:#16241d;--warn:#e8837a;--warnbg:#271619;--accent:#8fb3dd}}
:root[data-theme="light"]{{--bg:#f7f5f0;--panel:#fff;--ink:#161c26;--mut:#5d6779;
 --rule:#dcd6ca;--ok:#3f6b52;--okbg:#e9f1ec;--warn:#a2402f;--warnbg:#fbeeeb;--accent:#2f4f8f}}
*{{box-sizing:border-box}}
html,body{{height:100%}}
body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 var(--sans);
 display:flex;flex-direction:column}}

header{{background:var(--panel);border-bottom:1px solid var(--rule);padding:11px 20px 0;
 flex:0 0 auto}}
.top{{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:9px}}
.brand{{font:700 16px/1 var(--sans);letter-spacing:-.01em}}
.eng{{font:13px/1.4 var(--sans);color:var(--mut)}}
.eng b{{color:var(--ink);font-weight:600}}
.stats{{display:flex;gap:7px;flex-wrap:wrap;margin-left:auto}}
.stat{{font:11.5px/1.7 var(--sans);padding:1px 9px;border-radius:11px;
 background:var(--bg);border:1px solid var(--rule);color:var(--mut);white-space:nowrap}}
.stat b{{color:var(--ink);font-variant-numeric:tabular-nums}}
.stat.ok{{background:var(--okbg);border-color:transparent;color:var(--ok)}}
.stat.ok b{{color:var(--ok)}}
.stat.warn{{background:var(--warnbg);border-color:transparent;color:var(--warn)}}
.stat.warn b{{color:var(--warn)}}

/* The calibration line is a banner, not a chip, when it is bad: an uncalibrated floor
   skews toward refusing answerable questions, and that reads as diligence. */
.cal{{font:12.5px/1.5 var(--sans);padding:7px 12px;border-radius:6px;margin:0 0 10px}}
.cal.ok{{background:var(--okbg);color:var(--ok)}}
.cal.warn{{background:var(--warnbg);color:var(--warn);font-weight:500}}

[role=tablist]{{display:flex;gap:2px;overflow-x:auto}}
[role=tab]{{appearance:none;background:none;border:0;border-bottom:2px solid transparent;
 padding:8px 14px 9px;cursor:pointer;text-align:left;color:var(--mut);font-family:inherit;
 white-space:nowrap;border-radius:6px 6px 0 0}}
[role=tab]:hover{{background:var(--bg)}}
[role=tab][aria-selected=true]{{border-bottom-color:var(--accent);color:var(--ink)}}
[role=tab] .lbl{{display:block;font:600 13.5px/1.3 var(--sans)}}
[role=tab] .stg{{display:block;font:11px/1.4 var(--sans);color:var(--mut)}}
[role=tab].dim .lbl{{opacity:.5}} [role=tab].dim .stg{{opacity:.5}}

main{{flex:1 1 auto;min-height:0;position:relative}}
section{{position:absolute;inset:0}}
section[hidden]{{display:none}}
iframe{{width:100%;height:100%;border:0;background:var(--panel)}}
.absent{{height:100%;display:flex;flex-direction:column;align-items:center;
 justify-content:center;text-align:center;padding:40px;color:var(--mut)}}
.absent h2{{font:600 17px/1.3 var(--sans);margin:0 0 8px;color:var(--ink)}}
.absent p{{max-width:52ch;margin:0;font-size:13.5px}}
:focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
</style>

<header>
  <div class="top">
    <span class="brand">Cairn</span>
    <span class="eng"><b>{engagement}</b> · {n_docs} document(s): {docs}</span>
    <span class="stats">
      <span class="stat">contract v{contract}</span>
      <span class="stat"><b>{adj}</b> adjudication(s)</span>
      {ambs}
      {flags}
      <span class="stat {cal_cls}">{cal_short}</span>
    </span>
  </div>
  <p class="cal {cal_cls}">{calibration}</p>
  <div role="tablist" aria-label="Stages of the review">{tabs}</div>
</header>
<main>{bodies}</main>

<script>
const PANES = {pane_json};
// The open pane rides in the URL hash, so a refresh comes back to the work rather than
// to the first tab. Rebuilding after every ruling is the normal rhythm here, and
// re-navigating to the pane you were in each time is a tax on the loop (D81).
function show(want) {{
  if (!PANES.includes(want)) return false;
  document.querySelectorAll('[role=tab]').forEach(function (t) {{
    t.setAttribute('aria-selected', String(t.dataset.pane === want));
  }});
  PANES.forEach(function (k) {{
    document.getElementById('pane-' + k).hidden = (k !== want);
  }});
  return true;
}}
document.querySelectorAll('[role=tab]').forEach(function (tab) {{
  tab.addEventListener('click', function () {{
    if (show(tab.dataset.pane)) {{
      history.replaceState(null, '', '#' + tab.dataset.pane);
    }}
  }});
}});
show((location.hash || '').replace('#', ''));
</script>
"""
