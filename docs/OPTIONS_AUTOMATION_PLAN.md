# Options paper-trading automation plan (awaiting approval)

Written 2026-07-08. Human decisions already made: (1) automate options,
(2) the duplicate gate for option signals checks **option positions only**,
(3) LEAPS DTE parameterization acceptable, (4) Alpaca entitlement verified —
**paper account has options_trading_level 3, $91.8K options buying power**.
Status 2026-07-08: **PR-A and PR-B implemented** on feat/options-automation
(stacked on feat/yahoo-news-source) after explicit approval. PR-C and the
arming PR remain unimplemented pending shadow evidence.

## Current state (measured)

- Full lifecycle plumbing exists: `as_option=true` on the dry-run/paper
  routes → ATM call/put selection (7–14 DTE, spread ≤15%, OI/volume guards)
  → one-contract sizing within `min($1,900, 2% equity)` → fill polling →
  `close_option_trade` settles realized P/L into `training_rows`.
- Nothing automated ever requests options (`as_option` defaults False in
  every scheduler flow).
- The daily `options_lifecycle_validation` (PLTR) has been blocked for three
  straight days at `duplicate_position` because PLTR **equity** is held —
  the exact semantics the human has now decided to change.

## PR-A — duplicate gate: option signals check option positions only

**Behavior change to `evaluate_signal` (the safety kernel) — smallest
possible diff.** For `signal.asset_type == "option"` only, `_has_position`
matching narrows to positions whose symbol is an OCC option symbol on the
same underlying (equity positions no longer block). Equity/crypto signals:
byte-identical behavior.

- Gate name (`duplicate_position`), reason string, and trace shape unchanged
  (telemetry contract preserved; only the position set consulted differs
  for option signals).
- Tests: new decision-engine cases (equity held + option signal → passes;
  same-underlying option held → rejects; characterization suite untouched).
- Risk note: this *permits* equity+option stacking on one underlying —
  the exposure is still capped by the per-trade budget and slot limits, and
  the portfolio snapshot's theme/concentration metrics make the stack
  visible. Documented as an accepted, human-decided risk.

## PR-B — automation in shadow mode first (calibration protocol §2 step 4)

New flag `ALPHALAB_OPTIONS_AUTOMATION = off | shadow | on` (default **off**).

- **shadow**: automated flows evaluate option routing without ordering —
  for every accepted equity idea, the selector runs, and the would-be
  contract (symbol, DTE, cost, spread) plus eligibility verdict is recorded
  as an advisory `option_routing` record in the gate trace / execution
  audit. Zero orders. This accumulates the evidence pack: how many ideas
  would route, contract costs vs budget, spread quality.
- **on** (requires a further explicit human approval after ≥5 shadow
  sessions): ideas meeting the routing rule execute as options instead of
  equity through the UNCHANGED gate chain (alpha ≥70, approval flow,
  budget, all risk caps).
- Routing rule v1 (deliberately narrow): equity ideas with
  `alpha tier == high_conviction` (≥80) AND a selectable contract; fallback
  to equity when selection fails. Rationale: options add leverage/decay
  risk, so v1 reserves them for the highest-conviction band; widening is a
  later calibration decision with shadow data.

## PR-C — LEAPS support (after PR-B ships and shadow data exists)

- Parameterize the selector window via risk config
  (`options_min_dte`/`options_max_dte`, defaults 7/14 → no behavior change
  at merge) and add a distinct, human-invoked LEAPS profile (e.g. 365–730
  DTE) rather than changing the automated path.
- Honest constraint: the per-trade budget caps a contract at ~$1,900 — most
  large-cap LEAPS exceed it and will be rejected at
  `option_cost_within_budget`. Raising that budget is a **risk-limit
  change** (never-loosen list) and is NOT proposed; LEAPS candidates will
  be small-underlying or far-OTM until/unless the human changes limits.

## Sequencing & safety summary

PR-A (unblocks the daily validation immediately) → PR-B shadow → ≥5 sessions
of shadow data reviewed via the outcome/waterfall reports → human arms `on`.
No threshold, cap, approval flow, or paper-only enforcement changes anywhere;
the only loosening-shaped change is PR-A's duplicate-gate narrowing, which is
an explicit human decision recorded here and in the journal.
