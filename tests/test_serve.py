"""Standing tests for the loopback-only review server (RT-10b, D49).

The listener exists under protest: the MCP hardening brief says a local server's ABSENCE
of a listener is the win. The cause that justified it is determinism — a JavaScript
retrieval implementation would be a second oracle that can drift from the Python one — so
the guards that pay for it are tested, not assumed.
"""

from __future__ import annotations

import threading

import pytest

from cairn.serve import (
    NotLoopback,
    origin_allowed,
    require_loopback,
    serve,
)

pytestmark = pytest.mark.layer0


def test_non_loopback_binds_are_refused_not_warned():
    """A review server reachable from the network is a different product with a different
    threat model. Refusing beats warning: a warning gets scrolled past."""
    for host in ("0.0.0.0", "192.168.1.10", "10.0.0.1", "example.com", "::"):
        with pytest.raises(NotLoopback):
            require_loopback(host)


def test_loopback_binds_are_allowed():
    for host in ("127.0.0.1", "::1", "localhost", "127.0.0.53"):
        require_loopback(host)


def test_cross_origin_requests_are_refused():
    """A browser will happily let any page POST to 127.0.0.1, and DNS rebinding makes
    that reachable from a hostile site — the MCP Inspector RCE class. Origin is the only
    signal distinguishing our own console from someone else's page."""
    assert not origin_allowed("http://evil.example", 8765)
    assert not origin_allowed("https://127.0.0.1.nip.io", 8765)
    assert not origin_allowed("file://", 8765)
    # a different port is a different origin
    assert not origin_allowed("http://127.0.0.1:9999", 8765)


def test_same_origin_and_non_browser_clients_are_allowed():
    assert origin_allowed("http://127.0.0.1:8765", 8765)
    assert origin_allowed("http://localhost:8765", 8765)
    assert origin_allowed(None, 8765), "curl and tests send no Origin"


def test_the_server_exposes_no_tool_the_mcp_surface_lacks():
    """The handlers come from the same registry, so schema validation, path containment
    (D35) and bounded inputs (D41) apply unchanged — there is no second code path to keep
    in step, and no endpoint that exists only here."""
    import inspect

    from cairn import serve as serve_mod
    src = inspect.getsource(serve_mod)
    assert "tools.get(name)" in src, "handlers must come from the passed registry"
    assert "default_registry" not in src, "the module must not build its own tool set"


def test_adjudication_is_not_reachable_as_a_tool():
    """A machine must not be able to manufacture human judgments. Every other endpoint
    dispatches into the MCP registry; this one deliberately does not, so the agent — which
    can call any tool — has no route to writing a reviewer's judgment (D47's guard, at the
    transport)."""
    import inspect

    from cairn import serve as serve_mod
    src = inspect.getsource(serve_mod)
    assert '"/adjudicate"' in src, "the write path is its own endpoint"
    handler_src = src[src.index("def _adjudicate"):src.index("def do_POST")]
    assert "tools" not in handler_src, "it must not dispatch through the tool registry"


def test_recording_needs_a_named_reviewer_and_a_date():
    """A judgment with no author and no date is not evidence, so the endpoint refuses
    rather than recording one anonymously."""
    import inspect

    from cairn import serve as serve_mod
    src = inspect.getsource(serve_mod)
    assert "if adj_log is None or not reviewer or not on:" in src


def test_console_pages_are_never_cached(tmp_path):
    """The console is rebuilt in place at the same URLs, so a cached page shows
    findings that are no longer true with nothing on it admitting the page is old.
    This cost a real review round — the evidence pane was reported still broken when
    the file on disk had been correct for an hour."""
    import urllib.request
    (tmp_path / "index.html").write_text("<p>v1</p>", encoding="utf-8")
    srv = serve({}, tmp_path, port=0)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html") as r:
            assert "no-store" in r.headers.get("Cache-Control", "")
            assert r.read() == b"<p>v1</p>"
        # a rebuild at the same URL is visible on the next request
        (tmp_path / "index.html").write_text("<p>v2</p>", encoding="utf-8")
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html") as r:
            assert r.read() == b"<p>v2</p>"
    finally:
        srv.shutdown()
