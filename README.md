# GhostLedger

**The books for agent work: what it cost, per project, per model, per agent, per day.**

GhostSlice estimates tokens before a run, GhostProxy sees tokens in
flight, and GhostBench measures tokens on proof tasks. None of them
answer the end-of-day question: what did I spend today, where did the
estimate and the actual diverge, and did an agent quietly burn 3x
what the slice said it should? GhostLedger ingests all three sources
plus manual entries into one local ledger and reports totals that
can be checked.

By Ghost Developer Studio. MIT licensed. **Zero dependencies**
(Python standard library only), **local-first**: no network calls,
no telemetry, ever. Ledger never approves, blocks, or dispatches
anything; Agent Seatbelt still governs what an agent does.

> Build status: v0.1. The commands, entry shape, and report format
> in this README describe the shipped core (`src/ghostledger/`).
> Test results and known limits are recorded honestly in
> `REPORT_B.md` (Agent B) and `IMPLEMENTATION_A.md` (core).

## Install

From a checkout, no install needed:

```bash
cd ghostledger
PYTHONPATH=src python3 -m ghostledger --help
```

Or install it (still zero dependencies):

```bash
pip install .
ghostledger --help
```

Requires Python 3.10 or newer.

## Quickstart

```bash
# Book a manual entry (cost estimated from the local price table)
ghostledger add --project ghostbus --model claude-sonnet \
  --agent builder-a --task "review pass" \
  --input-tokens 10000 --output-tokens 2000 --estimated-tokens 12000

# Import what the other Ghost tools already recorded
ghostledger import --slice-history ~/my-project/.ghostslice-history.jsonl
ghostledger import --proxy-report proxy-report.json
ghostledger import --bench-report bench-report.json
ghostledger import --source-file mystery.json   # auto-detects the shape

# Ask the end-of-day question
ghostledger summary
ghostledger summary --since 2026-10-01 --json
ghostledger report --out-dir ./ledger-out       # ledger-report.json + LEDGER.md
```

The ledger file is `./.ghostledger.jsonl` by default. Override it
with the global `--ledger PATH` flag (before the subcommand) or the
`GHOSTLEDGER_FILE` environment variable. Imports are idempotent:
re-importing the same file adds zero entries, never double-books.

Exit codes: `0` ok, `1` loop warning present (`report`/`summary`
only), `2` error.

## The loop warning

When an entry's `estimated_tokens > 0` and its actual
`total_tokens > 3 * estimated_tokens` (strictly greater), the entry
is flagged `loop_warning: true`, its ratio is shown, and it appears
in a dedicated Warnings section in every report and summary, which
then exit `1`. An entry at exactly 3.0x or below is not flagged.

**3x is a warning, not a verdict.** Legitimate retries happen. The
copy says "exceeded 3x its estimate", never that an agent looped as
a proven fact. Ledger reports the warning; acting on it stays with
the human and Seatbelt.

## Costs are estimates, always labelled

Every dollar figure is computed from a **local, dated price table**
(`prices.json`, same shape as GhostSlice's: `as_of`, `models[]` with
`input_per_mtok_usd` / `output_per_mtok_usd`). Resolution order:
`--prices PATH`, `GHOSTLEDGER_PRICES`, a sibling GhostSlice
checkout's table, then the bundled snapshot (as of 2026-10-12 at
build time). Every report carries the line:

> Costs are ESTIMATES from a local dated price table (as of
> 2026-10-12), never billed amounts.

These are **not live prices and not billed amounts**. Real bills
differ. An entry whose model is not in the table gets
`cost_estimate_usd: null` and the model is listed under
`unknown_models` in every report: unknown is stated, never guessed,
and never shown as $0. A model listed at a zero rate (local models)
is genuinely $0.00, which is a different thing and books as 0.0.
Model labels are matched to the table case-insensitively after an
exact match, and stored stripped of surrounding whitespace, so
`Claude-Sonnet` books the claude-sonnet estimate instead of a
false "unknown"; a genuinely unlisted model still books null.

Token counts are counts: a negative count is invalid evidence and
is never booked. `add` with a negative count exits `2` and writes
nothing; an imported record with a negative booked count is
counted as skipped (a negative `before_tokens` reference is simply
dropped from the note).

## Ledger entry format

One JSON object per line in `.ghostledger.jsonl`:

| Field | Meaning |
|---|---|
| `id` | Content hash of the entry's core fields; dedupe key on import/add |
| `at` / `day` | Timestamp (ISO) and its `YYYY-MM-DD` day, the by-day grouping key |
| `project` / `model` / `agent` | Grouping labels; missing model/agent book as null and group under `unknown` |
| `source` | `manual`, `slice`, `proxy`, or `bench` |
| `kind` / `task` | What the entry was (export, request, bench-task, run, ...) and its label |
| `input_tokens` / `output_tokens` / `total_tokens` | Booked counts. `--total-tokens` alone on `add` books as input so totals reconcile |
| `estimated_tokens` | The pre-run estimate the actual is compared against, or null |
| `ratio` | `total / estimated`, or null when there is no estimate |
| `loop_warning` / `loop_threshold` | The 3x flag and the threshold applied (3.0 in v0.1) |
| `cost_estimate_usd` | Estimated cost from the local table, or null when the model is unknown |
| `price_table_as_of` | Date of the price table the cost came from |
| `source_ref` | For imports: source file name + line/task index. No file bodies, ever |
| `note` | Free text; Slice imports keep `before_tokens=<n>` here as reference data |

## What each import reads

- **Slice history** (`.ghostslice-history.jsonl`): one entry per
  valid line. Booked input = `after_tokens` (what was actually
  sent), estimated = `after_tokens`, `before_tokens` kept in the
  note. Lines that are not JSON or carry no `after_tokens` are
  counted as skipped in the import output, never silently swallowed
  and never fatal to the good lines.
- **Proxy report** (GhostProxy's report JSON): records from the
  `requests`/`entries`/`records`/`calls` list, a bare list, or a
  single request object. Token keys are read tolerantly
  (`input_tokens`/`prompt_tokens`/`tokens_in`,
  `output_tokens`/`completion_tokens`/`tokens_out`).
- **Bench report** (`bench-report.json`): one entry per task in
  `tasks[]`. The booked actual is the task's sliced/proxied tokens
  when present - read from the top-level token fields first, then
  from `variants{}` (priority: `sliced`, then `proxied`,
  `verified`, `recalled`; a `variants.full.tokens` supplies the
  full count when `full_tokens` is absent) - and the estimate is
  `full_tokens` whenever a different actual was found, so a Bench
  entry shows the sliced-vs-full divergence ratio. A variant whose
  tokens are null, negative, or unparseable is treated as absent
  and the full count is the fallback actual. (Polish, Oct 14, 2026:
  this closes finding F2; the v0.1 importer booked actual as
  `full_tokens` because it never looked inside `variants{}`. See
  `POLISH.md`.)
- **`--source-file`** auto-detects: `.jsonl` is Slice history, JSON
  with `tasks[]` is Bench, anything else is treated as Proxy.

## Secrets discipline

Ledger files never contain API keys by construction. Importers drop
any field whose name suggests a credential (`api_key`, `auth`,
`secret`, `password`, `credential`, `bearer`, `session`, `cookie`,
`private_key`) before an entry is built. Token *counts*
(`*_tokens`) are numbers, not credentials, and are the only
token-named fields kept. Prompts, completions, and file bodies are
never stored: counts and labels only. The test suite plants a
labelled fake credential canary in a Proxy-shaped fixture and proves
it appears nowhere in the ledger after import.

## Commands

| Command | What it does |
|---|---|
| `ghostledger [--ledger PATH] [--prices PATH] add --project P [--model M] [--agent A] [--task T] [--kind K] [--input-tokens N] [--output-tokens N] [--total-tokens N] [--estimated-tokens N] [--at ISO] [--note TEXT]` | Append one manual entry. Prints the loop warning and the unknown-model note when they apply. Adding the identical entry twice does not double-book |
| `ghostledger import [--slice-history F ...] [--proxy-report F ...] [--bench-report F ...] [--source-file F ...] [--project P]` | Import from the other Ghost tools. Per file prints parsed / added / skipped. With nothing to import, exits 2 |
| `ghostledger report [--by project\|model\|agent\|day] [--since D] [--until D] [--project P] [--out-dir DIR] [--json]` | Writes `ledger-report.json` + `LEDGER.md` (all four groupings, estimate-vs-actual per group, warnings, unknown models, price date) and prints the summary. `--json` prints the summary JSON instead and writes no files. Exits 1 when a loop warning is present |
| `ghostledger summary [--since D] [--until D] [--project P] [--json]` | Printed quick view: entries, total tokens, estimated cost, estimate-vs-actual headline, warning count. Writes no files. Exits 1 when a loop warning is present |
| `ghostledger --version` | Print the version |

`--since`/`--until` filter inclusively on the entry's day;
`--project` filters to one project.

## Report format

`ledger-report.json` (and the `summary --json` / `report --json`
output) carries: `tool`, `version`, `totals`, grouped totals under
`by_project`, `by_model`, `by_agent`, and `by_day`, `loop_warnings`
(the full flagged entries), `loop_threshold`, `unknown_models`,
`price_table_as_of`, `price_table_source`, and the `cost_note`
above. Each totals/group bucket has `entries`, `input_tokens`,
`output_tokens`, `total_tokens`, `estimated_tokens`,
`entries_with_estimate`, `actual_tokens_with_estimate`,
`estimate_delta_tokens`, `estimate_vs_actual_ratio`,
`cost_estimate_usd`, `entries_with_cost`, and `loop_warnings`.
The estimate-vs-actual figures compare only the entries that carry
an estimate: `estimate_vs_actual_ratio` is
`actual_tokens_with_estimate / estimated_tokens`, and
`estimate_delta_tokens` is their difference. Entries with no
estimate count in `total_tokens` but never inflate the ratio
(polish, Oct 14, 2026; the v0.1 formula divided the grand total
by the estimated sum and overstated divergence whenever coverage
was partial). Note the honest split in
the grouped cost column: a bucket's `cost_estimate_usd` sums only
the entries that have a cost (`entries_with_cost`), so a bucket
with unknown-model entries shows the known part, with the unknown
count visible in the same bucket.

Token counts from different sources are not perfectly comparable
(Slice estimates vs Proxy counts vs Bench static counts vs manual
entries). Every entry and group keeps its source visible so the
mix is shown, not averaged away.

Two labelled SAMPLE files in `examples/` show the formats:
`sample-history.jsonl` (8 ledger entries covering all four sources,
one planted 3.6x loop warning, one 2.9x under-threshold entry, one
unknown-model entry) and `sample-report.json` / `sample-report.md`
recomputed from it. They are format examples, never measured spend.

## Verification bar (from PLAN.md)

- Manual round-trip: an `add` with a known model hand-checks
  against the dated table (10,000 in / 2,000 out on claude-sonnet
  at $3/$15 per Mtok = $0.06 estimated).
- Slice import: entry count equals valid history lines, totals
  equal the sum of `after_tokens`, re-import adds zero.
- Loop test: 3.1x is flagged and listed; 2.9x is not.
- Unknown model: cost reports as unknown (null), never $0-as-fact.
- No-secrets test: a Proxy-shaped fixture carrying an `api_key`
  field imports with that field absent everywhere in the ledger.

## Out of scope for v0.1

Calling any model or billing API, fetching live prices (no network
at all), blocking or throttling a runaway agent, storing prompts or
completions, accounts, cloud sync, telemetry, dashboards (a panel
in GhostSlice's dashboard is a v0.2 candidate once the numbers are
trusted), and rewriting Slice history, Proxy logs, or Bench
reports. Ledger reads them; it owns only `.ghostledger.jsonl` and
its own reports.

## Layout

```
src/ghostledger/    the core (Agent A): entry model + IO, price
                    table, Slice/Proxy/Bench importers, reports, CLI
tests/              format + fixture tests (run without the core) and
                    black-box CLI tests for add / import / report /
                    summary, loop boundaries, and the canary drop
examples/
  sample-history.jsonl   SAMPLE ledger, 8 entries, all four sources
  sample-report.json     SAMPLE report recomputed from the history
  sample-report.md       the same report in the LEDGER.md shape
  inputs/                one importable file per source tool
PLAN.md             the v0.1 plan this build follows
REPORT_B.md         tests/docs build report: honest pass/fail + findings
POLISH.md           Oct 14, 2026 polish round: audit, F2 fix, passes
```
