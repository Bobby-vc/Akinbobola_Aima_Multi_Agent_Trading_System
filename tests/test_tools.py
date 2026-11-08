from types import SimpleNamespace as NS

import first_ai_agents.tools.custom_tool as tools


class FakeNewsAPI:
    def __init__(self, items):
        self.items = items
        self.requested = None

    def get_news(self, symbol, limit):
        self.requested = (symbol, limit)
        return self.items


def test_news_lists_dated_headlines_with_sources(monkeypatch):
    api = FakeNewsAPI([
        NS(created_at="2026-11-07T14:00:00Z", source="benzinga", headline="Nvidia cleared to sell H200 chips"),
        NS(created_at="2026-11-06T09:30:00Z", source="fiscal.ai", headline="Analysts raise targets"),
    ])
    monkeypatch.setattr(tools, "get_alpaca_api", lambda: api)

    result = tools.get_stock_news.run(ticker="nvda")

    assert api.requested == ("NVDA", 8)
    assert result.startswith("Recent news for NVDA, newest first:")
    assert "- 2026-11-07 (benzinga): Nvidia cleared to sell H200 chips" in result
    assert "- 2026-11-06 (fiscal.ai): Analysts raise targets" in result


def test_news_with_no_headlines(monkeypatch):
    monkeypatch.setattr(tools, "get_alpaca_api", lambda: FakeNewsAPI([]))
    assert tools.get_stock_news.run(ticker="ZZZZ") == "No recent news found for ZZZZ."
