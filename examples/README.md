# Examples

All files are local, illustrative, and free to re-run. No network,
no spend. The samples are format examples, never measured spend.

| File | What it is |
|---|---|
| `sample-history.jsonl` | A ledger in the core entry shape: 8 entries covering all four sources (slice, proxy, bench, manual), 2 projects, 3 models, 3 agents, 2 days. Includes the planted teaching cases: led-007 at 3.6x its estimate (loop warning), led-008 at 2.9x (under threshold, not warned) on an unlisted `mystery-model` (cost null, unknown, never $0-as-fact), and zero-rate `local` entries whose $0.00 cost is genuine. |
| `sample-report.json` | The report for that history, in the core `summarise()` shape, recomputed from the history alone. Carries `"sample": true` and a sample note. |
| `sample-report.md` | The same report in the `LEDGER.md` shape the core report writer produces. |
| `inputs/slice-history.jsonl` | A GhostSlice `.ghostslice-history.jsonl` in the real shape (at / kind / before_tokens / after_tokens / saved_tokens / estimator). |
| `inputs/proxy-report.json` | A GhostProxy report in the real shape: top-level `requests` count plus `entries[]` with `tokens_in` / `tokens_out` and slicable-context totals kept separate. |
| `inputs/bench-report.json` | A minimal GhostBench `bench-report.json`: `tasks[]` with `full_tokens` and a `variants` block, plus corpus totals. |

## Five-minute demo (all local)

```bash
cd ghostledger

# Start an empty ledger in /tmp and import one file per source
export GHOSTLEDGER_FILE=/tmp/demo-books.jsonl
rm -f "$GHOSTLEDGER_FILE"
PYTHONPATH=src python3 -m ghostledger import \
  --slice-history examples/inputs/slice-history.jsonl
PYTHONPATH=src python3 -m ghostledger import \
  --proxy-report examples/inputs/proxy-report.json
PYTHONPATH=src python3 -m ghostledger import \
  --bench-report examples/inputs/bench-report.json

# Add a manual entry that trips the loop warning (3.6x)
PYTHONPATH=src python3 -m ghostledger add --project demo-shop \
  --model claude-sonnet --agent loopy-agent \
  --task "retry-heavy refactor attempt" \
  --input-tokens 3400 --output-tokens 200 --estimated-tokens 1000 \
  --at 2026-10-14T10:47:00+00:00

# Summary exits 1 while a loop warning is present (warning, not error)
PYTHONPATH=src python3 -m ghostledger summary
PYTHONPATH=src python3 -m ghostledger report --out-dir /tmp/demo-report
cat /tmp/demo-report/LEDGER.md
```

What to notice in the demo output:

- Slice entries book `after_tokens` as the actual (45,770 for the
  big export), with `before_tokens=129555` kept in the note.
- Proxy entries book `tokens_in + tokens_out` per request.
- Bench tasks book their `variants{}.sliced.tokens` as the actual
  (1000 per task here) with `full_tokens` (4200) as the estimate,
  since the Oct 14, 2026 polish closed finding F2. See `POLISH.md`
  in the repo root. The demo total is 79,570 tokens (it was 85,970
  under the v0.1 full-tokens booking).
- The summary headline separates estimated cost from tokens and
  names the price table date; costs are estimates, never bills.
- Re-running any import line adds 0 entries: imports never
  double-book.
