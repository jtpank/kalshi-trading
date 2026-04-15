from loguru import logger as log
from abc import ABC, abstractmethod
from utils.utils import CurrentStrategyState, MarketOrder, MarketState, StrategyConfig
from typing import Optional
from datetime import datetime, UTC
import uuid
from traders.Trader import Trader


#Helpers
def to_float(value) -> Optional[float]:
    if value is None:
        return None
    return float(value)

class BaseStrategy(ABC):
    def __init__(self, trader: Trader) -> None:
        self.trader = trader

    @abstractmethod
    def update(self, ticker_id: str, current_market_state: MarketState) -> None:
        pass

