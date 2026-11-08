"""Token usage and estimated cost per run, priced from config/pricing.yaml.

The cost of each run decides what a subscription has to charge, so every
run records its model, token counts, and an estimated cost in US dollars.
"""
from pathlib import Path

import yaml

PRICING_PATH = Path(__file__).parent / "config" / "pricing.yaml"


def load_prices() -> dict:
    if not PRICING_PATH.exists():
        return {}
    with open(PRICING_PATH) as f:
        return yaml.safe_load(f) or {}


def estimate_cost(model: str | None, prompt_tokens: int, cached_tokens: int, completion_tokens: int) -> float | None:
    """US dollars, or None when the model has no price in pricing.yaml."""
    prices = load_prices().get(model or "")
    if not prices:
        return None
    uncached = max(prompt_tokens - cached_tokens, 0)
    cached_rate = prices.get("cached_input", prices["input"])
    return (uncached * prices["input"] + cached_tokens * cached_rate + completion_tokens * prices["output"]) / 1_000_000


def summarize_usage(token_usage, model: str | None) -> dict:
    """Turns CrewAI's UsageMetrics into the fields saved with each run."""
    prompt = getattr(token_usage, "prompt_tokens", 0) or 0
    cached = getattr(token_usage, "cached_prompt_tokens", 0) or 0
    completion = getattr(token_usage, "completion_tokens", 0) or 0
    return {
        "model": model,
        "prompt_tokens": prompt,
        "cached_tokens": cached,
        "completion_tokens": completion,
        "llm_requests": getattr(token_usage, "successful_requests", 0) or 0,
        "cost_usd": estimate_cost(model, prompt, cached, completion),
    }
