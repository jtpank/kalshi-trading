from loguru import logger as log
from abc import ABC, abstractmethod
from utils.utils import CurrentStrategyState, MarketOrder, MarketState
from typing import Optional
from datetime import datetime, UTC
import math
import uuid
from collections import deque

from model.BaseStrategy import BaseStrategy
from traders.BaseTrader import BaseTrader, EntryEnum, ExitEnum

# Buy when close SMA 30s crosses from under to over close SMA 60s
# Sell when SMA 30s crosses back from over to under close SMA 60s
class SmaCrossoverStrategy(BaseStrategy):
    # Buy when SMA30 crosses above SMA Long
    # Sell when SMA30 crosses below SMA Long
    def __init__(self, simulated: bool, trader: BaseTrader, strategy_state: CurrentStrategyState) -> None:
        super().__init__(trader)
        self.simulated = simulated
        self.strategy_state = strategy_state
        self.max_number_of_trades = 5
        self.balance_fraction = 0.05
        self.stop_loss_ratio = 0.3
        self.len_long_sma = 60
        self.min_ask_bound = 0.07
        self.max_ask_bound = 0.88
        self.max_contract_profit_threshold = 0.95
        self.close_window_30 = deque(maxlen=30)
        self.close_window = deque(maxlen=self.len_long_sma)
        self.prev_sma30: float | None = None
        self.prev_sma_long: float | None = None
        self.curr_sma30: float | None = None
        self.curr_sma_long: float | None = None

        self.min_sma_gap = 0.011          # require min cent separation
        self.cooldown_ticks = 30         # wait n updates after a trade
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
    def should_enter(self, market_st: MarketState) -> bool:
        if self.strategy_state.done or self.strategy_state.in_position:
            return False
        if self.strategy_state.entries_done > self.max_number_of_trades:
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

    def should_exit(self, market_st: MarketState) -> bool:
        if not self.strategy_state.in_position:
            return False
        if market_st.live_ask is None:
            return False
        if self.strategy_state.entry_price is None:
            return False
        if len(self.close_window) < self.len_long_sma:
            return False

        stop_loss_hit = market_st.live_ask <= (self.strategy_state.entry_price * (1 - self.stop_loss_ratio))
        if stop_loss_hit:
            log.warning("\t stop loss hit!")
            return True

        take_profit_hit = market_st.live_ask >= self.max_contract_profit_threshold
        if take_profit_hit:
            log.info("\t profit take hit!")
            return True

        # if self._in_cooldown():
        #     return False

        return self.pending_bearish and self._bearish_gap_ready()

    def update(self, ticker_id: str, current_market_state: MarketState) -> None:
        self.tick_count += 1

        if current_market_state.live_ask is None:
            return

        self._update_smas(current_market_state.live_ask)

        if len(self.close_window) < self.len_long_sma:
            # log.info(f"\t filling out sma long window: {len(self.close_window) }")
            return
        #log.info(f"\tprev sma30: {self.prev_sma30}")
        #log.info(f"\tprev smalong: {self.prev_sma_long}")
        #log.info(f"\tcurr sma30: {self.curr_sma30}")
        #log.info(f"\tcurr sma_long: {self.curr_sma_long}")

        if self._crossed_bullish_now():
            self.pending_bullish = True
            self.pending_bearish = False

        elif self._crossed_bearish_now():
            self.pending_bearish = True
            self.pending_bullish = False

        if self.should_enter(current_market_state):
            # This needs to go into the trader because it is a race condition for getting the port balance
            balance = self.trader.available_balance_dollars()
            # budget = balance * self.balance_fraction
            budget = 50
            base_count = 0
            base_count = max(1, math.floor(budget / current_market_state.live_ask))
            if(current_market_state.live_ask <= 0.5):
                base_count = max(100, round(base_count / 100) * 100)
            self.strategy_state.contract_count = base_count
            order = MarketOrder(
                ticker=ticker_id,
                favored_side="yes",
                count=self.strategy_state.contract_count,
                limit_price_dollars=current_market_state.live_ask,
            )
            self.trader.place_entry(ticker_id, order)
            self.strategy_state.in_position = True
            self.strategy_state.entries_done += 1
            self.last_trade_tick = self.tick_count
            self.pending_bullish = False

        elif self.should_exit(current_market_state):
            order = MarketOrder(
                ticker=ticker_id,
                favored_side="yes",
                count=self.strategy_state.contract_count,
                limit_price_dollars=current_market_state.live_ask,
            )
            self.trader.place_exit(ticker_id, order)
            self.strategy_state.in_position = False
            self.last_trade_tick = self.tick_count
            self.pending_bearish = False



"""
2026-04-16 18:41:54.480 | INFO     | traders.SimulatedTrader:place_exit:26 - [KXNBAGAME-26MAR31TORDET-DET sell] 1593 at 0.95
2026-04-16 18:41:54.481 | INFO     | traders.SimulatedTrader:place_exit:27 - Balance after exit: 23313.53

Using Close bars only!
self.balance_fraction = 0.05
self.stop_loss_ratio = 0.3
self.len_long_sma = 60
self.min_ask_bound = 0.07
self.max_ask_bound = 0.88
self.max_contract_profit_threshold = 0.95
self.close_window_30 = deque(maxlen=30)
"""