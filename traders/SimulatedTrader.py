from loguru import logger as log
from utils.utils import MarketOrder, Portfolio
from traders.BaseTrader import BaseTrader, EntryEnum, ExitEnum

class SimulatedTrader(BaseTrader):
    def __init__(self, portfolio: Portfolio):
        super().__init__(portfolio)
        log.info("SimulatedTrader constructed with fields:")
        log.info(f"Portfolio: {self.portfolio}")

    def place_entry(self, order: MarketOrder) -> EntryEnum:
        cost = order.count * order.limit_price_dollars
        if cost > self.portfolio.balance:
            log.info(f"Balance of {self.portfolio.balance} is not sufficient to place trade for {order.count} shares at {order.limit_price_dollars}")
            return EntryEnum.FailureInsufficientBalance
        self.portfolio.balance -= cost
        log.info(f"Placed trade: {order.count} at {order.limit_price_dollars}")
        return EntryEnum.Success

    def place_exit(self, order:MarketOrder) -> ExitEnum:
        proceeds = order.count * order.limit_price_dollars
        self.portfolio.balance += proceeds
        log.info(f"Placed trade: [sell] {order.count} at {order.limit_price_dollars}")
        log.info(f"Balance after exit: {self.get_balance()}")
        return ExitEnum.Success
