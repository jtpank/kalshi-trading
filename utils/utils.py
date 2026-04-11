from dataclasses import dataclass
from typing import Any, Dict, Optional
from enum import Enum

class KalshiEnvironment(Enum):
    DEMO = "demo"
    PROD = "prod"

@dataclass
class MarketOrder:
    ticker: str
    favored_side: str
    count: int
    limit_price_dollars: float

@dataclass
class MarketState:
    open_ts: int
    close_ts: int
    closing_ask: Optional[float] = None
    live_ask: Optional[float] = None
    last_price: Optional[float] = None

@dataclass
class TraderState:
    entry_price: float
    contract_count: int
    entries_done: int = 0
    in_position: bool = False
    done: bool = False
    last_print_ts: Optional[int] = None

@dataclass
class StrategyConfig:
    entry_ratio: float
    stop_loss_ratio: float
    exit_ratio: float
    secondary_exit_ratio: float
    max_entries: int
    min_entry_ask: float
    balance_fraction: float
    simulated:bool

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