"""Ledger entry model, IO, secret stripping, loop warning, filtering, grouping."""
from __future__ import annotations
import hashlib, json, os, re
from datetime import datetime, timezone
from pathlib import Path

from . import LOOP_THRESHOLD
from .prices import estimate_cost_usd, load_price_table

DEFAULT_LEDGER = ".ghostledger.jsonl"
# Credential-named keys are dropped on sight. *_tokens counts are kept:
# they are numbers, not credentials. Checked before the token rule.
_SECRET_RE = re.compile(r"(api[_-]?key|auth|secret|password|passwd|credential|bearer|session|cookie|private[_-]?key)", re.I)

def is_secret_key(key: str) -> bool:
    if key.endswith("_tokens") or key in ("total_tokens", "estimated_tokens"):
        return False
    return bool(_SECRET_RE.search(key))

def strip_secrets(obj):
    """Recursively drop credential-named fields from imported records."""
    if isinstance(obj, dict):
        return {k: strip_secrets(v) for k, v in obj.items() if not is_secret_key(str(k))}
    if isinstance(obj, list):
        return [strip_secrets(v) for v in obj]
    return obj

def default_ledger_path(explicit=None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("GHOSTLEDGER_FILE")
    return Path(env) if env else Path(DEFAULT_LEDGER)

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def _day(at: str) -> str:
    return (at or "")[:10] or "unknown"

def entry_id(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

def make_entry(*, project="unknown", model=None, agent=None, source="manual", kind="run",
               task="", at=None, input_tokens=0, output_tokens=0, total_tokens=None,
               estimated_tokens=None, note="", source_ref="", table=None) -> dict:
    at = at or _now_iso()
    input_tokens = int(input_tokens or 0)
    output_tokens = int(output_tokens or 0)
    total = int(total_tokens) if total_tokens is not None else input_tokens + output_tokens
    estimated_raw = int(estimated_tokens) if estimated_tokens is not None else None
    # Token counts are counts: a negative value is invalid evidence,
    # never a bookable entry (it would book negative cost and could
    # trip the loop warning on nonsense). Callers that import count
    # such records as skipped; the CLI reports this as an error.
    for label, value in (("input_tokens", input_tokens), ("output_tokens", output_tokens),
                         ("total_tokens", total), ("estimated_tokens", estimated_raw)):
        if value is not None and value < 0:
            raise ValueError(f"{label} must not be negative (got {value})")
    # Labels are grouping keys: surrounding whitespace is never
    # meaningful and would split one model/project into two groups.
    if isinstance(model, str):
        model = model.strip() or None
    if isinstance(agent, str):
        agent = agent.strip() or None
    if isinstance(project, str):
        project = project.strip()
    # If only a total was given, book it as input so totals reconcile.
    if total_tokens is not None and not input_tokens and not output_tokens:
        input_tokens = total
    estimated = estimated_raw
    table = table or load_price_table()
    cost = estimate_cost_usd(input_tokens, output_tokens, model, table)
    ratio = round(total / estimated, 4) if estimated else None
    loop = bool(estimated and total > LOOP_THRESHOLD * estimated)
    core = {
        "at": at, "project": project or "unknown", "model": model, "agent": agent,
        "source": source, "kind": kind, "task": task or "",
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "total_tokens": total, "estimated_tokens": estimated,
        "source_ref": source_ref,
    }
    entry = dict(core)
    entry["id"] = entry_id(core)
    entry["day"] = _day(at)
    entry["ratio"] = ratio
    entry["loop_warning"] = loop
    entry["loop_threshold"] = LOOP_THRESHOLD
    entry["cost_estimate_usd"] = cost
    entry["price_table_as_of"] = table.get("as_of")
    entry["note"] = note or ""
    return entry

def load_entries(path) -> list:
    p = Path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out

def append_entries(path, entries) -> int:
    """Append entries not already present by id; returns count added.

    Dedupe applies within the batch as well as against the file: a
    batch that carries the same id twice books it once.
    """
    existing = {e.get("id") for e in load_entries(path)}
    fresh, seen = [], set()
    for e in entries:
        eid = e.get("id")
        if eid in existing or eid in seen:
            continue
        seen.add(eid)
        fresh.append(e)
    if fresh:
        p = Path(path)
        if p.parent and str(p.parent) not in ("", "."):
            p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as fh:
            for e in fresh:
                fh.write(json.dumps(e, sort_keys=True) + "\n")
    return len(fresh)

def append_entry(path, entry) -> bool:
    return append_entries(path, [entry]) == 1

def filter_entries(entries, since=None, until=None, project=None):
    out = []
    for e in entries:
        day = e.get("day") or _day(e.get("at", ""))
        if since and day < since:
            continue
        if until and day > until:
            continue
        if project and e.get("project") != project:
            continue
        out.append(e)
    return out

def _blank():
    return {"entries": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0,
            "estimated_tokens": 0, "entries_with_estimate": 0,
            "actual_tokens_with_estimate": 0,
            "cost_estimate_usd": 0.0, "entries_with_cost": 0, "loop_warnings": 0}

def _accumulate(bucket: dict, e: dict):
    bucket["entries"] += 1
    bucket["input_tokens"] += int(e.get("input_tokens") or 0)
    bucket["output_tokens"] += int(e.get("output_tokens") or 0)
    bucket["total_tokens"] += int(e.get("total_tokens") or 0)
    if e.get("estimated_tokens") is not None:
        bucket["estimated_tokens"] += int(e["estimated_tokens"])
        bucket["entries_with_estimate"] += 1
        # The actual side of the estimate-vs-actual comparison: only
        # entries that carry an estimate belong in it. Entries with
        # no estimate still count in total_tokens, but including
        # their actuals in the ratio would blame the estimated
        # entries for tokens nobody estimated.
        bucket["actual_tokens_with_estimate"] += int(e.get("total_tokens") or 0)
    if e.get("cost_estimate_usd") is not None:
        bucket["cost_estimate_usd"] = round(bucket["cost_estimate_usd"] + float(e["cost_estimate_usd"]), 6)
        bucket["entries_with_cost"] += 1
    if e.get("loop_warning"):
        bucket["loop_warnings"] += 1

def _finish(bucket: dict) -> dict:
    est = bucket["estimated_tokens"]
    actual = bucket["actual_tokens_with_estimate"]
    bucket["estimate_vs_actual_ratio"] = round(actual / est, 4) if est else None
    bucket["estimate_delta_tokens"] = actual - est if bucket["entries_with_estimate"] else None
    return bucket

def group_entries(entries, by: str) -> dict:
    groups = {}
    for e in entries:
        if by == "day":
            key = e.get("day") or _day(e.get("at", ""))
        elif by in ("project", "model", "agent"):
            key = e.get(by) or "unknown"
        else:
            raise ValueError(f"unknown grouping: {by}")
        _accumulate(groups.setdefault(str(key), _blank()), e)
    return {k: _finish(v) for k, v in sorted(groups.items())}

def summarise(entries, table=None) -> dict:
    table = table or load_price_table()
    bucket = _blank()
    for e in entries:
        _accumulate(bucket, e)
    _finish(bucket)
    unknown_models = sorted({str(e.get("model")) for e in entries
                             if e.get("model") and e.get("cost_estimate_usd") is None})
    warnings = [e for e in entries if e.get("loop_warning")]
    return {
        "tool": "ghostledger", "version": "0.1.0",
        "totals": bucket,
        "by_project": group_entries(entries, "project"),
        "by_model": group_entries(entries, "model"),
        "by_agent": group_entries(entries, "agent"),
        "by_day": group_entries(entries, "day"),
        "loop_warnings": warnings,
        "loop_threshold": LOOP_THRESHOLD,
        "unknown_models": unknown_models,
        "price_table_as_of": table.get("as_of"),
        "price_table_source": table.get("_source"),
        "cost_note": (f"Costs are ESTIMATES from a local dated price table "
                      f"(as of {table.get('as_of')}), never billed amounts."),
    }
