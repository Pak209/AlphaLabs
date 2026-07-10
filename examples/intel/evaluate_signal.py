#!/usr/bin/env python3
"""AlphaLabs Intelligence — stdlib-only client example.

Evaluate a trade idea through the live engine, then fetch the glass-box
explanation for the same evaluation:

    INTEL_URL=http://127.0.0.1:8790 INTEL_KEY=sk-... python3 evaluate_signal.py
"""
import json
import os
import urllib.request

BASE = os.environ.get("INTEL_URL", "http://127.0.0.1:8790")
KEY = os.environ["INTEL_KEY"]


def call(method: str, path: str, body: dict = None) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", method=method,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {KEY}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        return json.load(res)


idea = {
    "ticker": "NVDA",
    "bias": "bullish",
    "confidence": 0.7,
    "catalyst": "NVDA wins major government AI contract",
    "thesis": "Contract expands datacenter demand beyond consensus",
    "catalyst_type": "Government Contract",
    "catalyst_score": 82,
}

evaluation = call("POST", "/v1/signal-evaluation", idea)
data = evaluation["data"]
print(f"composite={data['composite_score']} tier={data['tier']} "
      f"floors={data['floors_applied']}")
print(f"reasoning: {evaluation['reasoning']}")

explanation = call("GET", f"/v1/decision-explanation/{data['evaluation_id']}")
for name, component in explanation["data"]["component_reasoning"].items():
    print(f"\n[{name}] {component['explanation']}")
    for signal in component["sub_signals"]:
        print(f"  - {signal['name']}={signal['value']} (w={signal['weight']}): "
              f"{signal['detail']}")
