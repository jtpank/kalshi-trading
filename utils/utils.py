from dataclasses import dataclass
from typing import Any, Dict, Optional
from enum import Enum

class KalshiEnvironment(Enum):
    DEMO = "demo"
    PROD = "prod"


@dataclass
class MarketState:
    ticker: str
    favored_side: str
    open_ts: int
    close_ts: int
    closing_ask: Optional[float] = None
    live_ask: Optional[float] = None
    last_price: Optional[float] = None
    entries_done: int = 0
    in_position: bool = False
    entry_price: Optional[float] = None
    contract_count: int = 0
    done: bool = False
    last_print_ts: Optional[int] = None

@dataclass
class StrategyConfig:
    entry_ratio: float
    stop_loss_ratio: float
    exit_ratio: float
    max_entries: int
    balance_fraction: float

@dataclass
class KalshiPortfolioResponse:
    balance: int
    portfolio_value: int
    updated_ts: int

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "KalshiPortfolioResponse":
        return cls(
            balance=int(data.get("balance", 0)),
            portfolio_value=int(data.get("portfolio_value", 0)),
            updated_ts=int(data.get("updated_ts", 0)),
        )