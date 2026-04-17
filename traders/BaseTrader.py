
from loguru import logger as log
from abc import ABC, abstractmethod
from utils.utils import CurrentStrategyState, MarketOrder, MarketState, StrategyConfig
from typing import Optional
from enum import Enum
from utils.utils import Portfolio
import math

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
        self.total_fees = 0
        self.trade_count = 0
        # contract cost in cents, total fee cost in cents for 100 contracts
        self.fees_per100 = {
            1 : 7,
            5 : 34,
            10 : 63,
            15 : 90,
            20 : 112,
            25 : 132,
            30 : 147,
            35 : 160,
            40 : 168,
            45 : 174,
            50 : 175,
            55 : 174,
            60 : 168,
            65 : 160,
            70 : 147,
            75 : 132,
            80 : 112,
            85 : 90,
            90 : 63,
            95 : 34,
            99 : 7
        }

    def get_balance(self) -> float:
        return self.portfolio.balance / 100.0

    def get_total_fees(self) -> float:
        return self.total_fees
    
    def get_total_trades(self) -> int:
        return self.trade_count
    
    def compute_fees(self, order: MarketOrder) -> float:
        hundred_contracts = order.count // 100
        single_contracts = order.count % 100
        price = order.limit_price_dollars * 100
        def normalize_price_key(price_cents: float) -> int:
            p = int(round(price))
            if p <= 2:
                return 1
            if p >= 98:
                return 99
            return 5 * round(p / 5)
        
        key = normalize_price_key(price)
        hundreds_fee = (self.fees_per100[key] * hundred_contracts) / 100.0
        singles_fee = math.ceil(
            0.0175 * single_contracts * order.limit_price_dollars * (1 - order.limit_price_dollars) * 100
        ) / 100.0
        fees = hundreds_fee + singles_fee
        return fees

    @abstractmethod
    def place_entry(self, order: MarketOrder) -> EntryEnum:
        pass

    @abstractmethod
    def place_exit(self, order: MarketOrder) -> ExitEnum:
        pass

