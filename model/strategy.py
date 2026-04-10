from loguru import logger as log
from utils.utils import MarketState, StrategyConfig
from typing import Optional
from datetime import datetime, UTC
import asyncio
import math
import uuid
from traders.Trader import Trader


#Helpers
def to_float(value) -> Optional[float]:
    if value is None:
        return None
    return float(value)


class StrategyRunner:
    def __init__(self, config: StrategyConfig, trader: Trader, buying_power: float) -> None:
        self.config = config
        self.trader = trader
        self.buying_power = buying_power
        self.history: list[MarketState] = []

    def _should_enter(self, st: MarketState) -> bool:
        if st.done or st.in_position:
            return False
        if st.entries_done >= self.config.max_entries:
            return False
        if st.closing_ask is None or st.live_ask is None:
            return False
        return st.live_ask <= (st.closing_ask * (1-self.config.entry_ratio))

    def _should_stop_out(self, st: MarketState) -> bool:
        if not st.in_position:
            return False
        if st.live_ask is None or st.entry_price is None:
            return False
        return st.live_ask <= (st.entry_price * (1-self.config.stop_loss_ratio))

    def _should_take_profit(self, st: MarketState) -> bool:
        if not st.in_position:
            return False
        if st.live_ask is None or st.entry_price is None:
            return False
        return st.live_ask >= (st.entry_price * (1.0 + self.config.exit_ratio))
    
    def update(self) -> None:
        st = self.trader.get_market_state()

        if st is None or st.done:
            return

        # st.live_ask = to_float(yes_ask if st.favored_side == "yes" else no_ask)
        # st.last_price = to_float(last_price)

        now_ts = int(datetime.now(UTC).timestamp())
        if now_ts < st.open_ts:
            return

        if now_ts > st.close_ts:
            st.done = True
            return

        if not self.enable_trading:
            return

        if self._should_enter(st):
            self.trader.place_entry(st)
        elif self._should_take_profit(st):
            self.trader.place_exit(st, reason="take_profit")
        elif self._should_stop_out(st):
            self.trader.place_exit(st, reason="stop_loss")


class StrategyRunner:
    def __init__(
        self,
        # input_file: str,
        entry_ratio: float = 0.15,
        stop_loss_ratio: float = 0.50,
        exit_ratio: float = 0.11,
        max_entries: int = 3,
        balance_fraction: float = 0.02,
        poll_fallback_seconds: float = 2.0,
        enable_trading: bool = False,
    ):
        self.http = load_http_client()
        self.account_limits_dict = self.http.get_account_limits()
        print(self.account_limits_dict)
        self.ws = load_ws_client()
        # self.input_file = input_file
        self.entry_ratio = entry_ratio
        self.stop_loss_ratio = stop_loss_ratio
        self.exit_ratio = exit_ratio
        self.max_entries = max_entries
        self.balance_fraction = balance_fraction
        self.poll_fallback_seconds = poll_fallback_seconds
        self.markets: dict[str, MarketState] = {}
        self.enable_trading = enable_trading

    # def load_markets(self):
    #     rows = parse_input_file(self.input_file)
    #     for ticker, favored_side, user_closing_ask in rows:
    #         market = self.http.get(f"{self.http.markets_url}/{ticker}")["market"]
    #         state = MarketState(
    #             ticker=ticker,
    #             favored_side=favored_side,
    #             open_ts=iso_to_ts(market["open_time"]),
    #             close_ts=iso_to_ts(market["close_time"]),
    #         )
    #         px = self.http.get_market_prices(ticker)
    #         state.closing_ask = user_closing_ask
    #         state.live_ask = state.closing_ask
    #         state.last_price = self._to_float(px.get("last_price"))
    #         self.markets[ticker] = state

    def _extract_ask(self, px: dict, side: str) -> Optional[float]:
        return px.get("yes_ask") if side == "yes" else px.get("no_ask")

    def _to_float(self, value) -> Optional[float]:
        if value is None:
            return None
        return float(value)

    def _extract_mark(self, px: dict, side: str) -> Optional[float]:
        last = px.get("last_price")
        if last is None:
            return None
        return last if side == "yes" else (1.0 - last)

    def _available_balance_dollars(self) -> float:
        bal = self.http.get_balance()
        for key in ["balance", "cash_balance", "available_balance"]:
            if key in bal and bal[key] is not None:
                return float(bal[key]) / 100.0
        raise RuntimeError(f"Could not find balance field in: {bal}")

    def _contracts_for_price(self, ask_price: float) -> int:
        balance = self._available_balance_dollars()
        budget = balance * self.balance_fraction
        contracts = max(1, math.floor(budget / ask_price))
        print("SIZE_CHECK", {
            "balance": balance,
            "balance_fraction": self.balance_fraction,
            "budget_dollars": budget,
            "ask_price_dollars": ask_price,
            "raw_contracts": budget / ask_price,
            "contracts_floor": math.floor(budget / ask_price),
            "contracts_final": contracts,
        })
        return contracts

    def _should_enter(self, st: MarketState) -> bool:
        if st.done or st.in_position:
            return False
        if st.entries_done >= self.max_entries:
            return False
        if st.closing_ask is None or st.live_ask is None:
            return False
        return st.live_ask <= (st.closing_ask * (1-self.entry_ratio))

    def _should_stop_out(self, st: MarketState) -> bool:
        if not st.in_position:
            return False
        if st.live_ask is None or st.entry_price is None:
            return False
        return st.live_ask <= (st.entry_price * (1-self.stop_loss_ratio))

    def _should_take_profit(self, st: MarketState) -> bool:
        if not st.in_position:
            return False
        if st.live_ask is None or st.entry_price is None:
            return False
        return st.live_ask >= (st.entry_price * (1.0 + self.exit_ratio))

    def _place_entry(self, st: MarketState):
        count = self._contracts_for_price(st.live_ask)
        client_order_id = str(uuid.uuid4())
        print("ENTRY_ORDER", {
            "ticker": st.ticker,
            "side": st.favored_side,
            "live_ask": st.live_ask,
            "count": count,
            "notional_dollars": count * st.live_ask,
        })
        resp = self.http.buy_contract(
            ticker=st.ticker,
            side=st.favored_side,
            count=count,
            limit_price_dollars=st.live_ask,
            client_order_id=client_order_id,
        )
        st.in_position = True
        st.entry_price = st.live_ask
        st.contract_count = count
        st.entries_done += 1
        print("ENTRY", st.ticker, st.favored_side, st.live_ask, count, resp)

    def _place_exit(self, st: MarketState, reason: str):
        client_order_id = str(uuid.uuid4())
        resp = self.http.sell_contract(
            ticker=st.ticker,
            side=st.favored_side,
            count=st.contract_count,
            limit_price_dollars=0.01,
            client_order_id=client_order_id,
        )
        print("EXIT", st.ticker, st.favored_side, st.live_ask, st.contract_count, reason, resp)
        st.in_position = False
        st.entry_price = None
        st.contract_count = 0
        if st.entries_done >= self.max_entries:
            st.done = True

    def _handle_market_update(self, ticker: str, yes_ask: Optional[float], no_ask: Optional[float], last_price: Optional[float]):
        st = self.markets.get(ticker)
        if st is None or st.done:
            return

        st.live_ask = self._to_float(yes_ask if st.favored_side == "yes" else no_ask)
        st.last_price = self._to_float(last_price)
        self._maybe_print_status(st)

        now_ts = int(datetime.now(UTC).timestamp())
        if now_ts < st.open_ts:
            return

        if now_ts > st.close_ts:
            st.done = True
            return

        if not self.enable_trading:
            return

        if self._should_enter(st):
            self._place_entry(st)
        elif self._should_take_profit(st):
            self._place_exit(st, reason="take_profit")
        elif self._should_stop_out(st):
            self._place_exit(st, reason="stop_loss")

    def _maybe_print_status(self, st: MarketState, every_seconds: int = 5):
        now_ts = int(datetime.now(UTC).timestamp())
        if st.last_print_ts is not None and (now_ts - st.last_print_ts) < every_seconds:
            return

        print({
            "ts": now_ts,
            "ticker": st.ticker,
            "favored_side": st.favored_side,
            "closing_ask": st.closing_ask,
            "live_ask": st.live_ask,
            "last_price": st.last_price,
            "in_position": st.in_position,
            "entries_done": st.entries_done,
            "trading_enabled": self.enable_trading,
        })
        st.last_print_ts = now_ts

    async def ws_message_handler(self, data: dict):
        msg_type = data.get("type") or data.get("msg_type")
        if msg_type in {"subscribed", "error", "pong"}:
            return

        payload = data.get("msg") or data.get("data") or data

        ticker = (
            payload.get("market_ticker")
            or payload.get("ticker")
            or payload.get("market")
        )
        if ticker not in self.markets:
            return

        yes_ask = payload.get("yes_ask_dollars")
        no_ask = payload.get("no_ask_dollars")
        last_price = payload.get("price_dollars")

        if yes_ask is None and no_ask is None and last_price is None:
            return

        self._handle_market_update(ticker, yes_ask, no_ask, last_price)

    async def fallback_poll_loop(self):
        while True:
            for ticker, st in self.markets.items():
                if st.done:
                    continue
                try:
                    px = self.http.get_market_prices(ticker)
                    yes_ask = px.get("yes_ask")
                    no_ask = px.get("no_ask")
                    last_price = px.get("last_price")
                    self._handle_market_update(ticker, yes_ask, no_ask, last_price)
                except Exception as e:
                    print("POLL_ERROR", ticker, repr(e))
            await asyncio.sleep(self.poll_fallback_seconds)

    async def run(self):
        # self.load_markets()
        self.ws._tickers = list(self.markets.keys())
        self.ws._message_handler = self.ws_message_handler

        await asyncio.gather(
            self.ws.connect(),
            self.fallback_poll_loop(),
        )