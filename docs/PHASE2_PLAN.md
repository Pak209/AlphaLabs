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
