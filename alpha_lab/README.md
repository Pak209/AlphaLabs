# Alpha Lab

Alpha Lab is a local-first Mac research app for market scans, generated alpha ideas, dry-run decisions, Alpaca paper trading, journaling, and strategy analytics.

It is research and paper trading only. The app defaults to dry-run behavior and reuses the existing `paper_trader` Alpaca safety checks, including the hard requirement that trading uses `https://paper-api.alpaca.markets`.

## Setup

```bash
cd /Users/danielpak/Downloads/second-brain-app
python3 -m venv .venv-alpha-lab
source .venv-alpha-lab/bin/activate
pip install -r paper_trader/requirements.txt
cp alpha_lab/.env.example .env.alpha
```

Load Alpaca paper credentials only when you are ready to sync a real paper account:

```bash
set -a
source .env.alpha
set +a
```

## Run

Backend and local dashboard:

```bash
python3 -m alpha_lab.main --seed
```

Open:

```text
http://127.0.0.1:8787
```

Scheduler:

```bash
python3 -m alpha_lab.scheduler
```

Tests:

```bash
pytest alpha_lab/tests paper_trader/tests
```

## API

- `GET /api/health`
- `GET /api/dashboard`
- `POST /api/ideas`
- `POST /api/ideas/import`
- `GET /api/ideas`
- `POST /api/ideas/{id}/approve`
- `POST /api/ideas/{id}/reject`
- `POST /api/ideas/{id}/decision`
- `POST /api/ideas/{id}/dry-run-trade`
- `POST /api/ideas/{id}/paper-trade`
- `POST /api/alpaca/sync`
- `GET /api/trades`
- `GET /api/stats/strategies`
- `POST /api/journal`
- `POST /api/config`

## Import Sample Ideas

```bash
curl -X POST http://127.0.0.1:8787/api/ideas/import \
  -H 'Content-Type: application/json' \
  --data @alpha_lab/sample_alpha_idea.json
```

## Notes

- `.env.alpha` is ignored and must not be committed.
- `alpha_lab/data/` is ignored local state.
- Paper trades require Alpaca paper credentials and the paper base URL.
- Dry-run decisions work without Alpaca credentials using a simulated paper account.

