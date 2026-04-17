from loguru import logger as log
from utils.utils import MarketOrder, Portfolio
from traders.BaseTrader import BaseTrader, EntryEnum, ExitEnum

class SimulatedTrader(BaseTrader):
    def __init__(self, portfolio: Portfolio):
        super().__init__(portfolio)
        log.info("SimulatedTrader constructed with fields:")
        log.info(f"Portfolio: {self.portfolio}")

    def available_balance_dollars(self) -> float:
        return self.get_balance() 

    def place_entry(self, ticker_id: str, order: MarketOrder) -> EntryEnum:
        cost = order.count * order.limit_price_dollars
        if cost > self.get_balance():
            log.info(f"Balance of {self.get_balance()} is not sufficient to place trade for {order.count} shares at {order.limit_price_dollars}")
            return EntryEnum.FailureInsufficientBalance
        incrued_fees = self.compute_fees(order)
        self.total_fees += incrued_fees
        self.portfolio.balance -= cost * 100.0
        self.portfolio.balance -= incrued_fees * 100
        log.info(f"[{ticker_id} buy]: {order.count} at {order.limit_price_dollars}, trade_fee: {incrued_fees}")
        return EntryEnum.Success

    def place_exit(self, ticker_id: str, order:MarketOrder) -> ExitEnum:
        proceeds = order.count * order.limit_price_dollars
        incrued_fees = self.compute_fees(order)
        self.total_fees += incrued_fees
        self.portfolio.balance += proceeds * 100.0
        self.portfolio.balance -= incrued_fees * 100
        self.trade_count += 1
        log.info(f"[{ticker_id} sell] {order.count} at {order.limit_price_dollars}, , trade_fee: {incrued_fees}")
        log.info(f"Balance after exit: {self.get_balance()}")
        return ExitEnum.Success
