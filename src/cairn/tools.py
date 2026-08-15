"""CAIRN tool registry (ROADMAP M4-T1/M4-T2, brief §5).

The single source of truth for the tools Claude Code calls — shared by both the
MCP server (`mcp_server.py`) and the CLI mirror (`cli.py`), so the two interfaces
can never drift. Each `Tool` is a name + description + a JSON-Schema `input_schema`
+ a pure handler taking a JSON-able args dict and returning a JSON-able dict. The
schema is the tool's contract on the wire — the MCP adapter advertises it verbatim
(M4-T2), so the agent sees the same shape the CLI accepts.

Read/write asymmetry (I4) is structural: only the three write tools
(`check_support` / `check_claim` / `verify`, `read_only=False`) close over the
audit log and append a replayable record (I5); read tools hold no log reference,
so they cannot write even by mistake (M4-T3). Stdlib-only — the MCP dependency
lives in `mcp_server.py`, kept out of the Layer-0 gate.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .audit import AuditLog
from .calibration import ThresholdChoice
from .calibration import resolve as resolve_threshold
from .frame import ROLES, coverage_for_answer, coverage_to_json, frame_from_json
from .ingest import DocumentStore
from .ingest.document import content_hash
from .retrieval import Hit, Retriever
from .session import support_record, verify_record
from .spans import SpanStore
from .support import THRESHOLD as SUPPORT_THRESHOLD
from .support import check_support
from .verify import answer_from_json, result_to_json, verify


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    handler: Callable[[dict], dict]
    read_only: bool = True
    input_schema: dict = field(default_factory=lambda: {"type": "object"})


# --- JSON-Schema fragments (the on-the-wire contract; advertised by the MCP adapter) ---

# --- Reject-by-default input bounds (D41; MCP hardening brief P0.2) ---
# "The model proposes arguments; the schema decides admissibility" — validation is
# deterministic code running BEFORE any tool logic, which is the AI/deterministic
# boundary doing security work. `_obj` already closes the object
# (`additionalProperties: False`); these close the VALUES, which were unbounded.
#
# The doc_id pattern is deliberately stricter than `DocumentStore.doc_dir` accepts
# (which permits nesting): defence in depth. doc_dir containment-checks after
# canonicalization (D35) and this refuses the shapes outright, so a traversal
# attempt fails at the wire before it reaches a path join at all.
_DOC_ID = {"type": "string", "minLength": 1, "maxLength": 128,
           "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
           "description": "A document id in this corpus — a NAME, never a path."}
_TEXT = {"type": "string", "minLength": 1, "maxLength": 8192}
_OFFSET = {"type": "integer", "minimum": 0, "maximum": 100_000_000}
_TOPK = {"type": "integer", "minimum": 1, "maximum": 100, "default": 10}

_ATOM_SCHEMA: dict = {
    "type": "object",
    "description": "A load-bearing atom bound to an exact source location (D9/I1).",
    "properties": {
        "text": {"type": "string", "description": "The literal asserted at the location."},
        "doc_id": _DOC_ID,
        "char_start": _OFFSET,
        "char_end": _OFFSET,
        "content_hash": {
            "type": ["string", "null"],
            "description": "Doc hash the binding was made against (drift check, I3).",
        },
    },
    "required": ["text", "doc_id", "char_start", "char_end"],
    "additionalProperties": False,
}

_ANSWER_SCHEMA: dict = {
    "type": "object",
    "description": "A composed answer: sentences, each with bound atoms + derived values.",
    "properties": {
        "sentences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "atoms": {"type": "array", "items": _ATOM_SCHEMA},
                    "derived": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "operation": {"type": "string", "enum": [
                                    "subtract", "sum", "multiply", "divide", "ratio",
                                    "percent_change", "gt", "ge", "lt", "le", "eq",
                                    "within_range"]},
                                "operands": {"type": "array", "items": _ATOM_SCHEMA},
                            },
                            "required": ["text", "operation", "operands"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["text"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["sentences"],
    "additionalProperties": False,
}




def _tools(tools: Iterable[Tool] | dict[str, Tool]) -> list[Tool]:
    return list(tools.values() if isinstance(tools, dict) else tools)


def tool_manifest(tools: Iterable[Tool] | dict[str, Tool]) -> list[dict]:
    """The advertised surface: name + description + schema, in a stable order."""
    return [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in sorted(_tools(tools), key=lambda x: x.name)]


def tool_manifest_sha256(tools: Iterable[Tool] | dict[str, Tool]) -> str:
    """Content hash of the whole advertised tool surface (D41; brief P0.1).

    Tool metadata is a TRUST SURFACE, not documentation: an agent reads descriptions
    and schemas and acts on them, so a description edit is a behaviour change with the
    reach of a code change. That is the rug-pull shape — a server ships benign metadata,
    earns trust, then quietly rewrites what the model is told a tool does. Hashing the
    manifest means unreviewed drift fails the gate instead of shipping silently.
    """
    blob = json.dumps(tool_manifest(tools), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# Descriptions DESCRIBE; they never DIRECT. An imperative aimed at the model rather
# than at the human reader is the tool-poisoning shape — instructions smuggled into
# metadata the model treats as trusted. Checked, not merely asked for.
_INSTRUCTION_LIKE = re.compile(
    r"\b(ignore|disregard|instead of|you must|always call|never call|do not tell|"
    r"before (?:answering|responding)|regardless of|override)\b", re.IGNORECASE)


def lint_tool_descriptions(tools: Iterable[Tool] | dict[str, Tool]) -> list[str]:
    """Description strings that read as instructions to the model. Empty = clean."""
    return [f"{t.name}: {m.group(0)!r}"
            for t in _tools(tools) if (m := _INSTRUCTION_LIKE.search(t.description))]


def _obj(properties: dict, required: list[str]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _hit(h: Hit) -> dict:
    s = h.span
    return {
        "doc_id": s.doc_id,
        "span_id": s.span_id,
        "char_start": s.char_start,
        "char_end": s.char_end,
        "score": round(h.score, 6),
        "text": s.text,
    }


def default_registry(
    store_dir: Path | str, audit_path: Path | str | None = None,
    # None = resolve from the store's calibration record (RT-9). An explicit float is
    # an operator override and WINS: silently overriding a caller's stated intent is the
    # same class of defect this whole mechanism exists to remove.
    *, support_threshold: float | None = None,
) -> dict[str, Tool]:
    doc_store = DocumentStore(store_dir)
    span_store = SpanStore.from_store(doc_store)
    retriever = Retriever(span_store)
    # RT-9: the support floor is a BM25 score, which does not transfer between corpora.
    # Resolve it from THIS store's calibration record and carry the provenance forward,
    # so an uncalibrated or stale floor is visible in every result and every log entry
    # instead of silently producing false abstentions.
    if support_threshold is not None:
        _choice = ThresholdChoice(
            support_threshold, False,
            f"EXPLICIT OVERRIDE: the support floor {support_threshold} was supplied by "
            f"the caller, not read from this store's calibration record.")
    else:
        _ids = doc_store.list_docs()
        _choice = resolve_threshold(
            store_dir, SUPPORT_THRESHOLD, _ids,
            [doc_store.load(d).content_hash for d in _ids])
    support_threshold = _choice.threshold
    # The audit log is the single writable surface (I4); it is the *only* thing the
    # write tools below close over. The read tools never receive it, so the
    # read/write asymmetry is structural — a read handler cannot append even by
    # mistake, because it holds no reference to a log. (M4-T3)
    log = AuditLog(audit_path) if audit_path is not None else None

    def _append(payload: dict) -> None:
        if log is not None:
            log.append(payload)

    tools: list[Tool] = []

    def reg(
        name: str,
        desc: str,
        fn: Callable[[dict], dict],
        schema: dict,
        read_only: bool = True,
    ) -> None:
        tools.append(Tool(name, desc, fn, read_only, schema))

    # --- Read tools: pure, side-effect-free; no log reference (I4) ---

    reg("search_corpus", "Ranked candidate spans for a query (with offsets).",
        lambda a: {"hits": [_hit(h) for h in retriever.search(a["query"], a.get("k", 10))]},
        _obj(
            {
                "query": _TEXT,
                "k": _TOPK,
            },
            ["query"],
        ))

    # Every read hands back the corpus identity it read against, because a binding must
    # carry that hash for `verify` to detect drift (I3) — and until this was returned,
    # the agent had no way to obtain one. The field existed on AtomBinding from the
    # first commit and was supplied 0 times in 61 bindings: the check was unreachable,
    # not merely unused, and drift went silent for a whole engagement (D65).
    reg("get_span", "Fetch + hash-verify a span's exact text (I3). Returns the doc's "
        "content_hash — pass it back as the binding's content_hash.",
        lambda a: {"text": span_store.get_span(a["doc_id"], a["start"], a["end"]),
                   "doc_id": a["doc_id"],
                   "content_hash": content_hash(span_store.get_document(a["doc_id"]))},
        _obj(
            {
                "doc_id": _DOC_ID,
                "start": _OFFSET,
                "end": _OFFSET,
            },
            ["doc_id", "start", "end"],
        ))

    reg("get_document", "Full hash-verified canonical text — read freely (D11). Returns "
        "the content_hash to bind with.",
        lambda a: {"doc_id": a["doc_id"], "text": span_store.get_document(a["doc_id"]),
                   "content_hash": content_hash(span_store.get_document(a["doc_id"]))},
        _obj({"doc_id": _DOC_ID}, ["doc_id"]))

    # --- Write tools: append a replayable record to the audit log (I5); read_only=False ---

    def _check_support(a: dict) -> dict:
        rec = support_record(
            a["query"], check_support(a["query"], retriever, threshold=support_threshold),
            threshold=support_threshold, retrieval=retriever.method,
            calibration_warning=_choice.warning)
        _append(rec)
        return rec

    def _check_claim(a: dict) -> dict:
        rec = support_record(
            a["claim"], check_support(a["claim"], retriever, threshold=support_threshold),
            kind="check_claim", threshold=support_threshold, retrieval=retriever.method,
            calibration_warning=_choice.warning)
        _append(rec)
        return rec

    def _verify(a: dict) -> dict:
        answer = answer_from_json(a["answer"])
        result = verify(answer, span_store)
        frame_json = a.get("frame")
        coverage_json = None
        if frame_json is not None:
            coverage_json = coverage_to_json(
                coverage_for_answer(frame_from_json(frame_json), answer, span_store))
        _append(verify_record(a["answer"], result, a.get("outcome"),
                              frame_json, coverage_json))
        out = result_to_json(result)
        if coverage_json is not None:
            # D13/M2-T8: present ONLY if ok AND coverage.complete — the loop rule.
            out["coverage"] = coverage_json
        return out

    reg("check_support", "Supporting spans or 'insufficient' — the abstention decision (I2).",
        _check_support, _obj({"query": _TEXT}, ["query"]), read_only=False)

    reg("check_claim", "Resolve a user-supplied claim to supporting spans (or none).",
        _check_claim, _obj({"claim": _TEXT}, ["claim"]), read_only=False)

    reg("verify", "Resolve every bound atom + recompute derivations; flag unbound figures (I1/D9).",
        _verify, _obj({
            "answer": _ANSWER_SCHEMA,
            "outcome": {"type": "string", "enum": ["answer", "correction", "partial"],
                        "description": "Outcome class (D16) — for review; correction = "
                                       "grounded refutation of a false premise."},
            "frame": {
                "type": "object",
                "description": "Question frame (D13/M2-T8): the query decomposed into "
                               "typed constraints the cited evidence must cover. Present "
                               "only if verify is ok AND coverage.complete.",
                "properties": {
                    "question": {"type": "string"},
                    "constraints": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": list(ROLES)},
                            "text": {"type": "string"},
                            "required": {"type": "boolean", "default": True},
                        },
                        "required": ["role", "text"],
                        "additionalProperties": False,
                    }},
                },
                "required": ["question", "constraints"],
                "additionalProperties": False,
            },
        }, ["answer"]), read_only=False)

    if log is not None:

        def _get_audit_log(a: dict) -> dict:
            entries = log.entries()[a.get("offset", 0):]
            return {"entries": [{"seq": e.seq, "payload": e.payload} for e in entries]}

        reg("get_audit_log", "Replay past interactions from the audit log (I5).", _get_audit_log,
            _obj({"offset": {"type": "integer", "minimum": 0, "default": 0}}, []))

    return {t.name: t for t in tools}
