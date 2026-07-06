# AlphaLabs long-term architecture (five-year view)

Status: **architecture definition — no behavior changes.**
Written 2026-07-04. This document defines the target modular structure,
dependency rules, ownership boundaries, and extension points for AlphaLabs as
it evolves over the next five years, plus a behavior-preserving refactoring
roadmap to get there. Companion documents: `docs/RESEARCH_WORKFLOW.md`
(research/promotion governance), `docs/CALIBRATION_PLAN.md` (threshold
governance), `.ai/agent-rules.md` (operational safety rules — any roadmap
phase touching runtime code requires explicit human approval).

---

## 1. Where the system is today (measured, 2026-07-04)

~19,100 lines of Python across three packages plus scripts and a static
prototype. The load-bearing facts:

- **`alpha_lab/service.py` (2,281 lines) is the hub.** `AlphaLabService`
  orchestrates ingestion, scoring, decision plumbing, the trade path,
  diagnostics, and evaluations. It is imported by `api.py`, `main.py`,
  `scheduler.py`, `seed.py`, and three operational scripts, and it imports
  ~20 modules across both packages. Every new capability currently lands as
  another method on this class.
- **The cross-package dependency is one-directional and correct:**
  `alpha_lab → paper_trader` (broker client, decision engine, audit log,
  config, models). `paper_trader` never imports back. `paper_trader` is
  simultaneously a library (used by the service) and a standalone app
  (runner, webhook, dashboard) — a dual role worth making explicit.
- **Pure cores already exist and are the healthiest code:**
  `scoring_engine.py` (pure functions over explicit `scoring_models` inputs),
  `paper_trader/decision_engine.py` (pure `evaluate_signal` with injected
  `BrokerState`, telemetry-only `GateTrace`), `replay.py` (scenario scoring
  over recorded rows), `research/metrics.py` (stdlib statistics).
- **Analytics are duplicating.** `replay.py` carries its own Spearman;
  `attribution.py`, `outcomes.py`, `portfolio.py`, and `research/telemetry.py`
  each hand-roll DB-row-to-frame loading. Runtime analytics and research
  analytics are converging on the same primitives from opposite sides.
- **Delivery is concentrated:** `api.py` has 74 routes on one FastAPI app;
  `repository.py` is a single 1,325-line data-access module over a ~25-table
  SQLite schema defined in `database.py`.
- **Governance is real but implicit in code:** approval queue, safety status,
  arming flags, the never-loosen list, paper-endpoint-only enforcement — all
  present, but scattered across `service.py`, `scheduler.py`, config, and
  docs rather than owned by one module.

The architecture below keeps everything that is working (pure cores,
one-directional dependencies, telemetry-first design, human approval gates)
and gives the growth a place to go other than `service.py`.

---

## 2. Architectural principles (the rules that outlive any module)

1. **The dependency arrow points from volatile to stable.** Delivery and
   orchestration change weekly; domain logic monthly; contracts and the quant
   core rarely. Imports must flow toward stability, never away from it.
2. **Pure core, effectful edges.** Anything that computes (scores, gates,
   metrics, replays) is a pure function over explicit input models. Anything
   that touches the world (HTTP, broker, DB, clock, env) is an adapter behind
   a small interface. This is already the house style — make it law.
3. **Telemetry is the spine, not a feature.** Every decision writes its
   inputs, thresholds, and outcomes. Replay, attribution, calibration,
   research, and portfolio intelligence are all *readers* of that spine. New
   capabilities earn trust by reading it, then shadow-writing to it, then —
   with human approval — acting.
4. **The safety plane is a layer, not a convention.** Arming, approvals,
   never-loosen thresholds, and paper-only enforcement form a distinct module
   that everything action-shaped must pass through. Humans own it; code
   changes to it are always a separate, explicit decision.
5. **Modular monolith by default.** One process, one database, strict
   internal boundaries. Process/service extraction is a last resort reserved
   for proven contention (see §7 non-goals), not an aspiration.

---

## 3. Target architecture

### Diagram

```mermaid
flowchart TB
    subgraph delivery["DELIVERY (volatile)"]
        API[api routers]
        REVIEW[review api]
        MCP[mcp server]
        NOTIF[notifications]
        DASH[dashboards / prototype]
    end

    subgraph orchestration["ORCHESTRATION"]
        SCHED[scheduler jobs]
        USECASE[use-case services\n(decomposed AlphaLabService)]
        OPS[ops CLI / scripts]
    end

    subgraph governance["GOVERNANCE (human-owned safety plane)"]
        SAFE[safety status · arming flags\napproval queue · never-loosen registry]
    end

    subgraph domain["DOMAIN"]
        SIGNALS[signals\ncatalyst radar · generators]
        DECISION[decision\ngates · risk · sizing]
        EVAL[evaluation\noutcomes · performance\nattribution · portfolio]
    end

    subgraph core["QUANT CORE (pure, no I/O)"]
        QUANT[scoring engine · metrics\nreplay scenarios · calibration math]
        CONTRACTS[contracts\nmodels · enums · ids]
    end

    subgraph adapters["ADAPTERS (ports & implementations)"]
        INGEST[ingestion\nnews · prices · options\nfutures · dark pool]
        EXEC[execution\nalpaca paper · simulated\nfuture brokers]
        STORE[store\nschema · repositories\nread models · migrations]
    end

    RESEARCH[research\nexperiments · promotion\n(read-only)]

    delivery --> orchestration
    orchestration --> governance
    orchestration --> domain
    governance --> domain
    domain --> core
    domain --> adapters
    adapters --> core
    RESEARCH -. read-only .-> STORE
    RESEARCH --> QUANT
```

Text form of the same layering (dependencies point downward only):

```
┌──────────────────────────────────────────────────────────────┐
│ DELIVERY      api · review api · mcp · notifications · UIs   │
├──────────────────────────────────────────────────────────────┤
│ ORCHESTRATION scheduler jobs · use-case services · ops CLI   │
├──────────────────────────────────────────────────────────────┤
│ GOVERNANCE    arming · approvals · never-loosen · paper-only │  ← human-owned
├──────────────────────────────────────────────────────────────┤
│ DOMAIN        signals │ decision │ evaluation                │
├──────────────────────────────────────────────────────────────┤
│ ADAPTERS      ingestion ports │ execution ports │ store      │
├──────────────────────────────────────────────────────────────┤
│ QUANT CORE    scoring · metrics · replay · calibration math  │  ← pure, no I/O
├──────────────────────────────────────────────────────────────┤
│ CONTRACTS     pydantic models · enums · identifiers          │  ← zero deps
└──────────────────────────────────────────────────────────────┘
   research/ sits beside the stack: quant core + read-only store access.
```

### Module boundaries and ownership

| Module (target) | Today's code | Owns | Exposes | May depend on | Must never |
|---|---|---|---|---|---|
| **contracts** | `models.py`, `scoring_models.py`, `paper_trader/models.py` | Shared vocabulary: Signal, Idea, Decision, AlphaScore, gate record shape | Typed models, enums | stdlib, pydantic | Import anything else in the repo |
| **quant core** | `scoring_engine.py`, `replay.py` (scoring/metrics half), `research/metrics.py`, `performance.py` math | All pure computation: component scores, composite math, replay scenario scoring, interval/rank statistics, calibration math | Pure functions | contracts | I/O, env, DB, clock, network — anything effectful |
| **ingestion** | `live_sources.py`, `market_data.py`, `options_flow.py`, `dark_pool.py`, `futures_pulse.py` (fetch half), `catalysts.py` (source half) | Provider ports + adapters; normalization to contract events; per-provider config/keys | `MarketDataPort`, `NewsPort`, `OptionsFlowPort`, … | contracts, quant core (normalization only) | decision, execution, store writes |
| **signals** | `catalysts.py` (radar half), `daily_brief.py`, trending/crypto generators in `market_data.py` | Turning normalized events into scored candidate ideas; novelty; dedupe windows | Generator port (`propose(context) -> [Idea]`) | contracts, quant core, ingestion ports | execution, governance internals |
| **decision** | `paper_trader/decision_engine.py`, `options_selector.py`, risk config | Gates, risk checks, sizing, gate-trace emission | `evaluate(signal, ctx) -> Decision` | contracts, quant core | Broker SDKs, DB, HTTP — broker state arrives via port |
| **execution** | `alpaca_client.py`, `simulated_broker.py`, `audit_log.py`, order plumbing in `service.py` | Broker ports + adapters; order lifecycle; execution audit writing | `BrokerPort` (account, positions, clock, quote, submit) | contracts, store (audit write path), governance checks | Deciding anything; bypassing governance |
| **store** | `database.py`, `repository.py` | Schema, migrations, repositories per aggregate, read models (`training_rows`), retention | Repositories, read-only query API | contracts | Domain logic; callers never hand-write SQL elsewhere |
| **evaluation** | `outcomes.py`, `performance.py`, `attribution.py`, `portfolio.py`, `signal_evaluations` lifecycle | Forward-outcome labeling, source scorecards, attribution, portfolio intelligence | Report builders (pure over frames from store) | contracts, quant core, store (read) | execution, ingestion |
| **governance** | approval queue, `scheduler_safety_status`, arming env flags, paper-only enforcement (today inside `service.py`/`scheduler.py`) | The safety plane: arming state, approvals, never-loosen registry, kill criteria | `require_approval()`, `is_armed()`, safety status | contracts, store | Being bypassed: execution and orchestration must route through it |
| **orchestration** | `scheduler.py`, `AlphaLabService` (decomposed), `main.py`, `runner.py`, scripts | Composing use cases: poll→signal→decide→record; job cadence; retries | Named use-case functions | everything below it | delivery |
| **delivery** | `api.py` (split into routers), `review_api.py`, `mcp_server.py`, `notifications.py`, `dashboard.py`, `prototype/` | Transport, serialization, auth, push | HTTP/MCP endpoints, UI payloads | orchestration (and read models for GETs) | domain internals, adapters directly |
| **research** | `research/` (as built) | Experiments, validation reports, promotion evidence | Specs, reports, registry | quant core, store (read-only), contracts | Runtime imports in either direction; any write path |

Ownership of responsibilities, stated once: **humans own governance** (its
values change only by explicit human decision); **research owns evidence**
(no live effect by construction); **domain owns correctness** (pure,
testable); **adapters own the outside world** (replaceable); **orchestration
owns sequencing** (thin); **delivery owns presentation** (thin).

---

## 4. Dependency recommendations

**Direction rules (enforce, don't just document):**

1. Downward only, per the layer table. No module imports a layer above it.
2. `contracts` imports nothing internal; `quant core` imports only
   `contracts`. A single effectful import (os, requests, sqlite3) in the
   quant core is a build failure, not a review comment.
3. Adapters depend on ports defined in the domain/contracts, not vice versa
   (`BrokerState` in `decision_engine.py` already models this — generalize
   it to ingestion providers).
4. `research` ↔ runtime isolation stays absolute in both directions; shared
   code lives only in `quant core` and `contracts` (this dissolves today's
   metric duplication legally instead of by copy-paste).
5. `alpha_lab → paper_trader` remains one-directional until Phase 3 merges
   the decision/execution halves into their own layers; never add the
   reverse import in the interim.

**Enforcement tooling (diagnostics-only, adopt early):** implemented
2026-07-04 as a dependency-free AST checker in
`alpha_lab/tests/test_import_boundaries.py` (contracts C1–C8: package
direction, research isolation, store read path, pure-core purity, store
foundation, delivery entry points, frozen cross-package bridges, and a known
layer-debt register that must stay accurate in both directions). Seeded with
the graph as measured that day, so it passes and may only tighten. Migrating
the same contracts to `import-linter` in CI remains an option later; the
rules, not the tool, are the contract.

**Third-party policy:** the runtime footprint is admirably small (fastapi,
uvicorn, apscheduler, httpx, pydantic, pywebpush) — keep it that way. Rules
of thumb: stdlib first (research/metrics proved the battery needs nothing
more); any new runtime dependency needs a line in the handoff log with the
reason; analytics-only dependencies (numpy/pandas/scipy, if ever) are
confined to `research/` extras, never imported by runtime; broker/provider
SDKs live only inside their adapter.

**Data-layer recommendations:** SQLite remains correct at this scale
(single writer, launchd cadence, one host). Treat the *schema* as the public
contract: introduce numbered migrations (today `_ensure_columns` is an
implicit migration system — formalize it before table 30), keep
`execution_audit`/`decision_logs` append-only as the event spine, and add
read-model views (like `training_rows`) rather than letting delivery
hand-roll joins. If concurrency pressure ever arrives, the exit is
WAL-mode → Postgres behind the same repository interface — an adapter swap,
not a redesign.

---

## 5. Future extension points

Each extension has a designed seam; none requires touching the quant core or
governance semantics.

| Future capability | Extension point | What changes | What must not change |
|---|---|---|---|
| New data provider (news, alt-data, L2, sentiment) | `ingestion` port + registry entry | New adapter module + config key | Signals/domain code; provider outages stay invisible (absence = neutral, as scoring already does) |
| Options-flow / dark-pool going live | Same ports the stubs implement today | Adapter wiring + shadow period | Conviction-modifier gate semantics (CRITICAL RULE) |
| New broker or account | `execution.BrokerPort` adapter | New adapter + governance-gated config | Decision engine; paper-only enforcement stays in governance |
| Live (non-paper) trading — if ever | Governance plane: new arming tier + approval flow | A human decision first, code second | Everything else: the decision path must not know paper from live |
| New asset class (futures, FX) | contracts enums + decision gate table + sizing strategy | Per-class gates like today's crypto/option branches, made table-driven | Composite scoring (components renormalize already) |
| New scoring component or ML model | quant core: `ComponentScore` producer behind a `ModelPort` (`predict(features) -> score, explanation`) | Versioned model registry; promotion via research ladder (Class B/C) | Explainability contract — every score keeps its sub-signal breakdown; no opaque score enters the composite |
| New idea generator / strategy | `signals` generator port | New generator, Class D experiment, per-source attribution rides existing telemetry | Risk gates; watchlist scope (human-owned) |
| Portfolio construction / allocation | `evaluation/portfolio` → a sizing port consumed by decision | Sizing strategy selection, still under max caps | Never-loosen caps as the outer bound |
| Regime models / macro nowcasting | quant core inputs (`MacroInputs` already explicit) | Briefing adapter supplies inputs (audit item #7) | Decision-time purity: inputs computed before, passed in |
| Event-driven internals (bus/queue) | The telemetry spine is already the event log | Only if scheduler contention is *measured*; consumers read the same tables first | Don't build a bus speculatively (§7) |
| Multi-user / multi-tenant review | delivery + read models | AuthN/AuthZ at delivery; read models per audience | Single write path; governance singleton |

---

## 6. Refactoring roadmap (behavior-preserving, approval-gated)

Rules for every phase: no behavior change (characterization tests prove it);
one move per change; old import paths keep working via re-export shims until
a major cleanup; each step lands with a handoff entry. Phases touching
runtime files require explicit human approval per `.ai/agent-rules.md` —
this roadmap is a proposal, not authorization.

**Phase 0 — Freeze the contract (safe now; no runtime edits).**
Characterization tests around `AlphaLabService`'s public surface (the ~7
importers), golden-file tests for `rejection_waterfall()` and
`serialize_decision()` payload shapes, and import-boundary contracts encoding
*today's* graph. Exit: CI fails on any new upward or cross-boundary import.

> **Status: implemented 2026-07-04.** Rails live in
> `alpha_lab/tests/test_characterization_service.py` (56-member public-surface
> freeze, constructor signature, waterfall + decision golden payloads,
> telemetry schema spine) and `alpha_lab/tests/test_import_boundaries.py`
> (contracts C1–C8). Run both with the normal suite:
> `.venv/bin/python3 -m pytest alpha_lab/tests -q`. Golden values change only
> with a deliberate, human-approved contract change in the same commit.
> One quirk was discovered and pinned during characterization: boolean gate
> observations enter `observed_stats` as 1.0/0.0 because Python bools are
> ints — harmless today, documented in the test.

**Phase 1 — Extract the quant core (highest value, lowest risk).**
Create the pure package; *move* `scoring_engine`, `scoring_models`, the
scoring/statistics halves of `replay.py` and `performance.py`; fold
`research/metrics.py` duplicates (Spearman, quantiles, intervals) into it;
research and runtime both import it. Pure-function moves with shims —
byte-identical outputs verifiable by replaying recorded rows before/after.
Exit: zero duplicated statistics implementations; purity contract green.

**Phase 2 — Decompose `AlphaLabService` behind its own name.**
Strangler split into use-case services (intake, decision-path, trade-path,
evaluation, diagnostics), with `AlphaLabService` remaining as a façade
delegating method-by-method, so `api.py`, `scheduler.py`, and scripts change
zero lines. Trade-path and arming extraction moves the governance checks
into an explicit governance module — behavior identical, location explicit.
Exit: `service.py` < 300 lines of delegation; every use case unit-testable
without FastAPI.

**Phase 3 — Ports for the edges.**
Protocol interfaces for ingestion providers and brokers (generalizing
`BrokerState`); registry-based wiring from config; split `api.py`'s 74
routes into per-domain routers mounted on the same app (URLs unchanged).
Exit: adding a provider or broker touches only a new adapter file + config.

**Phase 4 — Store formalization.**
Numbered migrations replacing implicit `_ensure_columns` growth; repository
split per aggregate (ideas/decisions/evaluations/notifications); read models
for the dashboard/review payloads. Exit: schema changes are reviewable
diffs; no SQL outside the store package.

**Phase 5 — Epochal options (years 2–5, evidence-driven only).**
Table-driven per-asset-class gate/sizing config; model registry for ML
components (research ladder governs promotion); Postgres/WAL migration *if*
write contention is measured; process split of delivery vs scheduler *if*
deploy cadence demands it. Each gets its own design doc + approval when its
trigger condition actually occurs.

Sequencing rationale: Phase 1 pays for itself immediately (dedupes analytics
and hardens the research/runtime boundary), Phase 2 removes the growth
bottleneck, Phases 3–4 make the extension points in §5 one-file changes.
Nothing requires a rewrite, a freeze, or a migration weekend.

---

## 7. Non-goals — things this architecture deliberately resists

- **Microservices / service mesh.** One operator, one host, launchd cadence:
  a modular monolith with enforced boundaries gives the same evolvability
  without the operational tax.
- **A message bus before measured need.** The append-only telemetry tables
  already are the event log; add consumers there first.
- **Framework churn.** FastAPI + APScheduler + SQLite are boring and
  sufficient; boring is a feature in a system that trades.
- **Auto-tuning / self-modifying thresholds.** The never-loosen list and the
  research promotion ladder exist precisely so evidence proposes and humans
  dispose. No architecture change may shorten that loop.
- **Big-bang reorganization.** Every phase above is incremental with shims;
  if a phase stalls, the system is left strictly better than before it.
