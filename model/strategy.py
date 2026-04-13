from loguru import logger as log
from abc import ABC, abstractmethod
from utils.utils import CurrentStrategyState, MarketOrder, MarketState, StrategyConfig
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
    
    @abstractmethod
    def should_enter(self, st: CurrentStrategyState, market_st: MarketState) -> bool:
        pass

    @abstractmethod
    def should_exit(self, st: CurrentStrategyState, market_st: MarketState) -> bool:
        pass

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
    def should_enter(self, st: CurrentStrategyState, market_st: MarketState) -> bool:
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

    def should_exit(self, st: CurrentStrategyState, market_st: MarketState) -> bool:
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

    async def update(self, ticker_id: str, state: CurrentStrategyState, current_market_state: MarketState) -> None:
        self.tick_count += 1

        if not self.config.simulated:
            now_ts = int(datetime.now(UTC).timestamp())
            if now_ts < current_market_state.open_ts:
                return
            if now_ts > current_market_state.close_ts:
                state.done = True
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

        if self.should_enter(state, current_market_state):
            # This needs to go into the trader because it is a race condition for getting the port balance
            balance = self.trader.get_portfolio().balance / 100.0
            budget = balance * self.config.balance_fraction
            contract_count = max(1, math.floor(budget / current_market_state.live_ask))
            order = MarketOrder(
                ticker="simulated",
                favored_side="yes",
                count=contract_count,
                limit_price_dollars=current_market_state.live_ask,
            )
            await self.trader.place_entry(ticker_id, order, state)
            self.last_trade_tick = self.tick_count
            self.pending_bullish = False

        elif self.should_exit(state, current_market_state):
            order = MarketOrder(
                ticker="simulated",
                favored_side="yes",
                count=state.contract_count,
                limit_price_dollars=current_market_state.live_ask,
            )
            await self.trader.place_exit(ticker_id, order, state, reason="sma_crossover")
            self.last_trade_tick = self.tick_count
            self.pending_bearish = False

class MultiMarketRunner:
    def __init__(self, tickers: list[str], trader: Trader, config, ws_client) -> None:
        self.tickers = tickers
        self.trader = trader
        self.ws = ws_client

        self.states: dict[str, CurrentStrategyState] = {
            ticker: CurrentStrategyState(
                entry_price=0,
                contract_count=0,
                entries_done=0,
                in_position=False,
                done=False,
            )
            for ticker in tickers
        }

        self.strategies: dict[str, SmaCrossoverStrategy] = {
            ticker: SmaCrossoverStrategy(config=config, trader=trader)
            for ticker in tickers
        }

    def _build_market_state(self, payload: dict) -> MarketState | None:
        ticker = (
            payload.get("market_ticker")
            or payload.get("ticker")
            or payload.get("market")
        )

        yes_ask = payload.get("yes_ask_dollars")
        last_price = payload.get("price_dollars")

        if yes_ask is None and last_price is None:
            return None

        ts = payload.get("ts")
        if ts is None:
            return None

        return MarketState(
            open_ts=0,  # replace if you have real market open ts
            close_ts=9999999999,  # replace if you have real market close ts
            closing_ask=yes_ask,
            live_ask=yes_ask,
            last_price=last_price,
        )

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
        if ticker not in self.strategies:
            return

        market_state = self._build_market_state(payload)
        if market_state is None:
            return

        strategy = self.strategies[ticker]
        state = self.states[ticker]

        await strategy.update(ticker, state, market_state)

    async def run(self):
        self.ws._tickers = self.tickers
        self.ws._message_handler = self.ws_message_handler
        await self.ws.connect()