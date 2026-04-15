
from loguru import logger as log
from abc import ABC, abstractmethod
from utils.utils import CurrentStrategyState, MarketOrder, MarketState, StrategyConfig
from typing import Optional
from enum import Enum
from utils.utils import Portfolio

class EntryEnum(Enum):
    Success = 0
    FailureInsufficientBalance = 1
    Failure = 2

class ExitEnum(Enum):
    Success = 0
    Failure = 1

class BaseTrader(ABC):
    def __init__(self, portfolio: Portfolio) -> None:
        self.portfolio = portfolio

    def get_balance(self) -> float:
        return self.portfolio.balance

    @abstractmethod
    def place_entry(self, order: MarketOrder) -> EntryEnum:
        pass

    @abstractmethod
    def place_exit(self, order: MarketOrder) -> ExitEnum:
        pass

