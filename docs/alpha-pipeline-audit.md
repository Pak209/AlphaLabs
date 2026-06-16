# Alpha Pipeline Audit

Date audited: 2026-06-16

## Current Pipeline Map

| Source | Runner | Scheduler | Candidate Output | Persistence | Source Tags | Signal Evaluation | Skipped/Rejected Accounting |
| ------ | ------ | --------- | ---------------- | ----------- | ----------- | ----------------- | --------------------------- |
| Catalyst Radar | `AlphaLabService.poll_live_catalysts()` / `POST /api/catalysts/poll` | Weekdays 5am-2pm PT every 3 min | `import_catalysts_payload()` returns scored catalysts and `signals[]` | New non-duplicate signals flow through `import_and_test()` -> `create_idea()` | `catalyst_radar` plus strategy/category tags | Repository creates provisional evaluation; service may enrich alert price | Scanner run now records candidates, persisted ideas, duplicate skips, non-candidate count |
| Daily Market Brief | `AlphaLabService.import_daily_brief_and_test()` / `POST /api/brief/daily/import-and-test` | Weekdays 5:50, 6:35, 9:30, 12:00, 13:35 PT | `build_daily_market_brief()` compiles trending, catalyst, BTC/liquidity/oil context into `signals[]` | New non-duplicate signals flow through `import_and_test()` | `daily_market_brief` plus market brief tags | Repository creates provisional evaluation; service may enrich alert price | Scanner run now records candidates, persisted ideas, duplicate skips |
| Market Briefing | `AlphaLabService.generate_and_save_market_briefing()` / `POST /api/briefings/daily/generate` | Weekdays 5:45, 9:25, 11:55; weekends 6/12/18 PT | Analyst briefing payload | Saved to `market_briefings` | n/a | n/a | Daily activity report counts saved briefings |
| SEC Filings | `_fetch_sec_filings()` inside live catalyst radar | Via Catalyst Radar | Catalyst rows when `SEC_USER_AGENT` is configured | Only persisted if Catalyst Radar converts to accepted signal | Via Catalyst Radar | Via Catalyst Radar | Counted inside Catalyst Radar scanner summary, not separately |
| Insider Activity | `_fetch_benzinga_insiders()` inside live catalyst radar | Via Catalyst Radar | Catalyst rows when Benzinga key configured | Only persisted if Catalyst Radar converts to accepted signal | Via Catalyst Radar | Via Catalyst Radar | Counted inside Catalyst Radar scanner summary, not separately |
| FoxRunner-style/news providers | Polygon/Benzinga/Tiingo/Newsfilter inside Catalyst Radar | Via Catalyst Radar | Catalyst rows when keys configured | Only persisted if Catalyst Radar converts to accepted signal | Via Catalyst Radar | Via Catalyst Radar | Counted inside Catalyst Radar scanner summary, not separately |
| Options Flow | `run_options_flow_preview()` for scheduled context; `score_options_flow()` during decision/trade path | Weekdays 6:12am PT preview | Read-only call/put volume context for a tiny watchlist | Preview writes `scanner_runs`; trade path stores options-flow fields on `trades` when a trade record is created | n/a for preview | n/a for preview | Preview records requests, candidates with data, no-data count, and reasons |
| Macro/jobs/inflation | `score_macro(MacroInputs())` currently neutral/default unless wired to data | Not standalone | Score component only | Stored on trade alpha fields when a trade is created | n/a | n/a | No standalone candidate accounting yet |
| BTC/Crypto After-Hours | `generate_after_hours_btc_idea()` and `poll_weekend_crypto()` | Weekend every 30 min | One BTC setup when market data is available and not duplicate | Direct repository insert for generated BTC idea; weekend poll uses `import_and_test()` | `after_hours_btc` and crypto tags | Repository creates provisional evaluation | Weekend poll now records scanner run counts and duplicate/data-unavailable reasons |
| Manual/imported ideas | `POST /api/ideas`, `POST /api/ideas/import`, scripts calling `create_idea()` | Manual | User/script payload | `AlphaLabService.create_idea()` | Source fallback plus strategy tags | Repository creates provisional evaluation; service may enrich alert price | No scanner run expected |
| Options lifecycle validation | `scripts/validate_options_lifecycle.py` | Manual/script wrapper | One infra validation idea | `AlphaLabService.create_idea()` | `options_lifecycle_validation`, `infra validation` | Repository creates provisional evaluation; service may enrich alert price | No scanner run expected |
| Overnight Futures Pulse | `run_overnight_futures_pull()` | Weekdays 6:05am PT | Futures regime and read-only strategy preview | Saved to futures tables, not `alpha_ideas` | Futures tags in preview only | Not an idea unless a later importer is added | Futures snapshots are separate from scanner run accounting |

## Root Cause For The 4-Signal Day

The 2026-06-15 database showed four persisted ideas:

- `PLTR` from `options_lifecycle_validation`
- `NVDA` and `AMD` from `catalyst_radar`
- `TSLA` from `daily_market_brief`

Before this patch, existing rows had no `signal_evaluations`, and older/direct repository paths could bypass the service-level evaluation creation. Scanner run accounting also was not written, so the daily report could not distinguish "scanner did not run" from "scanner ran and rejected candidates." Market briefings were not saved that day, so the report correctly showed `Market briefings: 0`.

## Fixes Made

- Repository-level default: every `repo.create_idea()` now creates a provisional `signal_evaluation`.
- Startup backfill: `seed_defaults()` backfills missing source tags and missing signal evaluations for existing ideas.
- Source tag backfill: ideas with empty `source_tags` now fall back to source plus strategy labels.
- Scanner accounting: catalyst radar, daily market brief, and weekend BTC poll now write concise `scanner_runs` summaries.
- Daily activity report now shows Scanner Runs and Pipeline Health.

## Remaining Gaps

- Scanner accounting starts from this patch forward; old scanner runs cannot be reconstructed if no `scanner_runs` rows were written.
- Alert prices remain missing for backfilled historical ideas because no real quote was captured at original alert time.
- Options flow and macro are score components, not standalone scanners with candidate ledgers.
