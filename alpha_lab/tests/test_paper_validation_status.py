from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

OPS_SCRIPT = Path(__file__).resolve().parents[2] / "ops"

# A fully-ready key=value blob: every readiness check passes.
READY = {
    "scheduler_mode": "dry_run",
    "automation_paper_trading_armed": "false",
    "approval_required": "true",
    "manual_paper_trading_enabled": "true",
    "alpaca_base": "https://paper-api.alpaca.markets",
    "alpaca_paper_only": "true",
    "alpaca_account_code": "200",
    "dashboard_health_code": "200",
    "api_db_path": "/srv/alpha_lab/data/alpha_lab.sqlite3",
    "resolver_db_path": "/srv/alpha_lab/data/alpha_lab.sqlite3",
    "heartbeat_db_path": "/srv/alpha_lab/data/alpha_lab.sqlite3",
    "heartbeat_at": "2026-06-19T17:15:00-07:00",
    "heartbeat_age_seconds": "120",
    "heartbeat_max_age": "900",
}


def _blob(overrides: dict[str, str] | None = None) -> str:
    data = dict(READY)
    if overrides:
        data.update(overrides)
    return "\n".join(f"{k}={v}" for k, v in data.items()) + "\n"


def _run_eval(blob: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["zsh", str(OPS_SCRIPT), "__paper-validation-eval"],
        input=blob,
        capture_output=True,
        text=True,
    )


def test_ops_script_passes_zsh_syntax_check():
    result = subprocess.run(
        ["zsh", "-n", str(OPS_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_ops_script_wires_paper_validation_command():
    text = OPS_SCRIPT.read_text(encoding="utf-8")
    assert "paper-validation-status)" in text
    assert "cmd_paper_validation_status" in text
    assert "_paper_validation_eval" in text


def test_ready_blob_reports_ready_true():
    result = _run_eval(_blob())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ready_for_manual_validation=true" in result.stdout


# Each override flips exactly one input so that exactly one check fails; the
# command must then report not-ready and exit non-zero.
@pytest.mark.parametrize(
    "overrides",
    [
        {"scheduler_mode": "paper"},
        {"automation_paper_trading_armed": "true"},
        {"approval_required": "false"},
        {"manual_paper_trading_enabled": "false"},
        # paper-only is now derived from the base URL itself; a live base must fail.
        {"alpaca_base": "https://api.alpaca.markets"},
        {"alpaca_account_code": "403"},
        {"dashboard_health_code": "500"},
        {"api_db_path": "/srv/other/alpha_lab.sqlite3"},  # same-DB proof breaks
        {"heartbeat_age_seconds": "99999"},  # stale heartbeat
        {"heartbeat_age_seconds": ""},  # unparseable / missing heartbeat
    ],
)
def test_single_failure_blocks_readiness(overrides):
    result = _run_eval(_blob(overrides))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ready_for_manual_validation=false" in result.stdout


def test_missing_resolver_path_fails_same_db_proof():
    result = _run_eval(_blob({"resolver_db_path": ""}))
    assert result.returncode == 1
    assert "ready_for_manual_validation=false" in result.stdout


# --- Alpaca base URL parsing (no network): live/invalid bases must fail -------
@pytest.mark.parametrize(
    "base",
    [
        "https://api.alpaca.markets",  # live trading endpoint
        "https://api.alpaca.markets/v2",
        "http://paper-api.alpaca.markets.evil.example.com",  # look-alike host
        "not-a-url",
        "",  # missing base -> fail closed
    ],
)
def test_non_paper_base_url_blocks_readiness(base):
    result = _run_eval(_blob({"alpaca_base": base}))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ready_for_manual_validation=false" in result.stdout


def test_paper_base_url_passes():
    result = _run_eval(_blob({"alpaca_base": "https://paper-api.alpaca.markets"}))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ready_for_manual_validation=true" in result.stdout


# --- absent / mismatched heartbeat DB path ----------------------------------
def test_absent_heartbeat_db_path_blocks_readiness():
    # An unknown heartbeat DB path can no longer be waved through: the same-DB
    # proof now requires all three of resolver/api/heartbeat to be present AND
    # equal, so an unverifiable heartbeat DB is a split-brain risk that FAILS.
    result = _run_eval(_blob({"heartbeat_db_path": ""}))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ready_for_manual_validation=false" in result.stdout


def test_mismatched_heartbeat_db_path_blocks_readiness():
    result = _run_eval(_blob({"heartbeat_db_path": "/srv/other/alpha_lab.sqlite3"}))
    assert result.returncode == 1
    assert "ready_for_manual_validation=false" in result.stdout


# --- malformed parsed values fail closed ------------------------------------
@pytest.mark.parametrize(
    "overrides",
    [
        {"dashboard_health_code": "malformed"},
        {"dashboard_health_code": ""},
        {"alpaca_account_code": ""},
        {"api_db_path": ""},  # empty parse -> same-DB proof cannot hold
        {"resolver_db_path": '"escaped"'},  # quote-mangled parse mismatches api path
        {"api_db_path": "/srv/alpha_lab/data/alpha_lab.sqlite3 "},  # trailing space mismatch
    ],
)
def test_malformed_values_fail_closed(overrides):
    result = _run_eval(_blob(overrides))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ready_for_manual_validation=false" in result.stdout


# --- invalid heartbeat threshold fails closed -------------------------------
@pytest.mark.parametrize("hmax", ["abc", "-1", "9e9", "0x10", "12.5"])
def test_invalid_heartbeat_threshold_blocks_readiness(hmax):
    result = _run_eval(_blob({"heartbeat_max_age": hmax}))
    assert result.returncode == 1, result.stdout + result.stderr
    assert "ready_for_manual_validation=false" in result.stdout


# --- pure base-url decision (no network): proves no credentialed curl --------
# `_alpaca_base_is_paper` is the SINGLE shared guard injected verbatim into every
# remote inproj block that issues a credentialed Alpaca curl (the collector AND
# `./ops check alpaca`). This hidden subcommand exposes that exact pure decision
# so it is unit-testable without SSH: anything returning "not-paper" is what those
# paths treat as "refuse the credentialed request / no curl".
def _base_check(base: str) -> str:
    result = subprocess.run(
        ["zsh", str(OPS_SCRIPT), "__alpaca-base-paper-check", base],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


# Canonical policy: ONLY the bare paper host, with an optional trailing slash.
@pytest.mark.parametrize(
    "base",
    [
        "https://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets/",  # optional trailing slash allowed
    ],
)
def test_base_paper_check_accepts_canonical_only(base):
    assert _base_check(base) == "paper"


@pytest.mark.parametrize(
    "base",
    [
        # arbitrary paths must be rejected (the curl appends its own /v2/account)
        "https://paper-api.alpaca.markets/v2/account",
        "https://paper-api.alpaca.markets/v2",
        "https://paper-api.alpaca.markets//",
        "https://api.alpaca.markets",  # live trading endpoint
        "https://api.alpaca.markets/v2",
        "http://paper-api.alpaca.markets",  # not https
        "http://paper-api.alpaca.markets.evil.example.com",  # look-alike host
        "https://paper-api.alpaca.markets.evil.example.com",  # https look-alike
        "https://paper-api.alpaca.markets.anything",  # suffix look-alike
        "not-a-url",
        "",  # empty -> never paper
    ],
)
def test_base_paper_check_rejects_non_canonical(base):
    # A "not-paper" verdict is the no-credentialed-curl decision: these bases must
    # never be contacted with keys (live, look-alike, arbitrary path, malformed).
    assert _base_check(base) == "not-paper"


# --- composed account URL: normalization removes the trailing slash ----------
# `__alpaca-account-url` runs the same validate-then-normalize-then-compose path
# the credentialed curls use, so we can prove no composed URL ever contains a
# double slash before /v2/account — without SSH or network.
def _account_url(base: str) -> str:
    result = subprocess.run(
        ["zsh", str(OPS_SCRIPT), "__alpaca-account-url", base],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


CANONICAL_ACCOUNT_URL = "https://paper-api.alpaca.markets/v2/account"


def test_canonical_no_slash_composes_account_url():
    assert _account_url("https://paper-api.alpaca.markets") == CANONICAL_ACCOUNT_URL


def test_canonical_trailing_slash_normalizes_to_same_account_url():
    # The accepted trailing-slash form must normalize to the SAME composed URL.
    assert _account_url("https://paper-api.alpaca.markets/") == CANONICAL_ACCOUNT_URL


@pytest.mark.parametrize(
    "base",
    [
        "https://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets/",
    ],
)
def test_composed_url_never_contains_double_slash(base):
    url = _account_url(base)
    # No "//" in the path portion (after the scheme's "https://").
    assert "//v2/account" not in url
    assert url.split("://", 1)[1].count("//") == 0
    assert url == CANONICAL_ACCOUNT_URL


@pytest.mark.parametrize(
    "base",
    [
        "https://paper-api.alpaca.markets/v2/account",  # arbitrary path
        "https://api.alpaca.markets",  # live
        "http://paper-api.alpaca.markets",  # not https
        "https://paper-api.alpaca.markets.evil.example.com",  # look-alike
        "",  # empty
    ],
)
def test_rejected_base_composes_no_account_url(base):
    # Rejected bases must not yield a composed credentialed URL (fail closed).
    assert _account_url(base) == "SKIPPED"


def test_ops_uses_one_shared_alpaca_guard_everywhere():
    text = OPS_SCRIPT.read_text(encoding="utf-8")
    # One source-of-truth definition.
    assert "_ALPACA_PAPER_GUARD_SH=" in text
    assert text.count("_alpaca_base_is_paper() {") == 1
    # Hidden test hook is wired.
    assert "__alpaca-base-paper-check)" in text
    # Both credentialed-curl paths (collector + `check alpaca`) gate on the guard
    # by injecting the shared definition into their remote blocks.
    assert text.count('inproj "$_ALPACA_PAPER_GUARD_SH"') >= 2


def test_check_alpaca_gates_curl_behind_guard():
    # The `./ops check alpaca` path must validate+normalize the base before the
    # credentialed /v2/account curl and fail closed otherwise (no SSH/network
    # needed to assert the source wiring). It composes from the canonical value.
    text = OPS_SCRIPT.read_text(encoding="utf-8")
    alpaca_block = text.split("alpaca)", 1)[1]
    assert 'if canon="$(_alpaca_paper_base_canonical "$base")"; then' in alpaca_block
    assert '"$canon/v2/account"' in alpaca_block
    assert "refusing credentialed request" in alpaca_block


def test_no_raw_base_account_url_composition_remains():
    # Neither credentialed curl path may compose "$base/v2/account" directly; the
    # only account-URL composition must be from the normalized "$canon".
    text = OPS_SCRIPT.read_text(encoding="utf-8")
    assert '"$base/v2/account"' not in text
