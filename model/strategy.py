from loguru import logger as log
from abc import ABC, abstractmethod
from utils.utils import TraderState, MarketOrder, MarketState, StrategyConfig
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

class BaseStrategy(ABC):
    def __init__(self, config: StrategyConfig, trader: Trader) -> None:
        self.config = config
        self.trader = trader
        self.closing_ask = 0
        self.initial_closing_ask = 0
        self.hit_initial_take_profit = False
    
    @abstractmethod
    def should_enter(self, st: TraderState, market_st: MarketState) -> bool:
        pass

    @abstractmethod
    def should_exit(self, st: TraderState, market_st: MarketState) -> bool:
        pass

    

class StrategyRunner:
    def __init__(self, config: StrategyConfig, trader: Trader) -> None:
        self.config = config
        self.trader = trader
        self.closing_ask = 0
        self.initial_closing_ask = 0
        self.hit_initial_take_profit = False
        # self.history: list[MarketState] = []

    def _should_enter(self, st: TraderState, market_st: MarketState) -> bool:
        if st.done or st.in_position:
            return False
        if st.entries_done >= self.config.max_entries:
            return False
        if self.closing_ask is None or market_st.live_ask is None:
            return False
        if market_st.live_ask <= self.config.min_entry_ask * self.initial_closing_ask:
            return False
        return market_st.live_ask <= (self.closing_ask * (1-self.config.entry_ratio))

    def _should_stop_out(self, st: TraderState, market_st: MarketState) -> bool:
        if not st.in_position:
            return False
        if market_st.live_ask is None or st.entry_price is None:
            return False
        return market_st.live_ask <= (st.entry_price * (1-self.config.stop_loss_ratio))

    def _should_take_profit(self, st: TraderState, market_st: MarketState) -> bool:
        if not st.in_position:
            return False
        if market_st.live_ask is None or st.entry_price is None:
            return False
        # return market_st.live_ask >= (st.entry_price * (1.0 + self.config.exit_ratio))
        initial_take_profit = st.entry_price * (1.0 + self.config.exit_ratio)
        secondary_take_profit = st.entry_price * (1.0 + self.config.secondary_exit_ratio)

        if not self.hit_initial_take_profit:
            if market_st.live_ask >= initial_take_profit:
                log.info(f"Initial take profit reached at {market_st.live_ask}, waiting for secondary target")
                self.hit_initial_take_profit = True
            return False

        if market_st.live_ask >= secondary_take_profit:
            return True

        if market_st.live_ask <= initial_take_profit:
            return True

        return False
    
    def set_closing_ask(self, closing_ask: float):
        log.info(f"Updated closing ask: {closing_ask}")
        self.closing_ask = closing_ask
        self.initial_closing_ask = closing_ask

    def update(self, current_market_state: MarketState) -> None:
        current_trader_state = self.trader.get_trader_state()
        if current_trader_state is None or current_trader_state.done:
            return

        if not self.config.simulated:
            now_ts = int(datetime.now(UTC).timestamp())
            if now_ts < current_market_state.open_ts:
                return

            if now_ts > current_market_state.close_ts:
                current_trader_state.done = True
                return

        if self._should_enter(current_trader_state, current_market_state):
            balance = self.trader.get_portfolio().balance / 100.0 
            budget = balance * self.config.balance_fraction
            contract_count = max(1, math.floor(budget / current_market_state.live_ask))
            log.info(f"Balance: {balance}  Budget: {budget}  Contract Count: {contract_count}")
            self.hit_initial_take_profit = False
            order = MarketOrder(ticker="simulated", favored_side="yes", count=contract_count, limit_price_dollars=current_market_state.live_ask)
            self.trader.place_entry(order)
        elif self._should_take_profit(current_trader_state, current_market_state):
            order = MarketOrder(ticker="simulated", favored_side="yes", count=current_trader_state.contract_count, limit_price_dollars=current_market_state.live_ask)
            self.trader.place_exit(order, reason="take_profit")
            self.hit_initial_take_profit = False
        elif self._should_stop_out(current_trader_state, current_market_state):
            order = MarketOrder(ticker="simulated", favored_side="yes", count=current_trader_state.contract_count, limit_price_dollars=current_market_state.live_ask)
            self.trader.place_exit(order, reason="stop_loss")
            # TODO: make sure this works for our live trading
            log.info(f"Exited on stop loss, updating closing_ask to: {current_market_state.live_ask}")
            self.closing_ask = current_market_state.live_ask
            self.hit_initial_take_profit = False
            

# this strategy does a buy at open on favorite, and holds
# Todo: add options for 
# 1. selling at stop loss + dynamic stop loss triggering
# 2. accumulating more up to a fraction of portfolio at set tiers (i.e. 20%, 30% etc...)
# 3. sell at 0.9 or higher, never wait for insane comebacks

class BasicStrategy:
    def __init__(self):
        pass