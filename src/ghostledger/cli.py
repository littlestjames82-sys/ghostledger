"""GhostLedger CLI.

  ghostledger add    --project P [--model M] [--agent A] [--task T]
                     [--input-tokens N] [--output-tokens N]
                     [--total-tokens N] [--estimated-tokens N]
                     [--at ISO] [--note TEXT]
  ghostledger import [--slice-history F ...] [--proxy-report F ...]
                     [--bench-report F ...] [--source-file F ...]
  ghostledger report [--by project|model|agent|day] [--since D]
                     [--until D] [--project P] [--out-dir DIR] [--json]
  ghostledger summary [--since D] [--until D] [--project P] [--json]

Ledger file: --ledger PATH, else $GHOSTLEDGER_FILE, else
./.ghostledger.jsonl. Prices: --prices PATH, else $GHOSTLEDGER_PRICES,
else Slice's table, else the bundled dated snapshot. All costs are
ESTIMATES from that dated table, never billed amounts. No network.
Exit codes: 0 ok, 1 loop warning present (report/summary only), 2 error.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

from . import __version__
from .ingest import import_bench_report, import_proxy_report, import_slice_history, import_source_file
from .ledger import append_entries, append_entry, default_ledger_path, filter_entries, load_entries, make_entry, summarise
from .prices import load_price_table
from .report import write_reports

def _print_summary(summary, by=None):
    t = summary["totals"]
    print(f"ghostledger: {t['entries']} entries, {t['total_tokens']:,} total tokens, "
          f"${t['cost_estimate_usd']:,.4f} estimated cost")
    print(f"  {summary['cost_note']}")
    print(f"  estimate vs actual (entries with an estimate only): estimated {t['estimated_tokens']:,} "
          f"vs actual {t.get('actual_tokens_with_estimate', t['total_tokens']):,} "
          f"(ratio {t.get('estimate_vs_actual_ratio')})")
    groups = summary[{"project": "by_project", "model": "by_model", "agent": "by_agent", "day": "by_day"}[by or "project"]]
    for key, g in groups.items():
        print(f"  {key}: {g['entries']} entries, {g['total_tokens']:,} tokens, ${g['cost_estimate_usd']:,.4f} est.")
    for e in summary["loop_warnings"]:
        print(f"  WARNING exceeded 3x estimate: {e.get('at')} project={e.get('project')} "
              f"total={e.get('total_tokens')} estimated={e.get('estimated_tokens')} ratio={e.get('ratio')}")
    if summary.get("unknown_models"):
        print(f"  unknown models (no cost estimate): {', '.join(summary['unknown_models'])}")

def _filtered(args, ledger_path):
    entries = load_entries(ledger_path)
    return filter_entries(entries, since=getattr(args, "since", None),
                          until=getattr(args, "until", None), project=getattr(args, "project_filter", None))

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ghostledger", description="Local token and cost ledger for GhostSlice")
    parser.add_argument("--version", action="version", version=f"ghostledger {__version__}")
    parser.add_argument("--ledger", help="ledger file (default: $GHOSTLEDGER_FILE or ./.ghostledger.jsonl)")
    parser.add_argument("--prices", help="local prices.json (default: $GHOSTLEDGER_PRICES or bundled dated snapshot)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="add a manual entry")
    p_add.add_argument("--project", required=True)
    p_add.add_argument("--model")
    p_add.add_argument("--agent")
    p_add.add_argument("--task", default="")
    p_add.add_argument("--kind", default="run")
    p_add.add_argument("--input-tokens", type=int, default=0)
    p_add.add_argument("--output-tokens", type=int, default=0)
    p_add.add_argument("--total-tokens", type=int)
    p_add.add_argument("--estimated-tokens", type=int)
    p_add.add_argument("--at")
    p_add.add_argument("--note", default="")

    p_imp = sub.add_parser("import", help="import Slice history / Proxy / Bench reports")
    p_imp.add_argument("--slice-history", action="append", default=[])
    p_imp.add_argument("--proxy-report", action="append", default=[])
    p_imp.add_argument("--bench-report", action="append", default=[])
    p_imp.add_argument("--source-file", action="append", default=[])
    p_imp.add_argument("--project", help="override project label for imported entries")

    for name in ("report", "summary"):
        p = sub.add_parser(name, help=f"{name} the ledger")
        p.add_argument("--since", help="YYYY-MM-DD inclusive")
        p.add_argument("--until", help="YYYY-MM-DD inclusive")
        p.add_argument("--project", dest="project_filter")
        p.add_argument("--json", action="store_true")
        if name == "report":
            p.add_argument("--by", choices=["project", "model", "agent", "day"], default="project")
            p.add_argument("--out-dir", default=".")

    args = parser.parse_args(argv)
    ledger_path = default_ledger_path(args.ledger)
    try:
        table = load_price_table(args.prices)
    except Exception as exc:
        print(f"error: could not load price table: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "add":
        try:
            entry = make_entry(project=args.project, model=args.model, agent=args.agent,
                               source="manual", kind=args.kind, task=args.task, at=args.at,
                               input_tokens=args.input_tokens, output_tokens=args.output_tokens,
                               total_tokens=args.total_tokens, estimated_tokens=args.estimated_tokens,
                               note=args.note, table=table)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        added = append_entry(ledger_path, entry)
        print(f"added entry {entry['id']} to {ledger_path}" if added else
              f"duplicate entry {entry['id']} already in {ledger_path}, not re-booked")
        if entry["loop_warning"]:
            print(f"  WARNING: total {entry['total_tokens']} exceeded 3x estimate {entry['estimated_tokens']} (ratio {entry['ratio']})")
        if entry["cost_estimate_usd"] is None and args.model:
            print(f"  note: model {args.model!r} not in price table (as of {table.get('as_of')}); cost unknown, not guessed")
        return 0

    if args.cmd == "import":
        total_added, total_skipped, total_seen = 0, 0, 0
        jobs = []
        for f in args.slice_history:
            jobs.append((f, import_slice_history))
        for f in args.proxy_report:
            jobs.append((f, import_proxy_report))
        for f in args.bench_report:
            jobs.append((f, import_bench_report))
        for f, fn in jobs:
            try:
                entries, skipped = fn(f, table, args.project)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                print(f"error: {f}: {exc}", file=sys.stderr)
                return 2
            added = append_entries(ledger_path, entries)
            total_added += added; total_skipped += skipped; total_seen += len(entries)
            print(f"{f}: {len(entries)} entries parsed, {added} added, {skipped} skipped")
        for f in args.source_file:
            try:
                entries, skipped, detected = import_source_file(f, table, args.project)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                print(f"error: {f}: {exc}", file=sys.stderr)
                return 2
            added = append_entries(ledger_path, entries)
            total_added += added; total_skipped += skipped; total_seen += len(entries)
            print(f"{f}: detected {detected}, {len(entries)} entries parsed, {added} added, {skipped} skipped")
        if not jobs and not args.source_file:
            print("error: nothing to import (give --slice-history, --proxy-report, --bench-report, or --source-file)", file=sys.stderr)
            return 2
        print(f"import complete: {total_added} added ({total_seen} parsed, {total_skipped} skipped) into {ledger_path}")
        return 0

    if args.cmd in ("report", "summary"):
        entries = _filtered(args, ledger_path)
        summary = summarise(entries, table)
        if args.cmd == "report" and not args.json:
            jpath, mpath = write_reports(summary, args.out_dir)
            print(f"wrote {jpath} and {mpath}")
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            _print_summary(summary, by=getattr(args, "by", "project"))
        return 1 if summary["loop_warnings"] else 0

    return 2

if __name__ == "__main__":
    sys.exit(main())
