# Paper Trader Alpha

Paper Trader Alpha connects market-scan summaries/signals to Alpaca paper trading with strict guardrails. It does not use real-money endpoints and refuses to submit orders unless `ALPACA_PAPER_BASE_URL` is exactly `https://paper-api.alpaca.markets`.

## Setup

```bash
cd /Users/danielpak/Downloads/second-brain-app
python3 -m venv .venv-paper-trader
source .venv-paper-trader/bin/activate
pip install -r paper_trader/requirements.txt
cp paper_trader/.env.example .env.paper
```

Load your paper credentials locally:

```bash
set -a
source .env.paper
set +a
```

Do not commit `.env.paper` or any real secrets.

## Signal Format

```json
{
  "ticker": "NVDA",
  "bias": "bullish",
  "confidence": 0.82,
  "timeframe": "intraday",
  "reason": "summary of thesis",
  "source": "market_scan_bot",
  "timestamp": "2026-06-04T13:00:00Z"
}
```

## Commands

Dry-run a sample signal:

```bash
python3 -m paper_trader.main ingest --file paper_trader/sample_signals/nvda_bullish.json --dry-run
```

Dry-run can use a simulated paper account if Alpaca credentials are not loaded yet.

Submit paper orders after reviewing config and credentials:

```bash
python3 -m paper_trader.main ingest --file paper_trader/sample_signals/nvda_bullish.json
```

Manual CLI signal:

```bash
python3 -m paper_trader.main manual --ticker NVDA --bias bullish --confidence 0.8 --timeframe intraday --reason "Relative strength continuation" --dry-run
```

Webhook server:

```bash
python3 -m paper_trader.main serve --dry-run
curl -X POST http://127.0.0.1:8765/signals -H 'Content-Type: application/json' --data @paper_trader/sample_signals/nvda_bullish.json
```

Inbox processor:

```bash
mkdir -p paper_trader/inbox
cp paper_trader/sample_signals/nvda_bullish.json paper_trader/inbox/premarket-nvda.json
python3 -m paper_trader.main inbox --dry-run
```

Inbox files are claimed into `paper_trader/inbox/.processing`, then moved to `paper_trader/processed` when every signal is accepted or `paper_trader/rejected` when any signal is invalid or rejected by risk rules. Each moved file gets a `.result.json` sidecar so you can inspect exactly what happened.

Scheduler:

```bash
python3 -m paper_trader.main schedule --signals-dir paper_trader/sample_signals --dry-run
```

Dashboard:

```bash
python3 -m paper_trader.main dashboard
```

Tests:

```bash
pytest paper_trader/tests
```

## Guardrails

- Paper endpoint only: `https://paper-api.alpaca.markets`.
- Required config file; missing config refuses to run.
- Required env vars: `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_PAPER_BASE_URL`.
- Watchlist allow-list.
- Confidence threshold.
- Max trades per day.
- Max open positions.
- Duplicate-position rejection.
- Market-open rejection.
- Daily drawdown rejection.
- Conservative default sizing.
- Dry-run mode logs accepted trades without placing orders.
- Dry-run mode can run with a simulated account before credentials exist.

## Connecting Codex Market Scans

Have the existing Codex market-scan automation write or hand off JSON using the signal format above. The bot can consume:

- A local JSON file via `ingest`.
- A webhook POST to `/signals`.
- A dropped inbox file via `inbox`.
- A manual CLI signal via `manual`.

Recommended automation payload shape:

```json
{
  "signals": [
    {
      "ticker": "NVDA",
      "bias": "bullish",
      "confidence": 0.82,
      "timeframe": "intraday",
      "reason": "AI leadership with unusual relative strength and volume.",
      "source": "market_scan_bot",
      "timestamp": "2026-06-04T13:00:00Z"
    }
  ]
}
```
