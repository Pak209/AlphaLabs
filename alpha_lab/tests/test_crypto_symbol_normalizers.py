"""Phase 1 test frontier: the three crypto-symbol normalizers must agree.

Three independent implementations exist (health-audit §6):
  paper_trader.decision_engine._position_key       (duplicate-position gate)
  paper_trader.models._canonical_crypto_ticker     (signal validation)
  alpha_lab.market_data.normalize_crypto_symbol    (scanner/allowlist)

They were born from the same requirement and agree today by luck, not by
contract. This suite IS the contract until they are unified (P3): any change
that makes one drift on the tradeable corpus fails here first.
"""
from __future__ import annotations

import pytest

from alpha_lab.market_data import CRYPTO_ALLOWLIST, normalize_crypto_symbol
from paper_trader.decision_engine import _position_key
from paper_trader.models import _canonical_crypto_ticker


def spellings(pair: str) -> list[str]:
    """Every spelling a broker, feed, or human is known to produce for a pair."""
    base = pair.split("/")[0]
    return [pair, pair.lower(), f"{base}USD", f"{base.lower()}usd",
            f"{base}-USD", f"{base.lower()}-usd", f" {pair} "]


@pytest.mark.parametrize("pair", CRYPTO_ALLOWLIST)
def test_all_three_normalizers_agree_on_tradeable_pairs(pair):
    for spelling in spellings(pair):
        assert _position_key(spelling) == pair, spelling
        assert _canonical_crypto_ticker(spelling) == pair, spelling
        assert normalize_crypto_symbol(spelling) == pair, spelling


def test_bare_symbol_semantics_differ_by_design():
    """Documented divergence (do not 'fix' one side casually):

    - models._canonical_crypto_ticker maps bare known symbols to the pair
      (BTC -> BTC/USD) because signal validation wants the canonical ticker.
    - decision_engine._position_key leaves bare symbols alone (BTC -> BTC)
      because it only compares position symbols, which always arrive as pairs.
    - market_data.normalize_crypto_symbol maps allowlisted bare symbols via
      its alias table (BTC -> BTC/USD).

    If this test fails, one of the three changed semantics — check the
    duplicate-position gate before shipping.
    """
    assert _canonical_crypto_ticker("BTC") == "BTC/USD"
    assert normalize_crypto_symbol("BTC") == "BTC/USD"
    assert _position_key("BTC") == "BTC"


def test_equity_symbols_pass_through_everywhere():
    for symbol in ("NVDA", "smci", " XOM "):
        cleaned = symbol.strip().upper()
        assert _position_key(symbol) == cleaned
        assert normalize_crypto_symbol(symbol) == cleaned
