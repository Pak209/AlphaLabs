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

---

# PR4 plan — first APIRouter extraction from api.create_app (added 2026-07-09; PR1–PR3 merged)

`create_app` is a single 550-LOC closure holding **73 routes**. PR4 extracts
exactly one router — the smallest, safest cluster — and establishes the
pattern every later router PR copies. **No route path, response shape, auth
behavior, service call, telemetry, or DB access changes.**

## Router boundaries (the full future map, for orientation only)

ops/diagnostics · dashboard/market data · catalysts/intelligence · ideas +
approvals · trades/execution/performance · briefs/briefings · futures/options
· notifications/review · misc (journal, chat, seed). Each becomes its own
later PR; PR4 does ONE.

## First router to extract: **ops/diagnostics** (5 routes)

`GET /api/health`, `GET /api/db-status`, `GET /api/safety-status`,
`GET /api/diagnostics/rejection-waterfall`, `GET /api/ops/agent-status`

Why safest:
1. **All read-only GETs** — a botched extraction cannot approve, import, or
   trade; worst case is a broken status page.
2. **Smallest coherent cluster** (5 of 73) with the least handler logic —
   each is a one-line delegation to the service.
3. **Already tested by path**: health, safety-status, and the waterfall
   endpoint have direct assertions in `test_api.py`; the waterfall response
   body is additionally pinned by the golden test via the service delegate.
4. **Auth-neutral by construction**: `require_token_for_writes` is app-level
   middleware — routers included via `app.include_router` pass through it
   unchanged, and these are GETs (open by design) anyway.
5. They are physically the first block in the file (lines 63–94), so the
   extraction diff is contiguous and trivially reviewable.

## Files / functions to create

```
alpha_lab/routers/__init__.py      # empty marker (package exists for PR5+ siblings)
alpha_lab/routers/ops.py           # build_ops_router(lab) -> APIRouter
```

Factory-function pattern, preserving today's closure semantics exactly:
`build_ops_router(lab)` declares the five handlers on an `APIRouter` capturing
`lab`, with handler bodies moved **verbatim**. `create_app` replaces the five
inline handlers with one line: `app.include_router(build_ops_router(lab))`.
No `Depends`, no `app.state`, no DI framework — the same captured service
instance as today, just declared in another file.

## Dependency changes

- `routers/ops.py` imports `fastapi.APIRouter` + `typing.Any` only (the
  service instance arrives as a parameter; no `alpha_lab.service` import, so
  the import graph gains no new edges and boundary contracts are untouched).
- `api.py` imports `build_ops_router`. Nothing else moves.

## Tests that protect behavior

Existing (must pass unmodified): the three direct endpoint tests, auth suite,
golden waterfall (via service delegate), `PINNED_SURFACE`.

Added in commit A, **before** the split — the route-manifest characterization:
a test that snapshots the complete sorted `[(method, path)]` inventory of
`create_app().routes` (all 73) plus spot response-shape checks for
`db-status` and `agent-status` (the two cluster members without direct
tests). The extraction must keep the manifest byte-identical — the API
equivalent of PR1's golden test, and it protects every later router PR too.

## Risks

1. **Route registration order** — FastAPI matches distinct paths regardless
   of order, and none of the five overlap with other routes; the manifest
   test documents the full inventory either way.
2. **Closure drift** — handlers must capture the same `lab` instance;
   the factory receives it from `create_app`, same object, verified by the
   existing tests that exercise handlers against a seeded service.
3. **Scope creep** — resist "while I'm here" moves of dashboard or market
   routes; one cluster only.

## Rollback

Single revert: one new package, a five-handler deletion and one include line
in `api.py`. No callers, schemas, paths, or configs to unwind.

## Exact stopping point

PR4 = `routers/ops.py` + `routers/__init__.py` + route-manifest test +
five handlers removed from `api.py` + one `include_router` line. Expected
diff ≈ +90/−35 plus ~50 test lines. **Stop.** Not in PR4: any second router,
dashboard/market routes, auth changes, or `service.py` edits.

---

# PR5 plan — market-context seam, slice 1: pure BTC signal construction (added 2026-07-09; PR1–PR4 merged)

The market-context cluster in `service.py` has three coupling tiers, measured
by grep:

| Tier | Members | Coupling |
|---|---|---|
| **Pure** | `_btc_signal_from_market`, `_entry_zone`, `_stop_level`, `_target_level`, `_fmt_price` (~70 LOC) | none — functions of their inputs only |
| I/O-bearing | `_validation_price` (Polygon→Yahoo→Alpaca), `_equity_market_open` (+`_regular_equity_session_open`), `_safe_market_payload` | network / broker |
| Repo-coupled | `_current_market_regime`, `_latest_briefing_context` | repository/connection parameters |

**PR5 extracts the pure tier only.** The I/O and repo tiers are later slices
(PR6+), each with its own plan.

## Why this slice first

1. **Provably pure**: the five functions read no `self` state — they call only
   each other. A verbatim move cannot change behavior; the value-pin test
   makes that checkable.
2. **They construct trade-signal *text and levels*** (entry/stop/target,
   invalidation wording) for every after-hours BTC idea — exactly the kind of
   logic that deserves module-level unit testing it can't get as a private
   method tangle.
3. **Test-compatibility is a hard constraint discovered by measurement**: two
   crypto-scanner tests monkeypatch `lab._btc_signal_from_market` on the
   instance. The method therefore STAYS as a one-line delegate; the four
   helpers (no external callers — verified) move fully and are deleted from
   the class.

## Files / functions

```
alpha_lab/crypto_signals.py    # new: btc_signal_from_market(btc) public,
                               # _entry_zone/_stop_level/_target_level/_fmt_price private
alpha_lab/service.py           # −~70 LOC; _btc_signal_from_market → delegate
```

Flat module per the established pattern. Imports: `typing` only (pure
functions) — zero new import-graph edges.

## Test protection

- **Commit A (before the move)** — value-pin characterization:
  `_btc_signal_from_market` against three fixed payloads (bullish with full
  indicators, bearish, neutral/missing-EMA) asserting the exact returned
  signal dicts — ticker/bias/confidence/timeframe AND the composed thesis,
  catalyst, and invalidation strings with their price formatting.
- Existing suites unmodified: the two monkeypatching scanner tests (delegate
  preserves patchability), characterization surface, crypto-normalizer
  contract, golden waterfall.

## Risks

1. **Monkeypatch surface** — mitigated by keeping the delegate; the plan's
   defining constraint.
2. **String drift** — thesis/invalidation text feeds idea records and dedupe
   keys; the value-pin test compares full strings, not fragments.
3. **Scope creep** — `_safe_market_payload` (trivial but 3 call sites) and
   the I/O tier stay put; one tier per PR.

## Rollback

Single revert: one new module, one delegate, four deleted private methods,
zero public-surface or caller changes outside the class.

## Exact stopping point

PR5 = `crypto_signals.py` + value-pin test + delegate + four helper
deletions. Expected diff ≈ +90/−70 plus ~70 test lines. **Stop.** Not in
PR5: `_safe_market_payload`, `_validation_price`, market-open/session logic,
regime/briefing context, or any scanning-cluster method.

---

# PR6 plan — market-context seam, slice 2: self-free I/O helpers (added 2026-07-10; PR1–PR5 merged)

Extract the three **self-free** members of the I/O tier into a new
`alpha_lab/market_context.py` (the module the repo-coupled tier will also
join in PR7, completing the cluster's home):

| Function | Today | Notes (measured) |
|---|---|---|
| `validation_price(ticker)` | `_validation_price`, 4 internal call sites | Polygon→Yahoo→Alpaca chain; env/network only, no self-state |
| `regular_equity_session_open(now=None)` | `_regular_equity_session_open`, 1 caller | pure datetime; gains an optional `now` injection (default = real clock, behavior-identical) so it becomes testable for the first time |
| `safe_market_payload(fn)` | `_safe_market_payload`, 3 call sites | trivial error-envelope wrapper |

**Stays in service:** `_equity_market_open` (broker-factory coupling; two
tests monkeypatch it on the instance) — its fallback line changes to call the
module function. `_validation_price` **stays as a delegate** (test_performance
monkeypatches it on the instance).

## The wrinkle this plan must be honest about

`test_price_volume_feed` characterizes the quote-fallback chain by
monkeypatching `fetch_polygon_intraday` / `fetch_yahoo_price` **on the
service module's namespace**. After the move, the chain executes in
`market_context`'s namespace, so those patches no longer reach it. The tests
must be **mechanically retargeted** (patch `market_context.fetch_yahoo_price`
instead of `service_mod.fetch_yahoo_price`) with assertions unchanged. This
is a declared exception to the tests-pass-unmodified gold standard — same
semantics, new patch target — called out in the PR description and handoff.
The instance-level patch in `test_performance` is preserved by the delegate
and needs no edit.

## Test protection

- Existing integration coverage IS the pre-move characterization:
  the fallback-order tests (retargeted mechanically), scanner tests
  exercising `safe_market_payload` through `poll_crypto_24_7`, the
  after-hours flow, and the instance-level `_validation_price` patch.
- New unit tests arrive WITH the module (they cannot precede it):
  `regular_equity_session_open` weekday/weekend/9:29/9:30/15:59/16:00
  boundaries via `now` injection; `safe_market_payload` ok + error-envelope
  cases.
- Full suite + `PINNED_SURFACE` (none of these are public members).

## Risks

1. **Patch-retarget edits** (above) — mechanical, declared, assertions
   untouched.
2. **One-line touch in `poll_crypto_24_7`** (Codex-authored region) for the
   `safe_market_payload` call — smallest possible diff there.
3. **`now` parameter** — new-surface-only; the no-arg call path is
   byte-identical to today.

## Rollback

Single revert: one module, one delegate, two deleted methods, four one-line
call-site edits, one retargeted test file.

## Exact stopping point

PR6 = `market_context.py` + delegate + deletions + call-site edits +
retargeted patches + new unit tests. Expected diff ≈ +110/−60 plus ~60 test
lines. **Stop.** Not in PR6: `_equity_market_open` extraction, repo tier
(`_current_market_regime`, `_latest_briefing_context` — PR7), scanning
cluster, anything else.

---

# PR7 plan — market-context seam, slice 3: repo-coupled tier (added 2026-07-10; PR1–PR6 merged)

Move the last two cluster members into `alpha_lab/market_context.py`,
completing the cluster's home. Measured facts that make this the easiest
slice yet:

- `_current_market_regime(repo)` and `_latest_briefing_context(conn)` read
  **zero self-state** — their repo/connection dependencies are already
  threaded as parameters.
- **No test monkeypatches either method** (grep: zero references under
  tests/) → **no delegates needed**; both methods are deleted outright.
- Five call sites total (`create_idea` ×2, `catalyst_intelligence`,
  `generate_after_hours_btc_idea`, `place_trade`'s evaluation path), each a
  one-line `self._x(...)` → `x(...)` edit.
- `market_context` will import `AlphaLabRepository` — an alpha_lab-internal
  edge. Verified against the boundary contracts: the pure-core ban list only
  constrains `PURE_CORE_MODULES` (market_context is not one), and the
  paper_trader bridge entry already exists from PR6. **Zero contract edits.**

## Functions to create

```
market_context.current_market_regime(repo: AlphaLabRepository) -> str
market_context.latest_briefing_context(conn) -> dict[str, Any]
```

Bodies verbatim, including `current_market_regime`'s except→"unknown"
fail-safe (that behavior is load-bearing: a regime read must never block idea
creation).

## Test protection

- **Commit A (before the move)** — characterization through the PUBLIC path,
  which survives the move untouched: `create_idea` with no stored briefing
  stamps `market_regime == "unknown"`; after saving a briefing with
  `broad_market_tone: "Risk-On Watch"`, `create_idea` stamps the lowercased
  `"risk-on watch"`. (`latest_briefing_context` has no test-visible public
  surface — it feeds the analyst context — so its pins arrive as module unit
  tests in commit B; stated honestly rather than pretending coverage.)
- **Commit B** — module unit tests: regime with briefing / without / with a
  raising repo stub → "unknown"; briefing context empty → `{}` and populated
  → exact dict.
- Full suite; `PINNED_SURFACE` unaffected (both are private and unpinned).

## Risks

1. Two call sites sit in Codex-active regions (`catalyst_intelligence`,
   `generate_after_hours_btc_idea`) — one-line edits, smallest possible
   conflict surface.
2. The raising-repo stub in tests must not over-specify the repo interface —
   a plain object with a raising `list_market_briefings` suffices.
3. Scope: `_equity_market_open` remains in service **by design** (broker
   coupling); this PR closes the market-context cluster otherwise.

## Rollback

Single revert: two module functions, two method deletions, five one-line
call-site edits, tests.

## Exact stopping point

PR7 = the two moves + call-site edits + commit-A public-path characterization
+ commit-B unit tests. Expected diff ≈ +60/−35 plus ~70 test lines. **Stop.**
After PR7 the market-context seam is DONE; the next Phase 2 candidate is the
scanning cluster (highest Codex churn — needs coordination) or a deliberate
pause of Phase 2.

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
