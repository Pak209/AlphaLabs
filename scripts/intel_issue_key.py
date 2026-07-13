#!/usr/bin/env python3
"""Issue (or revoke) an AlphaLabs Intelligence beta API key — the beta faucet.

Hand-issued keys during invite-only beta (a public self-serve faucet comes
with the M4 flip, behind Cloudflare rules). The raw key prints ONCE and only
its sha256 lands in the intel DB.

    .venv/bin/python scripts/intel_issue_key.py issue --name partnername [--rate 60] [--tier beta]
    .venv/bin/python scripts/intel_issue_key.py revoke --name partnername
    .venv/bin/python scripts/intel_issue_key.py list
"""
from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alpha_lab.intel_gateway import IntelStore, _hash_key


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    issue = sub.add_parser("issue")
    issue.add_argument("--name", required=True)
    issue.add_argument("--rate", type=int, default=60)
    issue.add_argument("--tier", default="beta")
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--name", required=True)
    sub.add_parser("list")
    args = parser.parse_args()

    store = IntelStore()
    if args.cmd == "issue":
        raw = f"sk-intel-{secrets.token_urlsafe(24)}"
        with store._conn() as conn:
            conn.execute(
                "INSERT INTO api_keys (key_hash, name, tier, rate_per_min) VALUES (?, ?, ?, ?)",
                (_hash_key(raw), args.name, args.tier, args.rate))
            conn.commit()
        print(f"issued for '{args.name}' (tier={args.tier}, {args.rate}/min)")
        print(f"KEY (shown once, only the hash is stored): {raw}")
    elif args.cmd == "revoke":
        with store._conn() as conn:
            n = conn.execute(
                "UPDATE api_keys SET revoked_at = CURRENT_TIMESTAMP "
                "WHERE name = ? AND revoked_at IS NULL", (args.name,)).rowcount
            conn.commit()
        print(f"revoked {n} key(s) for '{args.name}'")
    else:
        with store._conn() as conn:
            for row in conn.execute(
                    "SELECT name, tier, rate_per_min, created_at, revoked_at FROM api_keys"):
                print(dict(zip(("name", "tier", "rate_per_min", "created_at", "revoked_at"), row)))


if __name__ == "__main__":
    main()
