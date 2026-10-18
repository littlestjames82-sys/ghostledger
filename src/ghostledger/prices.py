"""Local dated price table (estimates only, never live/billed).

Resolution order:
1. explicit path argument
2. GHOSTLEDGER_PRICES env var
3. sibling GhostSlice checkout prices.json
4. bundled snapshot prices.json next to this module
5. built-in minimal fallback
"""
from __future__ import annotations
import json, os

_FALLBACK = {
    "as_of": "2026-10-12",
    "models": [
        {"id": "claude-sonnet", "input_per_mtok_usd": 3.0, "output_per_mtok_usd": 15.0},
        {"id": "local", "input_per_mtok_usd": 0.0, "output_per_mtok_usd": 0.0},
    ],
    "note": "Built-in fallback snapshot, NOT live prices.",
    "_source": "builtin-fallback",
}

def load_price_table(explicit=None) -> dict:
    candidates = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("GHOSTLEDGER_PRICES")
    if env:
        candidates.append(env)
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.normpath(os.path.join(here, "..", "..", "..", "ghostslice", "src", "ghostslice", "prices.json")))
    try:
        import ghostslice  # type: ignore
        candidates.append(os.path.join(os.path.dirname(ghostslice.__file__), "prices.json"))
    except Exception:
        pass
    candidates.append(os.path.join(here, "prices.json"))
    for cand in candidates:
        if cand and os.path.isfile(cand):
            try:
                with open(cand, encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict) and isinstance(data.get("models"), list):
                    data["_source"] = cand
                    return data
            except (OSError, json.JSONDecodeError):
                continue
    return dict(_FALLBACK)

def _rates_of(entry):
    try:
        return (float(entry.get("input_per_mtok_usd")), float(entry.get("output_per_mtok_usd")))
    except (TypeError, ValueError):
        return None

def model_rates(table: dict, model):
    if not model:
        return None
    models = table.get("models") or []
    # Exact match first, so a table that deliberately lists two ids
    # differing only by case keeps its own meaning.
    for entry in models:
        if entry.get("id") == model:
            return _rates_of(entry)
    # Then a normalised match: model labels arrive from other tools'
    # reports and hand-typed --model flags, and "Claude-Sonnet" or a
    # trailing space should not silently book as an unknown model.
    wanted = str(model).strip().casefold()
    for entry in models:
        if str(entry.get("id") or "").strip().casefold() == wanted:
            return _rates_of(entry)
    return None

def estimate_cost_usd(input_tokens: int, output_tokens: int, model, table=None):
    """Estimated cost or None when model unknown (stated, not guessed)."""
    table = table or load_price_table()
    rates = model_rates(table, model)
    if rates is None:
        return None
    in_rate, out_rate = rates
    return round((input_tokens * in_rate + output_tokens * out_rate) / 1_000_000, 6)
