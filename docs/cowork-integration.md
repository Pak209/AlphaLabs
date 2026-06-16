# AlphaLab × Claude Cowork — Integration Guide

> How to connect Claude Cowork to AlphaLab so it can research catalysts, draft
> ideas, and prep a morning brief — **without any execution authority**.

This covers the three integration patterns:

1. **Cowork → AlphaLab import** — Cowork pushes researched catalysts/ideas into
   AlphaLab for scoring (dry-run only).
2. **AlphaLab MCP connector** — a local, zero-dependency MCP server exposing
   AlphaLab's research surface as Cowork tools.
3. **Morning brief autopilot** — a recurring Cowork task that pulls the daily
   brief + radar and drafts candidate ideas for human review.

---

## Guardrails (apply to all patterns)

These are hard rules, enforced in code by the MCP server
([`alpha_lab/mcp_server.py`](../alpha_lab/mcp_server.py)):

- **No execution authority.** Cowork can read state and push *ideas/catalysts*
  for **dry-run scoring** only. It cannot place paper or live trades, and it
  cannot approve, reject, or expire ideas. Those endpoints are deliberately not
  exposed as tools.
- **Dry-run is pinned, not a default.** Write tools strip any caller-supplied
  `execution_mode` and force `dry_run`. There is no tool path to paper/live.
- **Human-in-the-loop stays.** Imported ideas land in the pipeline and still
  require manual approval (`/api/ideas/{id}/approval/...`) before any paper run —
  and that approval is performed *outside* Cowork.
- **No impersonating stubbed providers.** Options-flow and dark-pool signals are
  **stubbed** (no real feed). Scraped web data (e.g. from Brightdata) must never
  be injected as if it were options/dark-pool provider data. Cowork-sourced
  research belongs in the *catalyst* and *narrative/thesis* fields only.

---

## Pattern 2 — AlphaLab MCP connector (the foundation)

The MCP server is a pure-stdlib JSON-RPC 2.0 server over stdio. It requires no
`pip install` (Python 3.9 stdlib only) and talks to a **running** AlphaLab API
over HTTP, so it shares the live dashboard's database/state.

### Prerequisites

1. AlphaLab API running (default `http://127.0.0.1:8787`):
   ```bash
   cd ~/AlphaLab && .venv/bin/python -m alpha_lab.main
   ```
2. Nothing else — no node, no `mcp` SDK, no extra packages.

### Connector config

Standard MCP `mcpServers` block (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "alphalab": {
      "command": "/Users/danielpak/AlphaLab/.venv/bin/python",
      "args": ["-m", "alpha_lab.mcp_server"],
      "env": {
        "ALPHALAB_BASE_URL": "http://127.0.0.1:8787"
      }
    }
  }
}
```

> **Caveat:** Cowork-specific connector *registration* (where Cowork reads this
> block from) is not in the public docs as of this writing. The server itself
> speaks standard MCP stdio, so it works with any MCP client that supports the
> `mcpServers` format; if Cowork uses a different registration path, only the
> location of this JSON changes — the `command`/`args`/`env` stay identical.

### Exposed tools

| Tool | Kind | Maps to |
| ---- | ---- | ------- |
| `get_dashboard` | read | `GET /api/dashboard` |
| `list_scored_ideas` | read | `GET /api/ideas?limit=` |
| `list_pending_approvals` | read | `GET /api/ideas/pending-approval` |
| `list_trades` | read | `GET /api/trades` |
| `get_daily_brief` | read | `GET /api/brief/daily` |
| `get_catalyst_radar` | read | `GET /api/catalysts/radar` |
| `get_idea_explanation` | read | `GET /api/ideas/{id}/explanation` |
| `import_catalyst` | write (dry-run) | `POST /api/catalysts/import-and-test` (`execution_mode` forced `dry_run`) |
| `import_idea` | write (no-exec) | `POST /api/ideas/import` (scores+stores, never trades) |

### Quick smoke test (no Cowork needed)

```bash
cd ~/AlphaLab && printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | .venv/bin/python -m alpha_lab.mcp_server
```

Tests: `alpha_lab/tests/test_mcp_server.py` (handshake, tools/list shape,
routing, and the dry-run safety guards).

---

## Pattern 1 — Cowork → AlphaLab import recipe

Once the connector is registered, Cowork can research a catalyst on the web
(via its own connectors, e.g. Brightdata) and push it into AlphaLab for scoring.

**Recipe for Cowork:**

1. Research the catalyst (earnings, FDA, guidance, M&A, etc.).
2. Call `import_catalyst` with a `catalysts` list. Each item should carry the
   factual catalyst (ticker, headline, source) — *not* fabricated options or
   dark-pool numbers.
3. Read back the scored result; if it confirms (passes the catalyst ≥40 /
   price-volume ≥55 hard gate), call `import_idea` to draft a full idea with a
   bias, confidence (0–1), timeframe (`intraday`|`swing`), and a written thesis.
4. The idea now sits in the pipeline awaiting **human** approval. Cowork's job
   ends here.

**Example `import_idea` arguments:**

```json
{
  "ticker": "NVDA",
  "bias": "bullish",
  "confidence": 0.7,
  "timeframe": "swing",
  "thesis": "Datacenter demand reaccelerating into print; catalyst = earnings 2026-06-18. Web research: hyperscaler capex guides revised up.",
  "source": "cowork-research",
  "source_url": "https://example.com/article"
}
```

---

## Pattern 3 — Morning brief autopilot

A recurring Cowork task that prepares a research brief for the human to review
each morning. **Read-and-draft only — it places nothing.**

**Suggested schedule:** weekdays pre-market (e.g. 08:15 ET).

**Recipe for Cowork:**

1. `get_daily_brief` → the day's catalysts, narrative, and candidate ideas.
2. `get_catalyst_radar` → upcoming/recent catalysts to enrich the brief.
3. For any compelling, *new* catalyst, optionally web-research it, then
   `import_catalyst` (dry-run) to see how it scores.
4. `list_scored_ideas` + `list_pending_approvals` → summarize what's already in
   the pipeline and what's waiting on the human.
5. Produce a concise written brief: top confirmed ideas, gated/watchlist ideas
   and *why* they're gated, and anything awaiting approval.

The human reads the brief and decides what (if anything) to approve for paper
trading — that approval happens in the AlphaLab dashboard, not in Cowork.

---

## What Cowork must NOT do

- ❌ Place paper or live trades (no tool exists; the API paper-trade endpoints
  are not exposed).
- ❌ Approve / reject / expire ideas.
- ❌ Set `execution_mode: "paper"` (stripped and forced to `dry_run`).
- ❌ Present scraped web data as options-flow or dark-pool provider signals.

If a future workflow needs any of the above, it must be added explicitly to the
MCP server with its own tests and an updated guardrail review — not worked
around at the Cowork prompt level.
