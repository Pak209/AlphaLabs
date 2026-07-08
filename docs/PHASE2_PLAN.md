# Phase 2 plan — first extraction seam from service.py

Planned 2026-07-08. Planning only; nothing implemented. Prerequisite
discovered during planning: **git on the Mac mini is currently broken by an
un-accepted Xcode/CLT license (`exit 69` on every command)** — run
`sudo xcodebuild -license accept` before any Phase 2 branch is cut.

## 1. Proposed first seam: extract `rejection_waterfall` → `alpha_lab/waterfall.py`

### Why this seam is the safest starting point (measured, not guessed)

1. **Maximum mass, minimum blast radius.** It is the #2 complexity hotspot in
   the entire codebase (195 LOC, 54 branches — health audit §4) and the
   largest single method in `service.py`, yet its coupling to the class is
   *two references*: `self.db_path` and the `_LEGACY_CLAUSE_GATES` class
   constant. Verified by grep: no broker, no scoring, no env flags, no other
   service state.
2. **Provably inert.** The method is read-only aggregation (SELECTs over
   `execution_audit`, `scanner_runs`, `alpha_ideas`, `trades`). A botched
   extraction cannot alter trading behavior — the worst possible failure is a
   wrong report, which the golden test catches.
3. **The pattern already exists.** Replay, attribution, outcomes, and
   portfolio all live as flat modules exposing `build_*(db_path, …)`
   functions. The waterfall is the *only* diagnostics aggregation still
   trapped inside the service class. PR1 makes `service.py` conform to the
   codebase's own established pattern rather than inventing a new one.
4. **Protection is already in place.** The characterization suite pins the
   golden payload shape of `rejection_waterfall()` AND its public signature
   (`PINNED_SURFACE`); dedicated behavior tests cover structured/legacy
   parsing, near-misses, and observed-value quantiles; the API endpoint has
   its own test.
5. **Low merge-conflict risk.** Codex activity clusters in the
   scanning/crypto regions of `service.py`; the waterfall block is
   Claude-only history.

### Why not the other candidate seams first

| Seam | Why it waits |
|---|---|
| Scoring glue (`_score_idea`, `_price_volume_inputs`) | feeds live trading inputs — wrong place to learn the extraction workflow |
| Execution (`place_trade`, `run_decision`, approval gates) | the safety kernel; reason strings and gate ordering are frozen contract; extract last, if ever |
| Scanning (`poll_crypto_24_7`, `poll_live_catalysts`) | highest Codex churn → conflict magnet; stateful (scanner_runs accounting) |
| Ops/status (heartbeat, db_status) | trivial mass — low value for a first PR |

## 2. Responsibilities to extract (PR1 scope, verbatim move)

- `rejection_waterfall(self, limit)` body → module function
  `build_rejection_waterfall(db_path: str, limit: int = 5000) -> dict`
- `_LEGACY_CLAUSE_GATES` class constant → module constant
  `LEGACY_CLAUSE_GATES` (same tuples, same order — it is parsing contract)
- `AlphaLabService.rejection_waterfall` becomes a two-line delegate keeping
  the exact signature and docstring.

Explicitly **not** in PR1: any decomposition of the function's internals, any
caller changes, any renaming of report keys or gate identifiers.

## 3. Module layout

```
alpha_lab/waterfall.py        # new: LEGACY_CLAUSE_GATES, build_rejection_waterfall()
alpha_lab/service.py          # −~200 LOC; delegate remains
```

Flat module, mirroring `replay.py` / `attribution.py` / `outcomes.py` /
`portfolio.py`. (A `diagnostics/` package grouping is a separate, later
decision — not smuggled into PR1.)

## 4. Dependency changes

- `waterfall.py` imports: `json`, `typing`, `alpha_lab.database`
  (`connect`, `resolve_db_path`). Nothing else.
- `service.py` adds `from .waterfall import build_rejection_waterfall`.
- No cross-package imports → **import-boundary contracts untouched**.
- Callers (`api.py`, `diagnose_trading_pipeline.py`, `waterfall_snapshot.py`)
  keep calling `service.rejection_waterfall()` — zero call-site changes.
  (`research/telemetry.py` references the near-miss margin in a comment only;
  optional comment touch-up, no code meaning.)

## 5. Characterization tests protecting the refactor

Already existing (must stay green, unmodified):
- `test_characterization_service.py`: golden payload shape + `PINNED_SURFACE`
  signature pin for `rejection_waterfall(self, limit)`.
- Waterfall behavior tests: structured `_gates` parsing, legacy clause
  mapping, first-failed histogram, near-miss counting, observed-value
  quantiles, stage funnel.
- API endpoint test for `/api/diagnostics/rejection-waterfall`.

Added in PR1 **before** the move (commit A):
- A golden-**value** fixture test: seed a deterministic DB (structured rows
  including an advisory alpha-gate record, legacy free-text rows, a
  confidence near-miss, mixed stages), snapshot the complete report dict, and
  deep-compare. This makes the move verbatim-or-fail and remains the guard
  for PR2's internal decomposition.

## 6. Rollback strategy

- PR1 is one revertable unit: `git revert` restores byte-identical behavior.
- No schema, config, data, or caller changes to unwind; the delegate means no
  call-site migration exists in either direction.
- Post-merge validation on the mini: full suite + `diagnose_trading_pipeline`
  + one `waterfall_snapshot.py` run compared against the previous snapshot
  (same DB ⇒ identical gate counts). Any diff → revert first, investigate
  second.

## 7. Step-by-step implementation plan

0. Human: `sudo xcodebuild -license accept` (git is currently exit-69 broken);
   confirm `main` is green (533 tests).
1. Branch `refactor/p2-extract-waterfall` off `main`.
2. **Commit A** — golden-value characterization test against *current* code.
3. **Commit B** — create `alpha_lab/waterfall.py`; move the function body
   verbatim (mechanical edits only: `self.db_path` → `db_path` parameter,
   `self._LEGACY_CLAUSE_GATES` → `LEGACY_CLAUSE_GATES`); service delegate.
4. Full suite (expect 533 + new golden), diagnose smoke, snapshot smoke.
5. Push, PR, handoff entry. Request review with the golden test called out.

## 8. Recommended stopping point for PR1

Stop after step 5. The PR should contain exactly: one new module (verbatim
code), one delegate, one golden test. Expected diff: `service.py` −~200 LOC,
`waterfall.py` +~215, tests +~120. Anything more (decomposition, report_io,
routers) dilutes reviewability and rollback cleanliness.

---

# PR2 plan — decompose build_rejection_waterfall internals (added 2026-07-09, PR1 merged as cb5bb82)

Behavior-frozen decomposition of the ~200-LOC function inside
`alpha_lab/waterfall.py`, entirely under the golden-value test. **No output
key, gate name, reason string, SQL query, telemetry shape, or API behavior
changes.** One file (plus optional helper unit tests); the public
`build_rejection_waterfall(db_path, limit=5000)` signature is untouched.

## Proposed helpers and responsibilities

| Helper | Responsibility | Source today |
|---|---|---|
| `_load_inputs(db_path, limit)` | ALL four SQL reads, verbatim query strings; returns a small private dataclass (`audit_rows`, `audit_total`, `ideas_total`, `trades_paper`, `scanner_rows`). Everything downstream becomes pure. | lines 60–75 |
| `_parse_scanner_runs(scanner_rows)` | `candidates_scanned` + `pre_idea_skips` dict | lines 77–88 |
| `_near_miss(record)` | promote the existing closure verbatim to a module function | lines 102–112 |
| `_aggregate_gates(audit_rows)` | the main loop; returns a private dataclass: `gates`, `first_failed`, `structured_rows`, `accepted`, `submitted`, `alpha_gate_seen/passed`. Internally two branch helpers: `_apply_structured_records(...)` and `_apply_legacy_clauses(...)` | lines 114–169 |
| `_quantiles(values)` | promote the existing closure verbatim | lines 171–183 |
| `_finalize_gate_failures(gates, n_rows)` | failures-desc sort, `share_of_attempts`, `observed_stats` / `_observed` pop | lines 185–188 |
| `_build_stage_funnel(...)` | the seven `stage()` rows, format strings verbatim | lines 190–207 |
| `_build_threshold_impact(gates)` | the sorted top-12 impact list | lines 209–219 |
| `build_rejection_waterfall` | ~25-line orchestrator: load → parse → aggregate → finalize → assemble the same report dict, `generated_at` stamped here | remainder |

All helpers are module-private (`_`-prefixed): they are NOT public API and PR2
creates no new import surface (import-boundary contracts untouched).

## Test protection

Already in place (must pass **unmodified** — that is the definition of done):
- `test_waterfall_golden.py` — full-dict golden, which already pins the two
  subtle order dependencies: (a) **first-example-wins** capture (`example` set
  only when empty, so row iteration order matters), and (b) **stable-sort
  tie-breaking** (golden contains a confidence/market_open tie at 1 failure
  whose order comes from dict insertion order during aggregation).
- Waterfall behavior tests, API endpoint test, `PINNED_SURFACE`, golden shape
  characterization.

Added by PR2 (additive only): small unit tests for the two promoted pure
functions — `_near_miss` boundary cases (exact threshold, margin edge, wrong
comparator, non-numeric) and `_quantiles` (empty → None, single value, ties)
— which become addressable for the first time.

Verification protocol beyond the suite: run `build_rejection_waterfall`
against the production DB **before branching and after the change**, diff the
JSON minus `generated_at` — must be byte-identical (same DB, deterministic
function).

## Risks

1. **Iteration-order drift** — bucket insertion order feeds tie-breaking in
   two stable sorts, and `example` capture is first-wins. Mitigation: helpers
   receive rows in the same order and mutate the same dict; the golden's
   embedded tie catches regressions.
2. **Rounding placement** — `round(...)` calls must stay at the same points
   (moving a round changes 4th-decimal output). Golden catches.
3. **Scope creep** — tempting adjacent "fixes" that are explicitly OUT:
   unifying the near-miss margin with `outcomes.NEAR_MISS_MARGIN` /
   `research/telemetry.py` (cross-module contract change → its own decision),
   renaming output keys, touching SQL, adding parameters.
4. **Dataclass serialization** — private carriers must never leak into the
   report dict; assembly stays plain dicts.

## Rollback

Single `git revert` of one commit touching one module (plus a test file);
no callers, signatures, or data to unwind. If the production-DB diff shows
any discrepancy post-merge: revert first, investigate second.

## Exact stopping point

PR2 contains: `alpha_lab/waterfall.py` decomposition + `test_waterfall_golden.py`
untouched + one new `test_waterfall_helpers.py` (~60 lines). Expected diff
≈ +100/−80 in one module. **Stop.** Not in PR2: report_io extraction (PR3),
APIRouter split (PR4), near-miss-margin unification, any service.py change.

## 9. Phase 2 sequence after PR1 (each its own small PR)

1. **PR2** — decompose `build_rejection_waterfall` internals into
   parse/aggregate/format helpers *under the golden test* (audit item 9).
2. **PR3** — extract shared `report_io.py` from the five diagnostics CLIs
   (audit item 8).
3. **PR4** — split `api.create_app` into `APIRouter`s by domain (audit
   item 10; mechanical, endpoint tests as the guard).
4. **PR5+** — service split by responsibility cluster (market-context first,
   then scanning, execution last if ever), one cluster per PR, each preceded
   by its own seam analysis like this one.
