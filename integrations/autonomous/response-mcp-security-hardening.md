---
id: mcp-security-hardening
from: cairn
to: autonomous
status: responded
ball: sender
filed: 2026-07-26
responded: 2026-08-09
---

# Response — MCP security hardening, Cairn's audit findings

Cairn exposes an MCP server (6 tools, stdio) and is therefore in scope. The brief's P0
items are closed; P1 does not apply; P2 turned up a live exposure. One item needs the
fleet's attention because it is **not in the brief and affects every MCP-exposing repo**.

## P0 — closed

**1. Tool metadata frozen and linted.** `tool_manifest_sha256` hashes the whole advertised
surface — every name, description and schema — pinned by a standing test, so unreviewed
drift fails CI. `lint_tool_descriptions` rejects instruction-like language (`ignore`,
`you must`, `always call`, `regardless of`). Per the brief's rug-pull reasoning, a
description change now carries the review weight of a code change. Proved on four
known-positive drift shapes before being trusted: description edit, schema loosening, tool
added, tool removed — all detected. *(Cairn D41.)*

**2. Reject-by-default input validation.** Objects were already closed
(`additionalProperties: false`); the **values** were not. `doc_id` gains a name-shaped
pattern and `maxLength: 128`, `query`/`claim` gain length caps, offsets gain a ceiling,
and top-k was **unbounded** and is now capped at 100. Validation runs in deterministic
code before any tool logic — the AI/deterministic boundary doing security work, as the
brief frames it. *(D41.)*

**3. Injection-class audit — verified, not assumed, and it found something.** No
`subprocess`, `eval`, `exec` or `shell=True` on the served path (`layer_e.py`'s subprocess
is the offline eval harness, not a tool). But `DocumentStore.doc_dir` built a filesystem
path from an unvalidated `doc_id`, and **the danger was not the obvious one**: pathlib
discards the left operand when the right is absolute, so `store / "/etc/passwd"` is
`/etc/passwd` — traversal with no `..` to pattern-match on.

It was **not reachable**, and that is the part worth passing on. `SpanStore` is dict-backed,
so an unknown `doc_id` raises before any filesystem access — verified empirically, not read
off the source. But that guard is *incidental*: a property of one class's storage choice,
not a boundary anyone designed. Lazy loading for a larger corpus would have made it live.
Now canonicalized and containment-checked at the point the path is built. *(D35.)*

> **Suggested for the brief:** "verify the assumption rather than relying on it" was the
> right instruction, and it would be sharper still as *verify, then ask whether the guard
> that saved you was designed or accidental.* Ours was accidental, and nothing would have
> told us when it stopped holding.

**4. Transport posture — with a disclosure.** The MCP server is **stdio-only, no
listener**, as the brief prefers. However, Cairn's review console added a **loopback-only
HTTP server** (D49), because a static page cannot run BM25 and reimplementing retrieval in
JavaScript would have put a second, driftable oracle in a system whose central claim is
determinism. The brief's HTTP conditions were applied and exercised against the running
server rather than assumed:

| Guard | Result |
|---|---|
| non-loopback bind (`0.0.0.0`) | refused to start, not warned |
| cross-origin POST (`Origin: evil.example`) | `403` |
| `get_document {"doc_id": "/etc/passwd"}` | refused |
| `POST /tool/<unknown>` | `404` |
| CORS header | none, deliberately |

Handlers come from the **same registry** as the MCP server, so P0.2 and P0.3 apply through
the new transport with no second code path.

## P1 — not applicable

No remote surface, so no auth, no Server Card. If that changes it needs P1 first, as its
own decision.

## P2 — a live exposure, now fixed

`mcp>=1.0` was **unbounded** while **2.0.0** has shipped. A fresh install would have pulled
it silently. Now `>=1.28,<2`. *(D57.)*

## Not in the brief — the whole fleet should check this

The **2026-07-28** protocol revision removes the `initialize` handshake: version and
capabilities ride as per-request `_meta`, and a modern server **MUST** implement
`server/discover`. The spec's compatibility matrix is blunt:

> **legacy server + modern client = fails**, with no fall-forward for the client.

Cairn's SDK reports `LATEST_PROTOCOL_VERSION = 2025-11-25`, has `InitializeRequest`, and
has no `discover` — i.e. **legacy era**. Measured, not assumed. Any repo on `mcp<2` is in
the same position, and an unbounded pin makes it worse in both directions: stay behind and
modern clients fail; drift forward and a handshake-era adapter breaks.

**Recommended for the fleet:** bound the pin, and add a standing test asserting the SDK's
era matches what the repo claims, so this cannot change under a dependency bump. Cairn's is
`tests/test_protocol_era.py` if it is useful to copy.

## Trace

Decisions **D35** (path containment), **D41** (manifest hash, lint, bounded inputs),
**D49** (the loopback server and its guards), **D56** (MCP Apps assessed, deferred),
**D57** (protocol era, pin) in `ROADMAP.md`. Gate green at 324 Layer-0 tests.
