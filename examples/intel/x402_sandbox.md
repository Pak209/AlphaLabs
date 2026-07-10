# Paying with x402 on the sandbox (Base Sepolia testnet)

The sandbox settles **real transactions with test money**: testnet USDC on
Base Sepolia, verified and settled through the free x402.org facilitator.
Nothing here touches mainnet funds.

## Server side (operator)

```bash
INTEL_X402_MODE=sandbox
INTEL_X402_PAY_TO=0x<receiving-test-wallet>     # any wallet you control; testnet only
# optional: INTEL_X402_FACILITATOR_URL to override the default x402.org facilitator
```

Keyless calls now return a spec-correct 402 whose `accepts[0]` names
`network: base-sepolia`, the Circle testnet USDC contract, and the price in
atomic units (6 decimals — `"20000"` = $0.02).

## Client side (payer agent)

The payer needs a wallet with Base Sepolia **USDC only — no ETH**: EIP-3009
authorizations are gasless for the payer; the facilitator broadcasts.

1. Create a throwaway key (any wallet tool, or `eth_account`), fund it with
   testnet USDC from Circle's faucet: https://faucet.circle.com (select
   Base Sepolia).
2. In a scratch venv, use the official x402 client to handle the
   402 → sign → retry loop automatically:

```bash
python3 -m venv /tmp/x402venv && /tmp/x402venv/bin/pip install x402 eth-account httpx
```

```python
import asyncio, httpx
from eth_account import Account
from x402.clients.httpx import x402HttpxClient

account = Account.from_key("0x<test-wallet-private-key>")   # testnet-only key

async def main():
    async with x402HttpxClient(account=account,
                               base_url="http://<host>:8790") as client:
        response = await client.get("/v1/catalysts")
        print(await response.aread())

asyncio.run(main())
```

(JS equivalent: `x402-fetch` / `x402-axios` npm packages with a viem
account.)

3. Verify on the server: the `payments` table gains a row (nonce, payer,
   tx hash), the usage row carries the payment id, and the response's
   `X-PAYMENT-RESPONSE` header holds the settlement receipt. The
   transaction is visible on https://sepolia.basescan.org.

## What live mode adds (M3-live, human-gated)

Mainnet Base USDC via the CDP facilitator (`INTEL_X402_FACILITATOR_BEARER`
for its auth) paid to the **dedicated business wallet — never a personal
one**. Blocked on: Coinbase business wallet + CDP KYB, licensing counsel,
and the public-launch checklist in docs/COMMERCIAL_LAUNCH_REVIEW.md.
