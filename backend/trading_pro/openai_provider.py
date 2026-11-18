"""Optional, explicit OpenAI Responses adapter; never called by the local server."""
from __future__ import annotations
import json
import os
from math import isfinite
from urllib.request import Request, build_opener

from .integrations import _NoRedirect
from .prompts import MODEL_AGENTS, PROMPTS

REPORT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "action": {"type": "string", "enum": ["BUY", "SELL", "WAIT"]},
        "rationale": {"type": "string"},
        "evidence": {"type": "array", "items": {"type": "string"}},
        "score": {"type": ["number", "null"]},
    },
    "required": ["action", "rationale", "evidence", "score"],
}


class OpenAIProvider:
    def __init__(self, *, api_key: str, input_usd_per_million: float,
                 output_usd_per_million: float, opener=None):
        if not isinstance(api_key, str) or not api_key.strip():
            raise ValueError("OpenAI key required")
        prices = (input_usd_per_million, output_usd_per_million)
        if any(isinstance(p, bool) or not isinstance(p, (float, int)) or not isfinite(p) or p < 0 for p in prices):
            raise ValueError("Verified nonnegative model prices required")
        self._key = api_key
        self._input_price, self._output_price = prices
        self._opener = opener if opener is not None else build_opener(_NoRedirect()).open

    def estimate_cost(self, agent: str, snapshot: dict) -> float:
        """Deliberately pessimistic projection: two characters per token plus the full output cap."""
        if agent not in MODEL_AGENTS:
            raise ValueError("Unknown model agent")
        size = len(PROMPTS[agent]["text"]) + len(json.dumps(snapshot, ensure_ascii=False, allow_nan=False))
        input_tokens = size // 2 + 100
        cost = (input_tokens * self._input_price + 512 * self._output_price) / 1_000_000
        return max(cost, 1e-9)

    def classify(self, agent: str, snapshot: dict, model: str) -> tuple[dict, dict]:
        if agent not in MODEL_AGENTS or not isinstance(model, str) or not model.strip():
            raise ValueError("Agent and configured model required")
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("cycle_id"), str):
            raise ValueError("Immutable cycle snapshot required")
        encoded_snapshot = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
        if len(encoded_snapshot) > 20000:
            raise ValueError("Snapshot too large")
        body = {
            "model": model,
            "store": False,
            "max_output_tokens": 512,
            "input": [
                {"role": "developer", "content": PROMPTS[agent]["text"]},
                {"role": "user", "content": json.dumps({"agent": agent, "snapshot": snapshot},
                                                        ensure_ascii=False, allow_nan=False)},
            ],
            "text": {"format": {"type": "json_schema", "name": "research_report",
                                "strict": True, "schema": REPORT_SCHEMA}},
        }
        request = Request("https://api.openai.com/v1/responses",
                          data=json.dumps(body, ensure_ascii=False).encode("utf-8"), method="POST",
                          headers={"Authorization": f"Bearer {self._key}",
                                   "Content-Type": "application/json", "Accept": "application/json"})
        with self._opener(request, timeout=20) as response:
            if response.status != 200:
                raise ValueError("Model request failed")
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Model response too large")
        result = json.loads(raw)
        if result.get("status") != "completed":
            raise ValueError("Model did not complete")
        texts = [item.get("text") for message in result.get("output", [])
                 if message.get("type") == "message" for item in message.get("content", [])
                 if item.get("type") == "output_text"]
        if len(texts) != 1 or not isinstance(texts[0], str):
            raise ValueError("Exactly one structured model output required")
        report = json.loads(texts[0])
        usage = result.get("usage") or {}
        token_in, token_out = usage.get("input_tokens"), usage.get("output_tokens")
        if any(isinstance(t, bool) or not isinstance(t, int) or t < 0 for t in (token_in, token_out)):
            raise ValueError("Provider usage missing")
        return report, {"input_tokens": token_in, "output_tokens": token_out,
                        "cost_usd": (token_in*self._input_price + token_out*self._output_price)/1_000_000}


def provider_from_env(environ=None) -> "OpenAIProvider":
    """Build the provider from server-side settings; no price is ever assumed or defaulted."""
    env = os.environ if environ is None else environ
    names = ("OPENAI_API_KEY", "TIP_OPENAI_INPUT_USD_PER_M", "TIP_OPENAI_OUTPUT_USD_PER_M")
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise ValueError("Missing configuration: " + ", ".join(missing) +
                         ". Copy the model prices from the provider's price list; none are assumed.")
    try:
        input_price = float(env["TIP_OPENAI_INPUT_USD_PER_M"])
        output_price = float(env["TIP_OPENAI_OUTPUT_USD_PER_M"])
    except ValueError:
        raise ValueError("Model prices must be numbers (USD per million tokens)") from None
    if not (isfinite(input_price) and isfinite(output_price)) or input_price <= 0 or output_price <= 0:
        raise ValueError("Model prices must be positive USD per million tokens")
    return OpenAIProvider(api_key=env["OPENAI_API_KEY"], input_usd_per_million=input_price,
                          output_usd_per_million=output_price)
