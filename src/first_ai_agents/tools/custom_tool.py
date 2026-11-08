import yfinance as yf
from crewai.tools import tool

from first_ai_agents.broker import get_alpaca_api, record_portfolio_snapshot
from first_ai_agents.database import DEFAULT_ACCOUNT, cache_stock_data, get_cached_stock, log_trade
from first_ai_agents.monitor import RunContext, check_order


@tool("Get Stock Price Data")
def get_stock_data(ticker: str) -> str:
    """Fetches current price, 52-week high/low, volume, P/E ratio,
    and recent 5-day closing prices for a given stock ticker."""
    cached = get_cached_stock(ticker)
    if cached:
        return cached["formatted"]

    stock = yf.Ticker(ticker)
    info = stock.info
    hist = stock.history(period="5d")
    closes = [round(c, 2) for c in hist['Close'].tolist()]
    formatted = f"""
    Ticker: {ticker}
    Current Price: ${info.get('currentPrice', 'N/A')}
    52-Week High: ${info.get('fiftyTwoWeekHigh', 'N/A')}
    52-Week Low: ${info.get('fiftyTwoWeekLow', 'N/A')}
    P/E Ratio: {info.get('trailingPE', 'N/A')}
    Volume: {info.get('volume', 'N/A')}
    Recent 5-Day Closes: {closes}
    """
    cache_stock_data(ticker, {
        "formatted": formatted,
        "currentPrice": info.get('currentPrice'),
        "fiftyTwoWeekHigh": info.get('fiftyTwoWeekHigh'),
        "fiftyTwoWeekLow": info.get('fiftyTwoWeekLow'),
        "trailingPE": info.get('trailingPE'),
        "volume": info.get('volume'),
        "closes": closes,
    })
    return formatted


@tool("Get Stock News")
def get_stock_news(ticker: str) -> str:
    """Fetches the most recent news headlines tagged to a given stock ticker,
    with their dates and sources. Useful for sentiment analysis."""
    # Alpaca's news feed (from Benzinga and others) is tagged by stock; the
    # yfinance news endpoint stopped working for the yfinance version that is
    # compatible with alpaca-trade-api
    news = get_alpaca_api().get_news(ticker.upper(), limit=8)
    if not news:
        return f"No recent news found for {ticker}."
    headlines = "\n".join(f"- {str(n.created_at)[:10]} ({n.source}): {n.headline}" for n in news)
    return f"Recent news for {ticker.upper()}, newest first:\n{headlines}"


def trading_tools(run: RunContext) -> list:
    """The Trader's tools for one run, bound to that run's broker and state, so
    runs happening at the same time cannot see each other's orders or signals."""
    broker = run.broker
    account = getattr(broker, "account_id", DEFAULT_ACCOUNT)

    @tool("Execute Paper Trade")
    def execute_paper_trade(ticker: str, qty: int, side: str) -> str:
        """Places a practice (paper) market order. No real money is involved.
        ticker: stock symbol (e.g. 'AAPL')
        qty: number of shares to trade
        side: must be 'buy' or 'sell'
        Every order is checked by the risk monitor first and may be blocked."""
        try:
            allowed, reason = check_order(broker, ticker, qty, side, run)
            if not allowed:
                log_trade(ticker, qty, side, None, "blocked", account=account)
                return (
                    f"Order BLOCKED by the risk monitor: {reason}\n"
                    f"Do not retry or resize this order. Report it as BLOCKED with this reason."
                )
            order = broker.submit_order(symbol=ticker, qty=qty, side=side, type="market", time_in_force="gtc")
            filled_price = getattr(order, "filled_avg_price", None)
            log_trade(ticker, qty, side, order.id, order.status, account=account,
                      filled_avg_price=float(filled_price) if filled_price else None)
            return (
                f"Order submitted successfully!\n"
                f"Action: {side.upper()} {qty} shares of {ticker}\n"
                f"Order ID: {order.id}\n"
                f"Status: {order.status}\n"
                f"Disclaimer: This is a simulated paper trade. Not real financial advice."
            )
        except Exception as e:
            log_trade(ticker, qty, side, None, "failed", account=account)
            return f"Trade execution failed: {str(e)}"

    @tool("Check Portfolio")
    def get_portfolio() -> str:
        """Returns the current practice portfolio: cash balance, total portfolio
        value, and open positions."""
        try:
            account_info, positions = record_portfolio_snapshot(broker)
            if positions:
                pos_str = "\n".join([
                    f"  {p.symbol}: {p.qty} shares @ avg ${p.avg_entry_price} "
                    f"(current: ${p.current_price}, P&L: ${p.unrealized_pl})"
                    for p in positions
                ])
            else:
                pos_str = "  No open positions."
            return (
                f"Cash Available: ${account_info.cash}\n"
                f"Portfolio Value: ${account_info.portfolio_value}\n"
                f"Buying Power: ${account_info.buying_power}\n"
                f"Open Positions:\n{pos_str}"
            )
        except Exception as e:
            return f"Failed to retrieve portfolio: {str(e)}"

    return [execute_paper_trade, get_portfolio]


@tool("Search SEC Filings")
def search_sec_filings(ticker: str, query: str) -> str:
    """Searches the company's latest 10-K annual report and 10-Q quarterly
    report, filed with the SEC, for passages relevant to a query such as
    "main risk factors", "revenue growth and outlook", or "competition".
    Returns quoted passages with the filing type, filing date, and section."""
    from first_ai_agents.filings import get_index
    try:
        results = get_index().search(ticker, query)
    except Exception as e:
        return f"SEC filings are unavailable for {ticker.upper()} right now ({e}). Continue without them."
    if not results:
        return f"No SEC filing passages found for {ticker.upper()}."
    passages = "\n\n".join(f"[{r['form']} filed {r['filed']}, {r['section']}]\n{r['text']}" for r in results)
    return f"Passages from {ticker.upper()}'s SEC filings for \"{query}\":\n\n{passages}"
