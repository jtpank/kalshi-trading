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
