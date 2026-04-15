from model.BaseStrategy import BaseStrategy
from traders.BaseTrader import BaseTrader, EntryEnum, ExitEnum
from utils.utils import CurrentStrategyState, MarketState, MarketOrder
from loguru import logger as log
import math

class FavoritesOnlyStrategy(BaseStrategy):
    def __init__(self, trader: BaseTrader, strategy_state: CurrentStrategyState) -> None:
        super().__init__(trader)
        self.balance_fraction = 0.05
        self.max_contract_price_to_exit = 0.97
        self.buy_price = 0
        self.stop_loss = 0.9
        self.strategy_state = strategy_state
        # no stop loss with favorites: Balance after exit: 1228.3900000000026
        # 50% stop loss: Balance after exit: 2006.3600000000001
        # 80% stop loss: Balance after exit: 1563.6499999999965 (stop when ask is 20% of intial buy)
        log.info("Constructed Favorites only strategy")

    def update(self, ticker_id: str, current_market_state: MarketState) -> None:
        if current_market_state.live_ask is None:
            return

        # Check if should enter
        if self.strategy_state.done:
            return
        
        if not self.strategy_state.in_position:
            budget = self.trader.get_balance() * self.balance_fraction
            self.strategy_state.contract_count = max(1, math.floor(budget / current_market_state.live_ask))
            self.buy_price = current_market_state.live_ask
            order = MarketOrder(
                ticker="simulated",
                favored_side="yes",
                count=self.strategy_state.contract_count,
                limit_price_dollars=current_market_state.live_ask,
            )
            if self.trader.place_entry(ticker_id, order) == EntryEnum.Success:
                self.strategy_state.in_position = True
            else:
                log.info(f"\t {ticker_id} buy failed!")
        else:
            # we are in position, check if we should exit
            if current_market_state.live_ask > self.max_contract_price_to_exit or current_market_state.live_ask <= self.buy_price * (1-self.stop_loss):
                order = MarketOrder(
                    ticker="simulated",
                    favored_side="yes",
                    count=self.strategy_state.contract_count,
                    limit_price_dollars=current_market_state.live_ask,
                )
                self.trader.place_exit(ticker_id, order)
                self.strategy_state.in_position = False
                self.strategy_state.done = True