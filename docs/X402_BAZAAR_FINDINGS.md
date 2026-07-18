# x402 Bazaar discovery — findings & scoped follow-up

Written 2026-07-13. Empirical result from trying to get AlphaLabs listed in
the CDP x402 Bazaar (the wallet-native discovery index where funded agents
find paid resources).

## What we proved

- **Merchant lookup works and we are NOT indexed.** `GET /v2/x402/discovery/
  merchant?payTo=0x5c23…fEf` returns `total: 0`. The endpoint is healthy —
  other merchants' resources return fine.
- **Settlement alone (v1) does not index.** Three real mainnet settlements
  through the CDP facilitator into the business wallet
  (catalysts + market-snapshot, txs 0xcaa5b76e…, 0xc5300f24…, 0xa8a367a9…)
  — none produced a Bazaar entry after 10-minute cache windows.
- **`resource` was relative before PR #43; now absolute.** That was a real
  bug (Bazaar catalogs by absolute URL) and is fixed regardless — merged.
- **Adding `extensions.bazaar` to a v1 challenge did NOT index either.**
  Built the documented `extensions.bazaar {info:{input,output}, schema}`
  structure, settled once with it present (tested locally against the real
  CDP facilitator, zero prod risk), polled 10 min → still `total: 0`.
  Branch discarded (unproven; not merged).

## Conclusion

Bazaar cataloging is **not** achieved by injecting discovery fields into an
otherwise-v1 challenge. The most likely requirement is the **full x402 v2
protocol** end to end (`x402Version: 2` negotiation, the v2
PaymentRequirements/PaymentPayload shapes, and the discovery extension
declared through that flow) — or an eligibility/onboarding step for Bazaar
indexing that isn't visible in the public docs.

Our v1 payment lane is proven and earning ($0.07 settled). Do not migrate it
to v2 speculatively — that risks the working revenue path.

## Scoped follow-up (when Bazaar discovery is worth the effort)

1. Read the x402 v2 spec + the CDP `@coinbase/x402` server SDK to see the
   exact v2 handshake and how `declareDiscoveryExtension()` wires into it.
2. Prototype a v2 lane **behind a flag** (`INTEL_X402_PROTOCOL=v2`),
   side-by-side with v1, and value-pin both — never replace v1 until v2
   settles + indexes.
3. Confirm indexing via merchant lookup before shipping.
4. If v2 also fails to index, open a CDP support ticket with the settlement
   tx hashes above — we have clean evidence it's not a client-side mistake.

## Meanwhile — discovery that DOES work

- **Smithery**: live and publicly listed (pak-labs/alphalabs-intelligence).
- **llms.txt / openapi.json / /v1/catalog**: machine-readable storefront (PR #42).
- **awesome-mcp-servers**: one-click PR staged on the fork.
- The Bazaar is additive, not a blocker: the platform is discoverable and
  earning without it.
