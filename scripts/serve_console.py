#!/usr/bin/env python3
"""Serve the console with live tools (RT-10b, D49).

Loopback only. The Locate pane needs the real retrieval implementation — a second one in
JavaScript could drift from it, and Cairn's central claim is that the same corpus and
query give the same result.

    python scripts/serve_console.py --store corpus/store \\
        --audit audit_log/agent.jsonl --dir console
"""

from __future__ import annotations

import argparse
import datetime as _dt
import webbrowser
from pathlib import Path

import _bootstrap  # noqa: F401  (puts src/ on sys.path)

from cairn.serve import NotLoopback, serve
from cairn.tools import default_registry


def main() -> int:
    ap = argparse.ArgumentParser(description="Serve the Cairn console (loopback only)")
    ap.add_argument("--store", required=True)
    ap.add_argument("--audit", required=True, help="write tools append here (I5)")
    ap.add_argument("--dir", default="console", help="console directory to serve")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--reviewer", help="who is recording judgments — enables /adjudicate")
    # Defaults to TODAY rather than being required. A pinned date in a launch config
    # silently backdates every judgment made after the day it was written -- judgments
    # made on the 15th were being stamped the 9th, which is a false provenance date on
    # the one record a human authors. An explicit --on still wins, for backfilling.
    ap.add_argument("--on", metavar="YYYY-MM-DD",
                    default=_dt.date.today().isoformat(),
                    help="date for recorded judgments (default: today)")
    ap.add_argument("--adjudications", help="path to the append-only judgment log")
    ap.add_argument("--open", action="store_true", help="open a browser at the console")
    ns = ap.parse_args()

    tools = default_registry(ns.store, ns.audit)
    adj_log = None
    if ns.reviewer and ns.on:
        from cairn.adjudication import AdjudicationLog
        adj_path = Path(ns.adjudications or (Path(ns.store).parent / "figures" /
                                             "adjudications.jsonl"))
        adj_log = AdjudicationLog(adj_path)
        if adj_log.path.exists():
            adj_log.verify_chain()
    try:
        httpd = serve(tools, Path(ns.dir), host=ns.host, port=ns.port,
                      reviewer=ns.reviewer, on=ns.on, adj_log=adj_log)
    except NotLoopback as e:
        print(f"refused: {e}")
        return 1

    url = f"http://{ns.host}:{ns.port}/index.html"
    print(f"Cairn console → {url}")
    print(f"  tools: {', '.join(sorted(tools))}")
    print(f"  audit: {ns.audit}  (every locate is recorded, I5)")
    judging = (f"as {ns.reviewer} on {ns.on}" if adj_log
               else "DISABLED (pass --reviewer and --on to enable)")
    print(f"  judgments: {judging}")
    print("  loopback only; cross-origin requests are refused. Ctrl-C to stop.")
    if ns.open:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
