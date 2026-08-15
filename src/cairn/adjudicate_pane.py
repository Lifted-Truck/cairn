"""adjudicate_pane — the review queue, with judgment recorded in place (RT-7b, D50).

Closes the loop the product roadmap identified as Cairn's one structural gap: the expert
whose judgment the system exists to support could read every surface and write to none of
them. RT-7a made judgment *durable*; this makes it *reachable* — a worklist where each row
is one decision and one click, instead of hand-typing coordinates into a CLI.

Three properties the page must not lose:

  · **Confirming is not the default.** Nothing is pre-selected and there is no "accept
    all". A queue that can be cleared without reading it produces a record that says a
    human looked when none did, which is worse than no record.
  · **The reviewer is named by the server, not the page.** Provenance comes from who
    started the session, so a judgment cannot be attributed by whoever has the tab open.
  · **An empty queue is not a clean bill of health,** and it says so: these checks compare
    drawings against the specification, so anything absent from both is invisible to all
    of them.
"""

from __future__ import annotations

import html
import json

from .annotate import box_to_display


def _e(s: object) -> str:
    return html.escape(str(s), quote=True)


def _crop(item, sheet_files: dict[int, str]) -> str:
    """A zoomed window of the sheet centred on the flagged spot, with the spot ringed.

    Scaled in the browser rather than pre-cropped in Python, because the sheet image is
    already copied beside the console and a second cropped copy per row would duplicate
    a confidential drawing many times over on disk for no gain.

    A `recited_not_drawn` item has no coordinates by construction — that IS the flag —
    so it gets a stated absence rather than an empty frame, which would read as "the
    system looked and found nothing here" instead of "the system has no location".

    The ring is drawn at the mark's REAL width and height, not a fixed size. Marks
    vary enormously — on sheet 9, "CL" is 0.050 x 0.014 of the page and "LTM" on sheet
    2 is 0.031 x 0.053 (tall, because it is rotated text) — so a fixed ring at the box
    centre sat beside the glyphs on wide marks and across the middle of tall ones, and
    read as a positioning bug. The reviewer is being asked whether OCR was right about
    a REGION, so the region is what gets drawn.

    The centre is computed here, through `annotate.box_to_display`, and NOT in the
    page's JavaScript. Manifest `y` is measured from the BOTTOM to the box's lower
    edge; a browser wants distance from the top. The first version of this crop did the
    arithmetic in JS as if `y` were top-down, and put the ring beside numeral 12 rather
    than on it — the exact failure `box_to_display`'s docstring warns about ("one
    tested function and one hopeful line of JavaScript"). The tested half now owns it.
    """
    file = sheet_files.get(item.page) if item.page is not None else None
    if file is None or item.x is None or item.y is None:
        if item.page is None and sheet_files:
            # No coordinates BECAUSE nothing was located — so the useful move is not to
            # explain the absence but to let the reviewer supply what OCR missed, here,
            # against the whole sheet. Telling them "not located" and stopping sends
            # them to another pane to do the one thing this row is asking for.
            return _locate_surface(item, sheet_files)
        why = ("nothing to show — this numeral was not located on any sheet, and no "
               "drawing sheets are available to search" if item.page is None else
               f"no sheet image available for page {item.page}")
        return f"<p class='nocrop'>{_e(why)}</p>"
    d = box_to_display(item.x, item.y, item.w or 0.0, item.h or 0.0)
    cx, cy = d["left"] + d["width"] / 2, d["top"] + d["height"] / 2
    return (f"<div class='crop' data-file='{_e(file)}' "
            f"data-x='{cx:.6f}' data-y='{cy:.6f}' "
            f"data-w='{d['width']:.6f}' data-h='{d['height']:.6f}'>"
            f"<img alt='sheet {_e(item.page)} near numeral {_e(item.label)}'>"
            f"<span class='ring'></span></div>"
            f"<p class='cropcap'>Sheet {_e(item.page)} at "
            f"({cx:.3f}, {cy:.3f} from the top-left) — the ring is where OCR placed "
            f"<b>{_e(item.label)}</b>. Zoom, or open the Drawings pane for the "
            f"whole sheet.</p>")


def _locate_surface(item, sheet_files: dict[int, str]) -> str:
    """Pick a sheet, drag a box, record where the numeral actually is.

    A `recited_not_drawn` row says the specification recites a numeral that OCR could
    not find on any sheet — an OCR miss and a drawing omission are indistinguishable
    from here (D10), and only a human can tell them apart by looking. So this is the
    row that most needs a drawing surface, and it was the one row that had none.

    Pixels only: the box is sent as browser pixels plus the displayed image size, and
    the conversion to manifest coordinates happens server-side in Python where a
    Layer-0 test reaches it (D51). The page never invents a normalized coordinate.
    """
    opts = "".join(
        f"<option value='{_e(p)}' data-file='{_e(f)}'>p.{_e(p)}</option>"
        for p, f in sorted(sheet_files.items()))
    return (
        "<div class='locate'>"
        f"<p class='nocrop'>Not located by OCR on any sheet. If you can see "
        f"<b>{_e(item.label)}</b> on a drawing, box it here and the location becomes "
        f"part of the record.</p>"
        "<div class='lbar'>"
        f"<select class='lpage'>{opts}</select>"
        "<button type='button' class='lopen'>Show the sheet</button>"
        "<button type='button' class='lsave' disabled>Record this location</button>"
        "<button type='button' class='lclear ghost'>Clear box</button>"
        "</div>"
        "<div class='lstage' hidden><img alt='drawing sheet'><div class='lrect'></div></div>"
        "</div>")


def render(items, *, reviewer: str | None, on: str | None,
           sheet_files: dict[int, str] | None = None) -> str:
    """`sheet_files` maps page → the sheet image beside the console (`sheets/<file>`).

    Without it the queue asks "is 20 really drawn here?" and shows nothing to look at,
    which leaves the reviewer to open the Drawings pane, find the sheet, and locate the
    spot by eye — for every row. A judgment surface that does not show the evidence
    invites judgment made on the description of the evidence.
    """
    sheet_files = sheet_files or {}
    rows = []
    for i in items:
        loc = (f"p.{i.page}" if i.page is not None else "not located")
        target = json.dumps({k: v for k, v in
                             (("page", i.page), ("numeral", i.label),
                              ("x", i.x), ("y", i.y)) if v is not None})
        rows.append(
            f"<li class='item' data-id='{_e(i.item_id)}' data-target='{_e(target)}'>"
            f"<div class='hd'><span class='kind k-{_e(i.kind)}'>{_e(i.kind.replace('_',' '))}"
            f"</span><span class='lbl'>{_e(i.label)}</span>"
            f"<span class='loc'>{_e(loc)}</span></div>"
            f"<p class='q'>{_e(i.question)}</p>"
            f"<p class='d'>{_e(i.detail)}</p>"
            + _crop(i, sheet_files) +
            "<div class='acts'>"
            "<button data-kind='confirm'>It is there</button>"
            "<button data-kind='refute'>It is not there</button>"
            "<button data-kind='note' class='ghost'>Note only</button>"
            "<span class='said'></span></div></li>")

    who = (f"Recording as <b>{_e(reviewer)}</b> on {_e(on)}."
           if reviewer and on else
           "<b>Read-only.</b> This server was started without a reviewer identity, so "
           "judgments cannot be recorded. Restart with --reviewer and --on.")
    empty = ("<li class='empty'><b>Nothing outstanding.</b> That is not a clean bill of "
             "health: these checks compare the drawings against the specification, so "
             "anything absent from both is invisible to all of them.</li>")
    return _PAGE.replace("{{ROWS}}", "".join(rows) or empty) \
                .replace("{{WHO}}", who) \
                .replace("{{N}}", str(len(items)))


_PAGE = r"""<meta charset="utf-8"><title>Adjudicate</title>
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
 padding:22px 26px 60px}
.wrap{max-width:880px;margin:0 auto}
h1{font:600 20px/1.3 var(--sans);margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin:0 0 6px;max-width:70ch}
.who{font-size:12.5px;color:var(--mut);margin:0 0 20px;padding:8px 12px;
 background:var(--panel);border:1px solid var(--rule);border-radius:6px}
ul{list-style:none;padding:0;margin:0}
.item{background:var(--panel);border:1px solid var(--rule);border-radius:9px;
 padding:14px 16px;margin:0 0 11px}
.item.done{opacity:.55}
.hd{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.kind{font:600 10.5px/1.7 var(--sans);text-transform:uppercase;letter-spacing:.05em;
 padding:1px 8px;border-radius:10px;background:var(--warnbg);color:var(--warn)}
.kind.k-recited_not_drawn{background:var(--bg);color:var(--mut)}
.lbl{font:700 17px/1 var(--mono)}
.loc{font:11.5px var(--mono);color:var(--mut)}
.q{margin:0 0 4px;font-weight:600;font-size:14.5px}
.d{margin:0 0 11px;font-size:13px;color:var(--mut);max-width:72ch}
.acts{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
button{padding:6px 13px;border:1px solid var(--rule);border-radius:6px;background:var(--bg);
 color:var(--ink);font:600 13px var(--sans);cursor:pointer}
button:hover{border-color:var(--accent)}
button.ghost{font-weight:400;color:var(--mut)}
button:disabled{opacity:.5;cursor:default}
.said{font-size:12.5px;color:var(--ok)}
.said.bad{color:var(--warn)}
.crop{position:relative;width:100%;max-width:420px;height:190px;overflow:hidden;
 border:1px solid var(--rule);border-radius:6px;background:#fff;margin:0 0 5px}
.crop img{position:absolute;max-width:none;image-rendering:auto}
.crop .ring{position:absolute;left:50%;top:50%;
 transform:translate(-50%,-50%);border:2px solid #c8402c;border-radius:3px;
 box-shadow:0 0 0 9999px rgba(0,0,0,.10);pointer-events:none}
.crop .zoom{position:absolute;right:6px;bottom:6px;display:flex;gap:4px}
.crop .zoom button{padding:1px 8px;font:600 13px var(--mono);opacity:.9}
.cropcap{margin:0 0 11px;font:12px var(--sans);color:var(--mut);max-width:72ch}
.locate{margin:0 0 11px}
.lbar{display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:0 0 8px}
.lbar select{padding:5px 8px;border:1px solid var(--rule);border-radius:6px;
 background:var(--bg);color:var(--ink);font:13px var(--sans)}
.lbar button{padding:5px 11px;font-size:12.5px}
.lstage{position:relative;display:inline-block;max-width:100%;
 border:1px solid var(--rule);border-radius:6px;overflow:hidden;background:#fff}
.lstage img{display:block;max-width:100%;height:auto;touch-action:none}
.lrect{position:absolute;border:2px solid #c8402c;background:rgba(200,64,44,.14);
 pointer-events:none;display:none}
.nocrop{margin:0 0 11px;font:12.5px var(--sans);color:var(--mut);
 padding:8px 11px;background:var(--bg);border:1px dashed var(--rule);border-radius:6px}
.empty{background:var(--panel);border:1px solid var(--rule);border-radius:9px;
 padding:18px;color:var(--mut);font-size:13.5px}
.note{margin-top:26px;padding-top:14px;border-top:1px solid var(--rule);
 font-size:12.5px;color:var(--mut);max-width:72ch}
</style>
<div class="wrap">
  <h1>Needs a human — {{N}} outstanding</h1>
  <p class="sub">Ranked by what costs most to get wrong, not by count. Nothing is
  pre-selected and there is no bulk accept: a queue that can be cleared without reading it
  produces a record saying someone looked when nobody did.</p>
  <p class="who">{{WHO}}</p>
  <ul id="q">{{ROWS}}</ul>
  <p class="note">Every judgment is appended to a hash-chained record with your name and
  the date. Nothing is edited or deleted — a later change of mind is a new entry that
  supersedes the old one, and both remain readable.</p>
</div>
<script>
// Position each crop so the flagged point sits at the frame's centre, under the ring.
// x/y are fractions of the sheet, so the maths needs the image's DISPLAYED size, which
// is only known after load — hence a load handler rather than inline styles.
document.querySelectorAll('.crop').forEach(box => {
  const img = box.querySelector('img');
  let z = 5;                                   // starting magnification
  function place() {
    const w = box.clientWidth * z;
    img.style.width = w + 'px';
    const h = img.clientHeight;                // set by the width, aspect preserved
    img.style.left = (box.clientWidth / 2 - box.dataset.x * w) + 'px';
    img.style.top  = (box.clientHeight / 2 - box.dataset.y * h) + 'px';
    // The ring is the mark's real extent, scaled with the image -- the reviewer is
    // judging whether OCR was right about a REGION, so draw the region.
    const ring = box.querySelector('.ring');
    ring.style.width  = Math.max(8, box.dataset.w * w) + 'px';
    ring.style.height = Math.max(8, box.dataset.h * h) + 'px';
  }
  img.addEventListener('load', place);
  img.src = 'sheets/' + box.dataset.file;
  const zoom = document.createElement('div');
  zoom.className = 'zoom';
  for (const [lbl, f] of [['−', 1 / 1.6], ['+', 1.6]]) {
    const b = document.createElement('button');
    b.textContent = lbl;
    b.addEventListener('click', () => {
      z = Math.min(24, Math.max(1, z * f));    // 1 = whole sheet width, 24 = glyph level
      place();
    });
    zoom.appendChild(b);
  }
  box.appendChild(zoom);
});

// Reconcile this page against the live judgment log. The page is a static build; the
// log moves on. Without this, a row already ruled on still offers its buttons, and
// clicking one collides with the reviewer's own earlier record.
fetch('judged').then(r => r.json()).then(d => {
  for (const [id, j] of Object.entries(d.judged || {})) {
    const li = document.querySelector(`.item[data-id="${CSS.escape(id)}"]`);
    if (!li) continue;
    li.classList.add('done');
    li.querySelectorAll('button').forEach(b => b.disabled = true);
    li.querySelector('.said').textContent =
      `already ${j.kind}ed by ${j.by} on ${j.on}`;
  }
  const left = document.querySelectorAll('.item:not(.done)').length;
  const h = document.querySelector('h1');
  if (h) h.textContent = `Needs a human — ${left} outstanding`;
}).catch(() => {});   // no server: the page still reads, it just cannot reconcile

// Locate-it-yourself, for a row OCR could not place. Pixels only -- the conversion
// to manifest coordinates lives in Python (D51), so the page never computes one.
document.querySelectorAll('.locate').forEach(loc => {
  const li = loc.closest('.item');
  const sel = loc.querySelector('.lpage'), stage = loc.querySelector('.lstage');
  const img = stage.querySelector('img'), rect = loc.querySelector('.lrect');
  const save = loc.querySelector('.lsave'), said = li.querySelector('.said');
  let box = null, drag = null;
  const clear = () => { box = null; rect.style.display = 'none'; save.disabled = true; };
  const show = () => {
    const o = sel.selectedOptions[0];
    if (o) { img.src = 'sheets/' + o.dataset.file; stage.hidden = false; clear(); }
  };
  loc.querySelector('.lopen').addEventListener('click', show);
  loc.querySelector('.lclear').addEventListener('click', clear);
  sel.addEventListener('change', () => { if (!stage.hidden) show(); });
  const at = ev => {
    const r = img.getBoundingClientRect();
    return {x: Math.max(0, Math.min(ev.clientX - r.left, r.width)),
            y: Math.max(0, Math.min(ev.clientY - r.top, r.height))};
  };
  img.addEventListener('pointerdown', ev => {
    ev.preventDefault(); drag = at(ev); img.setPointerCapture(ev.pointerId);
  });
  img.addEventListener('pointermove', ev => {
    if (!drag) return;
    const p = at(ev);
    Object.assign(rect.style, {display: 'block',
      left: Math.min(drag.x, p.x) + 'px', top: Math.min(drag.y, p.y) + 'px',
      width: Math.abs(p.x - drag.x) + 'px', height: Math.abs(p.y - drag.y) + 'px'});
  });
  img.addEventListener('pointerup', ev => {
    if (!drag) return;
    const p = at(ev), r = img.getBoundingClientRect();
    box = {x0: drag.x, y0: drag.y, x1: p.x, y1: p.y, width: r.width, height: r.height};
    drag = null;
    save.disabled = !(Math.abs(box.x1 - box.x0) > 3 && Math.abs(box.y1 - box.y0) > 3);
    said.className = 'said' + (save.disabled ? ' bad' : '');
    said.textContent = save.disabled
      ? 'That is a click, not a box \u2014 drag across the numeral.' : '';
  });
  save.addEventListener('click', async () => {
    if (!box) return;
    save.disabled = true; said.className = 'said'; said.textContent = 'recording\u2026';
    try {
      const r = await fetch('adjudicate', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          item_id: li.dataset.id, kind: 'confirm',
          target: {page: Number(sel.value), numeral: JSON.parse(li.dataset.target).numeral},
          box_px: box, note: 'located on the sheet by the reviewer'})
      });
      const d = await r.json();
      if (d.error) {
        said.className = 'said bad'; said.textContent = d.error; save.disabled = false;
      } else {
        said.textContent = 'recorded as ' + d.by + ' on ' + d.on +
          ' \u2014 rebuild the console to see it on the sheet.';
        li.classList.add('done');
        li.querySelectorAll('button').forEach(b => b.disabled = true);
      }
    } catch (e) {
      said.className = 'said bad';
      said.textContent = 'no review server \u2014 start scripts/serve_console.py';
      save.disabled = false;
    }
  });
});

document.querySelectorAll('.item .acts button').forEach(btn => {
  btn.addEventListener('click', async () => {
    const li = btn.closest('.item');
    const said = li.querySelector('.said');
    const note = (btn.dataset.kind === 'note')
      ? (prompt('Note (recorded verbatim, asserts nothing about the mark):') || '') : '';
    if (btn.dataset.kind === 'note' && !note) return;
    li.querySelectorAll('button').forEach(b => b.disabled = true);
    said.className = 'said'; said.textContent = 'recording…';
    try {
      const r = await fetch('adjudicate', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          item_id: li.dataset.id, kind: btn.dataset.kind,
          target: JSON.parse(li.dataset.target), note: note
        })
      });
      const d = await r.json();
      if (d.already) {
        said.className = 'said'; said.textContent = d.error;
        li.classList.add('done');          // it IS judged; the page was just stale
      } else if (d.error) {
        said.className = 'said bad'; said.textContent = d.error;
        li.querySelectorAll('button').forEach(b => b.disabled = false);
      } else {
        said.textContent = 'recorded as ' + d.by + ' on ' + d.on;
        li.classList.add('done');
      }
    } catch (e) {
      said.className = 'said bad';
      said.textContent = 'no review server — start scripts/serve_console.py';
      li.querySelectorAll('button').forEach(b => b.disabled = false);
    }
  });
});
</script>
"""
