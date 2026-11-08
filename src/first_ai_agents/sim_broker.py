"""Simulated practice portfolios, kept in the database.

Each account starts with virtual cash. Market orders fill immediately at the
latest trade price; there is no margin, and selling more shares than are held
is rejected. Prices come from Alpaca's market data by default.
"""
import uuid
from types import SimpleNamespace as NS

from first_ai_agents.database import get_conn, utc_now

STARTING_CASH = 100_000.0


def latest_price(symbol: str) -> float:
    from first_ai_agents.broker import get_alpaca_api
    return float(get_alpaca_api().get_latest_trade(symbol).price)


class SimulatedBroker:
    def __init__(self, account_id: str, price_source=None, starting_cash: float = STARTING_CASH):
        if not account_id.startswith("sim:") or len(account_id) <= 4:
            raise ValueError(f"Simulated account ids look like 'sim:<name>', got '{account_id}'.")
        self.account_id = account_id
        self.price = price_source or latest_price
        with get_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sim_accounts (id, cash, starting_cash, created_at) VALUES (?,?,?,?)",
                (account_id, starting_cash, starting_cash, utc_now().isoformat()),
            )

    def _cash(self, conn) -> float:
        return conn.execute("SELECT cash FROM sim_accounts WHERE id=?", (self.account_id,)).fetchone()["cash"]

    def get_latest_trade(self, symbol: str):
        return NS(price=self.price(symbol.upper()))

    def list_positions(self):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT symbol, qty, avg_price FROM sim_positions WHERE account_id=? ORDER BY symbol",
                (self.account_id,),
            ).fetchall()
        positions = []
        for row in rows:
            price = self.price(row["symbol"])
            qty, avg = row["qty"], row["avg_price"]
            positions.append(NS(
                symbol=row["symbol"], qty=qty, avg_entry_price=avg, current_price=price,
                market_value=qty * price, unrealized_pl=(price - avg) * qty,
                unrealized_plpc=price / avg - 1 if avg else 0.0,
            ))
        return positions

    def get_account(self):
        with get_conn() as conn:
            cash = self._cash(conn)
        holdings = sum(p.market_value for p in self.list_positions())
        return NS(cash=cash, portfolio_value=cash + holdings, buying_power=cash)

    def submit_order(self, symbol: str, qty, side: str, type: str = "market", time_in_force: str = "day"):
        symbol, qty = symbol.upper(), float(qty)
        if side not in ("buy", "sell") or qty <= 0:
            raise ValueError(f"Invalid order: {side} {qty} {symbol}")
        price = self.price(symbol)
        order_id = str(uuid.uuid4())
        with get_conn() as conn:
            # Take the write lock before reading the balance, so two orders at once
            # cannot both spend the same cash
            conn.execute("BEGIN IMMEDIATE")
            cash = self._cash(conn)
            row = conn.execute("SELECT qty, avg_price FROM sim_positions WHERE account_id=? AND symbol=?",
                               (self.account_id, symbol)).fetchone()
            held, avg = (row["qty"], row["avg_price"]) if row else (0.0, 0.0)
            if side == "buy" and price * qty > cash:
                status = "rejected"   # not enough cash; there is no margin
            elif side == "sell" and qty > held:
                status = "rejected"   # no short selling
            else:
                status = "filled"
                if side == "buy":
                    new_qty = held + qty
                    new_avg = (held * avg + qty * price) / new_qty
                    conn.execute(
                        """INSERT INTO sim_positions (account_id, symbol, qty, avg_price) VALUES (?,?,?,?)
                           ON CONFLICT(account_id, symbol) DO UPDATE SET qty=excluded.qty, avg_price=excluded.avg_price""",
                        (self.account_id, symbol, new_qty, new_avg),
                    )
                    cash -= price * qty
                else:
                    if qty == held:
                        conn.execute("DELETE FROM sim_positions WHERE account_id=? AND symbol=?",
                                     (self.account_id, symbol))
                    else:
                        conn.execute("UPDATE sim_positions SET qty=? WHERE account_id=? AND symbol=?",
                                     (held - qty, self.account_id, symbol))
                    cash += price * qty
                conn.execute("UPDATE sim_accounts SET cash=? WHERE id=?", (cash, self.account_id))
            conn.execute(
                """INSERT INTO sim_orders (id, account_id, symbol, qty, side, status, filled_avg_price, submitted_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (order_id, self.account_id, symbol, qty, side, status,
                 price if status == "filled" else None, utc_now().isoformat()),
            )
        return NS(id=order_id, status=status, filled_avg_price=price if status == "filled" else None)

    def get_order(self, order_id: str):
        with get_conn() as conn:
            row = conn.execute("SELECT status, filled_avg_price FROM sim_orders WHERE id=? AND account_id=?",
                               (order_id, self.account_id)).fetchone()
        if row is None:
            raise KeyError(f"No simulated order {order_id} in {self.account_id}")
        return NS(status=row["status"], filled_avg_price=row["filled_avg_price"])
