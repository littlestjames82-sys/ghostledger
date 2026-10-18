"""Report writers: ledger-report.json + LEDGER.md."""
from __future__ import annotations
import json
from pathlib import Path

def _fmt_cost(v):
    return "unknown" if v is None else f"${v:,.4f} (est.)"

def _group_table(title, groups):
    lines = [f"## By {title}", "", "| Group | Entries | Input | Output | Total | Estimated | Ratio | Cost est. | Warnings |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for key, g in groups.items():
        ratio = g.get("estimate_vs_actual_ratio")
        lines.append(f"| {key} | {g['entries']} | {g['input_tokens']:,} | {g['output_tokens']:,} | "
                     f"{g['total_tokens']:,} | {g['estimated_tokens']:,} | "
                     f"{ratio if ratio is not None else 'n/a'} | ${g['cost_estimate_usd']:,.4f} | {g['loop_warnings']} |")
    lines.append("")
    return lines

def render_markdown(summary: dict) -> str:
    t = summary["totals"]
    lines = ["# GhostLedger Report", "",
             summary["cost_note"], "",
             f"Price table as of: {summary.get('price_table_as_of')} (source: {summary.get('price_table_source')})",
             f"Loop warning threshold: actual > {summary.get('loop_threshold')}x estimate.", "",
             "## Totals", "",
             f"- Entries: {t['entries']}",
             f"- Input tokens: {t['input_tokens']:,}",
             f"- Output tokens: {t['output_tokens']:,}",
             f"- Total tokens: {t['total_tokens']:,}",
             f"- Estimated tokens (entries with an estimate): {t['estimated_tokens']:,}",
             f"- Estimate vs actual ratio: {t.get('estimate_vs_actual_ratio')}",
             f"- Estimated cost: ${t['cost_estimate_usd']:,.4f} (est., {t['entries_with_cost']} entries with a known model)",
             f"- Loop warnings: {t['loop_warnings']}", ""]
    if summary.get("unknown_models"):
        lines += [f"Unknown models (no cost estimate, never guessed): {', '.join(summary['unknown_models'])}", ""]
    lines += _group_table("project", summary["by_project"])
    lines += _group_table("model", summary["by_model"])
    lines += _group_table("agent", summary["by_agent"])
    lines += _group_table("day", summary["by_day"])
    lines += ["## Loop warnings (actual exceeded 3x its estimate)", ""]
    if summary["loop_warnings"]:
        for e in summary["loop_warnings"]:
            lines.append(f"- {e.get('at')} project={e.get('project')} model={e.get('model')} "
                         f"agent={e.get('agent')} task={e.get('task')!r} total={e.get('total_tokens')} "
                         f"estimated={e.get('estimated_tokens')} ratio={e.get('ratio')}")
    else:
        lines.append("None.")
    lines.append("")
    return "\n".join(lines)

def write_reports(summary: dict, out_dir) -> tuple:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "ledger-report.json"
    md_path = out / "LEDGER.md"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    return str(json_path), str(md_path)
