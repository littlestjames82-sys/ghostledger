"""Importers: GhostSlice history (.jsonl), GhostProxy report JSON, GhostBench bench-report.json.

All importers strip credential-named fields first, are tolerant of
missing/extra fields, count skipped records, and never invent values:
unknown tokens = 0 only where the source shape defines them, unknown
model = None (cost then reports as unknown, not $0-as-fact).
"""
from __future__ import annotations
import json
from pathlib import Path

from .ledger import make_entry, strip_secrets

def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

def _pick(d: dict, *keys):
    for k in keys:
        if d.get(k) is not None:
            return d.get(k)
    return None

# ---- GhostSlice history -------------------------------------------------

def import_slice_history(path, table=None, project=None):
    entries, skipped = [], 0
    name = Path(path).name
    for idx, line in enumerate(Path(path).read_text(encoding="utf-8", errors="replace").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = strip_secrets(json.loads(line))
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(rec, dict):
            skipped += 1
            continue
        after = _int(_pick(rec, "after_tokens", "sliced_tokens", "tokens"))
        if after is None or after < 0:
            skipped += 1
            continue
        before = _int(_pick(rec, "before_tokens", "full_tokens"))
        if before is not None and before < 0:
            before = None
        note = f"before_tokens={before}" if before is not None else ""
        entries.append(make_entry(
            project=project or _pick(rec, "project") or "unknown",
            model=_pick(rec, "model"), agent=_pick(rec, "agent"),
            source="slice", kind=str(_pick(rec, "kind") or "export"),
            task=str(_pick(rec, "task") or ""), at=_pick(rec, "at", "timestamp"),
            input_tokens=after, output_tokens=0, estimated_tokens=after,
            note=note, source_ref=f"{name}:{idx + 1}", table=table))
    return entries, skipped

# ---- GhostBench report ----------------------------------------------------

# Variant priority inside a Bench task's variants{} block. GhostBench
# always emits "sliced" for the measured variant and adds suite extras
# ("proxied" / "verified" / "recalled") alongside it; "sliced" is the
# variant Bench's own totals aggregate, so it wins. The extras are
# fallbacks for hand-built reports that carry only one of them.
_BENCH_VARIANT_PRIORITY = ("sliced", "proxied", "verified", "recalled")

def _variant_tokens(variants, name):
    """Token count for one variant, or None when absent/invalid.

    A variant value is normally {"tokens": N, ...}; a bare number is
    accepted tolerantly. Negative counts are invalid evidence and are
    treated as absent, never booked.
    """
    if not isinstance(variants, dict):
        return None
    var = variants.get(name)
    if isinstance(var, dict):
        n = _int(_pick(var, "tokens", "token_count", "total_tokens"))
    else:
        n = _int(var)
    return n if (n is not None and n >= 0) else None

def _bench_variant_actual(t):
    """(actual_tokens, variant_name) from variants{}, else (None, None)."""
    variants = t.get("variants")
    for name in _BENCH_VARIANT_PRIORITY:
        n = _variant_tokens(variants, name)
        if n is not None:
            return n, name
    return None, None

def import_bench_report(path, table=None, project=None):
    data = strip_secrets(json.loads(Path(path).read_text(encoding="utf-8", errors="replace")))
    entries, skipped = [], 0
    if not isinstance(data, dict):
        return entries, 1
    default_model = _pick(data, "model_for_cost_estimates", "model")
    run_id = _pick(data, "run_id") or ""
    at = _pick(data, "created_utc") if isinstance(_pick(data, "created_utc"), str) and "T" in str(_pick(data, "created_utc")) else None
    tasks = data.get("tasks")
    if not isinstance(tasks, list):
        return entries, 1
    for idx, t in enumerate(tasks):
        if not isinstance(t, dict):
            skipped += 1
            continue
        full = _int(_pick(t, "full_tokens"))
        if full is None:
            full = _variant_tokens(t.get("variants"), "full")
        if full is not None and full < 0:
            skipped += 1
            continue
        actual = _int(_pick(t, "sliced_tokens", "proxied_tokens", "after_tokens",
                            "input_tokens", "total_tokens"))
        variant_name = None
        if actual is None:
            actual, variant_name = _bench_variant_actual(t)
        if actual is not None and actual < 0:
            skipped += 1
            continue
        if actual is None:
            actual = full
        if actual is None:
            skipped += 1
            continue
        out_tokens = _int(_pick(t, "output_tokens")) or 0
        if out_tokens < 0:
            skipped += 1
            continue
        note_bits = [f"run_id={run_id}"] if run_id else []
        if variant_name:
            note_bits.append(f"bench_variant={variant_name}")
        entries.append(make_entry(
            project=project or _pick(t, "project") or _pick(data.get("corpus") or {}, "name") or "unknown",
            model=_pick(t, "model") or default_model, agent=_pick(t, "agent"),
            source="bench", kind="bench-task",
            task=str(_pick(t, "task", "task_id", "id") or ""), at=at,
            input_tokens=actual, output_tokens=out_tokens,
            estimated_tokens=full if (full is not None and actual != full) else actual,
            note="; ".join(note_bits),
            source_ref=f"{Path(path).name}:tasks[{idx}]", table=table))
    return entries, skipped

# ---- GhostProxy report ----------------------------------------------------

def _proxy_record_to_entry(rec, name, idx, table, project):
    inp = _int(_pick(rec, "input_tokens", "prompt_tokens", "tokens_in"))
    out = _int(_pick(rec, "output_tokens", "completion_tokens", "tokens_out"))
    total = _int(_pick(rec, "total_tokens"))
    if inp is None and out is None and total is None:
        return None
    if any(v is not None and v < 0 for v in (inp, out, total)):
        return None
    estimated = _int(_pick(rec, "estimated_tokens", "slice_estimate_tokens"))
    if estimated is not None and estimated < 0:
        return None
    return make_entry(
        project=project or _pick(rec, "project") or "unknown",
        model=_pick(rec, "model"), agent=_pick(rec, "agent", "client"),
        source="proxy", kind=str(_pick(rec, "kind") or "request"),
        task=str(_pick(rec, "task") or ""), at=_pick(rec, "at", "timestamp", "time", "ts"),
        input_tokens=inp or 0, output_tokens=out or 0,
        total_tokens=total if (total is not None and not inp and not out) else None,
        estimated_tokens=estimated,
        source_ref=f"{name}:{idx}", table=table)

def import_proxy_report(path, table=None, project=None):
    data = strip_secrets(json.loads(Path(path).read_text(encoding="utf-8", errors="replace")))
    entries, skipped = [], 0
    name = Path(path).name
    if isinstance(data, dict):
        records = None
        for key in ("requests", "entries", "records", "calls"):
            if isinstance(data.get(key), list):
                records = data[key]
                break
        if records is None:
            records = [data]
    elif isinstance(data, list):
        records = data
    else:
        return entries, 1
    for idx, rec in enumerate(records):
        if not isinstance(rec, dict):
            skipped += 1
            continue
        entry = _proxy_record_to_entry(rec, name, idx, table, project)
        if entry is None:
            skipped += 1
        else:
            entries.append(entry)
    return entries, skipped

# ---- auto-detect ------------------------------------------------------------

def import_source_file(path, table=None, project=None):
    """Returns (entries, skipped, detected_source)."""
    p = Path(path)
    if p.suffix == ".jsonl" or p.name.endswith(".jsonl"):
        e, s = import_slice_history(p, table, project)
        return e, s, "slice"
    data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    if isinstance(data, dict) and isinstance(data.get("tasks"), list):
        e, s = import_bench_report(p, table, project)
        return e, s, "bench"
    e, s = import_proxy_report(p, table, project)
    return e, s, "proxy"
