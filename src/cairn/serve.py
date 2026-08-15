"""serve — a loopback-only review server for the console (RT-10b, D49).

**Why a listener at all.** The console is static HTML, and a static page cannot run BM25.
The tempting alternative — reimplement retrieval in JavaScript so the page is
self-contained — would put a **second oracle** in the system: two retrieval
implementations that can silently drift, in a project whose central claim is that the
same corpus and query give the same result (I6). One mechanism, not two. So the page
calls the *actual* tools, and that requires a transport.

The MCP hardening brief is explicit that a local server's *absence* of a listener is the
win, and one should not be added without cause. The cause here is determinism. The cost is
paid down deliberately:

  · **Loopback only, enforced.** Binding anything but a loopback address is refused
    outright rather than warned about — a review server reachable from the network is a
    different product with a different threat model.
  · **Origin validated.** A browser will happily let `http://evil.example` POST to
    `127.0.0.1`; DNS rebinding makes that reachable even from a hostile page. Requests
    carrying a foreign `Origin` are rejected (the MCP Inspector RCE class).
  · **Read-shaped surface only.** The handlers come from the same registry the MCP server
    uses, so schema validation, path containment (D35) and bounded inputs (D41) apply
    unchanged. No new tool exists here that does not exist there.
  · **No file serving outside the console directory**, canonicalized — the same
    containment reasoning as `DocumentStore.doc_dir`.

This is a **development and review** server. It has no authentication because it has no
remote surface; if that ever changes, it needs the brief's P1 items first, and the change
should be a decision with its own row.
"""

from __future__ import annotations

import datetime as _dt
import http.server
import ipaddress
import json
import socketserver
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from .tools import Tool

MAX_BODY = 64 * 1024          # a query is small; a large body is a mistake or an attack


class NotLoopback(RuntimeError):
    """Refused to bind a non-loopback address (D49)."""


_REPO = Path(__file__).resolve().parent.parent.parent


def _today() -> str:
    """Today, for a rebuild's --on. A judgment's date comes from the SERVER's identity
    (D71); this is only the build stamp, and stamping it with the day the console was
    first built would age silently."""
    return _dt.date.today().isoformat()


def require_loopback(host: str) -> None:
    """Refuse anything the outside world could reach. Raises rather than warns."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host in ("localhost", "localhost.localdomain"):
            return
        raise NotLoopback(
            f"refusing to bind {host!r}: this is a loopback-only review server. "
            f"Serving it on a reachable interface is a different product with a "
            f"different threat model, and needs auth, TLS and a decision row first."
        ) from None
    if not ip.is_loopback:
        raise NotLoopback(f"refusing to bind {host!r}: not a loopback address")


def origin_allowed(origin: str | None, port: int) -> bool:
    """Same-origin or no Origin at all.

    A browser lets any page POST to 127.0.0.1, and DNS rebinding lets a hostile site
    reach it by name. `Origin` is the only signal that distinguishes our own console from
    someone else's page, so an unrecognised one is refused.
    """
    if origin is None:                       # non-browser client (curl, tests)
        return True
    try:
        u = urlparse(origin)
    except ValueError:
        return False
    if u.scheme not in ("http", "https"):
        return False
    if u.hostname not in ("127.0.0.1", "::1", "localhost"):
        return False
    return u.port in (port, None)


def make_handler(tools: dict[str, Tool], root: Path, port: int, *,
                 reviewer: str | None = None, on: str | None = None,
                 adj_log=None):
    root = Path(root).resolve()

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, fmt, *args):        # quiet by default; the audit log is the record
            pass

        def end_headers(self) -> None:
            """Never let a browser cache a console page.

            The console is rebuilt constantly — a fixed defect, a fresh session, a new
            judgment — and every rebuild rewrites these files in place at the same URLs.
            `SimpleHTTPRequestHandler` sends `Last-Modified` and no `Cache-Control`,
            which invites heuristic caching, so a reviewer reloads and sees the page
            from *before* the fix. That already cost a review round: the evidence pane
            was read as still broken when the file on disk had been correct for an hour.
            A stale review surface is worse than a slow one — it shows findings that are
            no longer true, and nothing on the page admits it is old.
            """
            self.send_header("Cache-Control", "no-store, must-revalidate")
            super().end_headers()

        def _json(self, code: int, body: dict) -> None:
            blob = json.dumps(body).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(blob)))
            # No CORS header on purpose: the console is served from this same origin, so
            # it needs none, and adding one would hand the surface to any page that asks.
            self.end_headers()
            self.wfile.write(blob)

        def _adjudicate(self) -> None:
            """Record a reviewer's judgment. **Deliberately not a tool.**

            Every other endpoint here dispatches into the MCP registry, and this one must
            not: if adjudication were a tool, the agent could call it, and a machine would
            be able to manufacture human judgments. That is the precise failure D47 exists
            to prevent — a machine value displacing a human one — so the write path for
            human judgment lives only on the console's own surface, and its provenance is
            the reviewer the operator named when starting the server.
            """
            if adj_log is None or not reviewer or not on:
                self._json(409, {"error": "this server was started without a reviewer "
                                          "identity, so it cannot record judgments. "
                                          "Restart with --reviewer and --on."})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(min(length, MAX_BODY)) or b"{}")
            except (ValueError, json.JSONDecodeError) as e:
                self._json(400, {"error": f"bad request: {e}"})
                return
            from .adjudication import KINDS, Adjudication
            # A drawn box arrives as browser pixels; the conversion to manifest
            # coordinates happens in Python (annotate.py) so a Layer-0 test can reach it.
            # The page never sends its own idea of a normalized coordinate.
            if "box_px" in body:
                from .annotate import BoxError, box_from_pixels
                bp = body["box_px"]
                try:
                    nb = box_from_pixels(bp["x0"], bp["y0"], bp["x1"], bp["y1"],
                                         width=bp["width"], height=bp["height"])
                except (BoxError, KeyError, TypeError) as e:
                    self._json(400, {"error": f"box: {e}"})
                    return
                tgt = dict(body.get("target") or {})
                body["target"] = nb.as_target(
                    page=tgt.get("page"), numeral=tgt.get("numeral", ""))

            kind = body.get("kind")
            if kind not in KINDS:
                self._json(400, {"error": f"kind must be one of {sorted(KINDS)}"})
                return
            item_id = str(body.get("item_id") or "").strip()
            if not item_id:
                self._json(400, {"error": "item_id is required"})
                return
            try:
                adj = Adjudication(
                    adj_id=f"{item_id}::{kind}::{on}", kind=kind,
                    target_kind=str(body.get("target_kind") or "figure-numeral"),
                    target=dict(body.get("target") or {}), by=reviewer, on=on,
                    note=str(body.get("note") or ""), value=dict(body.get("value") or {}),
                    supersedes=body.get("supersedes"))
                adj_log.append(adj)
            except ValueError as e:
                # An append-only log correctly refusing a duplicate is not a fault the
                # reviewer committed, and it was reaching them as a raw exception string
                # telling them to "append a new entry with supersedes=..." — advice with
                # no button behind it. Say what is already on the record and let the page
                # mark the row; a re-judgment is a deliberate act, not an error recovery.
                prior = next((a for a in adj_log.effective()
                              if a.adj_id.split("::")[0] == item_id), None)
                if prior is not None:
                    self._json(409, {
                        "error": f"already judged — recorded as “{prior.kind}” by "
                                 f"{prior.by} on {prior.on}. This queue page was built "
                                 f"before that; reload to refresh it.",
                        "already": {"kind": prior.kind, "by": prior.by, "on": prior.on}})
                    return
                self._json(409, {"error": str(e)})
                return
            except Exception as e:                # noqa: BLE001 — surfaced verbatim
                self._json(409, {"error": f"{type(e).__name__}: {e}"})
                return
            self._json(200, {"recorded": adj.adj_id, "by": reviewer, "on": on,
                             "in_force": len(adj_log.effective())})

        def do_GET(self) -> None:                # noqa: N802 — stdlib naming
            """`/judged` answers from the LIVE log; everything else is a static file.

            The queue pages are built once and then judged against for hours, so a page
            held open (or reloaded from an older build) still lists items the reviewer
            has already ruled on. Clicking one collided with its own earlier record and
            surfaced a raw `ValueError` about append-only logs — a correct refusal
            delivered as a stack-trace fragment, for doing nothing wrong.

            Rebuilding the page server-side would mean running the whole console build
            on a GET. Answering "what is already judged?" is the same information at a
            fraction of the cost, and it keeps the page static.
            """
            if self.path == "/judged":
                if adj_log is None:
                    self._json(200, {"judged": {}})
                    return
                judged = {}
                for a in adj_log.effective():
                    item_id = a.adj_id.split("::")[0]
                    judged[item_id] = {"kind": a.kind, "by": a.by, "on": a.on}
                self._json(200, {"judged": judged})
                return
            super().do_GET()

        def _rebuild(self) -> None:
            """Re-run the console build, so a ruling reaches the pages that show it.

            The console is a STATIC build: a judgment lands in the log immediately, but
            every surface derived from it — the queue, the reconciliation counts, the
            interpretation panel, the marks on a sheet — is HTML written at build time.
            Reloading the browser re-fetches the same bytes, so the reviewer's own
            decision appears to have done nothing until someone re-runs a script from a
            terminal. That is a loop with a manual step in the middle of it (D79).

            The build arguments come from `build.json`, which the build itself writes,
            rather than from a second copy of that CLI's surface kept in step by hand.
            """
            spec = root / "build.json"
            if not spec.exists():
                self._json(409, {"error": "this console has no build.json — it predates "
                                          "the refresh button. Re-run "
                                          "scripts/build_console.py once and the button "
                                          "will work from then on."})
                return
            try:
                cfg = json.loads(spec.read_text())
            except json.JSONDecodeError as e:
                self._json(409, {"error": f"build.json is unreadable: {e}"})
                return
            argv = [sys.executable, str(_REPO / "scripts" / "build_console.py"),
                    "--store", cfg["store"], "--audit", cfg["audit"],
                    "--out", cfg["out"], "--on", _today()]
            for flag in ("doc", "engagement", "reviewer"):
                if cfg.get(flag):
                    argv += [f"--{flag}", cfg[flag]]
            # cwd=_REPO because build.json records paths as the operator typed them,
            # which are relative to the repo root. Resolving them against whatever
            # directory the server happens to have been started from would make the
            # button work from one shell and fail from another.
            proc = subprocess.run(argv, capture_output=True, text=True, timeout=600,
                                  cwd=str(_REPO))
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout).strip().splitlines()
                self._json(500, {"error": tail[-1] if tail else "the rebuild failed"})
                return
            self._json(200, {"rebuilt": True, "on": _today()})

        def do_POST(self) -> None:               # noqa: N802 — stdlib naming
            if not origin_allowed(self.headers.get("Origin"), port):
                self._json(403, {"error": "cross-origin request refused (DNS-rebinding "
                                          "protection); this server answers its own "
                                          "console only"})
                return
            if self.path == "/adjudicate":
                self._adjudicate()
                return
            if self.path == "/rebuild":
                self._rebuild()
                return
            if not self.path.startswith("/tool/"):
                self._json(404, {"error": "unknown endpoint"})
                return
            name = self.path[len("/tool/"):]
            tool = tools.get(name)
            if tool is None:
                self._json(404, {"error": f"no such tool: {name}",
                                 "available": sorted(tools)})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._json(400, {"error": "bad Content-Length"})
                return
            if length > MAX_BODY:
                self._json(413, {"error": f"body over {MAX_BODY} bytes"})
                return
            try:
                args = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as e:
                self._json(400, {"error": f"invalid JSON: {e}"})
                return
            try:
                # The same handler the MCP server exposes — so schema validation, path
                # containment and bounded inputs all apply, and the audit log gets the
                # same record. There is no second code path to keep in step.
                self._json(200, tool.handler(args))
            except Exception as e:               # noqa: BLE001 — surfaced, never swallowed
                self._json(400, {"error": f"{type(e).__name__}: {e}"})

    return Handler


def serve(tools: dict[str, Tool], root: Path, *, host: str = "127.0.0.1",
          port: int = 8765, reviewer: str | None = None, on: str | None = None,
          adj_log=None) -> socketserver.TCPServer:
    """Start the review server. Caller owns `serve_forever` / shutdown.

    `reviewer` + `on` + `adj_log` enable `/adjudicate`. Without all three the endpoint
    refuses: a judgment with no named author and no date is not evidence, and recording
    one anyway would be worse than not offering the feature.
    """
    require_loopback(host)
    socketserver.TCPServer.allow_reuse_address = True
    return socketserver.TCPServer(
        (host, port),
        make_handler(tools, root, port, reviewer=reviewer, on=on, adj_log=adj_log))
