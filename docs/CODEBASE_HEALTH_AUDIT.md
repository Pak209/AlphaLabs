# AlphaLabs codebase health audit

Audited 2026-07-05 on the Mac mini working tree (branch
`merge/claude-codex-integration` @ `2f69194`, the merged Claude+Codex state;
note `origin/main` has since advanced to `aa048a2` — reconcile before acting).
Method: AST complexity scan, import-graph checks, reference greps, test-file
mapping, dependency inspection. **No runtime behavior was changed.** Every
recommendation below is either diagnostics, process, or a behavior-preserving
refactor gated on the characterization/boundary test suites — consistent with
the calibration protocol and approval model.

## 1. Overall health assessment

**Grade: B — structurally sound core with one god object and a thin test
frontier around I/O.**

Strengths (verified, not aspirational): the decision path is pure and
abstracted (`evaluate_signal` over `BrokerState`); the scoring engine is
deterministic with default-preserving scenario overrides; diagnostics layers
(replay/attribution/outcomes/portfolio) are read-only, fingerprinted, and share
one outcome vocabulary; **architecture rules are executable**
(`test_import_boundaries.py` enforces dependency direction and only tightens);
characterization tests pin service behavior; the ops journal is append-only
and current. 501 tests, ~12.3k test LOC against ~20.4k source LOC.

Weaknesses: `service.py` concentrates risk (2,459 LOC, 117 methods, 429
branch-mass — 2× the next file); network-facing modules are nearly untested;
Python 3.9.6 (EOL) with unpinned dependencies; a parallel legacy stack and
several dead adapters add reader load; production risk limits live in files
named `*.example.json`.

## 2. Technical debt inventory (evidence-backed)

| # | Debt | Evidence | Cost today |
|---|---|---|---|
| D1 | `AlphaLabService` god object | 2,459 LOC, 117 methods, one class; top branch-mass file (429) | every feature touches it; merge conflicts concentrate here (both July merges conflicted in service.py) |
| D2 | Untested network layer | `live_sources.py` (413 LOC, 5 vendor fetchers): **0** test files; `daily_brief`, `dashboard`, `db_status`, `runtime_diagnostics`, `seed`: 0 each | feed regressions are invisible until a live session breaks; contradicts the "silent failure detection" priority from the five-year review |
| D3 | Python 3.9.6 runtime (EOL Oct 2025) + unpinned deps (`>=` floors, no lockfile) | `.venv` python version; `requirements.txt` | security patches stopped; a fresh `pip install` can drift from the tested set |
| D4 | Two catalyst scoring systems | `catalysts.score_catalyst` (radar 8-factor, 133 LOC) **and** `scoring_engine.score_catalyst` (analyst-brain 4-signal) — same concept, different scales, bridged by adapters | every calibration change must be reasoned twice; confidence bug of 2026-07-04 was exactly this seam |
| D5 | Risk config from `*.example.json` | `DEFAULT_RISK_CONFIG = "alpha_lab/config.example.json"`; 3 example configs exist (root, alpha_lab, paper_trader), 2 diverge (max_open_positions 3 vs 20, allow_short false vs true) | "example" files are live safety limits; which file governs is tribal knowledge |
| D6 | Parallel legacy paper_trader stack | `runner/webhook/inbox_processor/scheduler/dashboard/main` (469 LOC) — standalone CLI stack predating alpha_lab; only `inbox_processor` is reached from alpha_lab's scheduler | two entry-point families to reason about in every safety review |
| D7 | Report-CLI boilerplate ×5 | `write_report`/timestamp/print scaffolding duplicated in all 5 diagnostics scripts | five copies to fix per change (already bit once: the snapshot-collision fix) |
| D8 | Dead/stale symbols | `_recent_crypto_idea_exists` (def only, superseded by cooldown in merge), `catalyst_inputs_from_alert` (unwired adapter), stale `.bak` files, `.venv.old-prepath/`, untracked `.pakos/` | reader confusion; grep noise |
| D9 | Branch drift | local tree ≠ `origin/main` (aa048a2); untracked junk in tree | audits and services run on a tree that GitHub doesn't show |

## 3. High-risk modules (change with extra care)

1. **`alpha_lab/service.py`** — D1; also the only module where *both* recent
   merges conflicted. Any edit here should run the characterization suite
   first and last.
2. **`paper_trader/decision_engine.py`** — `evaluate_signal` is now 216 LOC /
   26 branches (gate traces added). It is the safety kernel; it has strong
   tests, but its length now invites "just one more gate here" additions.
   Treat as frozen except through the approval process.
3. **`alpha_lab/api.py`** — `create_app` is a single 550-LOC closure holding
   ~60 routes (69 branches). Low logic density, but untestable in slices and
   hostile to grep.
4. **`alpha_lab/live_sources.py`** — highest external-failure surface, zero
   tests, and every scanner depends on it.
5. **`alpha_lab/repository.py`** — 1,330 LOC of hand-written SQL with the
   second-highest branch mass; schema drift lands here first.

## 4. Complexity hotspots (AST scan, top offenders)

| Function | Branches | Lines |
|---|---|---|
| `api.create_app` | 69 | 550 |
| `service.rejection_waterfall` | 54 | 195 |
| `futures_pulse.classify_regime` | 44 | 105 |
| `catalysts.classify_catalyst` | 28 | 46 |
| `models.normalize_idea_payload` | 27 | 76 |
| `decision_engine.evaluate_signal` | 26 | 216 |
| `service.poll_crypto_24_7` | 26 | 132 |
| `service.place_trade` | 24 | 162 |

Pattern: complexity clusters at *aggregation* (`rejection_waterfall`) and
*orchestration* (`place_trade`, `poll_crypto_24_7`) — not in the scoring math,
which stays clean. That is the right place for it, but the waterfall function
should be decomposed before it grows another section.

## 5. Dead code / unused abstractions

- `service._recent_crypto_idea_exists` — orphaned by the crypto_24_7 merge
  (cooldown superseded it); 1 remaining ref = its own definition.
- `scoring_engine.catalyst_inputs_from_alert` — adapter for a scanner-alert
  shape that nothing produces.
- `.ai/*.bak.*`, `scripts/verify_old_mac_runtime.sh.bak.*` — committed backup
  files.
- `.venv.old-prepath/` (46MB) and `.pakos/` — untracked junk in the tree.
- Borderline (decide, don't drift): the legacy paper_trader entry points (D6)
  — either promote to supported (add tests) or mark deprecated in README.

## 6. Duplicate logic

- **D4** is the significant one (two catalyst scorers). The merge already
  unified *confidence*; type-strength and materiality still exist twice.
- **D7** report-CLI scaffolding ×5 → one `alpha_lab/report_io.py` helper
  (write_report, timestamp naming, small-N warning banner, table printer).
- Three `config.example.json` files with divergent limits (D5).
- `_position_key` (decision_engine) vs `_canonical_crypto_ticker` (models) vs
  `normalize_crypto_symbol` (market_data) — three crypto-symbol normalizers
  born from the same requirement; they agree today, nothing enforces it.

## 7. Dependency review

- **Footprint is excellent**: six runtime deps, all mainstream (fastapi,
  uvicorn, apscheduler, httpx, pywebpush, pytest). No heavyweight scientific
  stack — the dependency-free metrics code is a deliberate and healthy choice.
- **Python 3.9.6 is EOL** (Apple CLT build; venv matches). The code already
  writes modern typing via `from __future__ import annotations`, so a move to
  3.11/3.12 is low-friction — but must be done deliberately (launchd agents
  pin the interpreter).
- **No pins/lockfile**: add a `requirements.lock` (pip freeze) checked in next
  to `requirements.txt`; services install from the lock, research from floors.
- npm side: `package.json` is script-shortcuts only, no JS dependencies — fine.

## 8. Test coverage gaps (by module, not lines)

Well covered: decision engine, scoring engine, replay/attribution/outcomes/
portfolio, waterfall, API auth/routes, scheduler safety, characterization and
import-boundary contracts.

Gaps, in order of risk:
1. `live_sources.py` — 0 tests. Highest value: fixture-based tests of each
   vendor parser (recorded JSON → normalized catalyst rows) plus the
   "disabled when key missing" contract for all five feeds.
2. `daily_brief.py` — 0 tests; it feeds `import_daily_brief_and_test` five
   times a day.
3. `notifications.py` — 1 test file for 1,003 LOC (push policy is
   safety-adjacent).
4. `market_data.py` — 1 test file for 1,228 LOC; the setup classifier
   (`_classify_stock_setup`, 21 branches) drives trending confidence and is
   directly testable with synthetic bars.
5. Ops/read-only modules (`db_status`, `runtime_diagnostics`, `seed`,
   `dashboard`) — low risk, lowest priority.

## 9. Prioritized implementation roadmap

**P0 — hygiene, zero behavior risk (one short session)**
1. Sync the branch state: land/reconcile with `origin/main` (aa048a2), delete
   merged local branches, add `.pakos/`/`.venv.old-prepath/` to local ignore,
   remove committed `.bak` files.
2. Check in `requirements.lock`; document interpreter version in README; add
   a `python --version` check to `diagnose_trading_pipeline.py`.
3. Delete D8 dead symbols (each is a 5-line change; characterization suite
   guards).

**P1 — test the frontier (diagnostics-only by definition)**
4. Fixture tests for `live_sources` parsers + disabled-feed contracts (gap #1).
5. Synthetic-bar tests for `_classify_stock_setup`; smoke test for
   `daily_brief`.
6. One shared crypto-symbol normalizer *test* asserting the three existing
   implementations agree on a symbol corpus (locks D6-adjacent drift without
   touching runtime code).

**P2 — structure-only refactors (behavior-frozen, suites before/after)**
7. Split `service.py` along its existing seams into mixins/submodules
   (scanning, execution, diagnostics/reporting, market context, ops) — the
   characterization tests exist precisely to make this safe.
8. Extract `report_io.py` from the 5 CLI scripts (D7).
9. Decompose `rejection_waterfall` into parse/aggregate/format helpers.
10. Split `api.create_app` into routers by domain (FastAPI `APIRouter`,
    mechanical move).

**P3 — decisions requiring your sign-off (architecture, not code)**
11. D5: rename live configs (`risk.paper.json`) and make `*.example.json`
    documentation-only — touches launch scripts, so it rides the deploy
    process.
12. D4: retire the radar's 8-factor scorer in favor of engine-derived scores
    (a *scoring* change → full calibration protocol with replay evidence).
13. D6: deprecate or re-adopt the legacy paper_trader entry points.
14. Python 3.11+ migration for the venv + launchd agents (ops window, with
    the diagnose script as the post-change verifier).

Ordering rationale: P0/P1 raise the safety net; P2 spends it on the god
object while it is still mergeable; P3 items change what the system *is* and
therefore wait for explicit approval, with D4 explicitly routed through the
calibration protocol since it touches scoring.
