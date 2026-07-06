"""Run a pre-registered experiment spec against recorded telemetry.

Usage (read-only; never mutates the database):

    python3 -m research.run_experiment research/experiments/EXP-0001-*.json
    python3 -m research.run_experiment SPEC.json --db /path/to/db --out research/validation

Loads the spec, builds the population frame, computes the standard metric
battery requested by the spec, evaluates the spec's minimum-sample gates, and
writes a validation report (Markdown + JSON) into the output directory.

The runner never renders a promote/reject decision. Its verdict is either
INSUFFICIENT_DATA (a sample gate failed — the evidence is not interpretable
yet) or READY_FOR_REVIEW (battery computed; a human applies the pre-registered
decision rule and the promotion criteria in docs/RESEARCH_WORKFLOW.md).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research import metrics, telemetry

DEFAULT_OUT_DIR = Path(__file__).resolve().parent / "validation"

REQUIRED_SPEC_FIELDS = ("id", "title", "class", "status", "hypothesis",
                        "population", "variable", "analyses", "sample_gates",
                        "decision_rule")


def load_spec(path: Path) -> dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    missing = [f for f in REQUIRED_SPEC_FIELDS if f not in spec]
    if missing:
        raise ValueError(f"spec {path.name} is missing required fields: {missing}")
    if spec["class"] not in {"A", "B", "C", "D"}:
        raise ValueError(f"spec class must be A/B/C/D, got {spec['class']!r}")
    return spec


def _apply_filters(rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    def keep(row: dict[str, Any]) -> bool:
        for key in ("source", "asset_type", "status"):
            allowed = filters.get(key)
            if allowed and row.get(key) not in allowed:
                return False
        if filters.get("evaluated_only") and not row.get("evaluated"):
            return False
        return True
    return [r for r in rows if keep(r)]


def build_population(conn, spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None]:
    """Returns (population frame, decision frame or None).

    The decision frame is loaded whenever any analysis needs gate traces,
    regardless of which frame the population uses.
    """
    population_cfg = spec["population"]
    table = population_cfg.get("table", "idea_outcomes")
    filters = population_cfg.get("filters", {}) or {}

    decision_frame = None
    needs_decisions = table == "decision_outcomes" or any(
        a.get("type") == "regret" for a in spec["analyses"]
    )
    if needs_decisions:
        decision_frame = telemetry.load_decision_outcomes(
            conn, limit=int(population_cfg.get("limit", 5000)))

    if table == "idea_outcomes":
        frame = telemetry.load_idea_outcomes(
            conn, since=filters.get("since"), until=filters.get("until"))
    elif table == "decision_outcomes":
        frame = decision_frame or []
    else:
        raise ValueError(f"unknown population table: {table!r}")
    return _apply_filters(frame, filters), decision_frame


def run_analyses(spec: dict[str, Any], population: list[dict[str, Any]],
                 decision_frame: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    value_key = spec["variable"]["key"]
    label_key = spec.get("label", {}).get("key", "excess_move_pct")
    hit_key = spec.get("label", {}).get("hit_key", "hit")
    results: list[dict[str, Any]] = []
    for analysis in spec["analyses"]:
        kind = analysis["type"]
        if kind == "summary":
            result: dict[str, Any] = metrics.outcome_summary(population, label_key, hit_key)
        elif kind == "threshold_step":
            result = metrics.threshold_step(
                population, value_key, float(analysis["threshold"]),
                near_margin_frac=float(analysis.get("near_margin_frac", 0.10)),
                label_key=label_key, hit_key=hit_key)
            result["simulated_pass_rates"] = [
                metrics.simulated_pass_rate(population, value_key, float(t))
                for t in analysis.get("proposed_thresholds", [])
            ]
        elif kind == "buckets":
            result = metrics.bucket_lift(population, value_key,
                                         buckets=int(analysis.get("buckets", 10)),
                                         label_key=label_key, hit_key=hit_key)
        elif kind == "calibration":
            result = {"table": metrics.calibration_table(
                population, confidence_key=analysis.get("confidence_key", value_key),
                buckets=int(analysis.get("buckets", 5)),
                hit_key=hit_key, label_key=label_key)}
        elif kind == "session_stability":
            result = metrics.session_stability(population, label_key, hit_key)
        elif kind == "regret":
            if decision_frame is None:
                raise ValueError("regret analysis requires decision telemetry")
            result = metrics.regret_analysis(decision_frame, analysis["gate"],
                                             label_key, hit_key)
        else:
            raise ValueError(f"unknown analysis type: {kind!r}")
        result["analysis"] = kind
        results.append(result)
    return results


def evaluate_sample_gates(spec: dict[str, Any], population: list[dict[str, Any]],
                          results: list[dict[str, Any]]) -> dict[str, Any]:
    cfg = spec["sample_gates"]
    labeled = sum(1 for r in population if r.get("hit") is not None)
    sessions = {str(r.get("session")) for r in population if r.get("hit") is not None}
    checks: dict[str, tuple[int, int]] = {
        "rows": (len(population), int(cfg.get("min_rows", 0))),
        "labeled_rows": (labeled, int(cfg.get("min_labeled_rows", 0))),
        "sessions": (len(sessions), int(cfg.get("min_sessions", 0))),
    }
    if "min_near_misses" in cfg:
        near = 0
        for result in results:
            if result.get("analysis") == "threshold_step":
                near = max(near, result["bands"]["near_miss"]["labeled"])
            if result.get("analysis") == "regret":
                near = max(near, result["rejected_near_miss"]["labeled"])
        checks["near_misses"] = (near, int(cfg["min_near_misses"]))
    return metrics.sample_gates(checks)


# ── report rendering ─────────────────────────────────────────────────────────

def _fmt_interval(iv: dict[str, Any] | None, pct: bool = False) -> str:
    if not iv:
        return "n/a"
    if "rate" in iv:
        return f"{iv['rate']:.1%} [{iv['low']:.1%}, {iv['high']:.1%}] (n={iv['n']})"
    unit = "%" if pct else ""
    return f"{iv['mean']:.3f}{unit} [{iv['low']:.3f}, {iv['high']:.3f}] (n={iv['n']})"


def _band_table(bands: dict[str, Any]) -> list[str]:
    lines = ["| band | rows | labeled | hit rate (95% CI) | mean excess move (95% CI) |",
             "|---|---|---|---|---|"]
    for name in ("below", "near_miss", "above"):
        b = bands[name]
        lines.append(f"| {name} | {b['rows']} | {b['labeled']} | "
                     f"{_fmt_interval(b['hit'])} | {_fmt_interval(b['label_mean'], pct=True)} |")
    return lines


def render_markdown(spec: dict[str, Any], results: list[dict[str, Any]],
                    gates: dict[str, Any], meta: dict[str, Any]) -> str:
    lines = [
        f"# Validation report — {spec['id']}: {spec['title']}",
        "",
        f"- Generated: {meta['generated_at']}  ",
        f"- Experiment class: {spec['class']} · spec status: {spec['status']}  ",
        f"- Database: `{meta['db_path']}` (read-only)  ",
        f"- Population: `{spec['population'].get('table', 'idea_outcomes')}`, "
        f"{meta['population_rows']} rows ({meta['labeled_rows']} labeled, "
        f"{meta['session_count']} sessions)  ",
        f"- Verdict: **{meta['verdict']}**",
        "",
        "## Hypothesis (pre-registered)",
        "", spec["hypothesis"], "",
        "## Decision rule (pre-registered)",
        "", spec["decision_rule"], "",
        "## Sample gates",
        "",
        "| gate | observed | required | passed |",
        "|---|---|---|---|",
    ]
    for name, d in gates["detail"].items():
        lines.append(f"| {name} | {d['observed']} | {d['required']} | "
                     f"{'yes' if d['passed'] else '**NO**'} |")
    lines.append("")

    for result in results:
        kind = result["analysis"]
        lines.append(f"## Analysis: {kind}")
        lines.append("")
        if kind == "summary":
            lines.append(f"- Hit rate: {_fmt_interval(result['hit'])}")
            lines.append(f"- Mean excess move: {_fmt_interval(result['label_mean'], pct=True)}")
            lines.append(f"- Label coverage: {result['coverage']}")
        elif kind == "threshold_step":
            lines.append(f"Variable `{result['value_key']}` at threshold "
                         f"{result['threshold']} (near-miss margin {result['near_margin']}).")
            lines.append("")
            lines.extend(_band_table(result["bands"]))
            lines.append("")
            step = result["step_detected_vs_near_miss"]
            lines.append(f"- Step detected vs near-miss band: "
                         f"{'undetermined (intervals unavailable)' if step is None else step}")
            for sim in result.get("simulated_pass_rates", []):
                lines.append(f"- Simulated pass rate at {sim['proposed_threshold']}: "
                             f"{sim['pass_rate']}")
        elif kind == "buckets":
            lines.append(f"Spearman({result['value_key']}, label) = "
                         f"{result['spearman_value_vs_label']}")
            lines.append("")
            lines.append("| bucket | value range | hit rate (95% CI) | mean excess move |")
            lines.append("|---|---|---|---|")
            for b in result["buckets"]:
                lines.append(f"| {b['bucket']} | {b['value_min']}–{b['value_max']} | "
                             f"{_fmt_interval(b['hit'])} | {_fmt_interval(b['label_mean'], pct=True)} |")
        elif kind == "calibration":
            lines.append("| stated confidence | realized hit rate (95% CI) |")
            lines.append("|---|---|")
            for row in result["table"]:
                lines.append(f"| {row['stated_mean']} "
                             f"({row['confidence_low']}–{row['confidence_high']}) | "
                             f"{_fmt_interval(row['realized_hit'])} |")
        elif kind == "session_stability":
            lines.append(f"- Sessions with labels: {result['session_count']} "
                         f"(qualifying: {result['qualifying_sessions']})")
            lines.append(f"- Positive-session share: {result['positive_session_share']}")
        elif kind == "regret":
            lines.append(f"Gate `{result['gate']}` — accepted vs rejected outcomes "
                         f"(first-failed attribution):")
            lines.append("")
            lines.append("| population | rows | labeled | hit rate (95% CI) | mean excess move |")
            lines.append("|---|---|---|---|---|")
            for name in ("accepted", "rejected_near_miss", "rejected_far"):
                b = result[name]
                lines.append(f"| {name} | {b['rows']} | {b['labeled']} | "
                             f"{_fmt_interval(b['hit'])} | {_fmt_interval(b['label_mean'], pct=True)} |")
            lines.append("")
            lines.append(f"- Regret flag: {result['regret_flag']}")
        lines.append("")

    lines.extend([
        "## Reproduction",
        "",
        "```bash",
        f"python3 -m research.run_experiment {meta['spec_path']}",
        "```",
        "",
        "_Generated by research/run_experiment.py — read-only; interprets nothing._",
        "_Promotion requires the human review steps in docs/RESEARCH_WORKFLOW.md._",
        "",
    ])
    return "\n".join(lines)


def run(spec_path: Path, db_path: str | None = None,
        out_dir: Path = DEFAULT_OUT_DIR) -> dict[str, Path]:
    spec = load_spec(spec_path)
    with telemetry.connect_readonly(db_path) as conn:
        population, decision_frame = build_population(conn, spec)
        results = run_analyses(spec, population, decision_frame)
        actual_db = db_path or "default (resolve_db_path)"
    gates = evaluate_sample_gates(spec, population, results)

    labeled = sum(1 for r in population if r.get("hit") is not None)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "db_path": actual_db,
        "spec_path": str(spec_path),
        "population_rows": len(population),
        "labeled_rows": labeled,
        "session_count": len({str(r.get("session")) for r in population if r.get("hit") is not None}),
        "verdict": "READY_FOR_REVIEW" if gates["passed"] else "INSUFFICIENT_DATA",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    base = out_dir / f"{spec['id']}-{stamp}"
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")
    json_path.write_text(json.dumps({"spec": spec, "meta": meta, "sample_gates": gates,
                                     "results": results}, indent=2, sort_keys=True),
                         encoding="utf-8")
    md_path.write_text(render_markdown(spec, results, gates, meta), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "verdict": meta["verdict"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, help="experiment spec JSON")
    parser.add_argument("--db", default=None, help="telemetry DB path (default: production path)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR,
                        help="report output directory")
    args = parser.parse_args(argv)
    written = run(args.spec, db_path=args.db, out_dir=args.out)
    print(f"verdict:  {written['verdict']}")
    print(f"report:   {written['markdown']}")
    print(f"data:     {written['json']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
