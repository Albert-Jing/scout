"""Model prices and the cost math for one API call.

All prices are dollars per million tokens (MTok), from Anthropic's pricing page.
"""

MODELS = {
    # key: model ID, prices, and effort (how hard the model thinks; Haiku doesn't support it)
    "haiku": {"id": "claude-haiku-4-5", "input": 1.00, "output": 5.00, "cache_read": 0.10, "effort": None},
    "sonnet": {"id": "claude-sonnet-5", "input": 2.00, "output": 10.00, "cache_read": 0.20, "effort": "medium"},
    "opus": {"id": "claude-opus-5-5", "input": 4.00, "output": 20.00, "cache_read": 0.20, "effort": "medium"},
}

CACHE_WRITE_MULTIPLIER = 1.25  # saving a prefix into the cache costs 25% more than normal input, once
WEB_SEARCH_PRICE = 10.00 / 1000  # $10 per 1,000 searches


def turn_cost(usage, model_key):
    """Turn one response's `usage` into token counts and a dollar amount."""
    prices = MODELS[model_key]
    # Fields can be None when a feature wasn't used, so default them to 0.
    uncached = usage.input_tokens or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    output = usage.output_tokens or 0
    server_tools = getattr(usage, "server_tool_use", None)
    searches = (getattr(server_tools, "web_search_requests", 0) or 0) if server_tools else 0

    dollars = (
        uncached * prices["input"]
        + cache_write * prices["input"] * CACHE_WRITE_MULTIPLIER
        + cache_read * prices["cache_read"]
        + output * prices["output"]
    ) / 1_000_000 + searches * WEB_SEARCH_PRICE

    return {
        "input": uncached,
        "cache_write": cache_write,
        "cache_read": cache_read,
        "output": output,
        "searches": searches,
        "dollars": dollars,
    }
