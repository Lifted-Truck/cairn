"""locate_pane — ranked term search over the corpus (RT-10b, D49; reframed D81).

**A search box, not an oracle.** This pane used to run `check_support` and report its
verdict — *supported* or *insufficient* — which was a mistake on this corpus and a
confusing one. The support floor here is **non-separable** (D53/D55): answerable and
content-absent questions overlap, so the verdict carries almost no information, and in
practice nearly every query a reviewer typed came back as an abstention. A pane whose
main output is a refusal the header already says is unreliable is worse than no pane.

So it does the honest thing instead: rank the spans by BM25 and show them. No floor, no
verdict, no abstention — the reviewer reads passages and decides, which is all the
support decision was ever standing in for here.

**Still the real retrieval.** The page calls `search_corpus`, the same tool the agent
calls, rather than reimplementing BM25 in JavaScript — a second retrieval implementation
is a second oracle that can drift, in a system whose claim is that the same corpus and
query give the same result (I6).

When an agent is wired into this surface, the abstention decision belongs to *it*, with
its reasoning shown — not to a floor that does not separate.
"""

from __future__ import annotations

from .refresh import button


def render(*, calibrated: bool = True, calibration: str = "") -> str:
    """The arguments are kept and ignored on purpose.

    They described the support floor, which this pane no longer applies — but the
    calibration state still belongs to the console header, and the caller passing it
    here is how it stays wired when an agent (with a real abstention decision) is put
    behind this surface. Dropping the parameters would make that a signature change
    rather than a body change.
    """
    return _PAGE + button()


_PAGE = r"""<meta charset="utf-8"><title>Locate</title>
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
.wrap{max-width:860px;margin:0 auto}
h1{font:600 20px/1.3 var(--sans);margin:0 0 4px}
.sub{color:var(--mut);font-size:13px;margin:0 0 16px;max-width:68ch}
.cal{font-size:12.5px;padding:8px 12px;border-radius:6px;margin:0 0 18px}
.cal.ok{background:var(--okbg);color:var(--ok)}
.cal.warn{background:var(--warnbg);color:var(--warn);font-weight:500}
form{display:flex;gap:8px;margin:0 0 6px}
input[type=text]{flex:1;padding:10px 13px;border:1px solid var(--rule);border-radius:7px;
 background:var(--panel);color:var(--ink);font:15px var(--sans)}
button{padding:10px 18px;border:0;border-radius:7px;background:var(--accent);color:#fff;
 font:600 14px var(--sans);cursor:pointer}
button:disabled{opacity:.55;cursor:default}
.hint{font-size:12px;color:var(--mut);margin:0 0 22px}
.verdict{border-radius:8px;padding:13px 16px;margin:0 0 14px;font-size:14px}
.verdict.supported{background:var(--okbg);color:var(--ok)}
.verdict.insufficient{background:var(--warnbg);color:var(--warn)}
.verdict b{display:block;font-size:15px;margin-bottom:3px}
.span{background:var(--panel);border:1px solid var(--rule);border-left:3px solid var(--accent);
 border-radius:0 7px 7px 0;padding:11px 14px;margin:0 0 9px}
.span .loc{font:11.5px var(--mono);color:var(--mut);margin-bottom:5px}
.span .txt{font:14px/1.6 Georgia,serif}
.span.near{border-left-color:var(--mut);opacity:.9}
.err{background:var(--warnbg);color:var(--warn);padding:11px 14px;border-radius:7px;
 font-size:13.5px}
.note-flag{background:var(--panel);border:1px solid var(--rule);
 border-left:3px solid var(--warn);border-radius:8px;padding:10px 13px;margin:0 0 9px;
 font-size:13px;color:var(--ink)}
.note-flag b{display:block;text-transform:uppercase;letter-spacing:.05em;
 font-size:10.5px;color:var(--warn);margin-bottom:3px}
.note-flag .terms{display:block;margin-top:5px;font:12px var(--mono);color:var(--mut)}
.note{margin-top:26px;padding-top:14px;border-top:1px solid var(--rule);
 font-size:12.5px;color:var(--mut);max-width:70ch}
</style>
<div class="wrap">
  <h1>Search the corpus</h1>
  <p class="sub">Type terms; get the passages that contain them, best match first. This
  is a <b>search box</b> — it does not decide whether anything answers your question, and
  it never abstains.</p>

  <form id="f">
    <input type="text" id="q" placeholder="e.g. magnetron wattage, dosing siphon, ash outlet"
           autocomplete="off" aria-label="Search terms">
    <button id="go">Search</button>
  </form>
  <p class="hint">Runs <code>search_corpus</code> — the same retrieval the agent uses, so
  the two can never drift apart.</p>

  <div id="out"></div>

  <p class="note"><b>Matching is exact-word.</b> Retrieval does no stemming, so a query
  in a different form from the document finds nothing at all — <code>magnetron</code>
  returns no passages while <code>magnetrons</code> returns three. That, more than the
  floor, is why natural-sounding questions used to come back empty here.</p>

  <p class="note">This pane used to report a <b>support verdict</b> (supported /
  insufficient). On this corpus that floor does <b>not separate</b> answerable questions
  from content-absent ones, so the verdict carried almost no information and nearly every
  query came back as an abstention. Ranking passages and letting you read them is the
  honest version of what that decision was standing in for. When an agent is wired into
  this pane, the abstention becomes <i>its</i> judgment, shown with its reasoning —
  not a threshold that cannot tell the two cases apart.</p>
</div>
<script>
const out = document.getElementById('out');
const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

// A hit is {span_id, score}; span_id is "doc@start-end". The TEXT is fetched through
// get_span, which re-verifies the document hash (I3) — so what the reviewer reads is
// exactly what verification would confirm, not a cached copy that could have drifted.
async function spanText(spanId) {
  const m = /^(.*)@(\d+)-(\d+)$/.exec(spanId);
  if (!m) return {loc: spanId, text: ''};
  const [, doc, start, end] = m;
  try {
    const r = await fetch('tool/get_span', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({doc_id: doc, start: Number(start), end: Number(end)})
    });
    const d = await r.json();
    return {loc: doc + '  ' + start + '–' + end, text: d.text || d.error || ''};
  } catch (e) {
    return {loc: doc + '  ' + start + '–' + end, text: ''};
  }
}

async function spanCard(h, near) {
  const s = await spanText(h.span_id);
  const score = (h.score != null) ? '  ·  score ' + h.score.toFixed(2) : '';
  return '<div class="span' + (near ? ' near' : '') + '">' +
         '<div class="loc">' + esc(s.loc) + esc(score) + '</div>' +
         '<div class="txt">' + esc(s.text) + '</div></div>';
}

document.getElementById('f').addEventListener('submit', async ev => {
  ev.preventDefault();
  const q = document.getElementById('q').value.trim();
  if (!q) return;
  const btn = document.getElementById('go');
  btn.disabled = true;
  out.innerHTML = '<p class="hint">locating…</p>';
  try {
    // Lint and search together: the findings explain a thin result before the reviewer
    // has to guess at one. Advisory only — the query runs either way (D83).
    let notes = '';
    try {
      const lr = await fetch('tool/lint_question', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({question: q})
      });
      const ld = await lr.json();
      notes = (ld.findings || []).map(f =>
        '<div class="note-flag"><b>' + esc(f.kind.replace(/_/g, ' ')) + '</b>' +
        esc(f.message) +
        (f.terms && f.terms.length
          ? '<span class="terms">' + f.terms.map(esc).join(' · ') + '</span>' : '') +
        '</div>').join('');
    } catch (e) { /* the linter is advice; its absence must never block a search */ }

    const r = await fetch('tool/search_corpus', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query: q, k: 20})
    });
    const d = await r.json();
    if (d.error) { out.innerHTML = '<div class="err">' + esc(d.error) + '</div>'; return; }
    const hits = d.hits || [];
    if (!hits.length) {
      out.innerHTML = notes + '<div class="verdict"><b>No passage contains these terms.</b>' +
        'Matching is on exact words \u2014 there is no stemming, so <i>magnetron</i> ' +
        'finds nothing while <i>magnetrons</i> finds three passages. Try the ' +
        'specification\u2019s own wording, including its plurals.</div>';
      return;
    }
    let html = notes + '<div class="verdict"><b>' + hits.length + ' passage(s), best first</b>' +
      'Ranked by term overlap (BM25). This is a search, not a judgment \u2014 nothing ' +
      'here decides whether a passage answers your question.</div>';
    html += (await Promise.all(hits.map(h => spanCard(h, false)))).join('');
    out.innerHTML = html;
  } catch (e) {
    out.innerHTML = '<div class="err">Could not reach the review server. Start it with ' +
      'python scripts/serve_console.py — this pane needs the real tools, because a ' +
      'second retrieval implementation in the browser could drift from the real one.' +
      '</div>';
  } finally { btn.disabled = false; }
});
</script>
"""
