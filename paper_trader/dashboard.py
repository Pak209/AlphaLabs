from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .audit_log import AuditLog


def build_report(account: dict[str, Any], positions: list[dict[str, Any]], log_path: str | Path) -> str:
    rows = AuditLog(log_path).read_today()
    counts = Counter(row.get("event", "unknown") for row in rows)
    rejected = [row for row in rows if row.get("event") == "trade_rejected"]
    orders = [row for row in rows if row.get("event") == "order_submitted"]

    lines = [
        "Paper Trader Alpha Dashboard",
        "",
        f"Equity: ${float(account.get('equity', 0) or 0):,.2f}",
        f"Cash: ${float(account.get('cash', 0) or 0):,.2f}",
        f"Open positions: {len(positions)}",
        f"Today's submitted paper orders: {len(orders)}",
        f"Today's rejected signals: {len(rejected)}",
        "",
        "Open Positions",
    ]
    if positions:
        for position in positions:
            lines.append(
                f"- {position.get('symbol')}: qty={position.get('qty')} market_value={position.get('market_value')} "
                f"unrealized_pl={position.get('unrealized_pl')}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "Event Counts"])
    for event, count in sorted(counts.items()):
        lines.append(f"- {event}: {count}")

    if rejected:
        lines.extend(["", "Recent Rejections"])
        for row in rejected[-10:]:
            reasons = row.get("reasons") or row.get("decision", {}).get("reasons") or []
            ticker = row.get("ticker") or row.get("decision", {}).get("ticker")
            lines.append(f"- {ticker}: {', '.join(reasons)}")

    return "\n".join(lines)

