# AlphaLab

AlphaLab is a local-first Mac research app for market scans, generated alpha ideas, dry-run decisions, Alpaca paper trading, journaling, and strategy analytics.

It is for research and paper trading only. It defaults to dry-run behavior and refuses non-paper Alpaca endpoints.

## Setup

```bash
cd ~/AlphaLab
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# For a byte-reproducible service environment, install from the lockfile instead:
#   pip install -r requirements.lock   (exact pins from the tested venv; see docs/CONFIG_SOURCES.md)
cp .env.example .env
```

Add only Alpaca paper-trading credentials to `.env`:

```env
ALPACA_API_KEY=your_paper_key_here
ALPACA_SECRET_KEY=your_paper_secret_here
ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets
```

Optional live Catalyst Radar providers:

```env
SEC_USER_AGENT=AlphaLab/0.1 your_email@example.com
POLYGON_API_KEY=
BENZINGA_API_KEY=
TIINGO_API_KEY=
NEWSFILTER_API_KEY=
CATALYST_WATCHLIST=NVDA,AMD,MSFT,META,AAPL,AMZN,GOOGL,TSLA,COIN,MSTR,SMCI,PLTR,ORCL,AVGO
```

Leave a provider key blank to keep it disabled. SEC EDGAR is public, but AlphaLab will not poll sec.gov unless `SEC_USER_AGENT` is set.

Optional LLM analyst layer:

```env
ANTHROPIC_API_KEY=
LLM_ANALYST_ENABLED=false
LLM_MODEL=claude-3-5-sonnet-latest
LLM_MAX_TOKENS=2000
LLM_TEMPERATURE=0.2
```

When `LLM_ANALYST_ENABLED=true` and `ANTHROPIC_API_KEY` is present, AlphaLab asks Claude to convert normalized signals, catalysts, filings, news, and saved briefing context into a structured thesis. The analyst layer only writes explanations and approval records; it never places orders. If the key is missing, AlphaLab returns a deterministic mock explanation so the app keeps running.

Optional paper-learning mode:

```env
ALPHALAB_ALLOW_AUTOMATION_PAPER_TRADES=true
ALPHALAB_ALLOW_MANUAL_PAPER_TRADES=true
ALPHALAB_REQUIRE_PAPER_APPROVAL=false
```

This allows paper-only executions to run without human approval so strategies can collect feedback. It still refuses live Alpaca endpoints, still requires `https://paper-api.alpaca.markets`, and still applies confidence, watchlist, market-open, max-trades/day, max-open-positions, duplicate-position, and drawdown checks.

## Run

```bash
set -a
source .env
set +a
python3 -m alpha_lab.main --seed
```

Open `http://127.0.0.1:8787`.

If you prefer the npm-style shortcuts:

```bash
npm run dev
npm run scheduler
npm run test
```

## Dashboard Workflows

- Bitcoin Insight uses CoinGecko close-price history for BTC/USD EMA, RSI, scenarios, and strategy hypotheses.
- Liquidity Flows estimates sector attention from crypto volume and Alpaca IEX stock/ETF dollar-volume proxies.
- Trending Stock Liquidity ranks the current stock/ETF universe by unusual dollar volume, recent momentum, EMA structure, and RSI.
- Catalyst Radar polls optional live sources for SEC filings, news, press releases, and insider transaction feeds, then scores catalysts before creating strict paper-trade signals.
- Daily Market Brief compiles BTC, liquidity, trending stocks/tokens, oil/energy, and catalysts into a strict `signals[]` block that can feed the dry-run agent.
- `Dry-Run Trending Strategies` creates strategy-test ideas and logs decisions without sending orders.
- `Paper-Test Trending Strategies` sends qualifying candidates to Alpaca paper trading only after the normal guardrails pass. Market-closed, watchlist, confidence, duplicate-position, max-trade, and max-position checks still apply.
- By default, LLM-assisted ideas enter `needs_review` and must be manually approved before they can reach the Alpaca paper executor. Set `ALPHALAB_REQUIRE_PAPER_APPROVAL=false` to let paper-only learning runs skip approval. Rejected or expired ideas do not execute.
- The `Approvals` dashboard page shows pending LLM-assisted ideas with thesis summary, setup type, catalyst, entry/stop/target, risk factors, invalidation condition, time horizon, source refs, and approval actions.
- The `Performance` page links paper-trade results back to original ideas and explanations, including entry/current price, unrealized/realized P/L, percent return, and stop/target watch status.
- The `Paper / Dry-Run Log` page includes an execution audit of every attempted action, including risk blocks, approval blocks, broker/network errors, dry-runs, and submitted Alpaca paper orders.
- The `Briefings` page generates and lists saved daily research briefings with market tone, top catalysts, tickers to monitor, macro risks, and active themes.

## Analyst Explanations

Every stored idea gets a `trade_explanation` object with:

```text
thesis_summary, catalyst, why_this_matters, market_context, setup_type,
confidence_score, risk_factors, invalidation_level_or_condition,
suggested_entry_zone, suggested_stop_loss, suggested_take_profit,
time_horizon, source_refs
```

The explanation is research context for paper testing. It is not financial advice and is not allowed to bypass risk checks.

## Approval Flow

In the app, open `http://127.0.0.1:8787/#approvals` or click `Approvals` in the left menu. Each pending card has:

- `Approve`: marks the idea approved for later paper execution attempts.
- `Reject`: removes it from the executable queue and stores the rejection note.
- `Expire`: marks stale ideas as expired before execution.

These buttons do not place trades. They only update the review status. A later paper-trade action still has to pass the existing risk engine and Alpaca paper-only checks.

If `ALPHALAB_REQUIRE_PAPER_APPROVAL=false`, pending approval is not required for paper execution. The approval page is still useful for review, and rejected or expired ideas remain blocked.

```bash
curl http://127.0.0.1:8787/api/ideas/pending-approval
curl -X POST http://127.0.0.1:8787/api/ideas/1/approval/approve \
  -H 'Content-Type: application/json' \
  -d '{"note":"approved for paper test"}'
curl -X POST http://127.0.0.1:8787/api/ideas/1/approval/reject \
  -H 'Content-Type: application/json' \
  -d '{"note":"setup already moved"}'
```

Approved ideas still go through confidence threshold, watchlist, market-open, max-trades/day, max-open-positions, duplicate-position, and drawdown checks before any paper order.

## Market Briefing Job

Generate and save a daily research briefing:

```bash
set -a
source .env
set +a
python3 -m alpha_lab.main --briefing-job
```

The saved briefing summarizes broad market tone, available sector/liquidity movement, strongest catalysts, unusual news or filings, AI/datacenter/semiconductor/energy/financing/partnership themes, macro risks, and candidate tickers to monitor. The strategy engine can use the latest saved briefing as context for future explanations.

## Research Cockpit

Use the dashboard pages together as a paper-trading research loop:

1. `Catalyst Radar` finds and classifies source-backed news/filings.
2. `Approvals` reviews LLM-assisted ideas, unless paper-learning mode is enabled with `ALPHALAB_REQUIRE_PAPER_APPROVAL=false`.
3. `Paper / Dry-Run Log` shows attempted executions and why they were submitted or blocked.
4. `Performance` tracks P/L by idea and groups outcomes by setup type, catalyst type, ticker, confidence bucket, and time horizon.
5. `Briefings` saves daily market context for future analyst explanations.

Source refs are clickable when AlphaLab receives a URL from Polygon, SEC EDGAR, or another source provider. If no URL exists, the UI shows the source label and timestamp.

## API

- `GET /api/health`
- `GET /api/dashboard`
- `POST /api/ideas`
- `POST /api/ideas/import`
- `POST /api/ideas/import-and-test`
- `POST /api/ideas/test-new`
- `POST /api/strategies/test-trending`
- `GET /api/catalysts/radar?live=true`
- `POST /api/catalysts/score`
- `POST /api/catalysts/import-and-test`
- `POST /api/catalysts/poll`
- `GET /api/brief/daily`
- `POST /api/brief/daily/import-and-test`
- `POST /api/briefings/daily/generate`
- `GET /api/briefings`
- `GET /api/market/bitcoin`
- `GET /api/market/liquidity`
- `GET /api/market/trending-stocks`
- `GET /api/ideas`
- `GET /api/ideas/pending-approval`
- `GET /api/ideas/{id}/explanation`
- `POST /api/ideas/{id}/approval/approve`
- `POST /api/ideas/{id}/approval/reject`
- `POST /api/ideas/{id}/approval/expire`
- `POST /api/ideas/{id}/decision`
- `POST /api/ideas/{id}/dry-run-trade`
- `POST /api/ideas/{id}/paper-trade`
- `POST /api/alpaca/sync`
- `GET /api/trades`
- `GET /api/execution-audit`
- `GET /api/performance/ideas`
- `GET /api/performance/scoreboard`
- `GET /api/stats/strategies`
- `POST /api/journal`

## Sample Import

```bash
curl -X POST http://127.0.0.1:8787/api/ideas/import \
  -H 'Content-Type: application/json' \
  --data @alpha_lab/sample_alpha_idea.json
```

## Safety

- `.env` is ignored by git.
- Local SQLite data lives in `alpha_lab/data/` and is ignored.
- Paper trades require `ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets`.
- Dry-run decisions work without Alpaca credentials using a simulated paper account.
- LLM-assisted signals require human approval before Alpaca paper execution unless `ALPHALAB_REQUIRE_PAPER_APPROVAL=false`.
- Live trading endpoints are not supported.
