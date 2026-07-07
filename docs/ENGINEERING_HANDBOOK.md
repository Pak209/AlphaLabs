# The AlphaLabs Engineering Handbook

*Final handoff from the retiring lead engineer — 2026-07-05.*

This is the document to read before touching anything. It is not a tour of the
code (see `docs/ARCHITECTURE.md`) or a plan (see the roadmaps). It is the
judgment layer: what must never change, what will tempt you, and how to extend
the system without eroding what makes it trustworthy. It is written for every
future contributor — Claude, Codex, Hermes, or human — on the assumption that
you are competent, well-intentioned, and about to make one of the mistakes in
§3.

---

## 1. Architectural principles that must never change

**P1. Paper-only, structurally.** The system refuses non-paper Alpaca
endpoints in code, not in configuration. Live trading is not a feature waiting
for a flag; it is out of scope by design. No change may create a code path
where a config value, env var, or LLM output can reach a live endpoint.

**P2. The decision engine is a pure function.** `evaluate_signal(signal,
config, broker_state, audit) → Decision` has no I/O, no globals, no clock
reads beyond its inputs. This one property is why backtests, replay, shadow
validation, and production all run the *same* gate code. Anything that would
make it impure — a network call, a DB read, a singleton — breaks four systems
to save one import.

**P3. Scoring is deterministic; overrides default to live behavior.** Given
identical inputs, the engine returns identical outputs, and every scenario
parameter (`type_weights=None`, `weights=None`, …) reproduces the live
constants when unset. The baseline replay scenario *is* production. Guard this
with tests whenever a new parameter is added.

**P4. Evidence before behavior.** No threshold, weight, gate, sizing rule, or
exit policy changes without: attribution nominating it, replay/backtest
quantifying it, shadow validation confirming it live-but-inert, and a human
approving it. One change at a time, with a handoff entry. This protocol
(docs/CALIBRATION_PLAN.md §2) is the platform's most valuable asset — more
valuable than any single alpha idea it will ever produce.

**P5. Diagnostics are read-only and fingerprinted.** Replay, attribution,
outcomes, portfolio, waterfall: SELECTs only, never a write to production
tables, and every report carries a dataset fingerprint. Two results are
comparable only on identical fingerprints — comparison across fingerprints
must raise, not warn.

**P6. Telemetry is structural, not narrative.** Every gate records what it
compared, against what, and why — as data (`_gates`), not prose. If you add a
gate anywhere, it emits a trace record in the same shape, or it doesn't merge.

**P7. Safety controls compose via minimum.** Floors, ceilings, and caps are
combined with `min()`; a strong signal can never *lift* a weak safety bound.
Modifiers (options flow, institutional) are excluded — not down-weighted,
excluded — when confirmation fails.

**P8. The operational journal is append-only.** `.ai/LEX_REVIEW_HANDOFF.md`
entries are never edited or deleted, only added. When two histories diverge,
the merge is the chronological union of unique entries (this has already
happened once; the procedure worked).

**P9. Absence of data is neutral, never negative — and never positive.** A
missing provider drops its component and renormalizes weights. It does not
score 50, does not penalize, and absolutely does not default to a value that
helps the trade.

## 2. Invariants that must always hold

Checkable, and mostly checked — keep them that way:

- `ALPACA_PAPER_BASE_URL == "https://paper-api.alpaca.markets"` or no order
  of any kind (enforced in `AlpacaClient`; tested).
- Scenario overrides unset ⇒ bit-identical to live scoring (tested).
- Rejected and expired ideas never execute, regardless of any other flag.
- Every execution attempt — accepted, rejected, errored — produces exactly one
  `execution_audit` row.
- Import direction: `paper_trader` never imports `alpha_lab`; `research`
  imports both, nothing imports `research` (executable in
  `test_import_boundaries.py`, which may only tighten).
- Catalyst events replay at `discovered_at`, never `published_at` — the
  platform cannot act before it saw the news.
- Outcome labels are the raw bias-signed move. Never a score that embeds
  confidence (the early-detection score does; using it as a label lets
  confidence predict itself).
- The three crypto-symbol normalizers agree (`_position_key`,
  `_canonical_crypto_ticker`, `normalize_crypto_symbol`) — until they are
  unified, treat divergence as a bug.
- Dry-run is the default everywhere; paper execution requires *two* switches
  (scheduler mode AND the automation guard) plus every gate passing.

## 3. Common mistakes future engineers will make

**M1. "The gate is too strict, I'll just lower it."** The waterfall says a
gate rejects 80% of candidates, so you loosen it. Wrong: rejection volume is
not evidence of miscalibration — the July 2026 audit found the biggest
"blockers" were *upstream data defects*, not thresholds. Fix inputs first;
then run the protocol.

**M2. Reimplementing instead of reusing the pure core.** The backtester, a
new scanner, a notebook — the temptation is to write a "quick" local copy of
scoring or gating. Every copy drifts. If the live function can't be called
where you are, that is a parameterization gap to fix in the live function
(with defaults preserved), not a reason to fork it.

**M3. Trusting small samples.** Below ~30 outcomes, every metric is
directional. The reports print this warning; do not delete it, and do not act
as if a hit rate over 7 trades means anything.

**M4. Editing the config that's actually live.** Risk limits currently load
from files named `*.example.json` (known debt, P3 roadmap). Check what the
running services actually read before "cleaning up examples."

**M5. Letting a helpful default leak upward.** A `or 0.75`, a `getattr(...,
50)`, a "reasonable" fallback deep in a scorer silently becomes a trading
input. Every default in the signal path must be *neutral* per P9 and visible
in telemetry.

**M6. Breaking append-only history to "fix" it.** Do not rewrite the journal,
do not force-push, do not amend pushed backup branches. The value of the
record is that it was never edited.

**M7. Confusing the two catalyst scorers.** The radar's 8-factor score and
the engine's component score are different numbers on different scales bridged
by adapters (D4 in the health audit). Changing one and reading the other has
already caused one real bug. If you touch this seam, read both files end to
end first.

**M8. Deploy drift.** The services run from a launchd-pinned checkout and
interpreter. Merging to GitHub does nothing to the Mac mini until the deploy
step runs. Verify with `diagnose_trading_pipeline.py` after every deploy; do
not assume.

## 4. Dangerous refactors (do not attempt casually)

- **Splitting `evaluate_signal`.** It is long because it is a *complete,
  ordered* statement of the risk policy, and its reason strings are load-
  bearing (legacy telemetry parses them). If it must be split, the reason
  strings, gate order, and trace shape are frozen contract; characterization
  tests first.
- **"Simplifying" the confirmation rule.** The unconfirmed-idea cap, modifier
  exclusion, and floors look redundant with the ≥70 paper gate. They are not:
  they bind at different points and fail independently. Removing "redundant"
  safety is how quant systems die.
- **Async-ifying the service layer.** Everything is synchronous SQLite +
  blocking HTTP by design (one machine, small scale, easy reasoning). An async
  rewrite buys nothing at this scale and costs the determinism guarantees.
- **Merging the diagnostics layers.** Replay/attribution/outcomes overlap
  ~20% and it is tempting to unify them into one "analytics engine." Their
  independence is the feature: each answers one question with one dataset
  contract, and each can be verified alone.
- **Schema migrations on production SQLite.** The DB is the system's memory.
  Additive columns and new tables only; destructive migrations require a
  backup, a human, and a very good reason.
- **Renaming gate identifiers.** `gate` names in traces are the join key
  across waterfall, outcomes, near-miss, and years of stored rows. They are
  API.

## 5. Safe extension patterns (copy these)

- **New signal source** → build fetcher in `live_sources`-style (disabled
  without key, `_disabled()` contract), emit the standard signal payload
  shape, let ideas flow through the *existing* gates. Never add a bypass lane.
- **New scoring feature** → ship it as a *shadow feature* first: computed and
  recorded (attribution measures it), never scored. Promotion to a weighted
  component goes through the protocol.
- **New gate or safety cap** → additive only (tightening is pre-approved
  philosophy; loosening never is), emits a standard trace record, appears in
  the waterfall automatically.
- **New diagnostics report** → read-only module + CLI in the established
  shape (fingerprint, `_outcome_stats` vocabulary, small-N warning, JSON to
  `alpha_lab/data/<name>/`). Extract the shared boilerplate when you're the
  third copier, not the fifth.
- **New strategy** → implement against the backtest `Strategy` interface from
  `docs/BACKTESTING_ARCHITECTURE.md`; it reaches production only as a signal
  source (above), never as a new execution path.
- **New experiment** → a registry entry with hypothesis, config hash, dataset
  fingerprint, and outcome — before you run it, not after.

## 6. Engineering philosophy

1. **Trust is the product.** This system's value is not its alpha (paper, and
   modest); it is that every number it shows can be traced to inputs, code,
   and a decision trail. Any change that makes a number less explainable makes
   the product worse, whatever it does to the metrics.
2. **Boring on purpose.** Stdlib + six dependencies, synchronous, SQLite, no
   ML in the hot path. Every piece of cleverness must pay rent in
   verifiability.
3. **The system may only tighten on its own.** Automation can add evidence,
   add telemetry, add tests, and add safety. Only a human can loosen, arm, or
   spend.
4. **Write for the next reader, who knows nothing.** The codebase's best
   habit is comments that state *constraints* ("Alpaca rejects 'day' for
   crypto") rather than narration. Keep that ratio.
5. **When the data and the story disagree, the story is wrong.** The July
   audit's lesson: the pipeline wasn't "conservative," it was *broken in six
   specific places*, and every one was findable by reading what the system
   actually recorded. Instrument first, conclude second.
6. **Leave a trail.** Every session ends with a handoff entry: what changed,
   what was run, what's risky, what's next. The next engineer starts where you
   stopped, not where they guess you stopped.

## 7. Pull-request review checklist

Safety (any ✗ blocks merge):
- [ ] No path to a non-paper endpoint; no weakening of the paper URL check.
- [ ] No gate, floor, cap, or threshold loosened — and no *effective*
      loosening via changed inputs or defaults (M5).
- [ ] Rejected/expired ideas still cannot execute; approval flow intact.
- [ ] Dry-run remains the default; the two-switch arming rule intact.

Correctness:
- [ ] Scenario/override defaults still reproduce live behavior (tests prove it).
- [ ] Every new decision point emits a structured gate/trace record.
- [ ] New data inputs are neutral-when-absent, with the absence visible.
- [ ] Reason strings, gate names, and stored-row shapes unchanged (or the
      change includes readers + a migration note).
- [ ] Timestamps: point-in-time discipline respected (`discovered_at`
      anchoring; no future data reachable from as-of context).

Evidence & process:
- [ ] Behavior changes carry their evidence pack (replay/backtest + shadow
      results) and human approval; diagnostics-only changes say so explicitly.
- [ ] Tests updated *with* the change; both suites green
      (`alpha_lab`, `paper_trader`, `research`); characterization and
      import-boundary suites untouched or tightened.
- [ ] Handoff entry appended (append-only; no edits to prior entries).
- [ ] No new dependency without justification against the "boring" rule.
- [ ] Docs touched if a contract changed (`ARCHITECTURE`, `CALIBRATION_PLAN`,
      or this handbook).

Deployment:
- [ ] If the change affects running services: deploy steps stated, and
      `diagnose_trading_pipeline.py` is the named post-deploy verification.

---

*Closing note.* You will inherit a system whose safety rails were built
before its profits — deliberately. The rails are the asset; the strategies are
tenants. Keep the rails, rotate the tenants, and demand evidence from both.
Good luck.
