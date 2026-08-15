"""annotate_pane — draw a box over a sheet to assert a mark OCR missed (RT-7c, D51).

The last leg of the loop. The review queue can only act on marks the tool already
*located*; a miss has no coordinates, so there is nothing to click. This is where the
reviewer supplies them.

The page deliberately does not convert anything. It reports the drag in pixels and the
displayed size, and the server turns that into manifest coordinates — see `annotate.py`
for why that split is load-bearing rather than tidy.

**A box is a sighting, not a search.** Recording one asserts "I can see this here", with
the reviewer's name and the date. It does not re-run OCR over the region: OCR is an
ingestion-time step whose output is frozen and hashed (D28), and calling an engine at
review time would put a model call on the runtime path (I6). The page says so, because a
reviewer who believes they triggered a re-scan would draw different conclusions from an
empty result than the truth warrants.
"""

from __future__ import annotations

import html
import json


def _e(s: object) -> str:
    return html.escape(str(s), quote=True)


def render(sheets: list[dict], *, reviewer: str | None, on: str | None) -> str:
    """`sheets` = [{page, file, figures, marks}] — already copied beside the console.

    `marks` are the numerals already located on that sheet, pre-converted to top-left
    display fractions by `annotate.box_to_display`. The page positions them; it never
    computes where they go.
    """
    opts = "".join(
        f"<option value='{_e(s['page'])}' data-file='{_e(s['file'])}'>"
        f"p.{_e(s['page'])}{(' — FIG ' + _e(s['figures'])) if s.get('figures') else ''}"
        f"</option>" for s in sheets)
    who = (f"Recording as <b>{_e(reviewer)}</b> on {_e(on)}."
           if reviewer and on else
           "<b>Read-only.</b> Started without a reviewer identity, so a box cannot be "
           "recorded. Restart the server with --reviewer and --on.")
    return (_PAGE.replace("{{OPTS}}", opts or "<option>no sheets</option>")
                 .replace("{{WHO}}", who)
                 .replace("{{SHEETS}}", json.dumps(sheets)))


_PAGE = r"""<meta charset="utf-8"><title>Mark a sheet</title>
<style>
:root{--bg:#f7f5f0;--panel:#fff;--ink:#161c26;--mut:#5d6779;--rule:#dcd6ca;
 --ok:#3f6b52;--okbg:#e9f1ec;--warn:#a2402f;--warnbg:#fbeeeb;--accent:#2f4f8f;
 --sans:ui-sans-serif,system-ui,"Segoe UI",Helvetica,sans-serif;
 --mono:ui-monospace,"SF Mono",Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#0f131a;--panel:#151b24;--ink:#e7e3d9;
 --mut:#98a2b3;--rule:#2a323f;--ok:#7fc39c;--okbg:#16241d;--warn:#e8837a;
 --warnbg:#271619;--accent:#8fb3dd}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14.5px/1.6 var(--sans);
 padding:20px 24px 60px}
.wrap{max-width:1000px;margin:0 auto}
h1{font:600 20px/1.3 var(--sans);margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin:0 0 12px;max-width:74ch}
.who{font-size:12.5px;color:var(--mut);margin:0 0 14px;padding:8px 12px;
 background:var(--panel);border:1px solid var(--rule);border-radius:6px}
.bar{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:0 0 12px}
select,input[type=text]{padding:8px 11px;border:1px solid var(--rule);border-radius:6px;
 background:var(--panel);color:var(--ink);font:14px var(--sans)}
button{padding:8px 15px;border:0;border-radius:6px;background:var(--accent);color:#fff;
 font:600 13.5px var(--sans);cursor:pointer}
button:disabled{opacity:.5;cursor:default}
button.ghost{background:var(--bg);color:var(--mut);border:1px solid var(--rule)}
#stage{position:relative;display:inline-block;max-width:100%;background:var(--panel);
 border:1px solid var(--rule);border-radius:8px;overflow:hidden;cursor:crosshair}
#sheet{display:block;max-width:100%;height:auto;user-select:none;-webkit-user-drag:none}
#rect{position:absolute;border:2px solid var(--accent);background:rgba(47,80,143,.14);
 pointer-events:none;display:none}
.said{font-size:13px;margin:12px 0 0}
.said.ok{color:var(--ok)} .said.bad{color:var(--warn)}
.legend{font-size:12.5px;color:var(--mut);margin:0 0 8px}
.legend b{color:var(--ink)}
#marks{position:absolute;inset:0;pointer-events:none}
.mk{position:absolute;border:1.5px solid var(--ok);background:rgba(63,107,82,.10);
 pointer-events:auto;cursor:pointer;border-radius:2px}
.mk[data-human="1"]{border-color:var(--accent);border-style:dashed;
 background:rgba(47,80,143,.12)}
.mk:hover{background:rgba(63,107,82,.26)}
.mk.on{border-width:2.5px;background:rgba(168,64,47,.22);border-color:var(--warn)}
.mk span{position:absolute;top:-15px;left:-1px;font:600 10px/1.4 var(--mono);
 background:var(--panel);border:1px solid var(--rule);border-radius:3px;padding:0 3px;
 white-space:nowrap}
.sel{margin:12px 0 0;padding:12px 15px;background:var(--panel);border:1px solid var(--rule);
 border-radius:8px;max-width:640px}
.sel p{margin:0 0 9px;font-size:14px}
.sel .muted{color:var(--mut);font:12px var(--mono)}
.sel .prov{color:var(--mut);font-size:12px}
.sel .acts{display:flex;gap:7px;flex-wrap:wrap;align-items:center}
.sel .fine{margin:9px 0 0;font-size:12px;color:var(--mut)}
button.danger{background:var(--warn)}
.note{margin-top:22px;padding-top:14px;border-top:1px solid var(--rule);
 font-size:12.5px;color:var(--mut);max-width:74ch}
.note b{color:var(--ink)}
</style>
<div class="wrap">
  <h1>Mark something OCR missed</h1>
  <p class="sub">Drag a box around a reference numeral you can see on the sheet, then name
  it. The queue can only offer marks the tool already located — a miss has no coordinates,
  so this is where you supply them.</p>
  <p class="who">{{WHO}}</p>

  <div class="bar">
    <select id="page">{{OPTS}}</select>
    <input type="text" id="label" placeholder="what is it? e.g. 14a, A, D3" size="14">
    <button id="save" disabled>Record this mark</button>
    <button id="clear" class="ghost">Clear box</button>
  </div>

  <p class="legend"><label><input type="checkbox" id="show" checked> show the
  <b id="nmarks">0</b> marks already located on this sheet</label> — click one to revise
  or remove it.</p>

  <div id="stage"><img id="sheet" alt="drawing sheet"><div id="marks"></div>
   <div id="rect"></div></div>
  <p class="said" id="said"></p>

  <div id="sel" class="sel" hidden>
    <p><b id="selLabel"></b> <span class="muted" id="selWhere"></span>
      <span class="prov" id="selProv"></span></p>
    <div class="acts">
      <input type="text" id="newLabel" placeholder="corrected label" size="12">
      <button id="doCorrect">Revise this reading</button>
      <button id="doRefute" class="danger">Not there — remove</button>
      <button id="deselect" class="ghost">Cancel</button>
    </div>
    <p class="fine">Neither edits the record. A revision appends a new judgment naming
    the one it supersedes, and both stay readable.</p>
  </div>

  <p class="note">A recorded box is a <b>sighting</b>: your name, the date, and where you
  saw it. It does <b>not</b> re-run OCR over the region — OCR is an ingestion-time step
  whose output is frozen and hashed, and running an engine at review time would put a
  model call on the path this system's determinism depends on. Your mark can inform a
  later ingestion pass; it does not silently become one.</p>
</div>
<script>
const SHEETS = {{SHEETS}};
const img = document.getElementById('sheet'), stage = document.getElementById('stage'),
      rect = document.getElementById('rect'), sel = document.getElementById('page'),
      said = document.getElementById('said'), save = document.getElementById('save');
let box = null, drag = null;

const marksEl = document.getElementById('marks'), selBox = document.getElementById('sel');
let picked = null;

function currentSheet() {
  return SHEETS.find(s => String(s.page) === String(sel.value)) || {marks: []};
}
function drawMarks() {
  const s = currentSheet(), on = document.getElementById('show').checked;
  document.getElementById('nmarks').textContent = (s.marks || []).length;
  marksEl.innerHTML = '';
  if (!on) return;
  (s.marks || []).forEach((m, i) => {
    // Positions arrive pre-converted from Python (annotate.box_to_display). The page
    // places them; it never works out where they go.
    const d = document.createElement('div');
    d.className = 'mk'; d.dataset.i = i; d.dataset.human = m.human ? '1' : '0';
    Object.assign(d.style, {left: (m.left * 100) + '%', top: (m.top * 100) + '%',
      width: (m.width * 100) + '%', height: (m.height * 100) + '%'});
    d.innerHTML = '<span>' + m.numeral + (m.human ? ' \u25c9' : '') + '</span>';
    marksEl.appendChild(d);
  });
}
function pick(i) {
  picked = i;
  const m = currentSheet().marks[i];
  document.querySelectorAll('.mk').forEach(e =>
    e.classList.toggle('on', e.dataset.i === String(i)));
  document.getElementById('selLabel').textContent = m.numeral;
  document.getElementById('selWhere').textContent =
    'x ' + m.left.toFixed(3) + '  y ' + m.top.toFixed(3);
  document.getElementById('selProv').textContent = m.human
    ? '· recorded by ' + (m.by || 'a reviewer') + (m.on ? ' on ' + m.on : '')
    : '· located by OCR' + (m.engines ? ' (' + m.engines + ')' : '');
  selBox.hidden = false;
}
function deselect() {
  picked = null; selBox.hidden = true;
  document.querySelectorAll('.mk').forEach(e => e.classList.remove('on'));
}
document.getElementById('show').addEventListener('change', drawMarks);
document.getElementById('deselect').addEventListener('click', deselect);

async function judge(kind, extra) {
  const m = currentSheet().marks[picked];
  const said = document.getElementById('said');
  said.className = 'said'; said.textContent = 'recording…';
  try {
    const r = await fetch('adjudicate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.assign({
        item_id: 'mark:p' + sel.value + ':' + m.numeral, kind: kind,
        target: {page: Number(sel.value), numeral: m.numeral,
                 x: m.x, y: m.y, w: m.width, h: m.height}
      }, extra || {}))
    });
    const d = await r.json();
    if (d.error) { said.className = 'said bad'; said.textContent = d.error; }
    else {
      said.className = 'said ok';
      said.textContent = 'recorded as ' + d.by + ' on ' + d.on +
        ' — rebuild the console to see the sheet update.';
      deselect();
    }
  } catch (e) {
    said.className = 'said bad';
    said.textContent = 'no review server — start scripts/serve_console.py';
  }
}
document.getElementById('doRefute').addEventListener('click', () =>
  judge('refute', {note: 'reviewer: nothing is drawn here'}));
document.getElementById('doCorrect').addEventListener('click', () => {
  const v = document.getElementById('newLabel').value.trim();
  const said = document.getElementById('said');
  if (!v) { said.className = 'said bad'; said.textContent = 'Type the corrected label.'; return; }
  const m = currentSheet().marks[picked];
  judge('correct', {value: {numeral: v, x: m.x, y: m.y, w: m.width, h: m.height},
                    note: 'reviewer: reads as ' + v + ', not ' + m.numeral});
});

function loadSheet() {
  const o = sel.selectedOptions[0];
  if (o && o.dataset.file) img.src = 'sheets/' + o.dataset.file;
  clearBox(); deselect(); drawMarks();
}
img.addEventListener('load', drawMarks);
function clearBox() { box = null; rect.style.display = 'none'; save.disabled = true; }
sel.addEventListener('change', loadSheet);
document.getElementById('clear').addEventListener('click', clearBox);

function at(ev) {
  const r = img.getBoundingClientRect();
  return {x: Math.max(0, Math.min(ev.clientX - r.left, r.width)),
          y: Math.max(0, Math.min(ev.clientY - r.top, r.height))};
}
stage.addEventListener('pointerdown', ev => {
  // A press that lands ON an existing mark SELECTS it; only empty space starts a new
  // box. Without this branch the mark is unreachable by mouse: preventDefault()
  // suppresses the click, and setPointerCapture() retargets every later pointer event
  // to the stage, so the mark's own click handler never fires. It looked wired --
  // dispatching .click() from the console selected it fine -- because a synthetic
  // click skips hit-testing and pointer capture, which are the two things breaking it.
  const mk = ev.target.closest && ev.target.closest('.mk');
  if (mk) { pick(Number(mk.dataset.i)); return; }
  deselect();
  ev.preventDefault(); drag = at(ev); stage.setPointerCapture(ev.pointerId);
});
stage.addEventListener('pointermove', ev => {
  if (!drag) return;
  const p = at(ev);
  Object.assign(rect.style, {display: 'block',
    left: Math.min(drag.x, p.x) + 'px', top: Math.min(drag.y, p.y) + 'px',
    width: Math.abs(p.x - drag.x) + 'px', height: Math.abs(p.y - drag.y) + 'px'});
});
stage.addEventListener('pointerup', ev => {
  if (!drag) return;
  const p = at(ev), r = img.getBoundingClientRect();
  // Pixels and the displayed size only. The page never computes a normalized
  // coordinate: that conversion lives in Python where a test can reach it.
  box = {x0: drag.x, y0: drag.y, x1: p.x, y1: p.y, width: r.width, height: r.height};
  drag = null;
  save.disabled = !(Math.abs(box.x1 - box.x0) > 3 && Math.abs(box.y1 - box.y0) > 3);
  said.textContent = save.disabled ? 'That is a click, not a box — drag across the mark.' : '';
  said.className = 'said' + (save.disabled ? ' bad' : '');
});

save.addEventListener('click', async () => {
  const label = document.getElementById('label').value.trim();
  if (!label) { said.className = 'said bad'; said.textContent = 'Name the mark first.'; return; }
  if (!box) return;
  save.disabled = true; said.className = 'said'; said.textContent = 'recording…';
  try {
    const r = await fetch('adjudicate', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        item_id: 'drawn:p' + sel.value + ':' + label, kind: 'confirm',
        target: {page: Number(sel.value), numeral: label}, box_px: box,
        note: 'drawn on the sheet by the reviewer'
      })
    });
    const d = await r.json();
    if (d.error) { said.className = 'said bad'; said.textContent = d.error; save.disabled = false; }
    else {
      said.className = 'said ok';
      said.textContent = 'recorded “' + label + '” as ' + d.by + ' on ' + d.on +
        ' — rebuild the console to see it on the sheet.';
      clearBox(); document.getElementById('label').value = '';
    }
  } catch (e) {
    said.className = 'said bad';
    said.textContent = 'no review server — start scripts/serve_console.py';
    save.disabled = false;
  }
});
loadSheet();
</script>
"""
