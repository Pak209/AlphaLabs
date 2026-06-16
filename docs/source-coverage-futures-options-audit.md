# Source Coverage, Futures/Options Wiring, and IQ Audit

Date audited: 2026-06-16

## Summary

Futures Pulse was present and already scheduled as a read-only premarket context
source. Options flow had a live Polygon provider and scoring tests, but it was
not scheduled as a standalone read-only preview. This audit wires a safe options
preview job and improves source accounting and AlphaLabs IQ explainability.

No futures/options path creates ideas, approves trades, places orders, or calls
Alpaca execution endpoints.

## Futures / Options Wiring

| Area | Status |
| ---- | ------ |
| Futures provider | `PolygonFuturesProvider` in `alpha_lab/futures_pulse.py`, graceful no-data behavior |
| Options provider | `PolygonOptionsFlowProvider` in `alpha_lab/options_flow.py`, graceful no-data behavior |
| Futures scheduler | `run_overnight_futures_pull()` at 6:05am PT weekdays |
| Options scheduler | `run_options_flow_preview()` at 6:12am PT weekdays |
| API endpoints | `/api/futures/pulse`, `/api/futures/snapshots`, `/api/options/flow-preview` |
| Persistence | Futures persist to futures tables; options preview persists only `scanner_runs` accounting |
| Dashboard | Futures Pulse card exists; options flow appears in strategy/trade breakdowns |
| Tests | Scheduler, futures pulse, options provider, service preview, source coverage, performance/IQ |

## AlphaLabs IQ

AlphaLabs IQ still scores from evaluated signals and trade returns. Futures and
options are now explained as context:

- Futures can affect the `regime_awareness` component indirectly when market
  regime context is available.
- Options remain context-only until enough samples accumulate; one-off options
  flow events do not inflate IQ.
- Missing futures/options data is reported as no effect, not as neutral points.

## Polygon / SEC Starvation Findings

- Polygon News, SEC EDGAR, Benzinga insiders, Tiingo, and Newsfilter flow through
  Catalyst Radar, but older scanner runs did not retain provider-level request
  counts. New Catalyst Radar accounting preserves provider statuses when present.
- Source coverage reports now distinguish aggregate Catalyst Radar counts from
  provider-level counts instead of copying aggregate counts onto each provider.
- SEC EDGAR depends on `SEC_USER_AGENT`; Polygon sources depend on
  `POLYGON_API_KEY`; insider activity depends on `BENZINGA_API_KEY`.
- If providers are configured but source coverage shows zero requests, the likely
  issue is either the scanner did not run after this accounting patch or the
  provider statuses were not captured in older rows.

## Remaining Risks

- Provider-level accounting starts from new scanner runs; historical rows cannot
  be reconstructed.
- Options preview stores summary accounting only. Persisting per-ticker historical
  samples would be useful before letting options influence source reliability.
- Paid Polygon entitlements were not probed in this audit because live network
  access may be restricted; the code continues to degrade gracefully.
