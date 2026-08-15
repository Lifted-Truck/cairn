"""refresh — the one control that reconciles a static console with a moving log (D79).

The console is built once and then judged against for hours. A ruling lands in the
append-only log immediately, but every surface derived from it is HTML written at build
time: the queue, the reconciliation counts, the interpretation panel, the marks drawn
on a sheet. Reloading the browser re-fetches the same bytes, so the reviewer's own
decision appears to have done nothing until somebody re-runs a script from a terminal.

That is a loop with a manual step in the middle, and the manual step is invisible — the
page gives no sign that what it shows is older than what the reviewer just did. This
button closes it: rebuild, then reload.

Deliberately **not** automatic. A console that regenerated itself under the reviewer
would move the ground while they read; the rebuild is a thing they ask for and can see
finish. It is also the honest place to say the page can be stale, which no amount of
reloading was communicating.

Every generated page includes this, because a reviewer opens whichever pane the work is
in and should never have to go looking for the control that makes it current.
"""

from __future__ import annotations

BUTTON_CSS = """
.cairn-refresh { position:fixed; right:14px; bottom:14px; z-index:9999;
  display:flex; align-items:center; gap:8px; padding:7px 13px; cursor:pointer;
  font:600 12.5px/1.2 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
  color:#e7e3d9; background:#1b2330; border:1px solid #38414f; border-radius:20px;
  box-shadow:0 2px 10px rgba(0,0,0,.35); }
.cairn-refresh:hover { border-color:#8fb3dd; }
.cairn-refresh[disabled] { opacity:.6; cursor:progress; }
.cairn-refresh .msg { font-weight:400; color:#98a2b3; }
@media (prefers-color-scheme: light) {
  .cairn-refresh { color:#161c26; background:#fff; border-color:#dcd6ca; }
  .cairn-refresh .msg { color:#5d6779; }
}
"""

# `top.location.reload()` rather than `location.reload()`: every pane is rendered inside
# an iframe in the console frame, and reloading only the iframe leaves the header — with
# its adjudication and open-reading counts — showing the previous build.
BUTTON_HTML = """
<button class="cairn-refresh" type="button" title="Rebuild every pane from the current
store, log and rulings, then reload">↻ Refresh<span class="msg"></span></button>
<script>
(() => {
  const b = document.querySelector('.cairn-refresh'), m = b.querySelector('.msg');
  b.addEventListener('click', async () => {
    b.disabled = true; m.textContent = ' rebuilding…';
    try {
      const r = await fetch('rebuild', {method: 'POST',
                                        headers: {'Content-Type': 'application/json'},
                                        body: '{}'});
      const d = await r.json();
      if (d.error) { m.textContent = ' ' + d.error; b.disabled = false; return; }
      m.textContent = ' reloading…';
      (window.top || window).location.reload();
    } catch (e) {
      m.textContent = ' no review server';
      b.disabled = false;
    }
  });
})();
</script>
"""


def button(*, style_tag: bool = True) -> str:
    """The refresh control, ready to append to a page's body.

    `style_tag=False` for pages that inline their CSS in one block and would rather add
    `BUTTON_CSS` there — the markup is the same either way.
    """
    css = f"<style>{BUTTON_CSS}</style>" if style_tag else ""
    return css + BUTTON_HTML
