from loguru import logger as log
from abc import ABC, abstractmethod
from utils.utils import TraderState, MarketOrder, MarketState, StrategyConfig
from typing import Optional
from datetime import datetime, UTC
import asyncio
import math
import uuid
from traders.Trader import Trader
from collections import deque


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

class BuyFavoritesStrategy:
    def __init__(self):
        pass


# Buy when close SMA 30s crosses from under to over close SMA 60s
# Sell when SMA 30s crosses back from over to under close SMA 60s
class SmaCrossoverStrategy(BaseStrategy):
    # Buy when SMA30 crosses above SMA Long
    # Sell when SMA30 crosses below SMA Long
    def __init__(self, config: StrategyConfig, trader: Trader) -> None:
        super().__init__(config, trader)
        self.len_long_sma = 120
        self.min_ask_bound = 0.1
        self.max_ask_bound = 0.85
        self.max_contract_profit_threshold = 0.95
        self.close_window_30 = deque(maxlen=30)
        self.close_window = deque(maxlen=self.len_long_sma)
        self.prev_sma30: float | None = None
        self.prev_sma_long: float | None = None
        self.curr_sma30: float | None = None
        self.curr_sma_long: float | None = None

        self.min_sma_gap = 0.01          # require min cent separation
        self.cooldown_ticks = 10         # wait n updates after a trade
        self.last_trade_tick = -10_000
        self.tick_count = 0

        self.pending_bullish = False
        self.pending_bearish = False

    def _update_smas(self, close_price: float) -> None:
        self.prev_sma30 = self.curr_sma30
        self.prev_sma_long = self.curr_sma_long

        self.close_window_30.append(close_price)
        self.close_window.append(close_price)

        self.curr_sma30 = sum(self.close_window_30) / len(self.close_window_30)
        self.curr_sma_long = sum(self.close_window) / len(self.close_window)

    def _sma_gap(self) -> float | None:
        if self.curr_sma30 is None or self.curr_sma_long is None:
            return None
        return self.curr_sma30 - self.curr_sma_long
    def _crossed_bullish_now(self) -> bool:
        if (
            self.prev_sma30 is None
            or self.prev_sma_long is None
            or self.curr_sma30 is None
            or self.curr_sma_long is None
        ):
            return False
        return self.prev_sma30 <= self.prev_sma_long and self.curr_sma30 > self.curr_sma_long
    def _crossed_bearish_now(self) -> bool:
        if (
            self.prev_sma30 is None
            or self.prev_sma_long is None
            or self.curr_sma30 is None
            or self.curr_sma_long is None
        ):
            return False
        return self.prev_sma30 >= self.prev_sma_long and self.curr_sma30 < self.curr_sma_long

    def _bullish_gap_ready(self) -> bool:
        gap = self._sma_gap()
        return gap is not None and gap >= self.min_sma_gap

    def _bearish_gap_ready(self) -> bool:
        gap = self._sma_gap()
        return gap is not None and (-gap) >= self.min_sma_gap

    def _in_cooldown(self) -> bool:
        return (self.tick_count - self.last_trade_tick) < self.cooldown_ticks
    
    def _has_bullish_crossover(self) -> bool:
        if (
            self.prev_sma30 is None
            or self.prev_sma_long is None
            or self.curr_sma30 is None
            or self.curr_sma_long is None
        ):
            return False

        crossed = self.prev_sma30 <= self.prev_sma_long and self.curr_sma30 > self.curr_sma_long
        gap_ok = (self.curr_sma30 - self.curr_sma_long) >= self.min_sma_gap
        return crossed and gap_ok

    def _has_bearish_crossover(self) -> bool:
        if (
            self.prev_sma30 is None
            or self.prev_sma_long is None
            or self.curr_sma30 is None
            or self.curr_sma_long is None
        ):
            return False

        crossed = self.prev_sma30 >= self.prev_sma_long and self.curr_sma30 < self.curr_sma_long
        gap_ok = (self.curr_sma_long - self.curr_sma30) >= self.min_sma_gap
        return crossed and gap_ok
    def should_enter(self, st: TraderState, market_st: MarketState) -> bool:
        if st.done or st.in_position:
            return False
        if market_st.live_ask is None:
            return False
        if market_st.live_ask < self.min_ask_bound or market_st.live_ask > self.max_ask_bound:
            return False
        if len(self.close_window) < self.len_long_sma:
            return False
        if self._in_cooldown():
            return False
        return self.pending_bullish and self._bullish_gap_ready()

    def should_exit(self, st: TraderState, market_st: MarketState) -> bool:
        if not st.in_position:
            return False
        if market_st.live_ask is None:
            return False
        if st.entry_price is None:
            return False
        if len(self.close_window) < self.len_long_sma:
            return False

        stop_loss_hit = market_st.live_ask <= (st.entry_price * (1 - self.config.stop_loss_ratio))
        if stop_loss_hit:
            return True

        take_profit_hit = market_st.live_ask >= self.max_contract_profit_threshold
        if take_profit_hit:
            return True

        if self._in_cooldown():
            return False

        return self.pending_bearish and self._bearish_gap_ready()

    def update(self, current_market_state: MarketState) -> None:
        self.tick_count += 1

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

        if current_market_state.live_ask is None:
            return

        self._update_smas(current_market_state.live_ask)

        if self._crossed_bullish_now():
            self.pending_bullish = True
            self.pending_bearish = False

        elif self._crossed_bearish_now():
            self.pending_bearish = True
            self.pending_bullish = False

        if self.should_enter(current_trader_state, current_market_state):
            balance = self.trader.get_portfolio().balance / 100.0
            budget = balance * self.config.balance_fraction
            contract_count = max(1, math.floor(budget / current_market_state.live_ask))
            order = MarketOrder(
                ticker="simulated",
                favored_side="yes",
                count=contract_count,
                limit_price_dollars=current_market_state.live_ask,
            )
            self.trader.place_entry(order)
            self.last_trade_tick = self.tick_count
            self.pending_bullish = False

        elif self.should_exit(current_trader_state, current_market_state):
            order = MarketOrder(
                ticker="simulated",
                favored_side="yes",
                count=current_trader_state.contract_count,
                limit_price_dollars=current_market_state.live_ask,
            )
            self.trader.place_exit(order, reason="sma_crossover")
            self.last_trade_tick = self.tick_count
            self.pending_bearish = False